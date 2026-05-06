import os
import psycopg2
from psycopg2 import pool
from flask import Flask, render_template, request, redirect, session, url_for, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'super-secret-key-123')

# Пул соединений для PostgreSQL
try:
    db_pool = psycopg2.pool.SimpleConnectionPool(
        1, 20,
        host=os.getenv('DB_HOST'),
        database=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD')
    )
except Exception as e:
    print(f"Ошибка БД: {e}")
    db_pool = None

def get_db_connection():
    if db_pool: return db_pool.getconn()
    raise Exception("Нет связи с базой данных")

def release_db_connection(conn):
    if db_pool and conn: db_pool.putconn(conn)

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
        finally: release_db_connection(conn)
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
        finally: release_db_connection(conn)
    return render_template('login.html')

@app.route('/')
def index():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username FROM users WHERE id != %s", (session['user_id'],))
            users = cur.fetchall()
        return render_template('index.html', users=users, username=session['username'])
    finally: release_db_connection(conn)

@app.route('/chat/<int:user_id>')
def chat(user_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT username FROM users WHERE id = %s", (user_id,))
            partner = cur.fetchone()
            cur.execute("""
                SELECT u.username, m.content, m.created_at, m.sender_id, m.id
                FROM messages m JOIN users u ON u.id = m.sender_id
                WHERE chat_type = 'private' AND ((sender_id=%s AND receiver_id=%s) OR (sender_id=%s AND receiver_id=%s))
                ORDER BY m.created_at ASC
            """, (session['user_id'], user_id, user_id, session['user_id']))
            messages = cur.fetchall()
            cur.execute("SELECT id, username FROM users WHERE id != %s", (session['user_id'],))
            all_users = cur.fetchall()
        return render_template('chat.html', messages=messages, partner=partner[0] if partner else "Чат",
                               partner_id=user_id, my_id=session['user_id'], all_users=all_users)
    finally: release_db_connection(conn)

@app.route('/global')
def global_chat():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT u.username, m.content, m.created_at, m.sender_id, m.id
                FROM messages m JOIN users u ON u.id = m.sender_id
                WHERE m.chat_type = 'global' ORDER BY m.created_at ASC
            """)
            messages = cur.fetchall()
            cur.execute("SELECT id, username FROM users WHERE id != %s", (session['user_id'],))
            all_users = cur.fetchall()
        return render_template('chat.html', messages=messages, partner='Общий чат', partner_id=None, my_id=session['user_id'], all_users=all_users)
    finally: release_db_connection(conn)

@app.route('/poll')
def poll():
    if 'user_id' not in session: return jsonify({'messages': []})
    last_id = int(request.args.get('last_id', 0))
    receiver_id = request.args.get('receiver_id')
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if receiver_id and receiver_id != 'None':
                cur.execute("SELECT m.id, u.username, m.content, m.sender_id, m.created_at::text FROM messages m JOIN users u ON u.id = m.sender_id WHERE m.id > %s AND chat_type='private' AND ((sender_id=%s AND receiver_id=%s) OR (sender_id=%s AND receiver_id=%s)) ORDER BY m.id ASC", (last_id, session['user_id'], int(receiver_id), int(receiver_id), session['user_id']))
            else:
                cur.execute("SELECT m.id, u.username, m.content, m.sender_id, m.created_at::text FROM messages m JOIN users u ON u.id = m.sender_id WHERE m.id > %s AND chat_type='global' ORDER BY m.id ASC", (last_id,))
            rows = cur.fetchall()
        return jsonify({'messages': [{'id': r[0], 'username': r[1], 'content': r[2], 'sender_id': r[3]} for r in rows]})
    finally: release_db_connection(conn)

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
            cur.execute("INSERT INTO messages (sender_id, receiver_id, content, chat_type) VALUES (%s, %s, %s, %s)",
                        (session['user_id'], receiver_id if receiver_id and receiver_id != 'None' else None, content, 'private' if receiver_id and receiver_id != 'None' else 'global'))
        conn.commit()
        return jsonify({'status': 'ok'})
    finally: release_db_connection(conn)

# --- ВОССТАНОВЛЕНИЕ ПАРОЛЯ ---
@app.route('/forgot')
def forgot():
    return render_template('Forgot.html')

@app.route('/forgot/check-user', methods=['POST'])
def forgot_check_user():
    username = request.json.get('username', '').strip()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = %s", (username,))
            user = cur.fetchone()
        return jsonify({'ok': True if user else False, 'error': 'Пользователь не найден' if not user else ''})
    finally: release_db_connection(conn)

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
    finally: release_db_connection(conn)

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
    finally: release_db_connection(conn)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)