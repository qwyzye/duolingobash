# app/auth.py
import bcrypt
import secrets
from datetime import datetime, timedelta
import sqlite3

def register_user(
    conn: sqlite3.Connection,
    username: str,
    password: str,
    city: str | None = None,
    school: str | None = None,
    grade: str | None = None,
) -> int | None:
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, city, school, grade) "
            "VALUES (?, ?, ?, ?, ?)",
            (username, pw_hash, city, school, grade),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None

def authenticate(conn: sqlite3.Connection, username: str, password: str) -> int | None:
    row = conn.execute(
        "SELECT id, password_hash FROM users WHERE username = ?", (username,)
    ).fetchone()
    if not row:
        # Защита от тайминг-атак: всё равно считаем хеш
        bcrypt.checkpw(password.encode(), bcrypt.hashpw(b"x", bcrypt.gensalt()))
        return None
    if not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        return None
    return row["id"]

def create_session(conn: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.utcnow() + timedelta(days=30)).isoformat()
    conn.execute(
        "INSERT INTO sessions (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user_id, token, expires),
    )
    conn.execute(
        "UPDATE users SET last_login_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), user_id),
    )
    conn.commit()
    return token

def get_user_by_token(conn: sqlite3.Connection, token: str) -> int | None:
    row = conn.execute(
        "SELECT user_id, expires_at FROM sessions WHERE token = ?", (token,)
    ).fetchone()
    if not row:
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.utcnow():
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        return None
    return row["user_id"]