import os
import re
import sys
import time
import logging
from pathlib import Path

# чтобы работало и из корня (`python parser.py`), и из bot/
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

import requests
from bs4 import BeautifulSoup

from handlers.db import init_db, insert_parsed_fragment, upsert_dictionary

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def is_bashkir(text):
    return bool(re.search(r"[әғҙҡңөҫүһ]", text.lower()))


def clean_and_split(text):
    result = []
    for s in re.split(r"(?<=[.!?])\s+", text):
        s = s.strip().replace("\n", " ")
        if 15 < len(s) < 300 and is_bashkir(s):
            result.append(s)
    return result


def parse_wikipedia(pages_count=50, lang_pair="ba-ru"):
    logger.info("Wikipedia: %d статей", pages_count)
    api = "https://ba.wikipedia.org/w/api.php"
    headers = {"User-Agent": "BashkirLangBot/1.0 (hackathon)"}
    try:
        res = requests.get(api, params={
            "action": "query", "format": "json", "list": "random",
            "rnnamespace": 0, "rnlimit": pages_count,
        }, headers=headers, timeout=10).json()
        pages = res["query"]["random"]
    except Exception:
        logger.exception("Wikipedia API failed")
        return

    total = 0
    for page in pages:
        title = page["title"]
        url = f"https://ba.wikipedia.org/wiki/{title.replace(' ', '_')}"
        try:
            soup = BeautifulSoup(requests.get(url, headers=headers, timeout=10).text, "html.parser")
            content = soup.find("div", class_="mw-parser-output")
            if not content:
                continue
            for p_idx, p in enumerate(content.find_all("p"), start=1):
                for sup in p.find_all("sup"):
                    sup.decompose()
                text = p.get_text(separator=" ").strip()
                for s_idx, sentence in enumerate(clean_and_split(text), start=1):
                    source = f"Википедия: {title} | {url} | абзац {p_idx}, предл. {s_idx}"
                    try:
                        if insert_parsed_fragment(sentence, source, lang_pair):
                            total += 1
                    except Exception:
                        pass
        except Exception:
            logger.exception("Ошибка парсинга %s", title)
        time.sleep(0.3)
    logger.info("Wikipedia: добавлено %d фрагментов", total)


def parse_local_txt(filepath, book_name, lang_pair="ba-ru"):
    if not os.path.exists(filepath):
        logger.error("Файл не найден: %s", filepath)
        return
    with open(filepath, "r", encoding="utf-8") as f:
        text = re.sub(r"\s+", " ", f.read())
    total = 0
    for s_idx, sentence in enumerate(clean_and_split(text), start=1):
        source = f"Книга: {book_name} | предл. {s_idx}"
        try:
            if insert_parsed_fragment(sentence, source, lang_pair):
                total += 1
        except Exception:
            pass
    logger.info("Книга '%s': добавлено %d", book_name, total)


def parse_dictionary(filepath, lang_pair="ba-ru"):
    if not os.path.exists(filepath):
        logger.error("Файл словаря не найден: %s", filepath)
        return
    total = 0
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or "\t" not in line:
                continue
            word, translation = line.split("\t", 1)
            if upsert_dictionary(word.strip(), translation.strip(), lang_pair, is_parsed=1, source="file"):
                total += 1
    logger.info("Словарь: добавлено %d", total)


if __name__ == "__main__":
    init_db()
    parse_wikipedia(pages_count=50)
    # parse_local_txt("book.txt", "Башкирский эпос")
    # parse_dictionary("dictionary.tsv")
    logger.info("Парсинг завершён.")