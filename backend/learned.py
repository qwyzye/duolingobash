"""Список изученных слов пользователя (app.db)."""
import sqlite3


def get_learned_ids(conn: sqlite3.Connection, user_id: int) -> set[int]:
    rows = conn.execute(
        "SELECT fragment_id FROM learned_words WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    return {r["fragment_id"] for r in rows}


def record_seen(conn: sqlite3.Connection, user_id: int, fragment_id: int) -> None:
    conn.execute(
        "INSERT INTO learned_words (user_id, fragment_id, seen_count) "
        "VALUES (?, ?, 1) "
        "ON CONFLICT(user_id, fragment_id) DO UPDATE SET seen_count = seen_count + 1",
        (user_id, fragment_id),
    )
    conn.commit()


def record_correct(conn: sqlite3.Connection, user_id: int, fragment_id: int) -> None:
    conn.execute(
        "INSERT INTO learned_words (user_id, fragment_id, seen_count, correct_count) "
        "VALUES (?, ?, 1, 1) "
        "ON CONFLICT(user_id, fragment_id) DO UPDATE SET "
        "seen_count = seen_count + 1, correct_count = correct_count + 1",
        (user_id, fragment_id),
    )
    conn.commit()


def mark_learned(conn: sqlite3.Connection, user_id: int, fragment_id: int) -> None:
    """Явно пометить слово как изученное (например, после 3 правильных ответов)."""
    conn.execute(
        "INSERT OR IGNORE INTO learned_words (user_id, fragment_id, seen_count, correct_count) "
        "VALUES (?, ?, 1, 1)",
        (user_id, fragment_id),
    )
    conn.commit()


def is_learned(conn: sqlite3.Connection, user_id: int, fragment_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM learned_words WHERE user_id = ? AND fragment_id = ?",
        (user_id, fragment_id),
    ).fetchone()
    return row is not None