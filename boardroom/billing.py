"""Stripe billing: Checkout for Pro subscriptions, webhooks, and the customer portal.

Uses Stripe's REST API directly (standard library only). Enabled when
STRIPE_SECRET_KEY and STRIPE_PRICE_ID are set.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

API = "https://api.stripe.com/v1"


class BillingError(Exception):
    pass


def stripe_post(secret_key: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        headers={"Authorization": f"Bearer {secret_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read())["error"]["message"]
        except Exception:
            message = f"Stripe returned HTTP {exc.code}"
        raise BillingError(message) from exc
    except urllib.error.URLError as exc:
        raise BillingError("Couldn't reach Stripe.") from exc


def verify_signature(payload: bytes, header: str, secret: str, tolerance: int = 300) -> bool:
    """Check a Stripe-Signature header (scheme v1, HMAC-SHA256 over "timestamp.payload")."""
    try:
        parts = [p.split("=", 1) for p in header.split(",")]
        timestamp = next(v for k, v in parts if k == "t")
        signatures = [v for k, v in parts if k == "v1"]
        ts = int(timestamp)
    except (StopIteration, ValueError):
        return False
    if abs(time.time() - ts) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in signatures)


class Billing:
    def __init__(
        self,
        secret_key: str,
        price_id: str,
        webhook_secret: str,
        post: Callable[[str, str, dict[str, Any]], dict[str, Any]] = stripe_post,
    ):
        self.secret_key = secret_key
        self.price_id = price_id
        self.webhook_secret = webhook_secret
        self._post = post

    def checkout_url(self, user_id: int, email: str, customer_id: str | None, base_url: str) -> str:
        params: dict[str, Any] = {
            "mode": "subscription",
            "line_items[0][price]": self.price_id,
            "line_items[0][quantity]": 1,
            "client_reference_id": str(user_id),
            "success_url": f"{base_url}/#/billing/success",
            "cancel_url": f"{base_url}/#/new",
            "allow_promotion_codes": "true",
        }
        if customer_id:
            params["customer"] = customer_id
        else:
            params["customer_email"] = email
        return self._post(self.secret_key, "/checkout/sessions", params)["url"]

    def portal_url(self, customer_id: str, base_url: str) -> str:
        return self._post(
            self.secret_key,
            "/billing_portal/sessions",
            {"customer": customer_id, "return_url": f"{base_url}/#/new"},
        )["url"]
