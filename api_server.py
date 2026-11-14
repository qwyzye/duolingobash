import json
import logging
import os

from aiohttp import web

from handlers.db import (
    get_or_create_user, get_fragment_by_level, upsert_translation,
    save_to_expert_review, award_points, get_user, init_db,
    get_best_translation, is_fragment_parsed, save_dictionary_suggestion,
    get_dictionary_word, get_fragment,
)
from handlers.tts import synthesize
from config import API_HOST, API_PORT

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "dist")
INDEX_PATH = os.path.join(FRONTEND_DIR, "index.html")
ASSETS_DIR = os.path.join(FRONTEND_DIR, "assets")


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
async def spa_fallback_middleware(request, handler):
    """GET-404 → отдаём index.html (SPA-роутинг). /assets/ не трогаем."""
    try:
        return await handler(request)
    except web.HTTPNotFound:
        if (
            request.method == "GET"
            and os.path.isfile(INDEX_PATH)
            and not request.path.startswith("/assets/")
        ):
            return web.FileResponse(INDEX_PATH)
        raise


async def health(request):
    return web.json_response({"ok": True})


async def auth(request):
    data = await _json(request)
    user_id = data.get("user_id")
    if not user_id:
        return web.json_response({"error": "user_id required"}, status=400)
    user = get_or_create_user(int(user_id), data.get("username"), data.get("first_name"))
    return web.json_response({"user": user})


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
    app = web.Application(middlewares=[cors_middleware, spa_fallback_middleware])

    # 1) API — сначала
    app.router.add_get("/health", health)
    app.router.add_post("/auth", auth)
    app.router.add_get("/task", task)
    app.router.add_post("/answer", answer)
    app.router.add_post("/suggest", suggest)
    app.router.add_get("/dictionary/{word}", dictionary)
    app.router.add_get("/voice", voice)

    # 2) Диагностика — видно в логах при старте
    logger.info("BASE_DIR        = %s", BASE_DIR)
    logger.info("FRONTEND_DIR    = %s", FRONTEND_DIR)
    logger.info("FRONTEND exists = %s", os.path.isdir(FRONTEND_DIR))
    logger.info("INDEX exists    = %s", os.path.isfile(INDEX_PATH))
    logger.info("ASSETS exists   = %s", os.path.isdir(ASSETS_DIR))

    # 3) Фронт
    if os.path.isfile(INDEX_PATH):
        if os.path.isdir(ASSETS_DIR):
            app.router.add_static("/assets/", ASSETS_DIR, name="assets")
        app.router.add_get("/", lambda r: web.FileResponse(INDEX_PATH))
    else:
        logger.warning(
            "index.html не найден в %s — фронт не отдаётся. "
            "Положи папку dist рядом с api_server.py.", INDEX_PATH,
        )

    return app


async def start_api():
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, API_HOST, API_PORT)
    await site.start()
    logger.info("HTTP API запущен на http://%s:%s", API_HOST, API_PORT)
    return runner