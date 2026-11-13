import aiohttp
import json
import random
from handlers.prompts import DAILY_TRANSLATE_PROMPT, PRACTICE_CHECK_PROMPT
from config import API_KEYS, MODEL_NAME

async def _request_ai(prompt):
    for api_key in API_KEYS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={api_key}"
        data = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 500}}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data, timeout=20) as response:
                    if response.status == 200:
                        result = await response.json()
                        content = result['candidates'][0]['content']['parts'][0]['text']
                        content = content.replace("```json", "").replace("```", "").strip()
                        return json.loads(content)
        except Exception:
            continue
    return None

async def get_daily_translation(text_ba: str, target_lang: str):
    inject_error = random.choice([True, False, False])
    prompt = DAILY_TRANSLATE_PROMPT.format(text_ba=text_ba, inject_error=inject_error, target_lang=target_lang)
    return await _request_ai(prompt)

async def check_user_translation(text_ba: str, user_translation: str, target_lang: str):
    prompt = PRACTICE_CHECK_PROMPT.format(text_ba=text_ba, user_translation=user_translation, target_lang=target_lang)
    return await _request_ai(prompt)