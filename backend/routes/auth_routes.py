import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

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
    db: sqlite3.Connection = Depends(get_db),
):
    if password != confirm_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пароли не совпадают")
    if len(password) < 8:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пароль слишком короткий")

    user_id = auth.register_user(db, username, password)
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
    return HTMLResponse(
        '<h1>Вход</h1>'
        '<form action="/login" method="POST">'
        '<p><label>Логин: <input name="username" required></label></p>'
        '<p><label>Пароль: <input type="password" name="password" required></label></p>'
        '<button type="submit">Войти</button>'
        '</form>'
        '<p><a href="/register">Регистрация</a></p>'
    )


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
        "SELECT id, username, level, points, created_at, last_login_at "
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