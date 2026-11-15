"""Mini App API (aiohttp) — порт 8080. Открывается в Telegram WebApp."""
import json
import logging
import os
import sys
import time
from pathlib import Path

from aiohttp import web

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import API_HOST, API_PORT, WEBAPP_URL

from backend.db import get_connection, init_db
from backend.sources_db import (
    random_fragment,
    get_confirmed_translation,
    random_distractors,
)
from backend.learned import (
    get_learned_ids,
    record_seen,
    award_points_event,
    recalculate_level,
)

from handlers.ai import generate_lesson_questions
from handlers.tts import synthesize

logger = logging.getLogger(__name__)

FRONTEND_DIR = ROOT_DIR / "webapp"
ASSETS_DIR = FRONTEND_DIR / "assets"

_LESSON_CACHE: dict[int, dict] = {}
_LESSON_CACHE_TTL = 3600


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
    try:
        return await handler(request)
    except web.HTTPNotFound:
        if request.method != "GET":
            raise
        rel = request.path.lstrip("/")
        if rel and not rel.startswith("assets/"):
            fp = FRONTEND_DIR / rel
            if fp.is_file() and str(fp).startswith(str(FRONTEND_DIR)):
                return web.FileResponse(fp)
        index = FRONTEND_DIR / "index.html"
        if index.is_file():
            return web.FileResponse(index)
        raise


def _ensure_user(conn, tg_id: int, username: str | None, first_name: str | None) -> dict:
    row = conn.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (tg_id,)
    ).fetchone()

    if row is None:
        uname = username or first_name or f"user_{tg_id}"
        clash = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (uname,)
        ).fetchone()
        if clash:
            uname = f"{uname}_{tg_id}"

        conn.execute(
            "INSERT INTO users(telegram_id, username, first_name) VALUES (?, ?, ?)",
            (tg_id, uname, first_name or "User"),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (tg_id,)
        ).fetchone()

    return dict(row)


def _progress_for(conn, user_pk: int, tg_id: int) -> dict:
    user = conn.execute(
        "SELECT id, first_name, username, points, level FROM users WHERE id = ?",
        (user_pk,),
    ).fetchone()

    done = []
    for r in conn.execute(
        "SELECT event_key FROM points_events "
        "WHERE user_id = ? AND event_type = 'lesson_complete'",
        (user_pk,),
    ).fetchall():
        k = r["event_key"]
        if k and k.startswith("lesson_"):
            try:
                done.append(int(k[len("lesson_"):]))
            except ValueError:
                pass

    return {
        "user_id": tg_id,
        "xp": user["points"] if user else 0,
        "level": user["level"] if user else 1,
        "done_lessons": sorted(set(done)),
        "first_name": user["first_name"] if user else None,
        "site_login": user["username"] if user else None,
    }


# ---------- handlers ----------

async def health(request):
    return web.json_response({"ok": True})


async def auth(request):
    data = await _json(request)
    tg_id = data.get("user_id")
    if not tg_id:
        return web.json_response({"error": "user_id required"}, status=400)
    tg_id = int(tg_id)

    conn = get_connection()
    try:
        user = _ensure_user(conn, tg_id, data.get("username"), data.get("first_name"))
        progress = _progress_for(conn, user["id"], tg_id)
    finally:
        conn.close()

    return web.json_response({"user": user, "progress": progress})


async def api_me(request):
    try:
        tg_id = int(request.query.get("user_id", "0"))
    except ValueError:
        return web.json_response({"error": "bad user_id"}, status=400)
    if not tg_id:
        return web.json_response({"error": "user_id required"}, status=400)

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (tg_id,)
        ).fetchone()
        if not row:
            return web.json_response({"error": "user not found"}, status=404)
        progress = _progress_for(conn, row["id"], tg_id)
    finally:
        conn.close()
    return web.json_response(progress)


async def api_leaderboard(request):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, "
            "       COALESCE(NULLIF(username,''), NULLIF(first_name,''), 'User') AS name, "
            "       level, points "
            "FROM users "
            "ORDER BY points DESC, level DESC, id ASC "
            "LIMIT 100"
        ).fetchall()
    finally:
        conn.close()

    return web.json_response([
        {"rank": i, "username": r["name"], "level": r["level"], "points": r["points"]}
        for i, r in enumerate(rows, start=1)
    ])


async def api_word_of_day(request):
    conn = get_connection()
    try:
        frag = random_fragment(conn)
        if not frag:
            return web.json_response({"detail": "No fragments"}, status=404)
        best = get_confirmed_translation(conn, frag["fragment_id"], frag["lang_pair"])
    finally:
        conn.close()
    if not best:
        return web.json_response({"detail": "No translation"}, status=404)
    return web.json_response({"text_ba": frag["text_ba"], "translation": best["translation"]})


async def api_users(request):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, username, city, school, grade, level, points, "
            "       created_at, last_login_at "
            "FROM users ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return web.json_response([dict(r) for r in rows])


async def api_lesson_questions(request):
    try:
        lesson_id = int(request.query.get("lesson_id", "-1"))
    except ValueError:
        return web.json_response({"error": "bad lesson_id"}, status=400)
    if lesson_id < 0:
        return web.json_response({"error": "lesson_id required"}, status=400)

    try:
        tg_id = int(request.query.get("user_id", "0"))
    except ValueError:
        tg_id = 0

    level = 1
    if tg_id:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT level FROM users WHERE telegram_id = ?", (tg_id,)
            ).fetchone()
            if row:
                level = row["level"]
        finally:
            conn.close()

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
        return web.json_response({"error": "ai_failed"}, status=502)

    _LESSON_CACHE[lesson_id] = {"ts": time.time(), "questions": qs}
    return web.json_response({
        "lesson_id": lesson_id,
        "questions": qs,
        "cached": False,
    })


async def api_lesson_complete(request):
    data = await _json(request)
    tg_id = data.get("user_id")
    lesson_id = data.get("lesson_id")
    xp = int(data.get("xp") or 0)
    if not tg_id or lesson_id is None:
        return web.json_response({"error": "user_id and lesson_id required"}, status=400)

    tg_id = int(tg_id)
    lesson_id = int(lesson_id)

    conn = get_connection()
    try:
        user = _ensure_user(
            conn, tg_id,
            data.get("username"),
            data.get("first_name") or "User",
        )
        result = award_points_event(
            conn, user["id"], "lesson_complete", f"lesson_{lesson_id}", xp
        )
        progress = _progress_for(conn, user["id"], tg_id)
    finally:
        conn.close()

    progress.update({
        "ok": True,
        "points": result["points"],
        "level": result["level"],
        "already_awarded": result["already_awarded"],
    })
    return web.json_response(progress)


async def exercise_random(request):
    tg_id = request.query.get("user_id")
    learned: set[int] = set()
    user_pk = None

    conn = get_connection()
    try:
        if tg_id:
            row = conn.execute(
                "SELECT id FROM users WHERE telegram_id = ?", (int(tg_id),)
            ).fetchone()
            if row:
                user_pk = row["id"]
                learned = get_learned_ids(conn, user_pk)

        frag = random_fragment(conn, exclude_ids=learned) or random_fragment(conn)
        if not frag:
            return web.json_response({"detail": "No fragments"}, status=404)
        best = get_confirmed_translation(conn, frag["fragment_id"], frag["lang_pair"])
        if not best:
            return web.json_response({"detail": "No translation"}, status=404)
        distractors = random_distractors(
            conn, frag["fragment_id"], frag["lang_pair"], limit=3
        )

        if user_pk:
            record_seen(conn, user_pk, frag["fragment_id"])
    finally:
        conn.close()

    fb = ["Нет перевода", "Другое значение", "Неизвестно"]
    while len(distractors) < 3:
        distractors.append(fb.pop())

    import random
    options = distractors + [best["translation"]]
    random.shuffle(options)

    return web.json_response({
        "fragment_id": frag["fragment_id"],
        "text_ba": frag["text_ba"],
        "translation": best["translation"],
        "options": options,
    })


async def answer(request):
    data = await _json(request)
    tg_id = data.get("user_id")
    frag_id = data.get("fragment_id")
    answer_text = data.get("answer")
    lang_pair = data.get("lang_pair", "ba-ru")
    if not (frag_id and tg_id and answer_text):
        return web.json_response(
            {"error": "fragment_id, user_id, answer required"}, status=400
        )

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (int(tg_id),)
        ).fetchone()
        if not row:
            return web.json_response({"error": "user not found"}, status=404)
        user_pk = row["id"]

        frag_row = conn.execute(
            "SELECT * FROM fragments WHERE fragment_id = ?", (int(frag_id),)
        ).fetchone()
        if not frag_row:
            return web.json_response({"error": "fragment not found"}, status=404)
        frag = dict(frag_row)

        from backend.sources_db import _normalize
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        normalized = _normalize(answer_text)

        if frag["is_parsed"]:
            return web.json_response({"error": "parsed_locked"}, status=409)

        existing = conn.execute(
            "SELECT id, confirmed FROM translations "
            "WHERE fragment_id=? AND lang_pair=? AND normalized=? AND status!='rejected'",
            (int(frag_id), lang_pair, normalized),
        ).fetchone()

        if existing:
            trans_id = existing["id"]
            already = conn.execute(
                "SELECT 1 FROM translation_votes WHERE translation_id=? AND user_id=?",
                (trans_id, user_pk),
            ).fetchone() is not None
            if already:
                return web.json_response({
                    "translation_id": trans_id,
                    "confirmed": existing["confirmed"],
                    "status": "already_voted",
                    "already": True,
                })
        else:
            cur = conn.execute(
                """INSERT INTO translations(fragment_id, user_id, lang_pair, text_ba,
                    source, translation, normalized, confirmed, status, is_parsed,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'pending', 0, ?, ?)""",
                (int(frag_id), user_pk, lang_pair, frag["text_ba"],
                 frag.get("source") or "", answer_text, normalized, now, now),
            )
            trans_id = cur.lastrowid

        try:
            conn.execute(
                "INSERT INTO translation_votes(translation_id, user_id, vote_type, created_at) "
                "VALUES (?, ?, 'confirm', ?)",
                (trans_id, user_pk, now),
            )
        except Exception:
            conn.rollback()
            return web.json_response({
                "translation_id": trans_id,
                "confirmed": 0,
                "status": "already_voted",
                "already": True,
            })

        conn.execute(
            "UPDATE translations SET confirmed = confirmed + 1, updated_at=? WHERE id=?",
            (now, trans_id),
        )
        confirmed = conn.execute(
            "SELECT confirmed FROM translations WHERE id=?", (trans_id,)
        ).fetchone()["confirmed"]
        if confirmed >= 3:
            conn.execute(
                "UPDATE translations SET status='confirmed' WHERE id=?", (trans_id,)
            )

        award_points_event(conn, user_pk, "web_answer", f"{frag_id}_{lang_pair}", 10)
    except Exception as e:
        logger.exception("answer failed")
        return web.json_response({"error": str(e)}, status=500)
    finally:
        conn.close()

    return web.json_response({
        "translation_id": trans_id,
        "confirmed": confirmed,
        "status": "confirmed" if confirmed >= 3 else "pending",
        "already": False,
    })


async def suggest(request):
    data = await _json(request)
    tg_id = data.get("user_id")
    word = (data.get("word") or "").strip()
    suggestion = (data.get("suggestion") or "").strip()
    lang_pair = data.get("lang_pair", "ba-ru")

    if not tg_id:
        return web.json_response({"error": "user_id required"}, status=400)
    if not word or not suggestion:
        return web.json_response({"error": "word and suggestion required"}, status=400)
    if len(suggestion) > 200:
        return web.json_response({"error": "suggestion too long"}, status=400)

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (int(tg_id),)
        ).fetchone()
        if not row:
            return web.json_response({"error": "user not found"}, status=404)
        user_pk = row["id"]

        existing = conn.execute(
            "SELECT * FROM dictionary WHERE word=? AND lang_pair=? "
            "ORDER BY is_parsed DESC, confirmed DESC LIMIT 1",
            (word, lang_pair),
        ).fetchone()
        if existing and existing["is_parsed"]:
            return web.json_response({
                "error": "parsed_locked",
                "message": "Это проверенный перевод.",
            }, status=409)

        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute(
            """INSERT INTO dictionary(word, translation, lang_pair,
                is_parsed, status, source, confirmed, created_at)
               VALUES (?, ?, ?, 0, 'expert_review', 'webapp', 0, ?)""",
            (word, suggestion, lang_pair, now),
        )
        rid = cur.lastrowid
        conn.commit()

        award_points_event(conn, user_pk, "web_suggest", str(rid), 5)
    finally:
        conn.close()

    return web.json_response({"ok": True, "review_id": rid})


async def dictionary(request):
    word = request.match_info["word"]
    lang_pair = request.query.get("lang_pair", "ba-ru")
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM dictionary WHERE word=? AND lang_pair=? "
            "ORDER BY is_parsed DESC, confirmed DESC LIMIT 1",
            (word, lang_pair),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response(dict(row))


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

    app.router.add_get("/health", health)
    app.router.add_post("/auth", auth)
    app.router.add_post("/api/auth", auth)
    app.router.add_get("/api/me", api_me)
    app.router.add_get("/api/users", api_users)
    app.router.add_get("/api/leaderboard", api_leaderboard)
    app.router.add_get("/api/word-of-day", api_word_of_day)
    app.router.add_get("/api/lesson/questions", api_lesson_questions)
    app.router.add_post("/api/lesson/complete", api_lesson_complete)
    app.router.add_get("/api/exercise/random", exercise_random)
    app.router.add_post("/answer", answer)
    app.router.add_post("/suggest", suggest)
    app.router.add_get("/dictionary/{word}", dictionary)
    app.router.add_get("/voice", voice)

    if ASSETS_DIR.is_dir():
        app.router.add_static("/assets/", ASSETS_DIR, name="assets")

    index = FRONTEND_DIR / "index.html"
    if index.is_file():
        app.router.add_get("/", lambda r: web.FileResponse(index))
    else:
        logger.warning("index.html не найден в %s", FRONTEND_DIR)

    logger.info("Mini App API: FRONTEND_DIR=%s", FRONTEND_DIR)
    return app


async def start_api():
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, API_HOST, API_PORT)
    await site.start()
    logger.info("Mini App API: http://%s:%s", API_HOST, API_PORT)
    return runner