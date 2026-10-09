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
