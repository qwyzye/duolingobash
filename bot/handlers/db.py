import sqlite3
import re
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
USERS_DB = BASE_DIR / "users.db"
CONTENT_DB = BASE_DIR / "content.db"

DAILY_LIMIT = 5
CONFIRM_THRESHOLD = 3


def _conn(path):
    c = sqlite3.connect(str(path))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


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
    u = _conn(USERS_DB)
    uc = u.cursor()
    uc.execute("""CREATE TABLE IF NOT EXISTS users(
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
    uc.execute("""CREATE TABLE IF NOT EXISTS points_events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        event_key TEXT NOT NULL,
        points INTEGER DEFAULT 0,
        date TEXT,
        UNIQUE(user_id, event_type, event_key)
    )""")
    uc.execute("""CREATE TABLE IF NOT EXISTS history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        points INTEGER,
        date TEXT
    )""")
    uc.execute("""CREATE TABLE IF NOT EXISTS vocabulary(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        word TEXT,
        translation TEXT,
        created_at TEXT,
        UNIQUE(user_id, word)
    )""")
    uc.execute("CREATE INDEX IF NOT EXISTS ix_points_events_ud ON points_events(user_id, date)")
    u.commit()
    u.close()

    c = _conn(CONTENT_DB)
    cc = c.cursor()
    cc.execute("""CREATE TABLE IF NOT EXISTS fragments(
        fragment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        text_ba TEXT UNIQUE,
        lang_pair TEXT DEFAULT 'ba-ru',
        source TEXT,
        is_parsed INTEGER DEFAULT 0,
        created_at TEXT
    )""")
    cc.execute("""CREATE TABLE IF NOT EXISTS translations(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fragment_id INTEGER,
        user_id INTEGER,
        lang_pair TEXT,
        text_ba TEXT,
        source TEXT,
        translation TEXT,
        normalized TEXT,
        confirmed INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',
        is_parsed INTEGER DEFAULT 0,
        created_at TEXT,
        updated_at TEXT
    )""")
    cc.execute("""CREATE TABLE IF NOT EXISTS translation_votes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        translation_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        vote_type TEXT NOT NULL,
        created_at TEXT,
        UNIQUE(translation_id, user_id)
    )""")
    cc.execute("""CREATE TABLE IF NOT EXISTS dictionary(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word TEXT NOT NULL,
        translation TEXT NOT NULL,
        lang_pair TEXT DEFAULT 'ba-ru',
        is_parsed INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',
        source TEXT,
        confirmed INTEGER DEFAULT 0,
        created_at TEXT,
        UNIQUE(word, translation, lang_pair)
    )""")
    cc.execute("CREATE INDEX IF NOT EXISTS ix_translations_lookup ON translations(fragment_id, lang_pair, normalized)")
    cc.execute("CREATE INDEX IF NOT EXISTS ix_dictionary_word ON dictionary(word, lang_pair)")
    c.commit()
    c.close()


# ---------------- USERS ----------------

def add_user(user_id, username, first_name):
    u = _conn(USERS_DB)
    u.execute("INSERT OR IGNORE INTO users(user_id, username, first_name) VALUES (?, ?, ?)",
              (user_id, username or "NoName", first_name or "User"))
    u.commit()
    u.close()


def get_user(user_id):
    u = _conn(USERS_DB)
    row = u.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    u.close()
    return dict(row) if row else None


def get_or_create_user(user_id, username=None, first_name=None):
    user = get_user(user_id)
    if user:
        return user
    if not first_name:
        return None
    add_user(user_id, username or "NoName", first_name)
    return get_user(user_id)


def update_lang_pair(user_id, lang_pair):
    u = _conn(USERS_DB)
    u.execute("UPDATE users SET lang_pair=? WHERE user_id=?", (lang_pair, user_id))
    u.commit()
    u.close()


def update_credentials(user_id, login, password):
    u = _conn(USERS_DB)
    u.execute("UPDATE users SET site_login=?, site_password=? WHERE user_id=?",
              (login, password, user_id))
    u.commit()
    u.close()


def check_daily_limit(user_id):
    user = get_user(user_id)
    if not user:
        return False
    today = datetime.now().strftime("%Y-%m-%d")
    if user.get("last_daily") != today:
        u = _conn(USERS_DB)
        u.execute("UPDATE users SET last_daily=?, daily_count=0 WHERE user_id=?", (today, user_id))
        u.commit()
        u.close()
        return True
    return user.get("daily_count", 0) < DAILY_LIMIT


def increment_daily_count(user_id):
    u = _conn(USERS_DB)
    u.execute("UPDATE users SET daily_count = daily_count + 1 WHERE user_id=?", (user_id,))
    u.commit()
    u.close()


# ---------------- POINTS ----------------

def award_points(user_id, event_type, event_key, points):
    today = datetime.now().strftime("%Y-%m-%d")
    u = _conn(USERS_DB)
    cur = u.cursor()
    try:
        cur.execute(
            "INSERT INTO points_events(user_id, event_type, event_key, points, date) VALUES (?, ?, ?, ?, ?)",
            (user_id, event_type, str(event_key), points, today),
        )
        if points:
            cur.execute("UPDATE users SET points = points + ? WHERE user_id=?", (points, user_id))
            cur.execute("UPDATE users SET level = (points / 100) + 1 WHERE user_id=?", (user_id,))
            cur.execute("INSERT INTO history(user_id, points, date) VALUES (?, ?, ?)",
                        (user_id, points, today))
        u.commit()
    except sqlite3.IntegrityError:
        pass
    finally:
        row = cur.execute("SELECT level FROM users WHERE user_id=?", (user_id,)).fetchone()
        u.close()
    return row[0] if row else 1


def count_events_today(user_id, event_types):
    if not event_types:
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    ph = ",".join("?" * len(event_types))
    u = _conn(USERS_DB)
    row = u.execute(
        f"SELECT COUNT(*) FROM points_events WHERE user_id=? AND date=? AND event_type IN ({ph})",
        (user_id, today, *event_types),
    ).fetchone()
    u.close()
    return row[0] if row else 0


# ---------------- FRAGMENTS ----------------

def get_fragment_by_level(level):
    c = _conn(CONTENT_DB)
    bounds = {1: (10, 30), 2: (25, 50), 3: (45, 70), 4: (65, 100)}
    mn, mx = bounds.get(level, (90, 200))
    row = c.execute(
        "SELECT * FROM fragments WHERE LENGTH(text_ba) BETWEEN ? AND ? ORDER BY RANDOM() LIMIT 1",
        (mn, mx),
    ).fetchone()
    if not row:
        row = c.execute("SELECT * FROM fragments ORDER BY RANDOM() LIMIT 1").fetchone()
    c.close()
    return dict(row) if row else None


def get_fragment(fragment_id):
    c = _conn(CONTENT_DB)
    row = c.execute("SELECT * FROM fragments WHERE fragment_id=?", (fragment_id,)).fetchone()
    c.close()
    return dict(row) if row else None


def is_fragment_parsed(fragment_id):
    c = _conn(CONTENT_DB)
    row = c.execute("SELECT is_parsed FROM fragments WHERE fragment_id=?", (fragment_id,)).fetchone()
    c.close()
    return bool(row[0]) if row else False


def get_best_translation(fragment_id, lang_pair):
    c = _conn(CONTENT_DB)
    row = c.execute(
        """SELECT * FROM translations
           WHERE fragment_id=? AND lang_pair=? AND status IN ('confirmed','pending')
           ORDER BY (status='confirmed') DESC, confirmed DESC LIMIT 1""",
        (fragment_id, lang_pair),
    ).fetchone()
    c.close()
    return dict(row) if row else None


# ---------------- TRANSLATIONS ----------------

def upsert_translation(fragment_id, lang_pair, text_ba, source, translation, user_id, vote_type="confirm"):
    normalized = normalize_text(translation)
    now = _now()
    c = _conn(CONTENT_DB)
    cur = c.cursor()

    frag = cur.execute("SELECT is_parsed FROM fragments WHERE fragment_id=?", (fragment_id,)).fetchone()
    if frag and frag[0]:
        c.close()
        return None, 0, "parsed_locked", False

    row = cur.execute(
        "SELECT id, confirmed FROM translations WHERE fragment_id=? AND lang_pair=? AND normalized=? AND status != 'rejected'",
        (fragment_id, lang_pair, normalized),
    ).fetchone()

    if row:
        trans_id, confirmed = row[0], row[1]
        already = cur.execute(
            "SELECT 1 FROM translation_votes WHERE translation_id=? AND user_id=?",
            (trans_id, user_id),
        ).fetchone() is not None
        if already:
            c.close()
            return trans_id, confirmed, "already_voted", True
    else:
        cur.execute(
            """INSERT INTO translations(fragment_id, user_id, lang_pair, text_ba, source, translation,
               normalized, confirmed, status, is_parsed, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'pending', 0, ?, ?)""",
            (fragment_id, user_id, lang_pair, text_ba, source, translation, normalized, now, now),
        )
        trans_id = cur.lastrowid

    try:
        cur.execute(
            "INSERT INTO translation_votes(translation_id, user_id, vote_type, created_at) VALUES (?, ?, ?, ?)",
            (trans_id, user_id, vote_type, now),
        )
    except sqlite3.IntegrityError:
        c.rollback()
        c.close()
        return trans_id, 0, "already_voted", True

    cur.execute("UPDATE translations SET confirmed = confirmed + 1, updated_at=? WHERE id=?", (now, trans_id))
    confirmed = cur.execute("SELECT confirmed FROM translations WHERE id=?", (trans_id,)).fetchone()[0]
    if confirmed >= CONFIRM_THRESHOLD:
        cur.execute("UPDATE translations SET status='confirmed' WHERE id=?", (trans_id,))
    c.commit()
    c.close()
    return trans_id, confirmed, "confirmed" if confirmed >= CONFIRM_THRESHOLD else "pending", False


def save_to_expert_review(fragment_id, user_id, translation, lang_pair, text_ba, source):
    now = _now()
    c = _conn(CONTENT_DB)
    cur = c.cursor()
    cur.execute(
        """INSERT INTO translations(fragment_id, user_id, lang_pair, text_ba, source, translation,
           normalized, confirmed, status, is_parsed, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'expert_review', 0, ?, ?)""",
        (fragment_id, user_id, lang_pair, text_ba, source, translation,
         normalize_text(translation), now, now),
    )
    tid = cur.lastrowid
    c.commit()
    c.close()
    return tid


# ---------------- DICTIONARY ----------------

def insert_parsed_fragment(text_ba, source, lang_pair="ba-ru"):
    now = _now()
    c = _conn(CONTENT_DB)
    cur = c.cursor()
    try:
        cur.execute(
            "INSERT OR IGNORE INTO fragments(text_ba, lang_pair, source, is_parsed, created_at) VALUES (?, ?, ?, 1, ?)",
            (text_ba, lang_pair, source, now),
        )
        added = cur.rowcount > 0
        c.commit()
    except Exception:
        c.rollback()
        added = False
    finally:
        c.close()
    return added


def upsert_dictionary(word, translation, lang_pair="ba-ru", is_parsed=0, source=None):
    if not word or not translation:
        return False
    now = _now()
    status = "confirmed" if is_parsed else "pending"
    confirmed = 999 if is_parsed else 0
    c = _conn(CONTENT_DB)
    cur = c.cursor()
    try:
        cur.execute(
            """INSERT OR IGNORE INTO dictionary(word, translation, lang_pair, is_parsed, status, source, confirmed, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (word, translation, lang_pair, is_parsed, status, source, confirmed, now),
        )
        added = cur.rowcount > 0
        c.commit()
    except Exception:
        c.rollback()
        added = False
    finally:
        c.close()
    return added


def save_dictionary_suggestion(word, suggestion, lang_pair="ba-ru", user_id=None, source=None):
    if not word or not suggestion:
        return None
    now = _now()
    c = _conn(CONTENT_DB)
    cur = c.cursor()
    cur.execute(
        """INSERT INTO dictionary(word, translation, lang_pair, is_parsed, status, source, confirmed, created_at)
           VALUES (?, ?, ?, 0, 'expert_review', ?, 0, ?)""",
        (word, suggestion, lang_pair, source, now),
    )
    tid = cur.lastrowid
    c.commit()
    c.close()
    return tid


def get_dictionary_word(word, lang_pair="ba-ru"):
    c = _conn(CONTENT_DB)
    row = c.execute(
        """SELECT * FROM dictionary WHERE word=? AND lang_pair=?
           ORDER BY is_parsed DESC, confirmed DESC LIMIT 1""",
        (word, lang_pair),
    ).fetchone()
    c.close()
    return dict(row) if row else None


def get_dictionary_review(limit=10):
    c = _conn(CONTENT_DB)
    rows = c.execute(
        "SELECT * FROM dictionary WHERE status='expert_review' ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


# ---------------- VOCABULARY ----------------

def add_learned_word(user_id, word, translation):
    if not word or word == "null":
        return
    u = _conn(USERS_DB)
    u.execute(
        "INSERT OR IGNORE INTO vocabulary(user_id, word, translation, created_at) VALUES (?, ?, ?, ?)",
        (user_id, word, translation, _now()),
    )
    u.commit()
    u.close()


def get_user_words(user_id):
    u = _conn(USERS_DB)
    rows = u.execute("SELECT word FROM vocabulary WHERE user_id=?", (user_id,)).fetchall()
    u.close()
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
    u = _conn(USERS_DB)
    rows = u.execute(
        """SELECT u.first_name, SUM(h.points) as total_points
           FROM history h JOIN users u ON h.user_id = u.user_id
           WHERE h.date >= ? GROUP BY h.user_id ORDER BY total_points DESC LIMIT 10""",
        (start_date,),
    ).fetchall()
    u.close()
    return rows


# ---------------- LESSON PROGRESS (mini app) ----------------

def complete_lesson(user_id, lesson_id, xp):
    """Начисляет XP за пройденный урок из мини-апп. Возвращает новый level."""
    return award_points(user_id, "lesson_complete", f"lesson_{lesson_id}", xp)


def get_completed_lessons(user_id):
    """Список пройденных lesson_id из БД."""
    u = _conn(USERS_DB)
    rows = u.execute(
        "SELECT event_key FROM points_events WHERE user_id=? AND event_type='lesson_complete'",
        (user_id,),
    ).fetchall()
    u.close()
    out = []
    for r in rows:
        k = r[0]
        if k and k.startswith("lesson_"):
            try:
                out.append(int(k[len("lesson_"):]))
            except ValueError:
                pass
    return sorted(set(out))


def get_full_progress(user_id):
    """Собирает всё, что нужно фронту."""
    user = get_user(user_id) or {}
    return {
        "user_id": user_id,
        "first_name": user.get("first_name"),
        "site_login": user.get("site_login"),
        "xp": user.get("points", 0),
        "level": user.get("level", 1),
        "done_lessons": get_completed_lessons(user_id),
    }