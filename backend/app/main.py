import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.captures import router as captures_router
from app.api.phase2 import router as phase2_router
from app.api.router import router
from app.config import Settings, get_settings
from app.database import SessionLocal
from app.migrations import upgrade_database, validate_database_revision
from app.models import User
from app.seed import seed_default_tags, seed_starter_playbooks
from app.services.push_notifications import push_configured, run_push_notification_tick

logger = logging.getLogger(__name__)


def prepare_database(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if settings.auto_migrate:
        upgrade_database(settings=settings)
    else:
        validate_database_revision(settings)

    # Creating the local desktop user and default content is useful in local
    # SQLite mode. Hosted startup must remain read-only after the revision check.
    if not settings.bootstrap_local_data:
        return
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == settings.local_user_email))
        if user is None:
            user = User(email=settings.local_user_email, display_name=settings.local_user_name)
            db.add(user)
            db.flush()
        seed_default_tags(db, user)
        seed_starter_playbooks(db, user)
        db.commit()


async def _push_loop() -> None:
    settings = get_settings()
    interval = max(60, settings.push_interval_seconds)
    while True:
        try:
            await asyncio.to_thread(run_push_notification_tick, settings=settings)
        except Exception:
            # Push is supplemental. A transient provider/configuration failure must
            # never take down JournalMe or its broker ingestion path.
            logger.exception("JournalMe push scheduler tick failed")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    prepare_database(settings)
    push_task = asyncio.create_task(_push_loop()) if push_configured(settings) else None
    try:
        yield
    finally:
        if push_task is not None:
            push_task.cancel()
            try:
                await push_task
            except asyncio.CancelledError:
                pass


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
