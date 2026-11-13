import sqlite3

db_name = "bashlingo.db"

def init_db():
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    progress INTEGER DEFAULT 0
    ) """)
    conn.commit()
    conn.close()

def add_user(user_id: int, username: str, first_name: str):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR IGNORE INTO users (user_id, username, first_name)
    VALUES (?, ?, ?)""",
    (user_id,username,first_name))
    conn.commit()
    conn.close()

def get_user(user_id: int):
    conn = sqlite3.connect(db_name)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return dict(row)
    return None

def update_progress(user_id: int, points: int):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET progress = progress + ? WHERE user_id = ?", (points, user_id))
    conn.commit()
    conn.close()