"""Privacy-preserving audit logging.

Addresses are personal data. By default only a hash of the *normalised* query is logged, enough to
correlate repeats and debug. Without ``TAHDEED_AUDIT_KEY`` this is a plain SHA-256, which someone
holding the log could test guesses against; with the key set it is an HMAC-SHA-256 and cannot be
tested without the key. Raw text is logged only when ``TAHDEED_LOG_RAW=1`` is set explicitly.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid

from .normalize import normalize_text

log = logging.getLogger("tahdeed.audit")


def query_hash(text: str) -> str:
    data = normalize_text(text or "").encode("utf-8")
    key = os.environ.get("TAHDEED_AUDIT_KEY")
    if key:
        return hmac.new(key.encode("utf-8"), data, hashlib.sha256).hexdigest()[:16]
    return hashlib.sha256(data).hexdigest()[:16]


def record(
    text: str, result: dict, ms: float, versions: dict, request_id: str | None = None
) -> dict:
    best = result.get("best") or {}
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "request_id": request_id or uuid.uuid4().hex[:12],
        "q_sha256_16": query_hash(text),
        "status": result.get("status"),
        "tier": best.get("tier"),
        "p50": best.get("p_within_50m"),
        "ms": round(ms, 2),
        **versions,
    }
    if os.environ.get("TAHDEED_LOG_RAW") == "1":
        rec["q"] = text
    log.info(json.dumps(rec, ensure_ascii=False))
    return rec
