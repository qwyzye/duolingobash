import aiohttp
import json
from handlers.prompts import TASK_PROMPT

API_KEYS = [
    "AQ.Ab8RN6JTic8tuGw-T-urvkXUjfU5cFHwggvaEWYPd79N4cslMw",
    "AQ.Ab8RN6K9O1flkC6bvFTeQXVDDKZuW93q_URKdvWQh2Cs1fy2_w",
    "AQ.Ab8RN6JaIjwG_N_l2BS4UvBdB9lOfcT0RdrXkf5UFJzNYb1frQ",
    "AQ.Ab8RN6JhXiJzxIHjpMTmms0GFM0_CK4ht-HRLbAtiQx8h-viNw"
]

MODEL_NAME = "gemini-3.5-flash-lite"

async def generate_task(task_type: str, level: int = 1, known_words: list = None):
    if known_words:
        known_words_text = f"Ученик уже знает эти слова: {', '.join(known_words)}. Старайся использовать их, но можешь добавить одно новое."
    else:
        known_words_text = "Ученик пока не знает слов."

    prompt = TASK_PROMPT.format(
        task_type=task_type, 
        level=level, 
        known_words_text=known_words_text
    )
    
    for index, api_key in enumerate(API_KEYS):
        print(f"Попытка запроса с ключом Gemini №{index + 1}...")
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={api_key}"
        
        headers = {"Content-Type": "application/json"}
        
        # Убрали generationConfig, который ломал запрос
        data = {
            "contents": [{"parts": [{"text": prompt}]}],
            # Добавили лимит токенов, чтобы JSON не обрывался на полуслове
            "generationConfig": {
                "maxOutputTokens": 1000
            }
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=data, timeout=20) as response:
                    
                    if response.status == 200:
                        result = await response.json()
                        content = result['candidates'][0]['content']['parts'][0]['text']
                        
                        # Очистка от маркдауна
                        content = content.replace("```json", "").replace("```", "").strip()
                        
                        try:
                            task_data = json.loads(content)
                            print(f"✅ Успех с ключом Gemini №{index + 1}")
                            return task_data
                        except json.JSONDecodeError as e:
                            # Если JSON опять обрезался, попробуем его "починить"
                            print(f"⚠️ Ключ №{index + 1} вернул битый JSON. Пытаемся исправить...")
                            
                            # Если не хватает закрывающей скобки
                            if not content.endswith("}"):
                                content += '"\n}' # Грубый фикс обрыва
                            
                            try:
                                task_data = json.loads(content)
                                print(f"✅ Успех после фикса с ключом Gemini №{index + 1}")
                                return task_data
                            except:
                                print(f"❌ Не удалось починить JSON. Пробуем следующий ключ...")
                                continue 
                    
                    elif response.status == 429:
                        print(f"⏳ Лимит запросов (429) на ключе №{index + 1}.")
                        continue
                    else:
                        # ВОТ ЗДЕСЬ МЫ ТЕПЕРЬ ВЫВОДИМ ТЕКСТ ОШИБКИ
                        error_text = await response.text()
                        print(f"❌ Ошибка API (Статус {response.status}) на ключе №{index + 1}.")
                        print(f"📄 Ответ сервера: {error_text}")
                        continue 

        except Exception as e:
            print(f"💥 Сетевая ошибка с ключом Gemini №{index + 1}: {e}")
            continue

    print("🚨 ВСЕ КЛЮЧИ GEMINI ИСЧЕРПАНЫ ИЛИ НЕ РАБОТАЮТ!")
    return None