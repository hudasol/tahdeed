import io

from fastapi.testclient import TestClient

from tahdeed.api import create_app


def _client(resolver):
    return TestClient(create_app(resolver))


def test_health(resolver):
    j = _client(resolver).get("/health").json()
    assert j["status"] == "ok" and j["gazetteer_stats"]["addresses"] > 1000


def test_resolve_endpoint(resolver):
    r = _client(resolver).post(
        "/resolve", json={"address": "29 Shabib Bin Saeed Al Muhairi Street, Al Khalidiyah"}
    )
    j = r.json()
    assert r.status_code == 200 and j["best"]["standard"]["ar"]
    assert 0.0 <= j["best"]["p_correct_at_tier"] <= 1.0


def test_empty_address_rejected(resolver):
    assert _client(resolver).post("/resolve", json={"address": "  "}).status_code == 422


def test_batch_csv(resolver):
    data = "address\nAl Khalidiyah Abu Dhabi\n29 Shabib Bin Saeed Al Muhairi Street Al Khalidiyah\n"
    r = _client(resolver).post(
        "/resolve/batch", files={"file": ("a.csv", io.BytesIO(data.encode()))}
    )
    lines = r.text.strip().splitlines()
    assert r.status_code == 200 and len(lines) == 3 and lines[0].startswith("address,status")


def test_batch_requires_column(resolver):
    r = _client(resolver).post("/resolve/batch", files={"file": ("a.csv", io.BytesIO(b"x\n1\n"))})
    assert r.status_code == 422


def test_security_headers_and_request_id(resolver):
    r = _client(resolver).get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-request-id"]


def test_degraded_flag_is_explicit(resolver):
    j = _client(resolver).post("/resolve", json={"address": "Al Khalidiyah, Abu Dhabi"}).json()
    # the test fixture uses the uncalibrated heuristic: the API must say so
    assert j["degraded"] is False or j["calibrated"] is False


def test_oversized_body_rejected(resolver):
    r = _client(resolver).post("/resolve", content=b"x", headers={"content-length": "99999999"})
    assert r.status_code == 413


def test_token_auth(monkeypatch, resolver):
    monkeypatch.setenv("TAHDEED_API_TOKEN", "s3cret")
    c = _client(resolver)
    assert c.post("/resolve", json={"address": "x"}).status_code == 401
    ok = c.post(
        "/resolve", json={"address": "Al Khalidiyah"}, headers={"authorization": "Bearer s3cret"}
    )
    assert ok.status_code == 200


def test_config_carries_odbl_attribution(monkeypatch, resolver):
    monkeypatch.setenv("TAHDEED_DATA_OFFER_URL", "https://example.org/data")
    j = _client(resolver).get("/config").json()
    assert "OpenStreetMap" in j["attribution"] and "ODbL" in j["attribution"]
    assert j["data_offer_url"] == "https://example.org/data" and j["tile_url"]


PII_QUERY = (
    "29 Shabib Bin Saeed Al Muhairi Street, Al Khalidiyah call +971 50 123 4567 / 0509876543 "
    "mail huda.test@example.com eid 784-1990-1234567-1"
)
PII_NEEDLES = ("123 4567", "1234567", "0509876543", "huda.test", "example.com", "784-1990")


def _logs(caplog) -> str:
    return "\n".join(rec.getMessage() for rec in caplog.records)


def _post_logged(caplog, resolver, monkeypatch, query, raw=False):
    import logging

    monkeypatch.delenv("TAHDEED_API_TOKEN", raising=False)
    monkeypatch.setenv("TAHDEED_RATE_LIMIT", "0")
    if raw:
        monkeypatch.setenv("TAHDEED_LOG_RAW", "1")
    else:
        monkeypatch.delenv("TAHDEED_LOG_RAW", raising=False)
    with caplog.at_level(logging.DEBUG):
        r = _client(resolver).post("/resolve", json={"address": query})
    assert r.status_code == 200
    return r


def test_pii_never_reaches_logs_by_default(monkeypatch, resolver, caplog):
    r = _post_logged(caplog, resolver, monkeypatch, PII_QUERY)
    logs = _logs(caplog)
    assert (
        "q_sha256_16" in logs
    )  # the audit record was emitted, so the absence below means something
    assert "Shabib" not in logs  # raw text is off by default
    for needle in PII_NEEDLES:
        assert needle not in logs and needle not in r.text


def test_pii_redacted_even_when_raw_logging_enabled(monkeypatch, resolver, caplog):
    _post_logged(caplog, resolver, monkeypatch, PII_QUERY, raw=True)
    logs = _logs(caplog)
    assert "Shabib" in logs  # explicit opt-in logs the (redacted) text
    for needle in PII_NEEDLES:
        assert needle not in logs


def test_pii_not_logged_by_batch(monkeypatch, resolver, caplog):
    import logging

    monkeypatch.setenv("TAHDEED_LOG_RAW", "1")
    monkeypatch.setenv("TAHDEED_RATE_LIMIT", "0")
    data = f'address\n"{PII_QUERY}"\n'
    with caplog.at_level(logging.DEBUG):
        r = _client(resolver).post(
            "/resolve/batch", files={"file": ("a.csv", io.BytesIO(data.encode()))}
        )
    assert r.status_code == 200
    logs = _logs(caplog)
    assert "q_sha256_16" in logs
    for needle in PII_NEEDLES:
        assert needle not in logs


def test_audit_hash_does_not_depend_on_pii(monkeypatch, resolver, caplog):
    """The logged hash must not be a dictionary-attackable pseudonym of a phone number."""
    import re

    _post_logged(caplog, resolver, monkeypatch, "Al Khalidiyah call 0501111111")
    a = _logs(caplog)
    caplog.clear()
    _post_logged(caplog, resolver, monkeypatch, "Al Khalidiyah call 0502222222")
    b = _logs(caplog)
    ha, hb = (re.search(r'"q_sha256_16": "(\w+)"', x).group(1) for x in (a, b))
    assert ha == hb
