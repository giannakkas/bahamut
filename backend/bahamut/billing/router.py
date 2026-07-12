"""Stripe billing - subscription management."""
import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from bahamut.auth.router import get_current_user
from bahamut.models import User
from bahamut.config import get_settings

logger = structlog.get_logger()
settings = get_settings()
router = APIRouter()

PLANS = {
    "starter": {
        "name": "Starter", "price": 49,
        "assets": 4, "cycles_per_day": 96, "agents": 6,
        "features": ["FX + Gold signals", "4H timeframe", "Email alerts", "Trade journal"],
    },
    "pro": {
        "name": "Pro", "price": 149,
        "assets": 10, "cycles_per_day": 288, "agents": 6,
        "features": ["All assets (FX, Crypto, Stocks)", "All timeframes",
                     "Breaking news alerts", "AI daily brief", "Priority support"],
    },
    "institutional": {
        "name": "Institutional", "price": 499,
        "assets": "Unlimited", "cycles_per_day": "Unlimited", "agents": 6,
        "features": ["Everything in Pro", "Custom agent weights", "API access",
                     "Multi-user workspace", "Dedicated support", "Custom integrations"],
    },
}


class CreateCheckoutRequest(BaseModel):
    plan: str


@router.get("/plans")
async def get_plans():
    return {"plans": PLANS}


@router.post("/create-checkout")
async def create_checkout(req: CreateCheckoutRequest, user: User = Depends(get_current_user)):
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Billing not configured. Add STRIPE_SECRET_KEY to Railway.")

    plan = PLANS.get(req.plan)
    if not plan:
        raise HTTPException(status_code=400, detail="Invalid plan")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.stripe.com/v1/checkout/sessions",
                auth=(settings.stripe_secret_key, ""),
                data={
                    "mode": "subscription",
                    "payment_method_types[]": "card",
                    "line_items[0][price_data][currency]": "usd",
                    "line_items[0][price_data][unit_amount]": plan["price"] * 100,
                    "line_items[0][price_data][recurring][interval]": "month",
                    "line_items[0][price_data][product_data][name]": f"Bahamut.AI {plan['name']}",
                    "line_items[0][quantity]": "1",
                    "success_url": f"{settings.frontend_url}/settings?billing=success",
                    "cancel_url": f"{settings.frontend_url}/settings?billing=cancelled",
                    "customer_email": user.email,
                    "metadata[user_id]": str(user.id),
                    "metadata[plan]": req.plan,
                },
            )
            resp.raise_for_status()
            session = resp.json()
        return {"checkout_url": session["url"], "session_id": session["id"]}
    except Exception as e:
        logger.error("stripe_error", error=str(e))
        raise HTTPException(status_code=500, detail="Checkout failed")


def _verify_stripe_signature(payload: bytes, sig_header: str, secret: str,
                             tolerance: int = 300) -> bool:
    """Verify a Stripe-Signature header (t=...,v1=...) per Stripe's spec:
    HMAC-SHA256 of "{t}.{payload}" with the webhook secret, constant-time
    compare against every v1 signature, and a timestamp tolerance check."""
    import hmac
    import hashlib
    import time as _t
    try:
        parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
        ts = int(parts.get("t", "0"))
        if abs(_t.time() - ts) > tolerance:
            return False
        signed = f"{ts}.".encode() + payload
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        v1_sigs = [v for k, v in
                   (p.split("=", 1) for p in sig_header.split(",") if "=" in p)
                   if k == "v1"]
        return any(hmac.compare_digest(expected, s) for s in v1_sigs)
    except Exception:
        return False


@router.post("/webhook")
async def stripe_webhook(request: Request):
    # Verify the event actually came from Stripe. Previously unauthenticated:
    # anyone could POST a forged checkout.session.completed.
    payload = await request.body()
    secret = settings.stripe_webhook_secret
    if secret:
        sig = request.headers.get("stripe-signature", "")
        if not sig or not _verify_stripe_signature(payload, sig, secret):
            logger.warning("stripe_webhook_bad_signature")
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        logger.warning("stripe_webhook_unverified",
                       reason="STRIPE_WEBHOOK_SECRET not configured")

    import json as _json
    try:
        body = _json.loads(payload)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload")
    event_type = body.get("type", "")
    if event_type == "checkout.session.completed":
        session = body["data"]["object"]
        logger.info("subscription_created",
                     user_id=session.get("metadata", {}).get("user_id"),
                     plan=session.get("metadata", {}).get("plan"))
    elif event_type == "customer.subscription.deleted":
        logger.info("subscription_cancelled")
    return JSONResponse({"status": "ok"})


@router.get("/status")
async def billing_status(user: User = Depends(get_current_user)):
    return {"plan": "pro", "status": "trial", "trial_days_remaining": 14,
            "features": PLANS["pro"]["features"]}
