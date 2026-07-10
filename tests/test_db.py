"""In-memory mock database for testing.

Replaces the real SQLAlchemy-backed DB module with an in-memory store.
This allows all endpoint tests to run without a real PostgreSQL instance.
"""

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID


class _MockDB:
    """In-memory database store for testing."""

    def __init__(self):
        self.clients: dict[str, dict] = {}
        self.dreams: dict[str, dict] = {}
        self.dialogues: dict[str, dict] = {}
        self.backups: dict[str, dict] = {}
        self.stripe_events: set[str] = set()
        self._dream_counter = 0

    def reset(self):
        """Reset all data between tests."""
        self.clients.clear()
        self.dreams.clear()
        self.dialogues.clear()
        self.backups.clear()
        self.stripe_events.clear()
        self._dream_counter = 0


_mock_db = _MockDB()


def get_mock_db() -> _MockDB:
    return _mock_db


# ──────────────────────────────────────────────
#  Mock implementations of db.py functions
# ──────────────────────────────────────────────

async def init_db() -> None:
    _mock_db.reset()


async def close_db() -> None:
    pass


async def upsert_client(client_id: UUID) -> dict:
    now = datetime.now(timezone.utc)
    cid = str(client_id)
    if cid in _mock_db.clients:
        _mock_db.clients[cid]["last_seen_at"] = now
    else:
        _mock_db.clients[cid] = {
            "client_id": cid,
            "created_at": now,
            "last_seen_at": now,
            "tier": "free",
            "tier_expires_at": None,
            "stripe_customer_id": None,
        }
    return _mock_db.clients[cid]


async def get_client(client_id: UUID) -> Optional[dict]:
    return _mock_db.clients.get(str(client_id))


async def touch_client(client_id: UUID) -> None:
    cid = str(client_id)
    if cid in _mock_db.clients:
        _mock_db.clients[cid]["last_seen_at"] = datetime.now(timezone.utc)


async def get_dream_count(client_id: UUID) -> int:
    cid = str(client_id)
    return sum(1 for d in _mock_db.dreams.values() if d["client_id"] == cid)


async def create_dream(dream_id: str, client_id: UUID, body: str, title: Optional[str] = None) -> dict:
    now = datetime.now(timezone.utc)
    dream = {
        "id": dream_id,
        "client_id": str(client_id),
        "title": title,
        "body": body,
        "created_at": now,
        "analyzed_at": None,
        "analysis": None,
        "extraction": None,
        "image_url": None,
        "tags": [],
        "mood": None,
    }
    _mock_db.dreams[dream_id] = dream
    return dream


async def get_dream(dream_id: str, client_id: UUID) -> Optional[dict]:
    dream = _mock_db.dreams.get(dream_id)
    if dream and dream["client_id"] == str(client_id):
        return dream
    return None


async def list_dreams(client_id: UUID) -> list[dict]:
    cid = str(client_id)
    dreams = [d for d in _mock_db.dreams.values() if d["client_id"] == cid]
    dreams.sort(key=lambda d: d["created_at"], reverse=True)
    return dreams


async def delete_dream(dream_id: str, client_id: UUID) -> bool:
    dream = _mock_db.dreams.get(dream_id)
    if dream and dream["client_id"] == str(client_id):
        del _mock_db.dreams[dream_id]
        # Also clean up dialogue
        for dlg_id, dlg in list(_mock_db.dialogues.items()):
            if dlg["dream_id"] == dream_id:
                del _mock_db.dialogues[dlg_id]
        return True
    return False


async def update_dream_analysis(
    dream_id: str, analysis: dict, mood: str, tags: list[str], title: Optional[str] = None
) -> None:
    dream = _mock_db.dreams.get(dream_id)
    if dream:
        dream["analysis"] = analysis
        dream["mood"] = mood
        dream["tags"] = tags
        dream["analyzed_at"] = datetime.now(timezone.utc)
        if title:
            dream["title"] = title


async def update_dream_extraction(dream_id: str, extraction: dict) -> None:
    dream = _mock_db.dreams.get(dream_id)
    if dream:
        dream["extraction"] = extraction


async def update_dream_image(dream_id: str, image_url: str) -> None:
    dream = _mock_db.dreams.get(dream_id)
    if dream:
        dream["image_url"] = image_url


async def get_dialogue_for_dream(dream_id: str) -> Optional[dict]:
    for dlg in _mock_db.dialogues.values():
        if dlg["dream_id"] == dream_id:
            return dlg
    return None


async def get_dialogues_for_dreams(dream_ids: list[str]) -> dict[str, dict]:
    ids = set(dream_ids)
    return {
        dlg["dream_id"]: dlg
        for dlg in _mock_db.dialogues.values()
        if dlg["dream_id"] in ids
    }


async def get_or_create_dialogue(dream_id: str, client_id: UUID) -> dict:
    for dlg in _mock_db.dialogues.values():
        if dlg["dream_id"] == dream_id:
            return dlg

    dlg_id = "dlg_mock_" + dream_id[-6:]
    now = datetime.now(timezone.utc)
    dialogue = {
        "id": dlg_id,
        "dream_id": dream_id,
        "client_id": str(client_id),
        "history": [],
        "grounded_at": None,
        "created_at": now,
        "updated_at": now,
    }
    _mock_db.dialogues[dlg_id] = dialogue
    return dialogue


async def update_dialogue_history(dialogue_id: str, history: list) -> None:
    dlg = _mock_db.dialogues.get(dialogue_id)
    if dlg:
        dlg["history"] = history
        dlg["updated_at"] = datetime.now(timezone.utc)


async def complete_dialogue(dream_id: str, client_id: UUID) -> Optional[datetime]:
    # Auto-create dialogue if it doesn't exist (mirrors real behavior)
    dlg = None
    for d in _mock_db.dialogues.values():
        if d["dream_id"] == dream_id and d["client_id"] == str(client_id):
            dlg = d
            break

    if dlg is None:
        dlg = await get_or_create_dialogue(dream_id, client_id)

    if dlg["grounded_at"] is None:
        dlg["grounded_at"] = datetime.now(timezone.utc)
        dlg["updated_at"] = datetime.now(timezone.utc)
        return dlg["grounded_at"]
    return None


async def store_backup(phrase_hash: str, encrypted_payload: str, client_id: UUID) -> None:
    _mock_db.backups[phrase_hash] = {
        "phrase_hash": phrase_hash,
        "encrypted_payload": encrypted_payload,
        "client_id": str(client_id),
        "created_at": datetime.now(timezone.utc),
        "restored_count": 0,
    }


async def get_backup(phrase_hash: str) -> Optional[dict]:
    return _mock_db.backups.get(phrase_hash)


async def increment_restore_count(phrase_hash: str) -> None:
    backup = _mock_db.backups.get(phrase_hash)
    if backup:
        backup["restored_count"] += 1


async def get_backup_count(client_id: UUID) -> int:
    cid = str(client_id)
    return sum(1 for b in _mock_db.backups.values() if b["client_id"] == cid)


async def stripe_event_exists(event_id: str) -> bool:
    return event_id in _mock_db.stripe_events


async def record_stripe_event(event_id: str) -> None:
    _mock_db.stripe_events.add(event_id)


# ──────────────────────────────────────────────
#  Webhook helpers (ORM-based)
# ──────────────────────────────────────────────


async def update_client_tier(client_id: UUID, tier: str, stripe_customer_id: str) -> None:
    cid = str(client_id)
    if cid in _mock_db.clients:
        _mock_db.clients[cid]["tier"] = tier
        _mock_db.clients[cid]["stripe_customer_id"] = stripe_customer_id


async def downgrade_client_by_stripe_customer(stripe_customer_id: str) -> None:
    for client in _mock_db.clients.values():
        if client.get("stripe_customer_id") == stripe_customer_id:
            client["tier"] = "free"
            break
