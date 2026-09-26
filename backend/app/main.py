from contextlib import asynccontextmanager
from pathlib import Path

from alembic.config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.api.captures import router as captures_router
from app.api.phase2 import router as phase2_router
from app.api.router import router
from app.config import get_settings
from app.database import SessionLocal
from app.models import User
from app.seed import seed_default_tags, seed_starter_playbooks


def upgrade_database() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(backend_root / "alembic.ini"))
    alembic_config.set_main_option(
        "script_location", str(backend_root / "alembic")
    )
    command.upgrade(alembic_config, "head")


@asynccontextmanager
async def lifespan(_: FastAPI):
    upgrade_database()
    settings = get_settings()
    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(User.email == settings.local_user_email)
        )
        if user is None:
            user = User(email=settings.local_user_email, display_name=settings.local_user_name)
            db.add(user)
            db.flush()
        seed_default_tags(db, user)
        seed_starter_playbooks(db, user)
        db.commit()
    yield


settings = get_settings()
app = FastAPI(
    title="JournalMe API",
    description="Trading-day journal and deterministic Tradovate import API.",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_, exc: IntegrityError):
    return JSONResponse(
        status_code=409,
        content={"detail": "That record already exists.", "type": exc.__class__.__name__},
    )


app.include_router(router, prefix=settings.api_prefix)
app.include_router(captures_router, prefix=settings.api_prefix)
app.include_router(phase2_router, prefix=settings.api_prefix)
