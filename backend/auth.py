"""Аутентификация сайта: app.db, users.id."""
import bcrypt
import secrets
import sqlite3
from datetime import datetime, timedelta, date


def register_user(conn, username, password, city=None, school=None, grade=None):
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


def authenticate(conn, username, password):
    row = conn.execute(
        "SELECT id, password_hash FROM users WHERE username = ?", (username,)
    ).fetchone()
    if not row or not row["password_hash"]:
        bcrypt.checkpw(password.encode(), bcrypt.hashpw(b"x", bcrypt.gensalt()))
        return None
    if not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        return None
    return row["id"]


def create_session(conn, user_id):
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


def get_user_by_token(conn, token):
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


def update_streak(conn, user_id):
    row = conn.execute(
        "SELECT streak_days, last_activity_date FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return 0

    today = date.today()
    last = row["last_activity_date"]
    streak = row["streak_days"] or 0

    if last == today.isoformat():
        return streak
    if last == (today - timedelta(days=1)).isoformat():
        streak += 1
    else:
        streak = 1

    conn.execute(
        "UPDATE users SET streak_days = ?, last_activity_date = ? WHERE id = ?",
        (streak, today.isoformat(), user_id),
    )
    conn.commit()
    return streak