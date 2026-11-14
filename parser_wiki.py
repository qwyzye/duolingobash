import requests
from bs4 import BeautifulSoup
import sqlite3
import re
import time

def create_tables():
    """Создает таблицу фрагментов, если база пустая"""
    conn = sqlite3.connect("bashlingo.db")
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS fragments(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text_ba TEXT UNIQUE,
    source TEXT
    )""")
    conn.commit()
    conn.close()

def parse_random_wikipedia():
    # 0. Создаем таблицы на всякий случай
    create_tables()
    
    # 1. Получаем случайную статью через API
    api_url = "https://ba.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "format": "json",
        "list": "random",
        "rnnamespace": 0,
        "rnlimit": 20 
    }
    
    headers = {'User-Agent': 'BashkirDuolingoBot/1.0 (test@example.com)'}
    
    print("📡 Получаем список случайных статей...")
    try:
        res = requests.get(api_url, params=params, headers=headers, timeout=10).json()
        pages = res['query']['random']
    except Exception as e:
        print(f"❌ Ошибка API: {e}")
        return

    # 2. Подключаемся к БД
    conn = sqlite3.connect("bashlingo.db")
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
                print("  ⚠️ Не найден блок текста")
                continue
                
            paragraphs = content_div.find_all('p')
            added_for_page = 0
            
            for p in paragraphs:
                # Удаляем сноски [1], [2] и т.д.
                for sup in p.find_all('sup'):
                    sup.decompose()
                
                text = p.get_text(separator=' ').strip()
                
                if len(text) < 30:
                    continue
                
                sentences = re.split(r'(?<=[.!?])\s+', text)
                
                for sentence in sentences:
                    clean_sentence = sentence.strip().replace('\n', ' ')
                    
                    if 15 < len(clean_sentence) < 300:
                        # Проверяем на наличие башкирских букв
                        if re.search(r'[әғҙҡңөҫүһ]', clean_sentence.lower()):
                            source = f"Википедия: {title}"
                            try:
                                cursor.execute("INSERT OR IGNORE INTO fragments (text_ba, source) VALUES (?, ?)", 
                                               (clean_sentence, source))
                                if cursor.rowcount > 0:
                                    total_added += 1
                                    added_for_page += 1
                            except Exception as e:
                                print(f"  💥 Ошибка БД: {e}")
            
            print(f"  ✅ Добавлено предложений: {added_for_page}")
            
        except Exception as e:
            print(f"  💥 Ошибка при парсинге {title}: {e}")
            
        time.sleep(0.5)

    conn.commit()
    conn.close()
    print(f"\n🎉 ГОТОВО! Всего добавлено новых фрагментов: {total_added}")

if __name__ == "__main__":
    parse_random_wikipedia()