"""FastAPI entrypoint for the health data hub."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import routes_export, routes_health, routes_mill, routes_oauth, routes_sync
from .config import get_settings
from .db import init_db
from .scheduler import maybe_start

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # dev convenience; use Alembic for production migrations
    poller = maybe_start()  # background Mill Sense poller (if MILL_POLL_ENABLED)
    try:
        yield
    finally:
        if poller is not None:
            await poller.stop()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(routes_health.router)
app.include_router(routes_oauth.router)
app.include_router(routes_sync.router)
app.include_router(routes_export.router)
app.include_router(routes_mill.router)


@app.get("/", tags=["root"])
def root() -> dict:
    return {
        "app": settings.app_name,
        "docs": "/docs",
        "connect_whoop": "/auth/whoop/login",
    }
