import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from backend.db import get_db
from backend import auth

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
    # если есть отдельный login.html — положите в static/ и отдайте здесь
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
def logout_submit(request_headers=Depends(lambda: None), db: sqlite3.Connection = Depends(get_db)):
    # проще через Request — перепишем ниже, но оставим заглушку
    return RedirectResponse(url="/login", status_code=303)