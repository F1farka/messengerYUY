💬 MessageYUY — Веб-мессенджер
Веб-мессенджер с личными чатами и глобальным чатом, реализованный на Flask + PostgreSQL.

⚡ Возможности

🔐 Регистрация и авторизация пользователей (хеширование паролей)
🔑 Восстановление пароля через секретное слово
💬 Личные чаты между пользователями
🌍 Глобальный чат для всех
⚡ Сообщения в реальном времени (long polling, обновление каждую секунду)
📱 Адаптивный дизайн — работает на телефоне и ПК
✨ Анимации при входе и регистрации


🛠️ Технологии
ЧастьТехнологияBackendPython, FlaskБаза данныхPostgreSQLFrontendHTML, CSS, JavaScriptБезопасностьWerkzeug (hashing), python-dotenv

🗄️ Структура базы данных
Таблица users
sqlCREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    secret_word TEXT,
    last_seen TIMESTAMP DEFAULT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
Таблица messages
sqlCREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    sender_id INTEGER NOT NULL REFERENCES users(id),
    receiver_id INTEGER REFERENCES users(id), -- NULL для глобального чата
    content TEXT NOT NULL,
    chat_type VARCHAR(10) NOT NULL DEFAULT 'global', -- 'private' или 'global'
    created_at TIMESTAMP DEFAULT NOW()
);

🚀 Установка и запуск
1. Клонировать репозиторий
bashgit clone https://github.com/твой_ник/messengerYUY.git
cd messengerYUY
2. Установить зависимости
bashpip install flask psycopg2 werkzeug python-dotenv
3. Создать файл .env
SECRET_KEY=твой_секретный_ключ
DB_HOST=localhost
DB_NAME=messenger
DB_USER=postgres
DB_PASSWORD=твой_пароль
4. Создать таблицы в PostgreSQL
Выполнить SQL из раздела выше в pgAdmin или psql.
5. Запустить
bashpython app.py
Открыть в браузере: http://127.0.0.1:5000

📁 Структура проекта
messengerYUY/
├── app.py              # Основной файл Flask
├── .env                # Секретные данные (не в Git)
├── .gitignore
└── templates/
    ├── login.html      # Страница входа
    ├── register.html   # Страница регистрации
    ├── forgot.html     # Восстановление пароля
    ├── index.html      # Список чатов
    └── chat.html       # Страница чата

📌 Выполненные требования

✅ База данных PostgreSQL
✅ Таблица пользователей и таблица сообщений
✅ Личные чаты между пользователями
✅ Глобальный чат для всех
✅ HTML-страницы вынесены в отдельные файлы (templates/)
✅ Диалоги хранятся в одной таблице, связаны через sender_id / receiver_id
✅ Колонка chat_type — private или global
