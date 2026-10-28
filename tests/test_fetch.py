"""Tests for tahdeed.fetch against a local HTTP server (no external network)."""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from tahdeed.fetch import FetchError, fetch_data, load_manifest, sha256_of

FILES = {"gazetteer.sqlite": b"sqlite-bytes" * 1000, "ranker.npz": b"npz-bytes" * 500}


def _manifest(files: dict[str, bytes]) -> dict:
    return {
        "schema_version": 1,
        "version": "test",
        "files": [
            {"name": n, "sha256": hashlib.sha256(b).hexdigest(), "size": len(b)}
            for n, b in files.items()
        ],
    }


@pytest.fixture()
def server():
    served: dict[str, bytes] = {}
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            name = self.path.lstrip("/")
            hits.append(name)
            body = served.get(name)
            if body is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}/releases", served, hits
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_downloads_and_verifies(server, tmp_path):
    base, served, hits = server
    served.update({"releases/" + k: v for k, v in FILES.items()})
    paths = fetch_data(tmp_path / "data", base, _manifest(FILES))
    assert [p.name for p in paths] == ["gazetteer.sqlite", "ranker.npz"]
    for p in paths:
        assert p.read_bytes() == FILES[p.name]
    assert not list((tmp_path / "data").glob("*.part"))


def test_reads_manifest_from_file(server, tmp_path):
    base, served, _ = server
    served.update({"releases/" + k: v for k, v in FILES.items()})
    mf = tmp_path / "MANIFEST.json"
    mf.write_text(json.dumps(_manifest(FILES)))
    assert len(fetch_data(tmp_path / "d", base, mf)) == 2


def test_mismatch_is_refused_and_leaves_no_file(server, tmp_path):
    base, served, _ = server
    served.update({"releases/" + k: v for k, v in FILES.items()})
    served["releases/ranker.npz"] = b"tampered"
    with pytest.raises(FetchError, match="checksum mismatch"):
        fetch_data(tmp_path / "data", base, _manifest(FILES))
    assert not (tmp_path / "data" / "ranker.npz").exists()
    assert not list((tmp_path / "data").glob("*.part"))


def test_existing_valid_file_is_not_downloaded_again(server, tmp_path):
    base, served, hits = server
    served.update({"releases/" + k: v for k, v in FILES.items()})
    fetch_data(tmp_path, base, _manifest(FILES))
    before = len(hits)
    fetch_data(tmp_path, base, _manifest(FILES))
    assert len(hits) == before


def test_corrupt_existing_file_is_replaced(server, tmp_path):
    base, served, _ = server
    served.update({"releases/" + k: v for k, v in FILES.items()})
    (tmp_path / "ranker.npz").write_bytes(b"old")
    fetch_data(tmp_path, base, _manifest(FILES))
    assert sha256_of(tmp_path / "ranker.npz") == hashlib.sha256(FILES["ranker.npz"]).hexdigest()


def test_names_restricts_the_download(server, tmp_path):
    base, served, hits = server
    served.update({"releases/" + k: v for k, v in FILES.items()})
    paths = fetch_data(tmp_path, base, _manifest(FILES), names=["ranker.npz"])
    assert [p.name for p in paths] == ["ranker.npz"]
    assert "releases/gazetteer.sqlite" not in hits
    with pytest.raises(FetchError, match="not in the manifest"):
        fetch_data(tmp_path, base, _manifest(FILES), names=["other.bin"])


def test_http_error_is_wrapped(server, tmp_path):
    base, _, _ = server
    with pytest.raises(FetchError, match="download failed"):
        fetch_data(tmp_path, base, _manifest(FILES))


def test_remote_http_is_refused(tmp_path):
    with pytest.raises(FetchError, match="HTTPS is required"):
        fetch_data(tmp_path, "http://example.com/releases", _manifest(FILES))


@pytest.mark.parametrize("name", ["../evil", "sub/dir.bin", ".hidden", ""])
def test_unsafe_names_are_rejected(name):
    bad = {"schema_version": 1, "files": [{"name": name, "sha256": "0" * 64}]}
    with pytest.raises(FetchError):
        load_manifest(bad)


def test_bad_schema_and_digest_are_rejected():
    with pytest.raises(FetchError, match="schema_version"):
        load_manifest({"schema_version": 2, "files": []})
    with pytest.raises(FetchError, match="sha256"):
        load_manifest({"schema_version": 1, "files": [{"name": "a", "sha256": "xyz"}]})
    with pytest.raises(FetchError, match="twice"):
        load_manifest(
            {
                "schema_version": 1,
                "files": [{"name": "a", "sha256": "0" * 64}, {"name": "a", "sha256": "0" * 64}],
            }
        )


def test_sha256_of(tmp_path: Path):
    p = tmp_path / "x"
    p.write_bytes(b"abc")
    assert sha256_of(p) == hashlib.sha256(b"abc").hexdigest()


def test_install_places_files_where_the_service_expects(server, tmp_path):
    from tahdeed.fetch import install

    base, served, _ = server
    served.update({"releases/" + k: v for k, v in FILES.items()})
    served["releases/MANIFEST.json"] = json.dumps(_manifest(FILES)).encode()
    paths = install(base, tmp_path)
    assert (tmp_path / "gazetteer.sqlite").read_bytes() == FILES["gazetteer.sqlite"]
    assert (tmp_path / "models" / "ranker.npz").read_bytes() == FILES["ranker.npz"]
    assert len(paths) == 2


def test_missing_manifest_is_a_fetch_error(server, tmp_path):
    from tahdeed.fetch import install

    base, _, _ = server
    with pytest.raises(FetchError):
        install(base, tmp_path)
