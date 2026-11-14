"""Доступ к content.db: фрагменты и переводы.
   Читает и пишет та же БД, что бот и Mini App.
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
CONTENT_DB = BASE_DIR / "content.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(CONTENT_DB), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_sources_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def init_sources_db():
    """Создаёт схему content.db, если её нет. Вызывается из seed/init."""
    conn = get_connection()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS fragments (
            fragment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            text_ba     TEXT UNIQUE,
            lang_pair   TEXT DEFAULT 'ba-ru',
            source      TEXT,
            is_parsed   INTEGER DEFAULT 0,
            created_at  TEXT
        );
        CREATE TABLE IF NOT EXISTS translations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            fragment_id INTEGER,
            user_id     INTEGER,
            lang_pair   TEXT,
            text_ba     TEXT,
            source      TEXT,
            translation TEXT,
            normalized  TEXT,
            confirmed   INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'pending',
            is_parsed   INTEGER DEFAULT 0,
            created_at  TEXT,
            updated_at  TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_translations_lookup
            ON translations(fragment_id, lang_pair, normalized);
        CREATE TABLE IF NOT EXISTS translation_votes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            translation_id  INTEGER NOT NULL,
            user_id         INTEGER NOT NULL,
            vote_type       TEXT NOT NULL,
            created_at      TEXT,
            UNIQUE(translation_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS dictionary (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            word        TEXT NOT NULL,
            translation TEXT NOT NULL,
            lang_pair   TEXT DEFAULT 'ba-ru',
            is_parsed   INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'pending',
            source      TEXT,
            confirmed   INTEGER DEFAULT 0,
            created_at  TEXT,
            UNIQUE(word, translation, lang_pair)
        );
        CREATE INDEX IF NOT EXISTS idx_dictionary_word ON dictionary(word, lang_pair);
        """)
        conn.commit()
    finally:
        conn.close()


def _normalize(text: str) -> str:
    import re
    t = (text or "").lower().strip()
    t = re.sub(r"[^\w\s]", "", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t)
    return t


# ---------- чтение ----------

def random_fragment(
    conn: sqlite3.Connection,
    lang_pair: str = "ba-ru",
    exclude_ids: set[int] | None = None,
) -> Optional[dict]:
    exclude_ids = exclude_ids or set()
    placeholders = ",".join("?" * len(exclude_ids)) if exclude_ids else "0"
    row = conn.execute(
        f"""SELECT f.fragment_id, f.text_ba, f.lang_pair, f.source
            FROM fragments f
            WHERE f.lang_pair = ?
              AND f.fragment_id NOT IN ({placeholders})
              AND EXISTS (
                  SELECT 1 FROM translations t
                  WHERE t.fragment_id = f.fragment_id
                    AND t.lang_pair = f.lang_pair
                    AND t.status = 'confirmed'
              )
            ORDER BY RANDOM() LIMIT 1""",
        (lang_pair, *exclude_ids),
    ).fetchone()
    return dict(row) if row else None


def get_confirmed_translation(
    conn: sqlite3.Connection, fragment_id: int, lang_pair: str = "ba-ru"
) -> Optional[dict]:
    row = conn.execute(
        """SELECT id, translation, confirmed
           FROM translations
           WHERE fragment_id = ? AND lang_pair = ? AND status = 'confirmed'
           ORDER BY confirmed DESC, id ASC
           LIMIT 1""",
        (fragment_id, lang_pair),
    ).fetchone()
    return dict(row) if row else None


def random_distractors(
    conn: sqlite3.Connection,
    exclude_fragment_id: int,
    lang_pair: str = "ba-ru",
    limit: int = 3,
) -> list[str]:
    rows = conn.execute(
        """SELECT DISTINCT translation
           FROM translations
           WHERE lang_pair = ? AND fragment_id != ? AND status = 'confirmed'
           ORDER BY RANDOM() LIMIT ?""",
        (lang_pair, exclude_fragment_id, limit),
    ).fetchall()
    return [r["translation"] for r in rows]


def get_or_create_translation_with_ai(
    fragment_id: int, text_ba: str, lang_pair: str = "ba-ru"
) -> Optional[str]:
    """Сначала ищет confirmed; если нет — pending/expert_review;
       если нет — зовёт Gemini и сохраняет как pending.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT translation FROM translations
               WHERE fragment_id = ? AND lang_pair = ?
                 AND status IN ('confirmed','pending','expert_review')
               ORDER BY (status='confirmed') DESC, confirmed DESC, id ASC
               LIMIT 1""",
            (fragment_id, lang_pair),
        ).fetchone()
        if row and row["translation"]:
            return row["translation"]
    finally:
        conn.close()

    # AI
    import asyncio
    try:
        from handlers.ai import translate_fragment
        translation = asyncio.run(translate_fragment(text_ba))
    except RuntimeError:
        # running loop — уходим в поток
        import concurrent.futures
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                translation = pool.submit(
                    lambda: asyncio.run(translate_fragment(text_ba))
                ).result(timeout=30)
        except Exception:
            translation = None
    except Exception:
        translation = None

    if not translation:
        return None

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO translations(fragment_id, user_id, lang_pair, text_ba,
                source, translation, normalized, confirmed, status, is_parsed,
                created_at, updated_at)
               VALUES (?, NULL, ?, ?, 'ai', ?, ?, 1, 'pending', 0, ?, ?)""",
            (fragment_id, lang_pair, text_ba, translation,
             _normalize(translation), now, now),
        )
        conn.commit()
    finally:
        conn.close()

    return translation


# ---------- запись ----------

def create(conn, text_ba, translation, lang_pair="ba-ru",
           source="seed", confirmed=5, status="confirmed"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        """INSERT OR IGNORE INTO fragments(text_ba, lang_pair, source, is_parsed, created_at)
           VALUES (?, ?, ?, 1, ?)""",
        (text_ba, lang_pair, source, now),
    )
    if cur.lastrowid:
        fid = cur.lastrowid
    else:
        row = conn.execute(
            "SELECT fragment_id FROM fragments WHERE text_ba = ?", (text_ba,)
        ).fetchone()
        if not row:
            raise RuntimeError(f"Не удалось создать фрагмент: {text_ba!r}")
        fid = row["fragment_id"]

    conn.execute(
        """INSERT INTO translations(fragment_id, user_id, lang_pair, text_ba,
            source, translation, normalized, confirmed, status, is_parsed,
            created_at, updated_at)
           VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
        (fid, lang_pair, text_ba, source, translation,
         _normalize(translation), confirmed, status, now, now),
    )
    conn.commit()
    return fid


def save_dispute(
    conn: sqlite3.Connection,
    fragment_id: int,
    user_id: int,
    translation: str,
    lang_pair: str,
    text_ba: str,
    source: str = "site",
) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        """INSERT INTO translations(
               fragment_id, user_id, lang_pair, text_ba, source,
               translation, normalized, confirmed, status, is_parsed,
               created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'expert_review', 0, ?, ?)""",
        (fragment_id, user_id, lang_pair, text_ba, source,
         translation, _normalize(translation), now, now),
    )
    conn.commit()
    return cur.lastrowid
def random_short_fragment(conn, lang_pair="ba-ru", exclude_ids=None):
    """Фрагмент 1–3 слова (короткий) с confirmed-переводом, не из exclude_ids.
       Если таких нет — fallback на любой confirmed."""
    exclude_ids = exclude_ids or set()
    ph = ",".join("?" * len(exclude_ids)) if exclude_ids else "0"

    base = f"""SELECT f.fragment_id, f.text_ba, f.lang_pair, f.source
               FROM fragments f
               WHERE f.lang_pair = ?
                 AND f.fragment_id NOT IN ({ph})
                 AND LENGTH(TRIM(f.text_ba)) BETWEEN 1 AND 40
                 AND (LENGTH(f.text_ba) - LENGTH(REPLACE(f.text_ba, ' ', ''))) <= 2
                 AND EXISTS (
                     SELECT 1 FROM translations t
                     WHERE t.fragment_id = f.fragment_id
                       AND t.lang_pair = f.lang_pair
                       AND t.status = 'confirmed'
                 )
               ORDER BY RANDOM() LIMIT 1"""

    row = conn.execute(base, (lang_pair, *exclude_ids)).fetchone()
    if row:
        return dict(row)

    # fallback 1: любая короткая без confirmed (AI переведёт)
    row = conn.execute(
        f"""SELECT f.fragment_id, f.text_ba, f.lang_pair, f.source
            FROM fragments f
            WHERE f.lang_pair = ?
              AND f.fragment_id NOT IN ({ph})
              AND LENGTH(TRIM(f.text_ba)) BETWEEN 1 AND 40
              AND (LENGTH(f.text_ba) - LENGTH(REPLACE(f.text_ba, ' ', ''))) <= 2
            ORDER BY RANDOM() LIMIT 1""",
        (lang_pair, *exclude_ids),
    ).fetchone()
    if row:
        return dict(row)

    # fallback 2: любой confirmed (старое поведение)
    return random_fragment(conn, lang_pair, exclude_ids)


def random_short_distractors(conn, exclude_fragment_id, lang_pair="ba-ru", limit=3):
    """Дистракторы из коротких переводов (1–3 слова), чтобы не подсовывать
       длинные предложения к короткому слову."""
    rows = conn.execute(
        """SELECT DISTINCT t.translation
           FROM translations t
           JOIN fragments f ON f.fragment_id = t.fragment_id
           WHERE t.lang_pair = ?
             AND t.fragment_id != ?
             AND t.status = 'confirmed'
             AND LENGTH(TRIM(t.translation)) BETWEEN 1 AND 40
             AND (LENGTH(t.translation) - LENGTH(REPLACE(t.translation, ' ', ''))) <= 2
           ORDER BY RANDOM() LIMIT ?""",
        (lang_pair, exclude_fragment_id, limit),
    ).fetchall()
    return [r["translation"] for r in rows]