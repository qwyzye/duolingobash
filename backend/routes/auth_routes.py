import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.responses import JSONResponse
from backend.deps import current_user_id

import random
from pydantic import BaseModel, Field

from backend.db import get_db
from backend import auth
from backend.auth import get_user_by_token

router = APIRouter()
STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"


@router.get("/register", response_class=HTMLResponse)
def register_page():
    return FileResponse(STATIC_DIR / "register.html")


@router.post("/register")
def register_submit(
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    city: str | None = Form(None),
    school: str | None = Form(None),
    grade: str | None = Form(None),
    db: sqlite3.Connection = Depends(get_db),
):
    if password != confirm_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пароли не совпадают")
    if len(password) < 8:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пароль слишком короткий")

    city = (city or "").strip() or None
    school = (school or "").strip() or None
    grade = (grade or "").strip() or None

    user_id = auth.register_user(db, username, password, city, school, grade)
    if user_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Логин уже занят")

    token = auth.create_session(db, user_id)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        "session_token", token,
        httponly=True, samesite="lax",
        max_age=30 * 24 * 3600,
    )
    return response


@router.get("/login", response_class=HTMLResponse)
def login_page():
    return FileResponse(STATIC_DIR / "login.html")


@router.post("/login")
def login_submit(
    username: str = Form(...),
    password: str = Form(...),
    db: sqlite3.Connection = Depends(get_db),
):
    user_id = auth.authenticate(db, username, password)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    token = auth.create_session(db, user_id)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        "session_token", token,
        httponly=True, samesite="lax",
        max_age=30 * 24 * 3600,
    )
    return response


@router.post("/logout")
def logout_submit(request: Request, db: sqlite3.Connection = Depends(get_db)):
    token = request.cookies.get("session_token")
    if token:
        db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        db.commit()
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session_token")
    return response


@router.get("/users")
def users_page():
    return FileResponse(STATIC_DIR / "users.html")


@router.get("/api/users")
def users_api(request: Request, db: sqlite3.Connection = Depends(get_db)):
    token = request.cookies.get("session_token")
    if not token or get_user_by_token(db, token) is None:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    rows = db.execute(
        "SELECT id, username, city, school, grade, level, points, "
        "created_at, last_login_at "
        "FROM users ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/leaderboard")
def leaderboard_api(request: Request, db: sqlite3.Connection = Depends(get_db)):
    token = request.cookies.get("session_token")
    if not token or get_user_by_token(db, token) is None:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    rows = db.execute(
        "SELECT id, username, level, points "
        "FROM users "
        "ORDER BY points DESC, level DESC, id ASC "
        "LIMIT 100"
    ).fetchall()

    result = []
    for i, r in enumerate(rows, start=1):
        item = dict(r)
        item["rank"] = i
        result.append(item)
    return result


@router.get("/leaderboard", response_class=HTMLResponse)
def leaderboard_page():
    return FileResponse(STATIC_DIR / "leaderboard.html")



from backend.sources_db import (
    get_connection,
    random_fragment,
    get_confirmed_translation,
    random_distractors,
    save_dispute,
)


@router.get("/api/exercise/random")
def random_exercise(
    user_id: int = Depends(current_user_id),
    db: sqlite3.Connection = Depends(get_db),
):
    from backend.learned import get_learned_ids, record_seen
    from backend.sources_db import (
        get_connection,
        random_short_fragment,
        random_short_distractors,
        get_or_create_translation_with_ai,
    )

    learned = get_learned_ids(db, user_id)

    conn = get_connection()
    try:
        frag = random_short_fragment(conn, exclude_ids=learned)
    finally:
        conn.close()

    if frag is None:
        return JSONResponse({"detail": "No fragments in content.db"}, status_code=404)

    # до 3 попыток: если AI не даёт перевод — берём другой фрагмент
    translation = None
    tried = set()
    for _ in range(3):
        if frag["fragment_id"] in tried:
            conn = get_connection()
            try:
                frag = random_short_fragment(
                    conn, exclude_ids=learned | tried
                )
            finally:
                conn.close()
            if frag is None:
                break
            continue
        tried.add(frag["fragment_id"])
        translation = get_or_create_translation_with_ai(
            frag["fragment_id"], frag["text_ba"], frag["lang_pair"]
        )
        if translation:
            break
        conn = get_connection()
        try:
            frag = random_short_fragment(conn, exclude_ids=learned | tried)
        finally:
            conn.close()
        if frag is None:
            break

    if not translation:
        return JSONResponse(
            {"detail": "AI translation failed (Gemini недоступен)"},
            status_code=503,
        )

    conn = get_connection()
    try:
        distractors = random_short_distractors(
            conn, frag["fragment_id"], frag["lang_pair"], limit=3
        )
    finally:
        conn.close()

    fallback = ["Другое значение", "Неизвестно", "Не подходит"]
    while len(distractors) < 3:
        distractors.append(fallback.pop())

    options = distractors + [translation]
    random.shuffle(options)

    record_seen(db, user_id, frag["fragment_id"])

    return {
        "fragment_id": frag["fragment_id"],
        "text_ba": frag["text_ba"],
        "translation": translation,
        "options": options,
    }

@router.get("/exercise", response_class=HTMLResponse)
def exercise_page():
    return FileResponse(STATIC_DIR / "exercise.html")

@router.get("/api/me")
def me(request: Request, db: sqlite3.Connection = Depends(get_db)):
    token = request.cookies.get("session_token")
    if not token:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    user_id = get_user_by_token(db, token)
    if user_id is None:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    row = db.execute(
        "SELECT id, username, level, points, city, school, grade, "
        "streak_days, last_activity_date, created_at, last_login_at "
        "FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return JSONResponse({"detail": "User not found"}, status_code=404)
    return dict(row)


@router.get("/api/word-of-day")
def word_of_day(user_id: int = Depends(current_user_id)):
    from backend.sources_db import get_connection, random_fragment
    conn = get_connection()
    try:
        frag = random_fragment(conn)
    finally:
        conn.close()
    if frag is None:
        return JSONResponse({"detail": "No fragments"}, status_code=404)
    return {
        "text_ba": frag["text_ba"],
        "translation": frag["translation"],
    }

class DisputeIn(BaseModel):
    fragment_id: int
    text_ba: str = Field(min_length=1, max_length=1000)
    translation: str = Field(min_length=1, max_length=2000)
    lang_pair: str = Field(default="ba-ru", pattern=r"^[a-z]{2}-[a-z]{2}$")


@router.post("/api/exercise/dispute", status_code=201)
def dispute_translation(data: DisputeIn, user_id: int = Depends(current_user_id)):
    conn = get_connection()
    try:
        tid = save_dispute(
            conn,
            fragment_id=data.fragment_id,
            user_id=user_id,             # ← это users.id (не telegram_id)
            translation=data.translation,
            lang_pair=data.lang_pair,
            text_ba=data.text_ba,
            source="site",
        )
    finally:
        conn.close()
    return {"translation_id": tid}

class AnswerIn(BaseModel):
    fragment_id: int
    correct: bool


@router.get("/api/exercise/status")
def exercise_status(
    user_id: int = Depends(current_user_id),
    db: sqlite3.Connection = Depends(get_db),
):
    """Возвращает: { completed: [fragment_id, ...], correct_count: {fid: n}, points, level }"""
    rows = db.execute(
        "SELECT fragment_id, correct_count FROM learned_words WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    completed = [r["fragment_id"] for r in rows if r["correct_count"] > 0]
    correct_count = {r["fragment_id"]: r["correct_count"] for r in rows}

    user = db.execute(
        "SELECT points, level FROM users WHERE id = ?", (user_id,)
    ).fetchone()

    return {
        "completed": completed,
        "correct_count": correct_count,
        "points": user["points"] if user else 0,
        "level": user["level"] if user else 1,
    }

@router.post("/api/exercise/answer")
def submit_answer(
    data: AnswerIn,
    user_id: int = Depends(current_user_id),
    db: sqlite3.Connection = Depends(get_db),
):
    from backend.learned import record_correct, mark_learned, award_points_event

    if not data.correct:
        return {"ok": True}

    record_correct(db, user_id, data.fragment_id)
    award_points_event(db, user_id, "web_answer", f"{data.fragment_id}", 10)

    row = db.execute(
        "SELECT correct_count FROM learned_words "
        "WHERE user_id = ? AND fragment_id = ?",
        (user_id, data.fragment_id),
    ).fetchone()
    if row and row["correct_count"] >= 3:
        mark_learned(db, user_id, data.fragment_id)

    return {"ok": True}