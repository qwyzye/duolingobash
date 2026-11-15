import sqlite3
import re
import logging
from datetime import datetime, timedelta
from pathlib import Path

from backend.db import get_connection, init_db as _init_schema

logger = logging.getLogger(__name__)

DAILY_LIMIT = 5
CONFIRM_THRESHOLD = 3


def _conn():
    return get_connection()


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text)
    return text


def init_db():
    _init_schema()


# ---------------- USERS ----------------

def _get_row_by_tg(user_id):
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row


def add_user(user_id, username, first_name):
    conn = _conn()
    conn.execute(
        """INSERT OR IGNORE INTO users(telegram_id, username, first_name)
           VALUES (?, ?, ?)""",
        (user_id, username or None, first_name or "User"),
    )
    conn.commit()
    conn.close()


def get_user(user_id):
    """Возвращает dict из users по telegram_id (совместимо со старым API)."""
    row = _get_row_by_tg(user_id)
    if not row:
        return None
    d = dict(row)
    # алиасы для совместимости со старым кодом бота
    d["user_id"] = d["telegram_id"]
    d["site_login"] = d.get("username")
    d["site_password"] = None
    return d


def get_or_create_user(user_id, username=None, first_name=None):
    user = get_user(user_id)
    if user:
        return user
    if not first_name:
        return None
    add_user(user_id, username or "NoName", first_name)
    return get_user(user_id)


def update_lang_pair(user_id, lang_pair):
    conn = _conn()
    conn.execute(
        "UPDATE users SET lang_pair = ? WHERE telegram_id = ?",
        (lang_pair, user_id),
    )
    conn.commit()
    conn.close()


def update_credentials(user_id, login, password):
    conn = _conn()
    conn.execute(
        "UPDATE users SET username = ? WHERE telegram_id = ?",
        (login, user_id),
    )
    conn.commit()
    conn.close()


def check_daily_limit(user_id):
    user = get_user(user_id)
    if not user:
        return False
    today = datetime.now().strftime("%Y-%m-%d")
    if user.get("last_activity_date") != today:
        conn = _conn()
        conn.execute(
            "UPDATE users SET last_activity_date = ? WHERE telegram_id = ?",
            (today, user_id),
        )
        conn.commit()
        conn.close()
        return True
    return True


def increment_daily_count(user_id):
    pass


# ---------------- POINTS ----------------

def award_points(user_id, event_type, event_key, points):
    """Пишет в points_events + history, обновляет users.points и level."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (user_id,)
        ).fetchone()
        if not row:
            return 1
        pk = row["id"]

        try:
            conn.execute(
                "INSERT INTO points_events(user_id, event_type, event_key, points, date) "
                "VALUES (?, ?, ?, ?, ?)",
                (pk, event_type, str(event_key), points, today),
            )
        except sqlite3.IntegrityError:
            row2 = conn.execute(
                "SELECT level FROM users WHERE id = ?", (pk,)
            ).fetchone()
            return row2["level"] if row2 else 1

        if points:
            conn.execute(
                "UPDATE users SET points = points + ? WHERE id = ?",
                (points, pk),
            )
            conn.execute(
                "UPDATE users SET level = (points / 100) + 1 WHERE id = ?",
                (pk,),
            )
            conn.execute(
                "INSERT INTO history(user_id, points, date) VALUES (?, ?, ?)",
                (pk, points, today),
            )
        conn.commit()
        row2 = conn.execute("SELECT level FROM users WHERE id = ?", (pk,)).fetchone()
        return row2["level"] if row2 else 1
    finally:
        conn.close()


def count_events_today(user_id, event_types):
    if not event_types:
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    ph = ",".join("?" * len(event_types))
    conn = _conn()
    row = conn.execute(
        f"""SELECT COUNT(*) FROM points_events pe
            JOIN users u ON u.id = pe.user_id
            WHERE u.telegram_id = ? AND pe.date = ?
              AND pe.event_type IN ({ph})""",
        (user_id, today, *event_types),
    ).fetchone()
    conn.close()
    return row[0] if row else 0


# ---------------- FRAGMENTS ----------------

def get_fragment_by_level(level):
    conn = _conn()
    bounds = {1: (10, 30), 2: (25, 50), 3: (45, 70), 4: (65, 100)}
    mn, mx = bounds.get(level, (90, 200))
    row = conn.execute(
        "SELECT * FROM fragments WHERE LENGTH(text_ba) BETWEEN ? AND ? "
        "ORDER BY RANDOM() LIMIT 1",
        (mn, mx),
    ).fetchone()
    if not row:
        row = conn.execute("SELECT * FROM fragments ORDER BY RANDOM() LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


def get_fragment(fragment_id):
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM fragments WHERE fragment_id = ?", (fragment_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def is_fragment_parsed(fragment_id):
    conn = _conn()
    row = conn.execute(
        "SELECT is_parsed FROM fragments WHERE fragment_id = ?", (fragment_id,)
    ).fetchone()
    conn.close()
    return bool(row[0]) if row else False


def get_best_translation(fragment_id, lang_pair):
    conn = _conn()
    row = conn.execute(
        """SELECT * FROM translations
           WHERE fragment_id=? AND lang_pair=?
             AND status IN ('confirmed','pending')
           ORDER BY (status='confirmed') DESC, confirmed DESC LIMIT 1""",
        (fragment_id, lang_pair),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------- TRANSLATIONS ----------------

def upsert_translation(fragment_id, lang_pair, text_ba, source,
                       translation, user_id, vote_type="confirm"):
    normalized = normalize_text(translation)
    now = _now()
    conn = _conn()
    cur = conn.cursor()

    frag = cur.execute(
        "SELECT is_parsed FROM fragments WHERE fragment_id=?", (fragment_id,)
    ).fetchone()
    if frag and frag["is_parsed"]:
        conn.close()
        return None, 0, "parsed_locked", False

    # приводим telegram_id к users.id
    u = cur.execute(
        "SELECT id FROM users WHERE telegram_id = ?", (user_id,)
    ).fetchone()
    if u:
        internal_uid = u["id"]
    else:
        cur.execute(
            "INSERT INTO users(telegram_id, first_name) VALUES (?, 'User')",
            (user_id,),
        )
        internal_uid = cur.lastrowid

    row = cur.execute(
        "SELECT id, confirmed FROM translations "
        "WHERE fragment_id=? AND lang_pair=? AND normalized=? AND status != 'rejected'",
        (fragment_id, lang_pair, normalized),
    ).fetchone()

    if row:
        trans_id, confirmed = row["id"], row["confirmed"]
        already = cur.execute(
            "SELECT 1 FROM translation_votes WHERE translation_id=? AND user_id=?",
            (trans_id, internal_uid),
        ).fetchone() is not None
        if already:
            conn.close()
            return trans_id, confirmed, "already_voted", True
    else:
        cur.execute(
            """INSERT INTO translations(fragment_id, user_id, lang_pair, text_ba,
                source, translation, normalized, confirmed, status, is_parsed,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'pending', 0, ?, ?)""",
            (fragment_id, internal_uid, lang_pair, text_ba, source,
             translation, normalized, now, now),
        )
        trans_id = cur.lastrowid

    try:
        cur.execute(
            "INSERT INTO translation_votes(translation_id, user_id, vote_type, created_at) "
            "VALUES (?, ?, ?, ?)",
            (trans_id, internal_uid, vote_type, now),
        )
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        return trans_id, 0, "already_voted", True

    cur.execute(
        "UPDATE translations SET confirmed = confirmed + 1, updated_at=? WHERE id=?",
        (now, trans_id),
    )
    confirmed = cur.execute(
        "SELECT confirmed FROM translations WHERE id=?", (trans_id,)
    ).fetchone()[0]
    if confirmed >= CONFIRM_THRESHOLD:
        cur.execute(
            "UPDATE translations SET status='confirmed' WHERE id=?", (trans_id,)
        )
    conn.commit()
    conn.close()
    return (
        trans_id, confirmed,
        "confirmed" if confirmed >= CONFIRM_THRESHOLD else "pending",
        False,
    )


def save_to_expert_review(fragment_id, user_id, translation, lang_pair, text_ba, source):
    now = _now()
    conn = _conn()
    cur = conn.cursor()

    u = cur.execute("SELECT id FROM users WHERE telegram_id = ?", (user_id,)).fetchone()
    internal_uid = u["id"] if u else None

    cur.execute(
        """INSERT INTO translations(fragment_id, user_id, lang_pair, text_ba,
            source, translation, normalized, confirmed, status, is_parsed,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'expert_review', 0, ?, ?)""",
        (fragment_id, internal_uid, lang_pair, text_ba, source,
         translation, normalize_text(translation), now, now),
    )
    tid = cur.lastrowid
    conn.commit()
    conn.close()
    return tid


# ---------------- DICTIONARY ----------------

def insert_parsed_fragment(text_ba, source, lang_pair="ba-ru"):
    now = _now()
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO fragments(text_ba, lang_pair, source, is_parsed, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (text_ba, lang_pair, source, now),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def upsert_dictionary(word, translation, lang_pair="ba-ru", is_parsed=0, source=None):
    if not word or not translation:
        return False
    now = _now()
    status = "confirmed" if is_parsed else "pending"
    confirmed = 999 if is_parsed else 0
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT OR IGNORE INTO dictionary(word, translation, lang_pair,
            is_parsed, status, source, confirmed, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (word, translation, lang_pair, is_parsed, status, source, confirmed, now),
    )
    added = cur.rowcount > 0
    conn.commit()
    conn.close()
    return added


def save_dictionary_suggestion(word, suggestion, lang_pair="ba-ru", user_id=None, source=None):
    if not word or not suggestion:
        return None
    now = _now()
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO dictionary(word, translation, lang_pair,
            is_parsed, status, source, confirmed, created_at)
           VALUES (?, ?, ?, 0, 'expert_review', ?, 0, ?)""",
        (word, suggestion, lang_pair, source, now),
    )
    tid = cur.lastrowid
    conn.commit()
    conn.close()
    return tid


def get_dictionary_word(word, lang_pair="ba-ru"):
    conn = _conn()
    row = conn.execute(
        """SELECT * FROM dictionary WHERE word=? AND lang_pair=?
           ORDER BY is_parsed DESC, confirmed DESC LIMIT 1""",
        (word, lang_pair),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_dictionary_review(limit=10):
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM dictionary WHERE status='expert_review' "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------- VOCABULARY ----------------

def add_learned_word(user_id, word, translation):
    if not word or word == "null":
        return
    conn = _conn()
    u = conn.execute(
        "SELECT id FROM users WHERE telegram_id = ?", (user_id,)
    ).fetchone()
    if not u:
        conn.close()
        return
    conn.execute(
        "INSERT OR IGNORE INTO vocabulary(user_id, word, translation, created_at) "
        "VALUES (?, ?, ?, ?)",
        (u["id"], word, translation, _now()),
    )
    conn.commit()
    conn.close()


def get_user_words(user_id):
    conn = _conn()
    rows = conn.execute(
        """SELECT v.word FROM vocabulary v
           JOIN users u ON u.id = v.user_id
           WHERE u.telegram_id = ?""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def update_progress(user_id, points):
    return award_points(user_id, "lesson_correct", f"lesson_{_now()}", points)


# ---------------- LEADERBOARD ----------------

def get_leaderboard(timeframe: str):
    today = datetime.now()
    if timeframe == "today":
        start_date = today.strftime("%Y-%m-%d")
    elif timeframe == "week":
        start_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    elif timeframe == "month":
        start_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    elif timeframe == "year":
        start_date = (today - timedelta(days=365)).strftime("%Y-%m-%d")
    else:
        start_date = "2000-01-01"

    conn = _conn()
    rows = conn.execute(
        """SELECT u.first_name,
                  COALESCE(NULLIF(u.username,''), u.first_name) AS name,
                  SUM(h.points) AS total_points
           FROM history h JOIN users u ON h.user_id = u.id
           WHERE h.date >= ?
           GROUP BY u.id
           ORDER BY total_points DESC LIMIT 10""",
        (start_date,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------- LESSON PROGRESS ----------------

def complete_lesson(user_id, lesson_id, xp):
    return award_points(user_id, "lesson_complete", f"lesson_{lesson_id}", xp)


def get_completed_lessons(user_id):
    conn = _conn()
    rows = conn.execute(
        """SELECT pe.event_key FROM points_events pe
           JOIN users u ON u.id = pe.user_id
           WHERE u.telegram_id = ? AND pe.event_type='lesson_complete'""",
        (user_id,),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        k = r["event_key"]
        if k and k.startswith("lesson_"):
            try:
                out.append(int(k[len("lesson_"):]))
            except ValueError:
                pass
    return sorted(set(out))


def get_full_progress(user_id):
    user = get_user(user_id) or {}
    return {
        "user_id": user_id,
        "first_name": user.get("first_name"),
        "site_login": user.get("username"),
        "xp": user.get("points", 0),
        "level": user.get("level", 1),
        "done_lessons": get_completed_lessons(user_id),
    }


# ---------------- ПУБЛИЧНЫЕ КОНСТАНТЫ (совместимость) ----------------

from pathlib import Path as _Path
CONTENT_DB = _Path(__file__).resolve().parent.parent / "app.db"
USERS_DB = CONTENT_DB