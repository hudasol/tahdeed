# Security policy

## Supported versions

Security fixes are made on the latest release and on `main`.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private vulnerability reporting for this repository (Security tab, "Report a vulnerability"). Include the version, how to reproduce the problem, and what you expect the impact to be.

You can expect an acknowledgement within seven days. A fix or a written assessment follows as soon as it can be prepared, and the report is credited in the changelog unless you prefer otherwise.

## Scope and design notes

The resolver runs offline. It uses no external services and no API keys, and it loads no pickle files: the model is a plain `.npz` array file with an embedded manifest, loaded with `allow_pickle=False` and checked against the gazetteer's SHA-256.

Data handling

- Addresses are personal data. The audit log records a hash of the normalised query, not the text. Raw text is logged only when `TAHDEED_LOG_RAW=1`, and contact details are redacted first even then.
- Phone numbers, e-mail addresses and Emirates ID numbers found in a query are removed before matching (`src/tahdeed/privacy.py`), and the response echoes the redacted query.
- The gazetteer contains public OpenStreetMap buildings and places, not residents.

Service hardening

- Rate limiting on `/resolve` and `/resolve/batch` (`TAHDEED_RATE_LIMIT`). It is per process and in memory, so it protects a single instance from a noisy client and is not a defence against distributed attacks. Trust `X-Forwarded-For` only behind a proxy you control (`TAHDEED_TRUST_PROXY`).
- Optional bearer token (`TAHDEED_API_TOKEN`), request body limit, security headers including a content security policy, no stack traces in error responses, and a time budget per query.
- The Docker image runs as a non root user and is designed for a read only root filesystem with no capabilities. The data directory is mounted read only.

Reports about any of these areas are welcome. Deployment guidance is in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Out of scope

Accuracy problems (a wrong address returned) are not security issues; report them with the bug template. The accuracy of OpenStreetMap data is outside this project.
