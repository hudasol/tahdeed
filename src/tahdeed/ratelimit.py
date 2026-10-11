"""Small in-memory token-bucket rate limiter (stdlib only, thread-safe, bounded memory).

One bucket per client key. A bucket holds up to ``burst`` tokens and refills at ``per_minute / 60``
tokens per second; a request costs ``cost`` tokens. Buckets that have been idle long enough to be
full again are indistinguishable from a fresh bucket, so they are evicted; if the table is still
over ``max_clients`` the least recently used buckets are dropped. Eviction can only ever *forgive*
a client (it restarts with a full bucket), never block one.

This is per-process state: with several workers or replicas each has its own table, so the
effective limit is multiplied by the number of processes. It limits abuse of a single small
instance; it is not a substitute for an edge or CDN limiter.

No request content is ever stored: only the client key (an IP address) and two floats.
"""

from __future__ import annotations

import ipaddress
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping

DEFAULT_PER_MINUTE = 60
BATCH_ROWS_PER_TOKEN = 50  # /resolve/batch costs one token per 50 rows, minimum one
MAX_KEY_LEN = 64  # longer than any textual IPv6 address


def parse_limit(value: str | None, default: int = DEFAULT_PER_MINUTE) -> int:
    """Requests per minute from an env string. ``0`` or negative disables; junk -> default."""
    if value is None or not value.strip():
        return default
    try:
        n = int(value.strip())
    except ValueError:
        return default
    return max(n, 0)


def burst_for(per_minute: int) -> int:
    """Bucket capacity: a quarter of the per-minute limit, at least 5."""
    return max(5, per_minute // 4)


def batch_cost(rows: int) -> int:
    """Tokens charged for a batch of ``rows`` addresses."""
    return max(1, math.ceil(rows / BATCH_ROWS_PER_TOKEN))


class TokenBucketLimiter:
    def __init__(
        self,
        per_minute: int,
        burst: int | None = None,
        *,
        max_clients: int = 10_000,
        idle_ttl: float = 600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if per_minute <= 0:
            raise ValueError("per_minute must be positive (use no limiter to disable)")
        self.rate = per_minute / 60.0  # tokens per second
        self.capacity = float(burst if burst is not None else burst_for(per_minute))
        self.max_clients = max(1, max_clients)
        # a bucket idle for capacity/rate seconds is full again, so it carries no information
        self.idle_ttl = max(idle_ttl, self.capacity / self.rate)
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()  # key -> (tokens, t)

    def __len__(self) -> int:
        with self._lock:
            return len(self._buckets)

    def check(self, key: str, cost: float = 1.0) -> tuple[bool, int]:
        """Try to take ``cost`` tokens. Returns ``(allowed, retry_after_seconds)``.

        A cost above the bucket capacity is clamped to it (it could never succeed otherwise), so
        the largest requests drain a full bucket instead of being refused forever.
        """
        key = key[:MAX_KEY_LEN]
        cost = min(max(cost, 0.0), self.capacity)
        with self._lock:
            now = self._clock()
            tokens, last = self._buckets.pop(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + max(0.0, now - last) * self.rate)
            if tokens >= cost:
                tokens -= cost
                allowed, retry = True, 0
            else:
                allowed, retry = False, max(1, math.ceil((cost - tokens) / self.rate))
            self._buckets[key] = (tokens, now)  # most recently used goes last
            if len(self._buckets) > self.max_clients:
                self._evict(now)
            return allowed, retry

    def _evict(self, now: float) -> None:
        # Oldest entries are first. Drop the ones that are idle (full again) ...
        while self._buckets:
            k, (_, last) = next(iter(self._buckets.items()))
            if now - last < self.idle_ttl:
                break
            del self._buckets[k]
        # ... and if an attacker is rotating addresses, drop least recently used regardless.
        while len(self._buckets) > self.max_clients:
            self._buckets.popitem(last=False)


def client_key(
    peer: str | None,
    headers: Mapping[str, str],
    *,
    trust_proxy: bool = False,
    proxy_hops: int = 1,
) -> str:
    """Identify the caller. ``X-Forwarded-For`` is used only when ``trust_proxy`` is set.

    Each trusted proxy appends the address it saw to the right of the header, so with N trusted
    proxies the real client is the Nth entry from the right; entries further left are
    client-supplied and spoofable. A missing or malformed header falls back to the socket peer.
    """
    fallback = peer or "unknown"
    if not trust_proxy:
        return fallback
    parts = [p.strip() for p in headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if not parts or proxy_hops < 1 or proxy_hops > len(parts):
        return fallback
    cand = parts[-proxy_hops]
    try:
        return str(ipaddress.ip_address(cand))
    except ValueError:
        return fallback
