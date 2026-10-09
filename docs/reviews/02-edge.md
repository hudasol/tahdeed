# Review 2: Edge Group (reliability, security, deployability lens)

*Reviewer's stance: "This will be run by someone who did not write it, on a machine that cannot call
home, and audited by someone who assumes it is hostile. Show me it fails safely."*

## What is good

- No LLM, no API keys, no runtime network use in the resolver itself. Deterministic by design.
- Honest abstention is the right default for operational use.
- MIT licence, ODbL data handled separately with a NOTICE.

## Critique

**C1. The model artefact is a pickle.** `ranker.pkl` executes arbitrary code on load. In a
controlled environment, loading a file that can run code is disqualifying, and scikit-learn is a heavy
inference dependency for four small tree ensembles.

**C2. Nothing proves that the gazetteer, the model, and the code belong together.** There is no
checksum, no schema version, no build provenance. A model trained on feature set A silently scoring
feature set B is exactly what happened during development (a 57-vs-50 feature crash), and a stale
model would not crash if the *count* matched.

**C3. The "offline" claim is false for the dashboard.** It loads Leaflet and fonts from public CDNs and
tiles from a public tile server. On an air-gapped network it renders nothing.

**C4. Input is trusted.** The API truncates at 500 characters but nothing is tested against hostile or
random Unicode, huge digit strings, bidi control characters, or pathological repetition. A parser that
can raise or spin on arbitrary input is an outage.

**C5. There is no time budget.** The fuzzy matcher is bounded per query only by construction, not by a
clock. One adversarial query should not be able to monopolise a worker.

**C6. Operations are blind.** No structured logs, no request id, no latency histogram, no version
in responses. And if logging were added naively it would write users' home addresses to disk.

**C7. Failure modes are not graceful.** A missing model file silently falls back to the uncalibrated
heuristic; the response does not say so, so downstream systems would treat 0.8 from an
uncalibrated rule as a calibrated probability.

**C8. Packaging.** No container, no pinned dependency set, no coverage gate, no vulnerability audit,
CI on one Python version, and `batch` is single-process.

**C9. API hygiene.** No security headers, no body-size limit at the HTTP layer, no rate limiting hook,
permissive error text.

## Checklist (✅ done this round)

- [x] **E1** Pickle-free model: export the four heads to a `.npz` + JSON manifest; NumPy inference; scikit-learn only at training time. Equivalence test against sklearn.
- [x] **E2** Provenance: gazetteer schema version + content hash + build metadata; model manifest records feature list, training config, and the gazetteer hash; load refuses a mismatch; `tahdeed verify`.
- [x] **E3** Offline dashboard: vendor Leaflet and drop remote fonts; tile server configurable, graceful "no basemap" mode.
- [x] **E4** Property-based fuzzing (Hypothesis) of `normalize`, `parse`, `resolve` for no-raise and bounded time on arbitrary Unicode.
- [x] **E5** Per-query time budget (default 250 ms) that degrades gracefully and says so.
- [x] **E6** Privacy-preserving audit log: request id, SHA-256 of the query (raw text only with an explicit flag), status, tier, latency, versions.
- [x] **E7** Explicit `degraded` flag and `ranker` name in every response; `/health` reports versions and checksums.
- [x] **E8** Dockerfile (non-root, read-only filesystem friendly, healthcheck), pinned constraints file, CI matrix 3.11-3.13 with coverage gate and `pip-audit`.
- [x] **E9** Multi-process `batch` in the CLI; throughput benchmark command (`tahdeed bench`) with p50/p95/p99, load time, RSS.
- [x] **E10** HTTP hardening: security headers, body-size limit, optional token auth hook, no stack traces in errors.
- [ ] **E11** Reduce memory/load time of the gazetteer indices. ➡ Round 5 (polish), measured not fixed here.

## Result of this round

- Model artefact is now `data/models/ranker.npz` (arrays + embedded manifest; `allow_pickle=False`),
  verified by checksum, feature list and gazetteer hash. NumPy inference matches scikit-learn to
  1e-13. `scikit-learn` moved to the `train` extra; inference needs only NumPy and RapidFuzz.
- `tahdeed verify` checks provenance; `tahdeed bench` reports load time, memory, p50/p95/p99, q/s.
- Fuzz + property tests (Hypothesis), pathological-input tests, determinism test, tamper test.
- API: security headers incl. CSP, body limit, optional bearer token, request ids, no stack traces,
  `degraded`/`calibrated` flags, privacy-preserving audit log (hash only unless `TAHDEED_LOG_RAW=1`).
- Dashboard verified with every host blocked except the tile server (configurable `TAHDEED_TILE_URL`).
- CI: Python 3.11-3.13, ruff lint+format, coverage gate (71% now), `pip-audit` (no known vulnerabilities in the pinned set).
- **Not verified**: the Dockerfile. This sandbox has no Docker daemon, so it has never been built.

Regression found and recorded: load time rose from ~7 s to ~19 s (content hashing, ambiguity tables,
sibling-key indices). Carried to round 5 as E11.
