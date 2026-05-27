import os
import psycopg2
from psycopg2 import pool
from flask import Flask, render_template, request, redirect, session, url_for, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'super-secret-key-123')

try:
    db_pool = psycopg2.pool.SimpleConnectionPool(
        1, 20,
        host=os.getenv('DB_HOST'),
        database=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD')
    )
except Exception as e:
    print(f"Ошибка пула БД: {e}")
    db_pool = None


def get_db_connection():
    if db_pool: return db_pool.getconn()
    raise Exception("Нет связи с базой данных")


def release_db_connection(conn):
    if db_pool and conn: db_pool.putconn(conn)


# Безопасная проверка онлайна с учетом разницы часовых поясов базы и сервера
def is_online(last_active):
    if not last_active: return False
    try:
        if last_active.tzinfo is not None:
            return (datetime.now(timezone.utc) - last_active).total_seconds() < 300
        return (datetime.now() - last_active).total_seconds() < 300
    except Exception:
        return False


# Фиксация активности пользователя при любом запросе
@app.before_request
def update_last_active():
    if 'user_id' in session:
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET last_active = NOW() WHERE id = %s", (session['user_id'],))
            conn.commit()
        except:
            pass
        finally:
            release_db_connection(conn)


# Получение списка контактов (только те, с кем реально велась переписка)
def get_active_contacts(user_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT u.id, u.username, u.last_active
                FROM users u
                WHERE u.id IN (
                    SELECT receiver_id FROM messages WHERE sender_id = %s AND receiver_id IS NOT NULL
                    UNION
                    SELECT sender_id FROM messages WHERE receiver_id = %s
                ) AND u.id != %s
            """, (user_id, user_id, user_id))
            users = cur.fetchall()
            return [{'id': u[0], 'username': u[1], 'is_online': is_online(u[2])} for u in users]
    except Exception as e:
        print(f"Ошибка при выборке контактов: {e}")
        return []
    finally:
        release_db_connection(conn)


@app.route('/api/search')
def search_users():
    if 'user_id' not in session: return jsonify([])
    q = request.args.get('q', '').strip()
    if not q: return jsonify([])

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username, last_active FROM users WHERE username ILIKE %s AND id != %s LIMIT 15",
                        (f'%{q}%', session['user_id']))
            users = cur.fetchall()
        return jsonify([{'id': u[0], 'username': u[1], 'is_online': is_online(u[2])} for u in users])
    finally:
        release_db_connection(conn)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        secret_word = request.form.get('secret_word', '').strip().lower()
        hashed = generate_password_hash(password)
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO users (username, password_hash, secret_word) VALUES (%s, %s, %s)",
                            (username, hashed, secret_word))
            conn.commit()
            return redirect(url_for('login'))
        except psycopg2.IntegrityError:
            conn.rollback()
            flash("Этот логин уже занят", "error")
            return render_template('register.html')
        finally:
            release_db_connection(conn)
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, password_hash FROM users WHERE username = %s", (username,))
                user = cur.fetchone()
            if user and check_password_hash(user[1], password):
                session['user_id'] = user[0]
                session['username'] = username
                return redirect(url_for('index'))
            flash("Неверный логин или пароль", "error")
            return render_template('login.html')
        finally:
            release_db_connection(conn)
    return render_template('login.html')


@app.route('/')
def index():
    if 'user_id' not in session: return redirect(url_for('login'))
    contacts = get_active_contacts(session['user_id'])
    return render_template('index.html', contacts=contacts, username=session['username'])


@app.route('/chat/<int:user_id>')
def chat(user_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT username, last_active FROM users WHERE id = %s", (user_id,))
            partner_data = cur.fetchone()
            if not partner_data:
                return redirect(url_for('index'))

            partner = partner_data[0]
            partner_online = is_online(partner_data[1])

            cur.execute("""
                SELECT u.username, m.content, m.created_at, m.sender_id, m.id
                FROM messages m JOIN users u ON u.id = m.sender_id
                WHERE (sender_id=%s AND receiver_id=%s) OR (sender_id=%s AND receiver_id=%s)
                ORDER BY m.created_at ASC
            """, (session['user_id'], user_id, user_id, session['user_id']))
            messages = cur.fetchall()

        contacts = get_active_contacts(session['user_id'])
        if not any(c['id'] == user_id for c in contacts):
            contacts.insert(0, {'id': user_id, 'username': partner, 'is_online': partner_online})

        return render_template('chat.html', messages=messages, partner=partner, partner_online=partner_online,
                               partner_id=user_id, my_id=session['user_id'], contacts=contacts)
    finally:
        release_db_connection(conn)


@app.route('/global')
def global_chat():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT u.username, m.content, m.created_at, m.sender_id, m.id
                FROM messages m JOIN users u ON u.id = m.sender_id
                WHERE m.receiver_id IS NULL ORDER BY m.created_at ASC
            """)
            messages = cur.fetchall()
        contacts = get_active_contacts(session['user_id'])
        return render_template('chat.html', messages=messages, partner='Общий чат', partner_online=True,
                               partner_id=None, my_id=session['user_id'], contacts=contacts)
    finally:
        release_db_connection(conn)


@app.route('/poll')
def poll():
    if 'user_id' not in session: return jsonify({'messages': []})
    last_id = int(request.args.get('last_id', 0))
    receiver_id = request.args.get('receiver_id')
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if receiver_id and receiver_id != 'None':
                cur.execute("""
                    SELECT m.id, u.username, m.content, m.sender_id, m.created_at::text 
                    FROM messages m JOIN users u ON u.id = m.sender_id 
                    WHERE m.id > %s AND ((sender_id=%s AND receiver_id=%s) OR (sender_id=%s AND receiver_id=%s)) 
                    ORDER BY m.id ASC
                """, (last_id, session['user_id'], int(receiver_id), int(receiver_id), session['user_id']))
            else:
                cur.execute("""
                    SELECT m.id, u.username, m.content, m.sender_id, m.created_at::text 
                    FROM messages m JOIN users u ON u.id = m.sender_id 
                    WHERE m.id > %s AND m.receiver_id IS NULL 
                    ORDER BY m.id ASC
                """, (last_id,))
            rows = cur.fetchall()
        return jsonify({'messages': [{'id': r[0], 'username': r[1], 'content': r[2], 'sender_id': r[3]} for r in rows]})
    finally:
        release_db_connection(conn)


@app.route('/send', methods=['POST'])
def send():
    if 'user_id' not in session: return jsonify({'error': 'unauthorized'}), 401
    data = request.json
    content = data.get('content', '').strip()
    receiver_id = data.get('receiver_id')
    if not content: return jsonify({'error': 'empty'}), 400
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO messages (sender_id, receiver_id, content) VALUES (%s, %s, %s)",
                        (session['user_id'], receiver_id if receiver_id and receiver_id != 'None' else None, content))
        conn.commit()
        return jsonify({'status': 'ok', 'username': session['username']})
    finally:
        release_db_connection(conn)


@app.route('/forgot')
def forgot(): return render_template('Forgot.html')


@app.route('/forgot/check-user', methods=['POST'])
def forgot_check_user():
    username = request.json.get('username', '').strip()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = %s", (username,))
            user = cur.fetchone()
        return jsonify({'ok': True if user else False, 'error': 'Пользователь не найден' if not user else ''})
    finally:
        release_db_connection(conn)


@app.route('/forgot/check-secret', methods=['POST'])
def forgot_check_secret():
    data = request.json
    username, secret = data.get('username', '').strip(), data.get('secret_word', '').strip().lower()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT secret_word FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
        if row and row[0] and row[0].lower() == secret: return jsonify({'ok': True})
        return jsonify({'ok': False, 'error': 'Неверное секретное слово'})
    finally:
        release_db_connection(conn)


@app.route('/forgot/reset', methods=['POST'])
def forgot_reset():
    data = request.json
    username, new_pass = data.get('username', '').strip(), data.get('new_password', '')
    if len(new_pass) < 4: return jsonify({'ok': False, 'error': 'Пароль слишком короткий'})
    hashed = generate_password_hash(new_pass)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET password_hash = %s WHERE username = %s", (hashed, username))
        conn.commit()
        return jsonify({'ok': True})
    except Exception:
        conn.rollback()
        return jsonify({'ok': False, 'error': 'Ошибка сервера'})
    finally:
        release_db_connection(conn)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)