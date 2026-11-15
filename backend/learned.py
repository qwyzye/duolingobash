"""learned_words + начисление очков. Единый источник истины для users.points/level."""
import sqlite3
from datetime import datetime


def get_learned_ids(conn: sqlite3.Connection, user_id: int) -> set[int]:
    rows = conn.execute(
        "SELECT fragment_id FROM learned_words WHERE user_id = ?", (user_id,)
    ).fetchall()
    return {r["fragment_id"] for r in rows}


def record_seen(conn, user_id, fragment_id):
    conn.execute(
        "INSERT INTO learned_words (user_id, fragment_id, seen_count) "
        "VALUES (?, ?, 1) "
        "ON CONFLICT(user_id, fragment_id) DO UPDATE SET seen_count = seen_count + 1",
        (user_id, fragment_id),
    )
    conn.commit()


def record_correct(conn, user_id, fragment_id):
    conn.execute(
        "INSERT INTO learned_words (user_id, fragment_id, seen_count, correct_count) "
        "VALUES (?, ?, 1, 1) "
        "ON CONFLICT(user_id, fragment_id) DO UPDATE SET "
        "seen_count = seen_count + 1, correct_count = correct_count + 1",
        (user_id, fragment_id),
    )
    conn.commit()


def mark_learned(conn, user_id, fragment_id):
    conn.execute(
        "INSERT OR IGNORE INTO learned_words "
        "(user_id, fragment_id, seen_count, correct_count) VALUES (?, ?, 1, 1)",
        (user_id, fragment_id),
    )
    conn.commit()


def recalculate_level(conn, user_id: int) -> dict:
    """Пересчитывает points = SUM(points_events) и level = points//100 + 1.
       Возвращает {points, level}.
    """
    row = conn.execute(
        "SELECT COALESCE(SUM(points), 0) AS total FROM points_events WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    total = row["total"] if row else 0
    level = total // 100 + 1
    conn.execute(
        "UPDATE users SET points = ?, level = ? WHERE id = ?",
        (total, level, user_id),
    )
    conn.commit()
    return {"points": total, "level": level}


def award_points_event(conn, user_id, event_type, event_key, points):
    """Идемпотентно: (user_id, event_type, event_key) уникально.
       Возвращает {points, level, already_awarded}.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        conn.execute(
            "INSERT INTO points_events(user_id, event_type, event_key, points, date) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, event_type, str(event_key), points, today),
        )
        inserted = True
    except sqlite3.IntegrityError:
        inserted = False

    if inserted and points:
        conn.execute(
            "INSERT INTO history(user_id, points, date) VALUES (?, ?, ?)",
            (user_id, points, today),
        )
    conn.commit()

    return {**recalculate_level(conn, user_id), "already_awarded": not inserted}


def award_points(conn, user_id, points):
    """Совместимость со старым API. points = users.id (не telegram_id)."""
    return award_points_event(
        conn, user_id, "generic", f"gen_{datetime.now().timestamp()}", points
    )