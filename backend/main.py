from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from backend.db import init_db, get_db
from backend.routes import auth_routes
from backend.deps import current_user_id


BASE_DIR = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()            # app.db: users, sessions, learned_words
    yield


app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(auth_routes.router)


@app.get("/", response_class=HTMLResponse)
def index(user_id: int = Depends(current_user_id)):
    return FileResponse(BASE_DIR / "static" / "index.html")