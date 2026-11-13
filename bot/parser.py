import requests
from bs4 import BeautifulSoup
import sqlite3
import re
import time
import os

db_name = "bashlingo.db"

def init_db():
    """Создает таблицу fragments ровно под твой db.py"""
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS fragments(
    fragment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    text_ba TEXT UNIQUE,
    lang_pair TEXT DEFAULT 'ba-ru',
    source TEXT
    )""")
    conn.commit()
    conn.close()

def is_bashkir(text):
    """Проверяем, что в тексте есть башкирские буквы"""
    return bool(re.search(r'[әғҙҡңөҫүһ]', text.lower()))

def clean_and_split(text):
    """Очищает текст и разбивает на предложения"""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    result = []
    for s in sentences:
        s = s.strip().replace('\n', ' ')
        # Берем предложения от 15 до 300 символов
        if 15 < len(s) < 300 and is_bashkir(s):
            result.append(s)
    return result

def parse_wikipedia(pages_count=50):
    """Парсит случайные статьи из Башкирской Википедии"""
    print(f"\n🌐 Начинаю парсинг Википедии ({pages_count} статей)...")
    api_url = "https://ba.wikipedia.org/w/api.php"
    headers = {'User-Agent': 'BashkirDuolingoBot/1.0 (hackathon@example.com)'}
    
    # Получаем список случайных статей
    params = {
        "action": "query", "format": "json", "list": "random",
        "rnnamespace": 0, "rnlimit": pages_count
    }
    
    try:
        res = requests.get(api_url, params=params, headers=headers, timeout=10).json()
        pages = res['query']['random']
    except Exception as e:
        print(f"❌ Ошибка API Википедии: {e}")
        return

    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    total_added = 0

    for page in pages:
        title = page['title']
        print(f"📖 Парсим: {title}")
        
        page_url = f"https://ba.wikipedia.org/wiki/{title.replace(' ', '_')}"
        try:
            response = requests.get(page_url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            content_div = soup.find('div', class_='mw-parser-output')
            if not content_div:
                continue
                
            paragraphs = content_div.find_all('p')
            for p in paragraphs:
                # Удаляем сноски [1], [2]
                for sup in p.find_all('sup'):
                    sup.decompose()
                
                text = p.get_text(separator=' ').strip()
                sentences = clean_and_split(text)
                
                for sentence in sentences:
                    source = f"Википедия: {title}"
                    try:
                        cursor.execute("""INSERT OR IGNORE INTO fragments (text_ba, lang_pair, source) 
                                          VALUES (?, 'ba-ru', ?)""", (sentence, source))
                        if cursor.rowcount > 0:
                            total_added += 1
                    except Exception as e:
                        pass
        except Exception as e:
            print(f"  💥 Ошибка: {e}")
        
        time.sleep(0.3) # Пауза, чтобы не забанили

    conn.commit()
    conn.close()
    print(f"✅ Из Википедии добавлено: {total_added} новых предложений.")

def parse_local_txt(filepath, book_name):
    """Парсит локальный txt файл (книгу) и закидывает в базу"""
    if not os.path.exists(filepath):
        print(f"❌ Файл {filepath} не найден!")
        return
        
    print(f"\n📚 Читаю книгу: {book_name}...")
    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()
        
    # Очищаем от лишних пробелов и переносов
    text = re.sub(r'\s+', ' ', text)
    sentences = clean_and_split(text)
    
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    total_added = 0
    
    for sentence in sentences:
        source = f"Книга: {book_name}"
        try:
            cursor.execute("""INSERT OR IGNORE INTO fragments (text_ba, lang_pair, source) 
                              VALUES (?, 'ba-ru', ?)""", (sentence, source))
            if cursor.rowcount > 0:
                total_added += 1
        except Exception as e:
            pass
            
    conn.commit()
    conn.close()
    print(f"✅ Из книги '{book_name}' добавлено: {total_added} новых предложений.")

if __name__ == "__main__":
    # 1. Создаем БД, если ее нет
    init_db()
    
    # 2. Парсим Википедию (можешь запускать скрипт много раз, каждый раз будет качать новые статьи)
    parse_wikipedia(pages_count=50) 
    
    # 3. Парсим книгу (если она есть).
    # Просто положи файл book.txt с башкирским текстом в эту же папку и раскомментируй строку ниже:
    # parse_local_txt("book.txt", "Башкирский эпос")
    
    print("\n🎉 ПАРСИНГ ЗАВЕРШЕН! База готова к работе.")