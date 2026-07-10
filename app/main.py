"""Oneiros API — FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import close_db, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize DB on startup, close on shutdown."""
    logger.info("Starting Oneiros API...")
    await init_db()
    logger.info("Database initialized")
    yield
    await close_db()
    logger.info("Database connections closed")


app = FastAPI(
    title="Oneiros API",
    description="Dream journaling with Jungian analysis",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and register routers
from app.routers import clients, dreams, dialogue, analysis, image, sync, webhooks

app.include_router(clients.router)
app.include_router(dreams.router)
app.include_router(dialogue.router)
app.include_router(analysis.router)
app.include_router(image.router)
app.include_router(sync.router)
app.include_router(webhooks.router)


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok", "version": "0.1.0"}
