"""Database engine, session factory, and query helpers using SQLAlchemy 2.0 async.

Uses asyncpg as the async PostgreSQL driver under the hood.
All queries use ORM-style operations rather than raw SQL.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Optional, TypeVar
from uuid import UUID

from sqlalchemy import select, func, update, delete
from sqlalchemy.exc import OperationalError, TimeoutError as SA_TimeoutError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.models import Backup, Base, Client, Dialogue, Dream, StripeEvent

logger = logging.getLogger(__name__)

_engine = None
_session_factory = None

# ──────────────────────────────────────────────
#  Retry helper for transient DB failures
# ──────────────────────────────────────────────

F = TypeVar("F")

_MAX_RETRIES = 3
_RETRY_DELAYS = [0.5, 1.0, 2.0]  # exponential backoff in seconds


def _is_transient_error(exc: Exception) -> bool:
    """Return True if the exception is likely a transient connection failure."""
    msg = str(exc).lower()
    # asyncpg TimeoutError / connection-closed / broken pipe
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return True
    if isinstance(exc, (OperationalError, SA_TimeoutError)):
        return True
    for keyword in (
        "timeout",
        "connection refused",
        "connection reset",
        "broken pipe",
        "could not connect",
        "ssl error",
        "server closed",
        "connection closed",
        "connection lost",
        "pool exhausted",
    ):
        if keyword in msg:
            return True
    return False


async def run_with_retry(fn, *args, **kwargs):
    """Execute an async DB operation with retry on transient failures.

    Retries up to _MAX_RETRIES times with exponential backoff.
    Only retries errors that match _is_transient_error.
    """
    last_exc = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if not _is_transient_error(exc):
                raise  # non-transient — re-raise immediately
            if attempt < _MAX_RETRIES:
                delay = _RETRY_DELAYS[attempt] if attempt < len(_RETRY_DELAYS) else 2.0
                logger.warning(
                    "Transient DB error (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt + 1, _MAX_RETRIES + 1, exc, delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "DB operation failed after %d retries: %s",
                    _MAX_RETRIES + 1, exc,
                )
    raise last_exc  # type: ignore[misc]


# ──────────────────────────────────────────────
#  Engine / session lifecycle
# ──────────────────────────────────────────────


async def init_db() -> None:
    """Create the async engine, run migrations (create tables), and set up session factory."""
    global _engine, _session_factory
    dsn = settings.database_url

    _engine = create_async_engine(
        dsn,
        pool_size=10,              # base connections in the pool
        max_overflow=20,           # additional connections allowed beyond pool_size
        pool_timeout=10,           # seconds to wait for a connection from the pool
        pool_pre_ping=True,        # verify connection before handing it out
        pool_recycle=1800,         # recycle connections after 30 minutes
        connect_args={
            "timeout": 15,         # asyncpg connection timeout (TCP + SSL handshake)
            "command_timeout": 60, # query timeout for any single command
        },
    )
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

    # Create all tables + indexes
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Create additional indexes (SQLAlchemy metadata doesn't auto-create these)
        from sqlalchemy import text
        for idx in [
            "CREATE INDEX IF NOT EXISTS idx_dreams_client_created ON dreams (client_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_dreams_mood ON dreams (client_id, mood) WHERE mood IS NOT NULL",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_dialogues_dream ON dialogues (dream_id)",
            "CREATE INDEX IF NOT EXISTS idx_dialogues_client ON dialogues (client_id)",
            "CREATE INDEX IF NOT EXISTS idx_backups_client ON backups (client_id)",
        ]:
            await conn.execute(text(idx))


async def close_db() -> None:
    """Dispose of the engine and connection pool."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None


def get_session() -> AsyncSession:
    """Get a new async session from the factory."""
    assert _session_factory is not None, "Database not initialized"
    return _session_factory()


def _model_to_dict(instance) -> dict:
    """Convert a SQLAlchemy model instance to a plain dict."""
    return {c.key: getattr(instance, c.key) for c in instance.__table__.columns}


# ──────────────────────────────────────────────
#  Client queries
# ──────────────────────────────────────────────


async def upsert_client(client_id: UUID) -> dict:
    return await run_with_retry(_upsert_client, client_id)


# last_seen_at only needs coarse accuracy. resolve_client runs on EVERY
# authenticated request (including frontend polling loops), so we skip the write
# unless the timestamp is actually stale — turning the common case into a single
# read instead of a read + write + commit.
LAST_SEEN_THROTTLE = timedelta(minutes=15)


async def _upsert_client(client_id: UUID) -> dict:
    async with get_session() as session:
        result = await session.execute(
            select(Client).where(Client.client_id == client_id)
        )
        client = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)
        if client:
            last_seen = client.last_seen_at
            is_stale = (
                last_seen is None
                or last_seen.tzinfo is None  # naive → just refresh
                or (now - last_seen) > LAST_SEEN_THROTTLE
            )
            if is_stale:
                client.last_seen_at = now
                await session.commit()
        else:
            logger.info("upsert_client: creating new client_id=%s", client_id)
            client = Client(client_id=client_id, last_seen_at=now)
            session.add(client)
            await session.commit()

        return _model_to_dict(client)


async def get_client(client_id: UUID) -> Optional[dict]:
    return await run_with_retry(_get_client, client_id)


async def _get_client(client_id: UUID) -> Optional[dict]:
    logger.info("get_client: looking up client_id=%s", client_id)
    async with get_session() as session:
        result = await session.execute(
            select(Client).where(Client.client_id == client_id)
        )
        client = result.scalar_one_or_none()
        if client:
            logger.info("get_client: found client_id=%s tier=%s", client_id, client.tier)
        else:
            logger.warning("get_client: client_id=%s NOT FOUND in database", client_id)
        return _model_to_dict(client) if client else None


async def touch_client(client_id: UUID) -> None:
    return await run_with_retry(_touch_client, client_id)


async def _touch_client(client_id: UUID) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(Client).where(Client.client_id == client_id)
        )
        client = result.scalar_one_or_none()
        if client:
            client.last_seen_at = func.now()
            await session.commit()


async def get_dream_count(client_id: UUID) -> int:
    return await run_with_retry(_get_dream_count, client_id)


async def _get_dream_count(client_id: UUID) -> int:
    async with get_session() as session:
        result = await session.execute(
            select(func.count(Dream.id)).where(Dream.client_id == client_id)
        )
        return result.scalar() or 0


# ──────────────────────────────────────────────
#  Dream queries
# ──────────────────────────────────────────────


async def create_dream(
    dream_id: str, client_id: UUID, body: str, title: Optional[str] = None
) -> dict:
    return await run_with_retry(_create_dream, dream_id, client_id, body, title)


async def _create_dream(
    dream_id: str, client_id: UUID, body: str, title: Optional[str] = None
) -> dict:
    async with get_session() as session:
        dream = Dream(id=dream_id, client_id=client_id, body=body, title=title)
        session.add(dream)
        await session.commit()
        await session.refresh(dream)
        return _model_to_dict(dream)


async def get_dream(dream_id: str, client_id: UUID) -> Optional[dict]:
    return await run_with_retry(_get_dream, dream_id, client_id)


async def _get_dream(dream_id: str, client_id: UUID) -> Optional[dict]:
    async with get_session() as session:
        result = await session.execute(
            select(Dream).where(Dream.id == dream_id, Dream.client_id == client_id)
        )
        dream = result.scalar_one_or_none()
        return _model_to_dict(dream) if dream else None


async def list_dreams(client_id: UUID) -> list[dict]:
    return await run_with_retry(_list_dreams, client_id)


async def _list_dreams(client_id: UUID) -> list[dict]:
    async with get_session() as session:
        result = await session.execute(
            select(Dream)
            .where(Dream.client_id == client_id)
            .order_by(Dream.created_at.desc())
        )
        return [_model_to_dict(d) for d in result.scalars().all()]


async def delete_dream(dream_id: str, client_id: UUID) -> bool:
    return await run_with_retry(_delete_dream, dream_id, client_id)


async def _delete_dream(dream_id: str, client_id: UUID) -> bool:
    async with get_session() as session:
        result = await session.execute(
            select(Dream).where(Dream.id == dream_id, Dream.client_id == client_id)
        )
        dream = result.scalar_one_or_none()
        if not dream:
            return False
        await session.delete(dream)
        await session.commit()
        return True


async def update_dream_analysis(
    dream_id: str, analysis: dict, mood: str, tags: list[str], title: Optional[str] = None
) -> None:
    return await run_with_retry(
        _update_dream_analysis, dream_id, analysis, mood, tags, title
    )


async def _update_dream_analysis(
    dream_id: str, analysis: dict, mood: str, tags: list[str], title: Optional[str] = None
) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(Dream).where(Dream.id == dream_id)
        )
        dream = result.scalar_one_or_none()
        if not dream:
            return
        dream.analysis = analysis
        dream.mood = mood
        dream.tags = tags
        dream.analyzed_at = func.now()
        if title:
            dream.title = title
        await session.commit()


async def update_dream_extraction(dream_id: str, extraction: dict) -> None:
    return await run_with_retry(_update_dream_extraction, dream_id, extraction)


async def _update_dream_extraction(dream_id: str, extraction: dict) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(Dream).where(Dream.id == dream_id)
        )
        dream = result.scalar_one_or_none()
        if dream:
            dream.extraction = extraction
            await session.commit()


async def update_dream_image(dream_id: str, image_url: str) -> None:
    return await run_with_retry(_update_dream_image, dream_id, image_url)


async def _update_dream_image(dream_id: str, image_url: str) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(Dream).where(Dream.id == dream_id)
        )
        dream = result.scalar_one_or_none()
        if dream:
            dream.image_url = image_url
            await session.commit()


# ──────────────────────────────────────────────
#  Dialogue queries
# ──────────────────────────────────────────────


async def get_dialogue_for_dream(dream_id: str) -> Optional[dict]:
    """Get dialogue for a dream (without creating one). Returns None if no dialogue exists."""
    return await run_with_retry(_get_dialogue_for_dream, dream_id)


async def _get_dialogue_for_dream(dream_id: str) -> Optional[dict]:
    async with get_session() as session:
        result = await session.execute(
            select(Dialogue).where(Dialogue.dream_id == dream_id)
        )
        dialogue = result.scalar_one_or_none()
        return _model_to_dict(dialogue) if dialogue else None


async def get_dialogues_for_dreams(dream_ids: list[str]) -> dict[str, dict]:
    """Batch-load dialogues for many dreams in a single query.

    Returns a {dream_id: dialogue_dict} map. Used to avoid the N+1 query that
    serializing a list of dreams would otherwise incur.
    """
    if not dream_ids:
        return {}
    return await run_with_retry(_get_dialogues_for_dreams, dream_ids)


async def _get_dialogues_for_dreams(dream_ids: list[str]) -> dict[str, dict]:
    async with get_session() as session:
        result = await session.execute(
            select(Dialogue).where(Dialogue.dream_id.in_(dream_ids))
        )
        return {d.dream_id: _model_to_dict(d) for d in result.scalars().all()}


async def get_or_create_dialogue(dream_id: str, client_id: UUID) -> dict:
    return await run_with_retry(_get_or_create_dialogue, dream_id, client_id)


async def _get_or_create_dialogue(dream_id: str, client_id: UUID) -> dict:
    async with get_session() as session:
        result = await session.execute(
            select(Dialogue).where(Dialogue.dream_id == dream_id)
        )
        dialogue = result.scalar_one_or_none()

        if dialogue:
            return _model_to_dict(dialogue)

        import nanoid
        dlg_id = "dlg_" + nanoid.generate(size=10)
        dialogue = Dialogue(id=dlg_id, dream_id=dream_id, client_id=client_id)
        session.add(dialogue)
        await session.commit()
        await session.refresh(dialogue)
        return _model_to_dict(dialogue)


async def update_dialogue_history(dialogue_id: str, history: list) -> None:
    return await run_with_retry(_update_dialogue_history, dialogue_id, history)


async def _update_dialogue_history(dialogue_id: str, history: list) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(Dialogue).where(Dialogue.id == dialogue_id)
        )
        dialogue = result.scalar_one_or_none()
        if dialogue:
            dialogue.history = history
            dialogue.updated_at = func.now()
            await session.commit()


async def complete_dialogue(dream_id: str, client_id: UUID) -> Optional[datetime]:
    return await run_with_retry(_complete_dialogue, dream_id, client_id)


async def _complete_dialogue(dream_id: str, client_id: UUID) -> Optional[datetime]:
    async with get_session() as session:
        result = await session.execute(
            select(Dialogue).where(
                Dialogue.dream_id == dream_id,
                Dialogue.client_id == client_id,
                Dialogue.grounded_at.is_(None),
            )
        )
        dialogue = result.scalar_one_or_none()
        if not dialogue:
            return None
        dialogue.grounded_at = func.now()
        dialogue.updated_at = func.now()
        await session.commit()
        # Refresh to load the server-generated grounded_at timestamp
        # before the session closes and expires the object.
        await session.refresh(dialogue)
        return dialogue.grounded_at


# ──────────────────────────────────────────────
#  Backup queries
# ──────────────────────────────────────────────


async def store_backup(phrase_hash: str, encrypted_payload: str, client_id: UUID) -> None:
    return await run_with_retry(_store_backup, phrase_hash, encrypted_payload, client_id)


async def _store_backup(phrase_hash: str, encrypted_payload: str, client_id: UUID) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(Backup).where(Backup.phrase_hash == phrase_hash)
        )
        backup = result.scalar_one_or_none()

        if backup:
            backup.encrypted_payload = encrypted_payload
            backup.client_id = client_id
        else:
            backup = Backup(
                phrase_hash=phrase_hash,
                encrypted_payload=encrypted_payload,
                client_id=client_id,
            )
            session.add(backup)
        await session.commit()


async def get_backup(phrase_hash: str) -> Optional[dict]:
    return await run_with_retry(_get_backup, phrase_hash)


async def _get_backup(phrase_hash: str) -> Optional[dict]:
    async with get_session() as session:
        result = await session.execute(
            select(Backup).where(Backup.phrase_hash == phrase_hash)
        )
        backup = result.scalar_one_or_none()
        return _model_to_dict(backup) if backup else None


async def increment_restore_count(phrase_hash: str) -> None:
    return await run_with_retry(_increment_restore_count, phrase_hash)


async def _increment_restore_count(phrase_hash: str) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(Backup).where(Backup.phrase_hash == phrase_hash)
        )
        backup = result.scalar_one_or_none()
        if backup:
            backup.restored_count += 1
            await session.commit()


async def get_backup_count(client_id: UUID) -> int:
    return await run_with_retry(_get_backup_count, client_id)


async def _get_backup_count(client_id: UUID) -> int:
    async with get_session() as session:
        result = await session.execute(
            select(func.count(Backup.phrase_hash)).where(Backup.client_id == client_id)
        )
        return result.scalar() or 0


# ──────────────────────────────────────────────
#  Stripe event idempotency
# ──────────────────────────────────────────────


async def stripe_event_exists(event_id: str) -> bool:
    return await run_with_retry(_stripe_event_exists, event_id)


async def _stripe_event_exists(event_id: str) -> bool:
    async with get_session() as session:
        result = await session.execute(
            select(StripeEvent).where(StripeEvent.stripe_event_id == event_id)
        )
        return result.scalar_one_or_none() is not None


async def record_stripe_event(event_id: str) -> None:
    return await run_with_retry(_record_stripe_event, event_id)


async def _record_stripe_event(event_id: str) -> None:
    async with get_session() as session:
        event = StripeEvent(stripe_event_id=event_id)
        session.add(event)
        try:
            await session.commit()
        except Exception:
            await session.rollback()


# ──────────────────────────────────────────────
#  ORM-based helpers for webhooks
# ──────────────────────────────────────────────


async def update_client_tier(client_id: UUID, tier: str, stripe_customer_id: str) -> None:
    """Upgrade a client to Pro tier with Stripe customer ID."""
    return await run_with_retry(_update_client_tier, client_id, tier, stripe_customer_id)


async def _update_client_tier(client_id: UUID, tier: str, stripe_customer_id: str) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(Client).where(Client.client_id == client_id)
        )
        client = result.scalar_one_or_none()
        if client:
            client.tier = tier
            client.stripe_customer_id = stripe_customer_id
            await session.commit()


async def downgrade_client_by_stripe_customer(stripe_customer_id: str) -> None:
    """Downgrade a client to free tier by Stripe customer ID."""
    return await run_with_retry(_downgrade_client_by_stripe_customer, stripe_customer_id)


async def _downgrade_client_by_stripe_customer(stripe_customer_id: str) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(Client).where(Client.stripe_customer_id == stripe_customer_id)
        )
        client = result.scalar_one_or_none()
        if client:
            client.tier = "free"
            await session.commit()
