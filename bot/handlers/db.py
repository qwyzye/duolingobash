import sqlite3

db_name = "bashlingo.db"

def init_db():
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    progress INTEGER DEFAULT 0,
    level INTEGER DEFAULT 1
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS user_words(
    user_id INTEGER,
    word TEXT,
    translation TEXT,
    UNIQUE(user_id, word)
    )""")
    conn.commit()
    conn.close()

def add_user(user_id: int, username: str, first_name: str):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR IGNORE INTO users (user_id, username, first_name)
    VALUES (?, ?, ?)""", (user_id,username,first_name))
    conn.commit()
    conn.close()

def get_user(user_id: int):
    conn = sqlite3.connect(db_name)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_progress(user_id: int, points: int):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET progress = progress + ? WHERE user_id = ?", (points, user_id))
    conn.commit()
    conn.close()

def add_learned_word(user_id: int, word: str, translation: str):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO user_words (user_id, word, translation) VALUES (?, ?, ?)", (user_id, word, translation))
    conn.commit()
    conn.close()

def get_user_words(user_id: int) -> list:
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("SELECT word FROM user_words WHERE user_id = ?", (user_id,))
    words = [row[0] for row in cursor.fetchall()]
    conn.close()
    return words