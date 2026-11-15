"""Заполняет content.db тестовыми фрагментами.
Запуск:
    python -m backend.seed_sources
"""
from backend.sources_db import get_connection, init_sources_db, create

SAMPLES = [
    ("Сәләм!",                "Привет!",                    "ba-ru", "Учебник.pdf, гл.1, стр.5",        12, "confirmed"),
    ("Һаумыһығыҙ!",           "Здравствуйте!",              "ba-ru", "Учебник.pdf, гл.1, стр.6",        8,  "confirmed"),
    ("Рәхмәт, һеҙгә лә!",     "Спасибо, и вам!",            "ba-ru", "Аудиокурс.mp3, урок 2, 00:03:21", 5,  "confirmed"),
    ("Беҙ ҡайтабыҙ.",         "Мы возвращаемся (домой).",   "ba-ru", "Аудиокурс.mp3, урок 3, 00:08:45", 2,  "confirmed"),
    ("Һеҙҙең исемегеҙ нисек?", "Как вас зовут?",            "ba-ru", "Разговорник.pdf, стр.12",         15, "confirmed"),
]


def seed() -> None:
    init_sources_db()
    conn = get_connection()
    added = 0
    try:
        for text_ba, translation, lang_pair, source, confirmed, status in SAMPLES:
            try:
                create(conn, text_ba, translation, lang_pair, source, confirmed, status)
                added += 1
            except Exception as e:
                print(f"  ⚠ {text_ba!r}: {e}")
        print(f"Добавлено фрагментов в content.db: {added}")
    finally:
        conn.close()


if __name__ == "__main__":
    seed()