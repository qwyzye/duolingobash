import sqlite3
from fastapi import Depends, HTTPException, Request, status

from backend.db import get_db
from backend.auth import get_user_by_token


def current_user_id(
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
) -> int:
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user_id = get_user_by_token(db, token)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    return user_id