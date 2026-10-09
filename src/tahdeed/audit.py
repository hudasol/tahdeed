"""Privacy-preserving audit logging.

Addresses are personal data. By default only a salted-free SHA-256 of the *normalised* query is
logged (enough to correlate repeats and debug, not to read the address). Raw text is logged only
when ``TAHDEED_LOG_RAW=1`` is set explicitly.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid

from .normalize import normalize_text

log = logging.getLogger("tahdeed.audit")


def query_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text or "").encode("utf-8")).hexdigest()[:16]


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
