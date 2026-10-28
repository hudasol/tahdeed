"""Download the gazetteer and the ranker from a release and verify them against a manifest.

The gazetteer and the model are derived from OpenStreetMap (ODbL) and are large, so they are not
stored in the repository. They are published as release assets together with ``MANIFEST.json``
(schema in ``docs/DEPLOYMENT.md``). :func:`fetch_data` downloads the files named in the manifest,
checks the SHA-256 of every file and refuses to keep a file whose hash does not match.

Only the standard library is used. Remote URLs must be HTTPS; plain HTTP is accepted only for a
loopback host, which is how the tests run.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

__all__ = ["FetchError", "fetch_data", "load_manifest", "sha256_of"]

MANIFEST_SCHEMA_VERSION = 1
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_CHUNK = 1 << 20


class FetchError(RuntimeError):
    """Raised when a download fails or does not match the manifest."""


def sha256_of(path: str | Path) -> str:
    """Return the hex SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(manifest: str | os.PathLike[str] | Mapping[str, Any]) -> dict[str, Any]:
    """Read and validate a manifest given as a path or an already parsed mapping."""
    if isinstance(manifest, Mapping):
        doc: dict[str, Any] = dict(manifest)
    else:
        doc = json.loads(Path(manifest).read_text(encoding="utf-8"))
    if doc.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise FetchError(
            f"unsupported manifest schema_version {doc.get('schema_version')!r}; "
            f"expected {MANIFEST_SCHEMA_VERSION}"
        )
    files = doc.get("files")
    if not isinstance(files, list) or not files:
        raise FetchError("manifest has no files")
    seen: set[str] = set()
    for entry in files:
        name = entry.get("name") if isinstance(entry, dict) else None
        digest = entry.get("sha256") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not name or name != Path(name).name or name.startswith("."):
            raise FetchError(f"manifest file name is not a plain file name: {name!r}")
        if name in seen:
            raise FetchError(f"manifest lists {name} twice")
        seen.add(name)
        if not isinstance(digest, str) or len(digest) != 64 or digest != digest.lower():
            raise FetchError(f"manifest sha256 for {name} is not 64 lowercase hex digits")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise FetchError(f"manifest sha256 for {name} is not hexadecimal") from exc
    return doc


def _check_url(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return
    if parts.scheme == "http" and parts.hostname in _LOOPBACK:
        return
    raise FetchError(f"refusing to download from {url!r}: HTTPS is required")


def _download(url: str, part: Path, timeout: float) -> str:
    """Stream ``url`` into ``part`` and return the SHA-256 of what was written."""
    h = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": "tahdeed-fetch/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(part, "wb") as out:  # noqa: S310
            for chunk in iter(lambda: resp.read(_CHUNK), b""):
                h.update(chunk)
                out.write(chunk)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        part.unlink(missing_ok=True)
        raise FetchError(f"download failed for {url}: {exc}") from exc
    return h.hexdigest()


def fetch_data(
    dest: str | os.PathLike[str],
    base_url: str,
    manifest: str | os.PathLike[str] | Mapping[str, Any],
    *,
    names: Iterable[str] | None = None,
    timeout: float = 120.0,
) -> list[Path]:
    """Download the files listed in ``manifest`` from ``base_url`` into ``dest``.

    Each file is fetched from ``base_url/<name>``, written to a temporary ``.part`` file and renamed
    into place only if its SHA-256 equals the manifest value and, when the manifest gives one, its
    size matches. A mismatch raises :class:`FetchError` and leaves no file behind. A file that is
    already present with the right hash is kept and not downloaded again.

    ``names`` restricts the download to some entries of the manifest (for example only
    ``ranker.npz``). Returns the paths of the verified files in manifest order.
    """
    doc = load_manifest(manifest)
    entries = doc["files"]
    if names is not None:
        wanted = set(names)
        unknown = wanted - {e["name"] for e in entries}
        if unknown:
            raise FetchError(f"not in the manifest: {', '.join(sorted(unknown))}")
        entries = [e for e in entries if e["name"] in wanted]
    base = base_url.rstrip("/")
    _check_url(base + "/")
    out_dir = Path(dest)
    out_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for entry in entries:
        name, want = entry["name"], entry["sha256"]
        target = out_dir / name
        if target.is_file() and sha256_of(target) == want:
            paths.append(target)
            continue
        part = out_dir / (name + ".part")
        url = f"{base}/{urllib.parse.quote(name)}"
        got = _download(url, part, timeout)
        size = part.stat().st_size
        want_size = entry.get("size")
        if got != want or (want_size is not None and size != want_size):
            part.unlink(missing_ok=True)
            raise FetchError(
                f"{name}: checksum mismatch (expected sha256 {want}, got {got}); file discarded"
            )
        part.replace(target)
        paths.append(target)
    return paths
