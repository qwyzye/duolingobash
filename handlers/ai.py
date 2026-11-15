import asyncio
import json
import logging
import random
import aiohttp

from handlers.prompts import (
    DAILY_TRANSLATE_PROMPT, PRACTICE_CHECK_PROMPT, GENERATE_TASK_PROMPT, MODULE_TASK_PROMPT
)
from config import API_KEYS, MODEL_NAME

logger = logging.getLogger(__name__)


def _validate(data, schema):
    if not isinstance(data, dict):
        return False
    for field, types in schema.items():
        if field not in data:
            return False
        if not isinstance(data[field], types):
            return False
    return True


async def _request_ai(prompt, expect_schema=None):
    if not API_KEYS:
        logger.error("No API keys configured")
        return None
    for i, api_key in enumerate(API_KEYS):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 1500,
                "responseMimeType": "application/json",
            },
        }
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        body = (await resp.text())[:300]
                        logger.warning("AI key#%d status=%d body=%s", i, resp.status, body)
                        continue
                    data = await resp.json()
                    try:
                        content = data["candidates"][0]["content"]["parts"][0]["text"]
                    except (KeyError, IndexError):
                        logger.warning("AI key#%d malformed response", i)
                        continue
                    content = content.replace("```json", "").replace("```", "").strip()
                    try:
                        parsed = json.loads(content)
                    except json.JSONDecodeError:
                        logger.warning("AI key#%d invalid JSON: %s", i, content[:200])
                        continue
                    if expect_schema and not _validate(parsed, expect_schema):
                        logger.warning("AI key#%d schema mismatch: %s", i, parsed)
                        continue
                    return parsed
        except asyncio.TimeoutError:
            logger.warning("AI key#%d timeout", i)
        except Exception:
            logger.exception("AI key#%d error", i)
    return None


async def get_daily_translation(text_ba: str, target_lang: str):
    inject_error = random.choice([True, False, False])
    prompt = DAILY_TRANSLATE_PROMPT.format(
        text_ba=text_ba, inject_error=str(inject_error).lower(), target_lang=target_lang
    )
    return await _request_ai(prompt, expect_schema={"translation": str, "is_messed_up": bool})


async def check_user_translation(text_ba, user_translation, target_lang):
    prompt = PRACTICE_CHECK_PROMPT.format(
        text_ba=text_ba, user_translation=user_translation, target_lang=target_lang
    )
    return await _request_ai(prompt, expect_schema={"is_correct": bool})


async def generate_task(task_type, level=1, known_words=None):
    prompt = GENERATE_TASK_PROMPT.format(
        task_type=task_type, level=level,
        known_words=", ".join(known_words) if known_words else "нет",
    )
    return await _request_ai(prompt, expect_schema={"question": str, "correct_answer": str})


async def generate_module_task(task_type, difficulty=1, known_words=None):
    prompt = MODULE_TASK_PROMPT.format(
        task_type=task_type,
        difficulty=difficulty,
        known_words=", ".join(known_words) if known_words else "нет",
    )
    return await _request_ai(prompt, expect_schema={
        "task_type": str, "question": str, "correct_answer": str,
    })


# ---------------- LESSON QUESTIONS (mini app) ----------------

LESSON_TOPICS = {
    0: "Приветствия и вежливые слова (привет, спасибо, да, нет, до свидания)",
    1: "Знакомство (я, ты, друг, имя, здравствуйте)",
    2: "Семья (мама, папа, брат, сестра, бабушка)",
    3: "Числа 1–5",
    4: "Числа 6–10",
    5: "Цвета (красный, зелёный, жёлтый, синий, белый)",
}

LESSON_QUESTIONS_PROMPT = """Ты — учитель башкирского языка для детей. Сгенерируй ровно {count} заданий на перевод слов для урока на тему «{topic}». Уровень ученика: {level}.

Правила:
- "w" — слово или короткая фраза на БАШКИРСКОМ языке (2–20 символов). Только башкирские буквы.
- "ok" — правильный перевод "w" на РУССКИЙ.
- "bad" — неправильный, но правдоподобный перевод на РУССКИЙ (это должно быть ДРУГОЕ слово, не синоним и не антоним правильного).
- Все {count} пар должны быть про РАЗНЫЕ слова темы, без повторов.
- ok и bad должны быть РАЗНЫМИ.

Пример правильного ответа для темы «Приветствия»:
"w": "Сәләм", "ok": "Привет", "bad": "Пока"

Верни СТРОГО JSON без комментариев и без markdown:
{{
  "questions": [
    {{"w": "Сәләм", "ok": "Привет", "bad": "Пока"}},
    {{"w": "Рәхмәт", "ok": "Спасибо", "bad": "Пожалуйста"}}
  ]
}}
"""


async def generate_lesson_questions(lesson_id: int, level: int = 1, count: int = 5):
    """Возвращает список [{"w","ok","bad"}, ...] или None."""
    topic = LESSON_TOPICS.get(lesson_id, "Общая лексика башкирского языка")
    prompt = LESSON_QUESTIONS_PROMPT.format(topic=topic, level=level, count=count)
    data = await _request_ai(prompt)
    if not data or not isinstance(data.get("questions"), list):
        return None

    seen_w = set()
    out = []
    for q in data["questions"]:
        if not isinstance(q, dict):
            continue
        w = (q.get("w") or "").strip()
        ok = (q.get("ok") or "").strip()
        bad = (q.get("bad") or "").strip()
        if not (w and ok and bad):
            continue
        if ok.lower() == bad.lower():
            continue
        if w.lower() in seen_w:
            continue
        seen_w.add(w.lower())
        out.append({"w": w, "ok": ok, "bad": bad})

    if len(out) < 3:
        logger.warning("generate_lesson_questions: too few valid questions (%d)", len(out))
        return None
    return out[:count]
async def translate_fragment(text_ba: str) -> str | None:
    """Перевод фрагмента ba→ru через Gemini. Возвращает строку или None."""
    from handlers.prompts import SITE_TRANSLATE_PROMPT
    prompt = SITE_TRANSLATE_PROMPT.format(text_ba=text_ba)
    data = await _request_ai(prompt, expect_schema={"translation": str})
    if not data:
        return None
    t = (data.get("translation") or "").strip()
    return t or None