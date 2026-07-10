"""Sync endpoints — encrypted backup and restore."""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db import (
    get_backup,
    get_backup_count,
    get_client,
    increment_restore_count,
    list_dreams,
    store_backup,
)
from app.middleware.client import resolve_client
from app.middleware.rate_limit import check_rate_limit
from app.services.encryption import (
    decrypt,
    derive_key,
    encrypt,
    generate_mnemonic,
    phrase_hash,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/sync/init")
async def sync_init(
    client: dict = Depends(resolve_client),
) -> dict:
    """Create an encrypted backup of all dreams. Returns a BIP-39 mnemonic."""
    client_id = client["client_id"]

    # Rate limit check
    await check_rate_limit(client_id, "sync_init", client.get("tier") == "pro")

    # Free tier: max 1 backup
    if client.get("tier") == "free":
        count = await get_backup_count(client_id)
        if count >= 1:
            raise HTTPException(
                status_code=402,
                detail="Multiple backups require a Pro subscription.",
            )

    # Fetch all dreams
    dreams = await list_dreams(client_id)
    dreams_data = [
        {
            "id": d["id"],
            "title": d.get("title"),
            "body": d["body"],
            "createdAt": d["created_at"].isoformat(),
            "analyzedAt": d["analyzed_at"].isoformat() if d.get("analyzed_at") else None,
            "analysis": d.get("analysis"),
            "extraction": d.get("extraction"),
            "imageUrl": d.get("image_url"),
            "tags": d.get("tags") or [],
            "mood": d.get("mood"),
        }
        for d in dreams
    ]

    payload = {
        "client_id": str(client_id),
        "dreams": dreams_data,
    }

    # Generate mnemonic and encrypt
    phrase = generate_mnemonic()
    key = derive_key(phrase)
    encrypted = encrypt(payload, key)
    hashed = phrase_hash(phrase)

    # Store backup
    await store_backup(hashed, encrypted, client_id)

    phrase_words = phrase.split()

    return {
        "phrase": phrase_words,
        "encryptedPayload": encrypted,
    }


class SyncRestoreRequest(BaseModel):
    phrase: list[str]


@router.post("/sync/restore")
async def sync_restore(body: SyncRestoreRequest) -> dict:
    """Decrypt and restore dreams from a recovery phrase."""
    phrase = " ".join(body.phrase)
    hashed = phrase_hash(phrase)

    backup = await get_backup(hashed)
    if not backup:
        raise HTTPException(status_code=404, detail="No backup found for this phrase.")

    # Decrypt
    key = derive_key(phrase)
    try:
        data = decrypt(backup["encrypted_payload"], key)
    except Exception as e:
        logger.error("Decryption failed: %s", str(e))
        raise HTTPException(status_code=400, detail="Invalid recovery phrase.")

    # Increment restore count
    await increment_restore_count(hashed)

    return {
        "client_id": data["client_id"],
        "dreams": data["dreams"],
    }
