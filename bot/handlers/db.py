import sqlite3
from datetime import datetime, timedelta

db_name = "bashlingo.db"

def init_db():
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY, 
    username TEXT, 
    first_name TEXT,
    points INTEGER DEFAULT 0, 
    level INTEGER DEFAULT 1,
    last_daily TEXT, 
    daily_count INTEGER DEFAULT 0,
    lang_pair TEXT,
    site_login TEXT,
    site_password TEXT
    )""")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS fragments(
    fragment_id INTEGER PRIMARY KEY AUTOINCREMENT, 
    text_ba TEXT UNIQUE,
    lang_pair TEXT DEFAULT 'ba-ru', 
    source TEXT
    )""")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS translations(
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    fragment_id INTEGER, 
    user_id INTEGER,
    translation TEXT, 
    confirmed INTEGER DEFAULT 0, 
    status TEXT DEFAULT 'pending', 
    created_at TEXT
    )""")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS history(
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    user_id INTEGER, 
    points INTEGER, 
    date TEXT
    )""")
    
    conn.commit()
    conn.close()

def add_user(user_id, username, first_name):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)", (user_id, username, first_name))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(db_name)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_lang_pair(user_id, lang_pair):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET lang_pair = ? WHERE user_id = ?", (lang_pair, user_id))
    conn.commit()
    conn.close()

def update_credentials(user_id, login, password):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET site_login = ?, site_password = ? WHERE user_id = ?", (login, password, user_id))
    conn.commit()
    conn.close()

def get_fragment_by_level(level):
    conn = sqlite3.connect(db_name)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if level == 1: min_len, max_len = 10, 30
    elif level == 2: min_len, max_len = 25, 50
    elif level == 3: min_len, max_len = 45, 70
    elif level == 4: min_len, max_len = 65, 100
    else: min_len, max_len = 90, 200
        
    cursor.execute("SELECT * FROM fragments WHERE LENGTH(text_ba) BETWEEN ? AND ? ORDER BY RANDOM() LIMIT 1", (min_len, max_len))
    row = cursor.fetchone()
    if not row:
        cursor.execute("SELECT * FROM fragments ORDER BY RANDOM() LIMIT 1")
        row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def check_daily_limit(user_id):
    user = get_user(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    
    if user.get('last_daily') != today:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET last_daily = ?, daily_count = 0 WHERE user_id = ?", (today, user_id))
        conn.commit()
        conn.close()
        return True
        
    return user.get('daily_count', 0) < 5

def increment_daily_count(user_id):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET daily_count = daily_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def save_translation(fragment_id, user_id, translation_text, status):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    date_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO translations (fragment_id, user_id, translation, status, created_at) 
        VALUES (?, ?, ?, ?, ?)
    """, (fragment_id, user_id, translation_text, status, date_now))
    trans_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return trans_id

def confirm_translation(trans_id):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("UPDATE translations SET confirmed = confirmed + 1 WHERE id = ?", (trans_id,))
    cursor.execute("UPDATE translations SET status = 'confirmed' WHERE id = ? AND confirmed >= 3", (trans_id,))
    conn.commit()
    conn.close()

def add_points(user_id, points):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
    cursor.execute("UPDATE users SET level = (points / 100) + 1 WHERE user_id = ?", (user_id,))
    cursor.execute("SELECT level FROM users WHERE user_id = ?", (user_id,))
    new_level = cursor.fetchone()[0]
    today_date = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("INSERT INTO history (user_id, points, date) VALUES (?, ?, ?)", (user_id, points, today_date))
    conn.commit()
    conn.close()
    return new_level

def get_leaderboard(timeframe: str):
    conn = sqlite3.connect(db_name)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    today = datetime.now()
    if timeframe == "today": start_date = today.strftime("%Y-%m-%d")
    elif timeframe == "week": start_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    elif timeframe == "month": start_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    else: start_date = "2000-01-01"
    
    cursor.execute("""
        SELECT u.first_name, SUM(h.points) as total_points
        FROM history h JOIN users u ON h.user_id = u.user_id
        WHERE h.date >= ? GROUP BY h.user_id ORDER BY total_points DESC LIMIT 10
    """, (start_date,))
    rows = cursor.fetchall()
    conn.close()
    return rows