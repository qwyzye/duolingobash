"""База источников (sources.db): фрагменты на башкирском и их переводы.
Внутренний модуль — наружу через HTTP не отдаётся.
"""
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent.parent / "sources.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS fragments (
    fragment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    text_ba     TEXT NOT NULL,
    lang_pair   TEXT NOT NULL,
    translation TEXT NOT NULL,
    source      TEXT,
    confirmed   INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL CHECK (status IN ('confirmed', 'expert_review'))
);

CREATE INDEX IF NOT EXISTS idx_fragments_lang_pair ON fragments(lang_pair);
CREATE INDEX IF NOT EXISTS idx_fragments_status ON fragments(status);
"""

_COLUMNS = "fragment_id, text_ba, lang_pair, translation, source, confirmed, status"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_sources_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)


# ---------- внутренний API ----------

def list_all(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM fragments ORDER BY fragment_id"
    ).fetchall()
    return [dict(r) for r in rows]


def get(conn: sqlite3.Connection, fragment_id: int) -> Optional[dict]:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM fragments WHERE fragment_id = ?",
        (fragment_id,),
    ).fetchone()
    return dict(row) if row else None


def create(
    conn: sqlite3.Connection,
    text_ba: str,
    translation: str,
    lang_pair: str = "ba-ru",
    source: str | None = None,
    confirmed: int = 0,
    status: str = "confirmed",
) -> dict:
    if status not in ("confirmed", "expert_review"):
        raise ValueError("status must be 'confirmed' or 'expert_review'")
    cur = conn.execute(
        "INSERT INTO fragments (text_ba, lang_pair, translation, source, confirmed, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (text_ba, lang_pair, translation, source, confirmed, status),
    )
    conn.commit()
    return get(conn, cur.lastrowid)


def update(
    conn: sqlite3.Connection,
    fragment_id: int,
    text_ba: str,
    translation: str,
    lang_pair: str = "ba-ru",
    source: str | None = None,
    confirmed: int = 0,
    status: str = "confirmed",
) -> Optional[dict]:
    if get(conn, fragment_id) is None:
        return None
    if status not in ("confirmed", "expert_review"):
        raise ValueError("status must be 'confirmed' or 'expert_review'")
    conn.execute(
        "UPDATE fragments SET text_ba = ?, lang_pair = ?, translation = ?, "
        "source = ?, confirmed = ?, status = ? WHERE fragment_id = ?",
        (text_ba, lang_pair, translation, source, confirmed, status, fragment_id),
    )
    conn.commit()
    return get(conn, fragment_id)


def delete(conn: sqlite3.Connection, fragment_id: int) -> bool:
    cur = conn.execute("DELETE FROM fragments WHERE fragment_id = ?", (fragment_id,))
    conn.commit()
    return cur.rowcount > 0

def random_fragment(conn: sqlite3.Connection) -> Optional[dict]:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM fragments "
        "WHERE status = 'confirmed' "
        "ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def random_translations(
    conn: sqlite3.Connection,
    exclude_fragment_id: int,
    lang_pair: str,
    limit: int = 3,
) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT translation FROM fragments "
        "WHERE lang_pair = ? AND fragment_id != ? AND status = 'confirmed' "
        "ORDER BY RANDOM() LIMIT ?",
        (lang_pair, exclude_fragment_id, limit),
    ).fetchall()
    return [r["translation"] for r in rows]

def add_disputed(
    conn: sqlite3.Connection,
    text_ba: str,
    translation: str,
    lang_pair: str = "ba-ru",
    source: str | None = None,
) -> dict:
    """Пользователь предложил свой вариант перевода — сохраняем как непроверенный."""
    cur = conn.execute(
        "INSERT INTO fragments (text_ba, lang_pair, translation, source, confirmed, status) "
        "VALUES (?, ?, ?, ?, 0, 'expert_review')",
        (text_ba, lang_pair, translation, source),
    )
    conn.commit()
    return get(conn, cur.lastrowid)

def random_fragment_weighted(
    conn: sqlite3.Connection,
    learned_fragment_ids: set[int],
    learned_weight: int = 1,
    fresh_weight: int = 5,
) -> Optional[dict]:
    """Выбирает фрагмент с приоритетом неизученных.

    Изученные слова попадаются реже (вес 1), новые — чаще (вес 5).
    Простая реализация: берём случайный фрагмент, но с вероятностью
    80% предпочитаем тот, которого нет в learned_fragment_ids.
    """
    if learned_fragment_ids:
        placeholders = ",".join("?" for _ in learned_fragment_ids)
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM fragments "
            f"WHERE status = 'confirmed' AND fragment_id NOT IN ({placeholders}) "
            "ORDER BY RANDOM() LIMIT 1",
            tuple(learned_fragment_ids),
        ).fetchone()
        if row:
            # 80% шанс взять новое слово, 20% — изученное
            import random as _r
            if _r.random() < 0.8:
                return dict(row)
    # fallback — любое подтверждённое (включая изученные)
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM fragments "
        "WHERE status = 'confirmed' ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    return dict(row) if row else None