"""Доступ к content.db бота: фрагменты и переводы.

Сайт читает только таблицы fragments и translations.
Запись — только через save_to_expert_review (оспаривание).
"""
import sqlite3
from pathlib import Path
from typing import Optional

# content.db лежит рядом с users.db — в корне проекта
BASE_DIR = Path(__file__).resolve().parent.parent
CONTENT_DB = BASE_DIR / "content.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(CONTENT_DB), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_sources_db():
    """Зависимость FastAPI, если понадобится."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


# ---------- чтение ----------

def random_fragment(conn: sqlite3.Connection, lang_pair: str = "ba-ru") -> Optional[dict]:
    """Случайный фрагмент, у которого есть хотя бы один подтверждённый перевод."""
    row = conn.execute(
        """SELECT f.fragment_id, f.text_ba, f.lang_pair, f.source
           FROM fragments f
           WHERE f.lang_pair = ?
             AND EXISTS (
                 SELECT 1 FROM translations t
                 WHERE t.fragment_id = f.fragment_id
                   AND t.lang_pair = f.lang_pair
                   AND t.status = 'confirmed'
             )
           ORDER BY RANDOM() LIMIT 1""",
        (lang_pair,),
    ).fetchone()
    return dict(row) if row else None


def get_confirmed_translation(
    conn: sqlite3.Connection, fragment_id: int, lang_pair: str = "ba-ru"
) -> Optional[dict]:
    """Лучший подтверждённый перевод для фрагмента."""
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
    """Случайные подтверждённые переводы из других фрагментов — для вариантов ответа."""
    rows = conn.execute(
        """SELECT DISTINCT translation
           FROM translations
           WHERE lang_pair = ? AND fragment_id != ? AND status = 'confirmed'
           ORDER BY RANDOM() LIMIT ?""",
        (lang_pair, exclude_fragment_id, limit),
    ).fetchall()
    return [r["translation"] for r in rows]


# ---------- запись (оспаривание) ----------

def save_dispute(
    conn: sqlite3.Connection,
    fragment_id: int,
    user_id: int,
    translation: str,
    lang_pair: str,
    text_ba: str,
    source: str = "site",
) -> int:
    """Кладёт предложенный пользователем перевод со статусом expert_review.

    Полностью повторяет логику save_to_expert_review из бота.
    """
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _normalize(text: str) -> str:
        import re
        t = (text or "").lower().strip()
        t = re.sub(r"[^\w\s]", "", t, flags=re.UNICODE)
        t = re.sub(r"\s+", " ", t)
        return t

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