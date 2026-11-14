import json
import logging
import os
import sys
import time

from aiohttp import web

API_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(API_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from handlers.db import (
    get_or_create_user, get_fragment_by_level, upsert_translation,
    save_to_expert_review, award_points, get_user, init_db,
    get_best_translation, is_fragment_parsed, save_dictionary_suggestion,
    get_dictionary_word, get_fragment,
    complete_lesson, get_completed_lessons, get_full_progress,
)
from handlers.ai import generate_lesson_questions
from handlers.tts import synthesize
from config import API_HOST, API_PORT

logger = logging.getLogger(__name__)

# кэш вопросов в памяти: {lesson_id: {"ts": float, "questions": [...]}}
_LESSON_CACHE = {}
_LESSON_CACHE_TTL = 3600  # 1 час


def _pick_frontend_dir():
    for base in (API_DIR, ROOT_DIR):
        for name in ("dist", "webapp"):
            d = os.path.join(base, name)
            if os.path.isdir(d):
                return d
    return os.path.join(ROOT_DIR, "webapp")

FRONTEND_DIR = _pick_frontend_dir()
ASSETS_DIR = os.path.join(FRONTEND_DIR, "assets")

if os.path.isfile(os.path.join(FRONTEND_DIR, "index.html")):
    INDEX_PATH = os.path.join(FRONTEND_DIR, "index.html")
elif os.path.isfile(os.path.join(FRONTEND_DIR, "home.html")):
    INDEX_PATH = os.path.join(FRONTEND_DIR, "home.html")
else:
    INDEX_PATH = os.path.join(FRONTEND_DIR, "index.html")


async def _json(request):
    try:
        return await request.json()
    except json.JSONDecodeError:
        return {}


def _cors(resp: web.Response) -> web.Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, ngrok-skip-browser-warning"
    resp.headers["Access-Control-Max-Age"] = "86400"
    return resp


@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        return _cors(web.Response(status=204))
    try:
        resp = await handler(request)
    except web.HTTPException as e:
        resp = e
    return _cors(resp)


@web.middleware
async def static_or_spa_middleware(request, handler):
    try:
        return await handler(request)
    except web.HTTPNotFound:
        if request.method != "GET":
            raise
        rel = request.path.lstrip("/")
        if rel and not rel.startswith("assets/"):
            fp = os.path.join(FRONTEND_DIR, rel)
            if os.path.isfile(fp) and os.path.abspath(fp).startswith(os.path.abspath(FRONTEND_DIR)):
                return web.FileResponse(fp)
        if os.path.isfile(INDEX_PATH):
            return web.FileResponse(INDEX_PATH)
        raise


# ---------------- API ----------------

async def health(request):
    return web.json_response({"ok": True})


async def auth(request):
    data = await _json(request)
    user_id = data.get("user_id")
    if not user_id:
        return web.json_response({"error": "user_id required"}, status=400)
    user_id = int(user_id)
    user = get_or_create_user(user_id, data.get("username"), data.get("first_name"))
    if not user:
        user = get_user(user_id)
    return web.json_response({"user": user, "progress": get_full_progress(user_id)})


async def api_me(request):
    try:
        user_id = int(request.query.get("user_id", "0"))
    except ValueError:
        return web.json_response({"error": "bad user_id"}, status=400)
    if not user_id:
        return web.json_response({"error": "user_id required"}, status=400)
    user = get_user(user_id)
    if not user:
        return web.json_response({"error": "user not found"}, status=404)
    return web.json_response(get_full_progress(user_id))


async def api_lesson_questions(request):
    try:
        lesson_id = int(request.query.get("lesson_id", "-1"))
    except ValueError:
        return web.json_response({"error": "bad lesson_id"}, status=400)
    if lesson_id < 0:
        return web.json_response({"error": "lesson_id required"}, status=400)

    try:
        user_id = int(request.query.get("user_id", "0"))
    except ValueError:
        user_id = 0
    user = get_user(user_id) if user_id else None
    level = user["level"] if user else 1

    force = request.query.get("force") == "1"
    cached = _LESSON_CACHE.get(lesson_id)
    if not force and cached and (time.time() - cached["ts"]) < _LESSON_CACHE_TTL:
        return web.json_response({
            "lesson_id": lesson_id,
            "questions": cached["questions"],
            "cached": True,
        })

    qs = await generate_lesson_questions(lesson_id, level=level, count=5)
    if not qs:
        logger.warning("AI не сгенерировал вопросы для урока %d", lesson_id)
        return web.json_response({"error": "ai_failed"}, status=502)

    _LESSON_CACHE[lesson_id] = {"ts": time.time(), "questions": qs}
    return web.json_response({
        "lesson_id": lesson_id,
        "questions": qs,
        "cached": False,
    })


async def api_lesson_complete(request):
    data = await _json(request)
    user_id = data.get("user_id")
    lesson_id = data.get("lesson_id")
    xp = int(data.get("xp") or 0)
    if not user_id or lesson_id is None:
        return web.json_response({"error": "user_id and lesson_id required"}, status=400)

    user_id = int(user_id)
    lesson_id = int(lesson_id)

    if not get_user(user_id):
        get_or_create_user(user_id, data.get("username"), data.get("first_name") or "User")

    new_level = complete_lesson(user_id, lesson_id, xp)
    progress = get_full_progress(user_id)
    progress["ok"] = True
    progress["level"] = new_level
    return web.json_response(progress)


async def task(request):
    try:
        user_id = int(request.query.get("user_id", "0"))
    except ValueError:
        return web.json_response({"error": "bad user_id"}, status=400)
    user = get_user(user_id)
    level = user["level"] if user else 1
    frag = get_fragment_by_level(level)
    if not frag:
        return web.json_response({"error": "no fragments"}, status=404)
    lang_pair = (user["lang_pair"] if user else None) or "ba-ru"
    existing = get_best_translation(frag["fragment_id"], lang_pair)
    parsed = is_fragment_parsed(frag["fragment_id"])
    return web.json_response({
        "fragment": frag, "parsed": parsed,
        "existing": existing, "lang_pair": lang_pair,
    })


async def answer(request):
    data = await _json(request)
    fragment_id = data.get("fragment_id")
    user_id = data.get("user_id")
    answer_text = data.get("answer")
    lang_pair = data.get("lang_pair", "ba-ru")
    if not (fragment_id and user_id and answer_text):
        return web.json_response({"error": "fragment_id, user_id, answer required"}, status=400)
    frag = get_fragment(fragment_id)
    if not frag:
        return web.json_response({"error": "fragment not found"}, status=404)

    tid, confirmed, status, already = upsert_translation(
        fragment_id=fragment_id, lang_pair=lang_pair,
        text_ba=frag["text_ba"], source=frag.get("source") or "",
        translation=answer_text, user_id=user_id, vote_type="confirm",
    )
    if status == "parsed_locked":
        return web.json_response({"error": "parsed_locked"}, status=409)
    if not already:
        award_points(user_id, "web_answer", f"{fragment_id}_{lang_pair}", 10)
    return web.json_response({
        "translation_id": tid, "confirmed": confirmed,
        "status": status, "already": already,
    })


async def suggest(request):
    data = await _json(request)
    user_id = data.get("user_id") or data.get("user")
    word = (data.get("word") or "").strip()
    suggestion = (data.get("suggestion") or "").strip()
    lang_pair = data.get("lang_pair", "ba-ru")

    if not user_id:
        return web.json_response({"error": "user_id required"}, status=400)
    if not word or not suggestion:
        return web.json_response({"error": "word and suggestion required"}, status=400)
    if len(suggestion) > 200:
        return web.json_response({"error": "suggestion too long"}, status=400)

    existing = get_dictionary_word(word, lang_pair)
    if existing and existing.get("is_parsed"):
        return web.json_response({
            "error": "parsed_locked",
            "message": "Это проверенный перевод. Оспаривать нельзя."
        }, status=409)

    review_id = save_dictionary_suggestion(
        word=word, suggestion=suggestion,
        lang_pair=lang_pair, user_id=user_id, source="webapp",
    )
    award_points(user_id, "web_suggest", str(review_id), 5)
    return web.json_response({"ok": True, "review_id": review_id})


async def dictionary(request):
    word = request.match_info["word"]
    lang_pair = request.query.get("lang_pair", "ba-ru")
    row = get_dictionary_word(word, lang_pair)
    if not row:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response(row)


async def voice(request):
    text = request.query.get("text", "")
    if not text:
        return web.json_response({"error": "text required"}, status=400)
    audio = synthesize(text[:300])
    if not audio:
        return web.json_response({"error": "tts unavailable"}, status=404)
    return web.Response(body=audio, content_type="audio/ogg")


def create_app() -> web.Application:
    init_db()
    app = web.Application(middlewares=[cors_middleware, static_or_spa_middleware])

    app.router.add_get("/health", health)
    app.router.add_post("/auth", auth)
    app.router.add_post("/api/auth", auth)
    app.router.add_get("/api/me", api_me)
    app.router.add_get("/api/lesson/questions", api_lesson_questions)
    app.router.add_post("/api/lesson/complete", api_lesson_complete)

    app.router.add_get("/task", task)
    app.router.add_post("/answer", answer)
    app.router.add_post("/suggest", suggest)
    app.router.add_get("/dictionary/{word}", dictionary)
    app.router.add_get("/voice", voice)

    logger.info("API_DIR        = %s", API_DIR)
    logger.info("ROOT_DIR       = %s", ROOT_DIR)
    logger.info("FRONTEND_DIR   = %s", FRONTEND_DIR)
    logger.info("INDEX_PATH     = %s", INDEX_PATH)
    logger.info("INDEX exists   = %s", os.path.isfile(INDEX_PATH))

    if os.path.isfile(INDEX_PATH):
        app.router.add_get("/", lambda r: web.FileResponse(INDEX_PATH))
    else:
        logger.warning("index.html не найден в %s", FRONTEND_DIR)

    if os.path.isdir(ASSETS_DIR):
        app.router.add_static("/assets/", ASSETS_DIR, name="assets")

    return app


async def start_api():
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, API_HOST, API_PORT)
    await site.start()
    logger.info("HTTP API запущен на http://%s:%s", API_HOST, API_PORT)
    return runner