"""Download the gazetteer and model for a hosted deployment at BUILD time (stdlib only).

    TAHDEED_GAZETTEER_URL=https://.../gazetteer.sqlite.gz \
    TAHDEED_GAZETTEER_SHA256=<sha256 of the DECOMPRESSED file> \
    TAHDEED_MODEL_URL=https://.../ranker.npz \
    TAHDEED_MODEL_SHA256=<sha256> \
    python deploy/fetch_data.py --dest data

Writes ``DEST/gazetteer.sqlite`` and ``DEST/ranker.npz``. A URL ending in ``.gz`` is gunzipped on
the fly (a 50 MB gazetteer compresses to roughly a third). HTTPS only. When a ``*_SHA256`` is set the
download is verified and the build fails on a mismatch; set them. Existing files whose hash already
matches are kept, so rebuilding is cheap.

Why this exists: the data are ODbL-derived and large, so they are not in git (see docs/DEPLOYMENT.md).
Host a copy yourself, for example as a GitHub Release asset; that URL is also a natural place to
satisfy the ODbL "offer a copy" duty (TAHDEED_DATA_OFFER_URL).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import shutil
import sys
import urllib.request
from pathlib import Path

JOBS = (
    ("TAHDEED_GAZETTEER_URL", "TAHDEED_GAZETTEER_SHA256", "gazetteer.sqlite"),
    ("TAHDEED_MODEL_URL", "TAHDEED_MODEL_SHA256", "ranker.npz"),
)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, dest: Path, want_sha: str | None) -> None:
    if not url.startswith("https://"):
        sys.exit(f"refusing non-HTTPS URL for {dest.name}")
    if want_sha and dest.exists() and sha256_of(dest) == want_sha:
        print(f"{dest.name}: already present, hash matches")
        return
    tmp = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "tahdeed-fetch/1"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as out:  # noqa: S310
        src = gzip.GzipFile(fileobj=r) if url.split("?")[0].endswith(".gz") else r
        shutil.copyfileobj(src, out, 1 << 20)
    got = sha256_of(tmp)
    if want_sha and got != want_sha:
        tmp.unlink(missing_ok=True)
        sys.exit(f"{dest.name}: sha256 mismatch (got {got}, expected {want_sha})")
    if not want_sha:
        print(f"WARNING: no SHA-256 configured for {dest.name}; unverified download ({got})")
    tmp.replace(dest)
    print(f"{dest.name}: {dest.stat().st_size / 1e6:.1f} MB ok")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dest", type=Path, default=Path("data"))
    a = ap.parse_args(argv)
    a.dest.mkdir(parents=True, exist_ok=True)
    for url_var, sha_var, name in JOBS:
        url = os.environ.get(url_var)
        if not url:
            sys.exit(f"{url_var} is not set")
        fetch(url, a.dest / name, os.environ.get(sha_var) or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
