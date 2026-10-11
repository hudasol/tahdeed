import io
import logging

import pytest
from fastapi.testclient import TestClient

from tahdeed.api import create_app
from tahdeed.ratelimit import (
    TokenBucketLimiter,
    batch_cost,
    burst_for,
    client_key,
    parse_limit,
)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_parse_limit_and_burst():
    assert parse_limit(None) == 60 and parse_limit("") == 60 and parse_limit("abc") == 60
    assert parse_limit("0") == 0 and parse_limit("-5") == 0 and parse_limit("120") == 120
    assert burst_for(60) == 15 and burst_for(8) == 5 and burst_for(400) == 100
    assert batch_cost(1) == 1 and batch_cost(50) == 1 and batch_cost(51) == 2
    assert batch_cost(5000) == 100


def test_bucket_burst_refill_and_retry_after():
    clk = Clock()
    lim = TokenBucketLimiter(60, 5, clock=clk)  # 1 token/s, capacity 5
    assert [lim.check("a")[0] for _ in range(5)] == [True] * 5
    ok, retry = lim.check("a")
    assert not ok and retry == 1
    assert lim.check("b")[0]  # other clients are independent
    clk.t += 2.0
    assert lim.check("a")[0] and lim.check("a")[0] and not lim.check("a")[0]
    clk.t += 1000.0  # refill is capped at capacity
    assert [lim.check("a")[0] for _ in range(6)] == [True] * 5 + [False]


def test_cost_above_capacity_is_clamped_not_refused_forever():
    lim = TokenBucketLimiter(60, 5, clock=Clock())
    assert lim.check("a", 100)[0]  # drains the whole bucket
    assert not lim.check("a")[0]


def test_memory_is_bounded_and_idle_buckets_evicted():
    clk = Clock()
    lim = TokenBucketLimiter(60, 5, max_clients=100, idle_ttl=10, clock=clk)
    for i in range(1000):
        lim.check(f"10.0.{i // 256}.{i % 256}")
    assert len(lim) <= 100
    clk.t += 10_000
    for i in range(101):  # once over the bound, idle buckets are swept first
        lim.check(f"x{i}")
    assert len(lim) <= 100


def test_client_key_xff_only_when_trusted():
    h = {"x-forwarded-for": "6.6.6.6, 203.0.113.9"}
    assert client_key("10.0.0.1", h) == "10.0.0.1"
    assert client_key("10.0.0.1", h, trust_proxy=True) == "203.0.113.9"  # rightmost, not spoofable
    assert client_key("10.0.0.1", h, trust_proxy=True, proxy_hops=2) == "6.6.6.6"
    assert client_key("10.0.0.1", h, trust_proxy=True, proxy_hops=3) == "10.0.0.1"
    assert client_key("10.0.0.1", {"x-forwarded-for": "junk"}, trust_proxy=True) == "10.0.0.1"
    assert client_key("10.0.0.1", {}, trust_proxy=True) == "10.0.0.1"


def _client(resolver, monkeypatch, limit="20", **env):
    monkeypatch.setenv("TAHDEED_RATE_LIMIT", limit)  # burst 5
    monkeypatch.delenv("TAHDEED_TRUST_PROXY", raising=False)
    monkeypatch.delenv("TAHDEED_API_TOKEN", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return TestClient(create_app(resolver))


def _post(c, **kw):
    return c.post("/resolve", json={"address": "Al Khalidiyah, Abu Dhabi"}, **kw)


def test_429_after_burst_with_retry_after_and_json_body(resolver, monkeypatch):
    c = _client(resolver, monkeypatch)
    codes = [_post(c).status_code for _ in range(8)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429] * 3
    r = _post(c)
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1
    j = r.json()
    assert j["error"] == "rate limit exceeded" and j["retry_after_seconds"] >= 1
    assert "Khalidiyah" not in r.text  # nothing about the query comes back
    assert r.headers["x-content-type-options"] == "nosniff"


def test_health_is_exempt(resolver, monkeypatch):
    c = _client(resolver, monkeypatch)
    for _ in range(8):
        _post(c)
    assert _post(c).status_code == 429
    assert all(c.get("/health").status_code == 200 for _ in range(30))


def test_disabled_with_zero(resolver, monkeypatch):
    c = _client(resolver, monkeypatch, limit="0")
    assert c.app.state.limiter is None
    assert all(_post(c).status_code == 200 for _ in range(40))


def test_default_is_60_per_minute(resolver, monkeypatch):
    monkeypatch.delenv("TAHDEED_RATE_LIMIT", raising=False)
    lim = create_app(resolver).state.limiter
    assert lim.rate == pytest.approx(1.0) and lim.capacity == 15


def test_xff_ignored_unless_trusted(resolver, monkeypatch):
    c = _client(resolver, monkeypatch)
    # spoofing a fresh address per request must not buy a fresh bucket
    codes = [_post(c, headers={"x-forwarded-for": f"198.51.100.{i}"}).status_code for i in range(8)]
    assert codes.count(429) == 3


def test_xff_honoured_when_trusted(resolver, monkeypatch):
    c = _client(resolver, monkeypatch, TAHDEED_TRUST_PROXY="1")
    for _ in range(5):
        assert _post(c, headers={"x-forwarded-for": "203.0.113.1"}).status_code == 200
    assert _post(c, headers={"x-forwarded-for": "203.0.113.1"}).status_code == 429
    # a different client behind the proxy still has its own bucket
    assert _post(c, headers={"x-forwarded-for": "203.0.113.2"}).status_code == 200
    # a client-supplied leftmost entry does not change which bucket is used
    assert _post(c, headers={"x-forwarded-for": "1.2.3.4, 203.0.113.1"}).status_code == 429


def test_batch_costs_one_token_per_50_rows(resolver, monkeypatch):
    c = _client(resolver, monkeypatch)  # capacity 5
    rows = "address\n" + "Al Khalidiyah\n" * 120  # 3 tokens in total (1 charged up front + 2)
    r = c.post("/resolve/batch", files={"file": ("a.csv", io.BytesIO(rows.encode()))})
    assert r.status_code == 200
    # 2 tokens left: a second 120-row batch cannot be afforded
    r = c.post("/resolve/batch", files={"file": ("a.csv", io.BytesIO(rows.encode()))})
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert r.json()["error"] == "rate limit exceeded"


def test_rate_limited_requests_are_not_logged_with_query(resolver, monkeypatch, caplog):
    c = _client(resolver, monkeypatch)
    with caplog.at_level(logging.DEBUG):
        for _ in range(8):
            c.post("/resolve", json={"address": "SECRET-STREET-NAME 0501234567"})
    assert "SECRET-STREET-NAME" not in caplog.text
