from flask import Flask, render_template, request, redirect, session, url_for, jsonify
import psycopg2
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import os

app = Flask(__name__)
from dotenv import load_dotenv
import os

load_dotenv()

app.secret_key = os.getenv('SECRET_KEY')

def get_db():
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST'),
        database=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD')
    )
    return conn

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        secret_word = request.form.get('secret_word', '').strip().lower()
        hashed = generate_password_hash(password)

        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO users (username, password_hash, secret_word) VALUES (%s, %s, %s)",
                (username, hashed, secret_word)
            )
            conn.commit()
            return redirect(url_for('login'))
        except:
            return "Пользователь уже существует"
        finally:
            cur.close()
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, password_hash FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user and check_password_hash(user[1], password):
            session['user_id'] = user[0]
            session['username'] = username
            return redirect(url_for('index'))
        return "Неверный логин или пароль"
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username FROM users WHERE id != %s", (session['user_id'],))
    users = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('index.html', users=users, username=session['username'])

@app.route('/chat/<int:user_id>')
def chat(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT username FROM users WHERE id = %s", (user_id,))
    partner = cur.fetchone()

    cur.execute("""
        SELECT u.username, m.content, m.created_at, m.sender_id, m.id
        FROM messages m
        JOIN users u ON u.id = m.sender_id
        WHERE chat_type = 'private'
          AND ((sender_id = %s AND receiver_id = %s)
            OR (sender_id = %s AND receiver_id = %s))
        ORDER BY m.created_at ASC
    """, (session['user_id'], user_id, user_id, session['user_id']))
    messages = cur.fetchall()

    cur.execute("SELECT id, username FROM users WHERE id != %s", (session['user_id'],))
    all_users = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('chat.html',
                           messages=messages,
                           partner=partner[0],
                           partner_id=user_id,
                           my_id=session['user_id'],
                           all_users=all_users)

@app.route('/global')
def global_chat():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT u.username, m.content, m.created_at, m.sender_id, m.id
        FROM messages m
        JOIN users u ON u.id = m.sender_id
        WHERE m.chat_type = 'global'
        ORDER BY m.created_at ASC
    """)
    messages = cur.fetchall()

    cur.execute("SELECT id, username FROM users WHERE id != %s", (session['user_id'],))
    all_users = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('chat.html',
                           messages=messages,
                           partner='Общий чат',
                           partner_id=None,
                           my_id=session['user_id'],
                           all_users=all_users)

@app.route('/poll')
def poll():
    if 'user_id' not in session:
        return jsonify({'messages': []})

    receiver_id = request.args.get('receiver_id') or None
    last_id = int(request.args.get('last_id', 0))

    conn = get_db()
    cur = conn.cursor()

    if receiver_id:
        receiver_id = int(receiver_id)
        cur.execute("""
            SELECT m.id, u.username, m.content, m.sender_id, m.created_at::text
            FROM messages m
            JOIN users u ON u.id = m.sender_id
            WHERE m.id > %s AND m.chat_type = 'private'
              AND ((sender_id = %s AND receiver_id = %s)
                OR (sender_id = %s AND receiver_id = %s))
            ORDER BY m.created_at ASC
        """, (last_id, session['user_id'], receiver_id, receiver_id, session['user_id']))
    else:
        cur.execute("""
            SELECT m.id, u.username, m.content, m.sender_id, m.created_at::text
            FROM messages m
            JOIN users u ON u.id = m.sender_id
            WHERE m.id > %s AND m.chat_type = 'global'
            ORDER BY m.created_at ASC
        """, (last_id,))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    msgs = [{'id': r[0], 'username': r[1], 'content': r[2], 'sender_id': r[3], 'created_at': r[4]} for r in rows]
    return jsonify({'messages': msgs})

@app.route('/send', methods=['POST'])
def send():
    if 'user_id' not in session:
        return jsonify({'error': 'not logged in'}), 401

    data = request.json
    content = data.get('content', '').strip()
    receiver_id = data.get('receiver_id')
    chat_type = 'private' if receiver_id else 'global'

    if not content:
        return jsonify({'error': 'empty'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO messages (sender_id, receiver_id, content, chat_type)
        VALUES (%s, %s, %s, %s)
    """, (session['user_id'], receiver_id, content, chat_type))
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({'status': 'ok', 'username': session['username'], 'content': content})

# ─── FORGOT PASSWORD ───────────────────────────────────────────────────────────

@app.route('/forgot')
def forgot():
    return render_template('forgot.html')

@app.route('/forgot/check-user', methods=['POST'])
def forgot_check_user():
    data = request.json
    username = data.get('username', '').strip()
    if not username:
        return jsonify({'ok': False, 'error': 'Введите логин'})

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = %s", (username,))
    user = cur.fetchone()
    cur.close()
    conn.close()

    if user:
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Пользователь не найден'})

@app.route('/forgot/check-secret', methods=['POST'])
def forgot_check_secret():
    data = request.json
    username = data.get('username', '').strip()
    secret = data.get('secret_word', '').strip().lower()

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT secret_word FROM users WHERE username = %s", (username,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row and row[0] and row[0].lower() == secret:
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Неверное секретное слово'})

@app.route('/forgot/reset', methods=['POST'])
def forgot_reset():
    data = request.json
    username = data.get('username', '').strip()
    new_password = data.get('new_password', '')

    if len(new_password) < 4:
        return jsonify({'ok': False, 'error': 'Пароль слишком короткий'})

    hashed = generate_password_hash(new_password)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET password_hash = %s WHERE username = %s", (hashed, username))
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({'ok': True})

if __name__ == '__main__':
    app.run(debug=True)