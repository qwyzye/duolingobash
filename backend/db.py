"""БД сайта и юзеров бота: app.db (users, sessions, learned_words, points, history)."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "app.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def db_cursor():
    conn = get_connection()
    try:
        yield conn.cursor()
        conn.commit()
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id        INTEGER UNIQUE,
    username           TEXT UNIQUE,
    first_name         TEXT,
    password_hash      TEXT,
    city               TEXT,
    school             TEXT,
    grade              TEXT,
    lang_pair          TEXT DEFAULT 'ba-ru',
    level              INTEGER NOT NULL DEFAULT 1,
    points             INTEGER NOT NULL DEFAULT 0,
    streak_days        INTEGER NOT NULL DEFAULT 0,
    last_activity_date TEXT,
    last_login_at      TEXT,
    created_at         TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_users_telegram ON users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    token       TEXT NOT NULL UNIQUE,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    expires_at  TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);

CREATE TABLE IF NOT EXISTS learned_words (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    fragment_id   INTEGER NOT NULL,
    seen_count    INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    learned_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, fragment_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_learned_user ON learned_words(user_id);

CREATE TABLE IF NOT EXISTS points_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    event_type  TEXT NOT NULL,
    event_key   TEXT NOT NULL,
    points      INTEGER DEFAULT 0,
    date        TEXT,
    UNIQUE(user_id, event_type, event_key),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_points_user_date ON points_events(user_id, date);

CREATE TABLE IF NOT EXISTS history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    points      INTEGER,
    date        TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_history_user_date ON history(user_id, date);

CREATE TABLE IF NOT EXISTS vocabulary (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    word        TEXT,
    translation TEXT,
    created_at  TEXT,
    UNIQUE(user_id, word),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""


def init_db():
    with get_connection() as conn:
        conn.executescript(SCHEMA)