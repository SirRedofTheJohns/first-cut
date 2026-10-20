"""Webhook signatures: HMAC-SHA256 over `{timestamp}.{raw body}` (the scheme Stripe uses).

Signing the timestamp together with the body means a captured request can't be replayed
later with a fresh timestamp, and the tolerance window bounds how long a capture is useful.
"""

import hashlib
import hmac
import time

SIGNATURE_HEADER = "X-FirstCut-Signature"
TIMESTAMP_HEADER = "X-FirstCut-Timestamp"
DELIVERY_HEADER = "X-FirstCut-Delivery"


class InvalidSignature(ValueError):
    pass


def sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def verify(
    secret: str,
    timestamp: str | None,
    signature: str | None,
    body: bytes,
    *,
    tolerance_seconds: int = 300,
    now: float | None = None,
) -> None:
    if not timestamp or not signature:
        raise InvalidSignature("missing signature or timestamp header")
    try:
        sent_at = int(timestamp)
    except ValueError as exc:
        raise InvalidSignature("timestamp is not a unix time") from exc
    if abs((now or time.time()) - sent_at) > tolerance_seconds:
        raise InvalidSignature("timestamp outside the allowed window")
    # Constant-time comparison: `==` would leak how many leading characters matched.
    if not hmac.compare_digest(sign(secret, timestamp, body), signature):
        raise InvalidSignature("signature mismatch")
