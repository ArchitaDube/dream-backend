"""Stripe webhook receiver."""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.db import (
    downgrade_client_by_stripe_customer,
    record_stripe_event,
    stripe_event_exists,
    update_client_tier,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request) -> dict:
    """Handle Stripe webhook events for subscription lifecycle."""
    if not settings.stripe_webhook_secret:
        logger.warning("Stripe webhook secret not configured; skipping verification")
        return {"ok": True}

    import stripe

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig, settings.stripe_webhook_secret
        )
    except Exception as e:
        logger.error("Stripe webhook verification failed: %s", str(e))
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_id = event["id"]

    # Idempotency check
    if await stripe_event_exists(event_id):
        return {"ok": True}

    await record_stripe_event(event_id)

    event_type = event["type"]

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        client_id_str = session.get("metadata", {}).get("client_id")
        stripe_customer_id = session.get("customer")

        if client_id_str and stripe_customer_id:
            client_id = UUID(client_id_str)
            await update_client_tier(client_id, "pro", stripe_customer_id)
            logger.info("Client %s upgraded to pro", client_id)

    elif event_type == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        customer_id = subscription.get("customer")

        if customer_id:
            await downgrade_client_by_stripe_customer(customer_id)
            logger.info("Client with customer %s downgraded to free", customer_id)

    return {"ok": True}
