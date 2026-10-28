# Deployment

How to run tahdeed in a container, what every environment variable does, what the rate limiter
and the logs do (and do not do), and whether a free hosted demo is feasible.

> **Status of this document.** The rate limiter, the logging guarantees and the regional-gazetteer
> measurements below were run and tested. **Everything that involves Docker, Render or Vercel has
> not been run by the author**: the sandbox this was written in has no Docker daemon, and nothing
> was deployed. The Dockerfile and the smoke test are first exercised by the `docker` GitHub
> Actions workflow; treat them as unverified until that has gone green once.

## 1. Docker

The image contains the code and the dashboard only. The data are **not** baked in: the gazetteer
is large and ODbL-derived (section 6), so you mount it.

```bash
# 1. data (once): see the README. Produces data/gazetteer.sqlite and data/models/ranker.npz
tahdeed build ... && tahdeed train
mkdir -p serve && cp data/gazetteer.sqlite serve/ && cp data/models/ranker.npz serve/

# 2. image
docker build -t tahdeed .

# 3. run, hardened: read-only root filesystem, no capabilities, data mounted read-only
docker run -d --name tahdeed -p 127.0.0.1:8000:8000 \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --cap-drop ALL --security-opt no-new-privileges \
  -v "$PWD/serve:/data:ro" \
  -e TAHDEED_RATE_LIMIT=60 \
  tahdeed
curl -s localhost:8000/health
```

What the image does:

- Multi-stage build; the runtime stage has no compiler and no pip cache. Dependencies are installed
  from `constraints.txt` (a resolution failure fails the build instead of silently using "latest").
- Runs as uid/gid 10001 (`tahdeed`), no home directory, no shell login.
- `TAHDEED_STRICT=1`: the service **refuses to start** if the model is missing or was trained on a
  different gazetteer (it checks the gazetteer's sha256 against the model manifest). Without strict
  mode it would start in a degraded, uncalibrated state, and say so in `/health`.
- `ENTRYPOINT python -m uvicorn tahdeed.api:app_factory --factory --host 0.0.0.0 --port 8000`;
  `docker run ... tahdeed --workers 2` appends flags. Note each worker loads its own copy of the
  gazetteer (about 490 MB) and has its own rate-limit table.
- `HEALTHCHECK` calls `/health` (exempt from rate limiting). Loading the full data takes about 8 s.
- It needs only: read access to `/data`, a writable `/tmp` (SQLite temp files), and one TCP port.

### The CI smoke test

`scripts/docker_smoke.sh` (run by `.github/workflows/docker.yml` on every push and pull request)
builds the image and starts it against a tiny gazetteer and model that
`scripts/make_smoke_model.py` trains from the committed fixture `tests/fixtures/mini.sqlite`
(about 20 s). It then checks, with the container run read-only with all capabilities dropped:

1. strict-mode start from `-v DIR:/data:ro`; `/health` is `ok`, not degraded; Docker's own
   HEALTHCHECK turns `healthy`;
2. `/resolve` returns coordinates for a fixture address and for an Arabic query; the dashboard `/` is served;
3. a phone number and an e-mail address in a query appear in neither the response nor `docker logs`
   (also with `TAHDEED_LOG_RAW=1`), while audit lines *are* present, so the absence means something;
4. uid is 10001, effective capabilities are empty, `/` and `/data` are not writable;
5. a second container with `TAHDEED_RATE_LIMIT=20` answers a burst with HTTP 429 + `Retry-After`
   and keeps answering `/health`.

Run it locally with `pip install -e ".[train]" && scripts/docker_smoke.sh` (needs Docker and curl;
container logs go to `smoke-logs/`). The script's checking logic was exercised against a real
`uvicorn` process in the sandbox (with a stand-in for the `docker` command), including a negative
run where the PII redaction was disabled and the script failed as it should. The `docker build`,
`docker run` flags, `docker exec` checks and the HEALTHCHECK have **not** been run.

## 2. Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `TAHDEED_DB` | `data/gazetteer.sqlite` (image: `/data/gazetteer.sqlite`) | Path to the gazetteer SQLite file (opened read-only). |
| `TAHDEED_MODEL` | `data/models/ranker.npz` (image: `/data/ranker.npz`, or `/data/models/ranker.npz` when that is where the file is) | Path to the trained model. Its manifest must match the gazetteer's sha256. |
| `TAHDEED_STRICT` | `0` (image: `1`) | `1`: fail to start on a missing/mismatched model. `0`: fall back to the uncalibrated heuristic and report `degraded: true`. |
| `TAHDEED_RATE_LIMIT` | `60` | Requests per minute per client on `/resolve` and `/resolve/batch`. `0` (or negative) disables. Burst is `max(5, limit/4)`. See section 3. |
| `TAHDEED_TRUST_PROXY` | unset | `1`: take the client address from `X-Forwarded-For` for rate limiting. Set it **only** behind a proxy you control or trust; otherwise anyone can claim any address. |
| `TAHDEED_PROXY_HOPS` | `1` | With `TAHDEED_TRUST_PROXY=1`: how many trusted proxies append to `X-Forwarded-For`. The client is the Nth entry from the right. |
| `TAHDEED_API_TOKEN` | unset | If set, `/resolve*` requires `Authorization: Bearer <token>` (constant-time compare). `/health`, `/config` and the dashboard stay open. |
| `TAHDEED_LOG_RAW` | unset | `1`: also log the query text in the audit line. PII (phone numbers, e-mails, Emirates IDs) is redacted first even then. Off by default; leave it off. |
| `TAHDEED_AUDIT_KEY` | unset | Secret for an HMAC of the logged query hash. Without it the hash is a plain SHA-256 that can be tested against guessed addresses. |
| `TAHDEED_TILE_URL` | `https://tile.openstreetmap.org/{z}/{x}/{y}.png` | Tile URL template the dashboard map uses. For a public demo use a provider whose terms allow your traffic (the OSM community tile servers are not meant for production sites). |
| `TAHDEED_DATA_OFFER_URL` | unset | Where the public can obtain the database (ODbL). Returned by `/config` as `data_offer_url` for the dashboard to show. |
| `TAHDEED_WEB` | auto (the `web` directory inside the installed package) | Directory of the static dashboard. Set it only to serve a modified copy. |
| `OMP_NUM_THREADS` | `1` (image) | Keeps numpy single-threaded; the service is request-parallel instead. |

`TAHDEED_GAZETTEER_URL`, `TAHDEED_GAZETTEER_SHA256`, `TAHDEED_MODEL_URL`, `TAHDEED_MODEL_SHA256`
are read by `deploy/fetch_data.py` at build time only (section 5), not by the service.

## 3. Rate limiting

Until this change the API had **no** rate limiting. It now has an in-memory token bucket per client
(`src/tahdeed/ratelimit.py`, standard library only).

- **Scope**: `POST /resolve` and `POST /resolve/batch`. `/health`, `/config`, `/docs` and the
  static dashboard are exempt, so health checks and the page itself are never throttled.
- **Rate and burst**: `TAHDEED_RATE_LIMIT` tokens per minute refill continuously; the bucket holds
  `max(5, limit // 4)` (15 at the default of 60). A fresh client may therefore send 15 requests at
  once, then one per second.
- **Cost**: a request costs 1 token. A batch costs `ceil(rows / 50)` tokens (minimum 1), charged
  once the CSV is parsed; a request that costs more than the bucket holds is clamped to a full
  bucket, so the largest batch (5000 rows = 100 tokens) empties the bucket instead of being
  refused forever.
- **Refusal**: HTTP 429 with a `Retry-After: <seconds>` header and
  `{"error": "rate limit exceeded", "retry_after_seconds": N}`. The limiter runs before the token
  check, so it also slows token guessing. The 429 body and any log line contain nothing about the query.
- **Client identity**: the socket peer address. `X-Forwarded-For` is honoured only with
  `TAHDEED_TRUST_PROXY=1`, and then the entry `TAHDEED_PROXY_HOPS` from the right is used (each
  trusted proxy appends the address it saw, so entries further left are client-supplied and
  spoofable). A malformed header falls back to the socket peer.
  *Behind a proxy without `TAHDEED_TRUST_PROXY=1`, all users share one bucket*: that fails closed
  (a global cap) rather than open.
- **Memory**: at most 10,000 buckets; idle ones (full again) are evicted first, then the least
  recently used. Eviction can only forgive a client, never block one.
- **Limits of the design**: state is per process. With several uvicorn workers or replicas the
  effective limit is multiplied by their number, and a restart resets everyone. It protects one
  small instance from a noisy client; it is not a DDoS defence. Put a CDN or WAF in front of anything
  that matters.

## 4. Logging and privacy

Verified by reading `audit.py`, `api.py`, `resolve.py`, `privacy.py` and by tests
(`tests/test_api.py::test_pii_*`):

- The audit line (`tahdeed.audit`, JSON) carries a 16-hex-digit SHA-256 prefix of the **normalised**
  query, status, tier, p50, latency and versions. It never carries the query text unless
  `TAHDEED_LOG_RAW=1`.
- **Defect found and fixed.** The resolver redacted contact details before matching, but the API
  passed the *original* text to the audit logger. So with `TAHDEED_LOG_RAW=1` a phone number or
  e-mail went into the log in clear, and the logged hash was a hash of a string containing the
  number (a pseudonym that can be reversed by trying all UAE mobile numbers). `api.py` now runs
  `redact_pii` before `record(...)`. The new tests fail on the old behaviour (checked) and pass now.
  (`audit.py` itself still trusts its caller; making `record` redact too would be better defence in
  depth, but that file was outside this change.)
- **Defect found and fixed.** The `tahdeed` loggers had no handler under uvicorn, so audit lines
  were silently dropped in a container. `app_factory` now attaches a stdout handler (only if
  logging is not already configured).
- uvicorn's access log records method, path and client address, not bodies. The 500 handler logs a
  traceback and a request id, never the request body. Batch rows go through the same path as single
  queries, so they get the same treatment.
- The `/resolve` response echoes the query **after** redaction (`query` field).

## 5. Free hosted demo: feasibility

Question: can the service run on a free tier of Render (web service) or Vercel (Python function),
with the full gazetteer?

### Measured on the data in this repo

Measured here with `/proc/self/status` (VmRSS) on the real files, after importing FastAPI and
uvicorn and answering four queries (load time from `load_resolver`; the same machine as the
numbers in `docs/EVALUATION.md`):

| Gazetteer | File | Rows (addr / street / area / POI) | Steady RSS | Peak RSS | Load |
|---|---|---|---|---|---|
| **Full UAE** | 50.4 MB | 146,864 / 84,767 / 3,105 / 59,511 | **486 MB** | **512 MB** | 8.2 s |
| Abu Dhabi emirate (Abu Dhabi, Al Ain, Ruwais, Madinat Zayed, Liwa) | 37.3 MB | 127,705 / 46,660 / 1,798 / 13,925 | 359 MB | 369 MB | 4.1 s |
| Abu Dhabi city only | 19.8 MB | 64,777 / 24,730 / 996 / 11,509 | 226 MB | 232 MB | 2.5 s |
| Dubai + Hatta + Sharjah + Khor Fakkan + Kalba + Ajman | 11.7 MB | 17,671 / 35,054 / 883 / 40,396 | **174 MB** | 191 MB | 3.1 s |

Baseline of the interpreter with FastAPI and uvicorn imported and nothing loaded: 58 MB. The model
file (0.5 MB) is negligible. Where the memory goes in the 50 MB file: `addresses` 26.1 MB (52%),
`streets` 14.8 MB (29%), `pois` 6.6 MB (13%), the city index 2.5 MB, `areas` 0.3 MB. Rows by city
(all tables): Abu Dhabi 102,012; Al Ain 60,903; Dubai 58,618; Sharjah 26,756; Madinat Zayed 21,986;
Ajman 5,795; Dibba 4,562; the remaining eight small cities 1,000 to 2,700 each.
Memory grows by roughly 8 to 10 MB per MB of database file on top of that baseline; the region
figures above are measured, not extrapolated. Dubai has few structured addresses in OSM (13,503 of 146,864), which is
why the northern emirates are small in memory but large in POIs.

The regional gazetteers above were produced with `deploy/make_region.py` (section 5.4). All four
runs, including the full one, used the uncalibrated fallback (`strict` off) because the model in the
working data directory did not match the code checked out for this change (its feature list
differs) or, for the regions, the gazetteer. The model is 0.5 MB and the fallback allocates little,
so the effect on resident memory is far below the rounding above, but the full-data 486 MB should be
re-read with `tahdeed bench` on a matching model. The **accuracy** of a regional deployment is not
measured at all: a regional file needs its own `tahdeed train` run, and nothing in `EVALUATION.md`
describes it.

### Render, free web service (checked 2026-10-11)

Limits, from Render's documentation:

- Compute plans table, <https://render.com/docs/compute-plans>: **Free = 0.1 CPU, 512 MB RAM**
  (Starter = 0.5 CPU, 512 MB; Standard = 1 CPU, 2 GB).
- <https://render.com/docs/free>: "Render spins down a Free web service that goes 15 minutes without
  receiving any inbound traffic." "This process takes about one minute." "Like all Render services,
  Free web services have an ephemeral filesystem." Persistent disks: "Free web services cannot."
  "Render grants 750 Free instance hours to each workspace per calendar month". "Render might
  restart a Free web service at any time." Free web services cannot scale beyond a single
  instance, and "can't listen on reserved ports `18012`, `18013`, or `19099`". Outbound bandwidth
  and build pipeline minutes are counted against monthly included amounts (the numbers are only
  shown in the dashboard's Billing page).
- <https://render.com/docs/faq>: "Free web service instances spin down if they receive no incoming
  traffic for 15 consecutive minutes." / "These services take about a minute to spin back up".

Verdict: **the full gazetteer does not fit.** The service alone needs 486 MB steady and touches
512 MB at peak on this machine, against a 512 MB limit: no headroom at all for concurrent requests,
so an out-of-memory restart is the expected outcome. (The Render pages read do not say what happens
at the limit.) A **reduced region
fits**: Dubai+Sharjah+Ajman needs about 175 to 190 MB, Abu Dhabi city about 230 MB, the Abu Dhabi
emirate about 360 to 370 MB (workable, but only about 140 MB of headroom under concurrent requests).
Other consequences, none of them blockers for a demo:

- **CPU**: 0.1 CPU is a tenth of a core. Loading is CPU-bound, so expect roughly ten times the load
  times above (estimate, not measured): about 30 s for the northern emirates. Per-request latency
  (about 6 ms median here) would be tens of milliseconds. Every spin-up costs about a minute of
  platform start plus that load, so the first visitor after 15 idle minutes waits one to two minutes.
- **Hours**: 750 free hours a month is enough for one always-on service (about 720 h), but the
  service sleeps when idle anyway.
- **Data shipping**: the filesystem is ephemeral and git should not hold a 50 MB ODbL database
  (GitHub warns above 50 MB per file and blocks above 100 MB, and the history keeps every version).
  The blueprint downloads the data in the **build command** from an HTTPS URL (for example a GitHub
  Release asset, gzip-compressed, about a third of the size) and verifies its SHA-256; the files
  then sit next to the code for the lifetime of that deploy. Whether Render has an undocumented
  size cap on build output was not found in the pages read.
- **Rate limiting**: Render's proxy sits in front of the service. Leave `TAHDEED_TRUST_PROXY` unset
  until you know how many `X-Forwarded-For` entries Render appends; the pages read do not say.
  Unset, all users share one bucket (`TAHDEED_RATE_LIMIT=120` in the blueprint is therefore a global cap).

Ready file: `deploy/render.yaml` (section 5.3).

### Vercel, Hobby (free) Python function (checked 2026-10-11)

From <https://vercel.com/docs/functions/limitations> (page dated 2026-08-24):

- Memory: "Hobby: 2 GB / 1 vCPU" (default and maximum); Pro up to 4 GB / 2 vCPU.
- Size: "250 MB, or 500 MB for Python" uncompressed; Large functions (beta) up to 5 GB.
- Duration: Hobby "300s default and maximum" (with Fluid compute).
- Payload: "The maximum payload size for the request body or the response body of a Vercel Function is
  **4.5 MB**" (the API's own 2 MB upload cap is below this).
- "1,024 file descriptors shared across all concurrent executions".

From <https://vercel.com/docs/functions/runtimes/python> (dated 2026-08-12): Python functions run
ASGI apps (FastAPI) from an entrypoint exposing `app`; versions 3.12 (default), 3.13, 3.14; "By
default, Python Vercel Functions include all files from your project that are reachable at build
time"; relative paths resolve from the base of the project; `excludeFiles` in `vercel.json` trims the bundle.

From <https://vercel.com/docs/plans/hobby> (dated 2026-09-14): Hobby includes **4 CPU-hrs of Active
CPU, 360 GB-hrs of Provisioned Memory and 1,000,000 function invocations** a month; "the Hobby plan
restricts users to non-commercial, personal use only" (fair-use guidelines); exceeding a limit means
waiting 30 days. From <https://vercel.com/docs/fluid-compute>: functions are scaled to demand;
"Reduces the effects of cold starts through automatic bytecode optimization, and function
pre-warming on production deployments"; one instance can serve several concurrent requests.

Verdict: **it fits, on paper, and is the only free option here that holds the full UAE data**:
486 MB of a 2 GB function, about 50 MB of data plus roughly 100 to 150 MB of dependencies under
500 MB, well inside 300 s. It has not been deployed, and the points that decide whether it is
*pleasant* are the following.

- **Cold start**: every new instance imports the app and loads the gazetteer on its first request,
  about 8 s here on one fast vCPU, then 486 MB stay resident while the instance is warm. The
  documentation does not give an idle time before an instance is dropped, so assume a slow first
  request after quiet periods and after every scale-out.
- **Budget**: 4 Active-CPU hours is 14,400 CPU-seconds. If a cold start costs about 8 CPU-seconds, a
  thousand cold starts use 8,000 of them; per-request cost (about 6 ms) is negligible. At 2 GB
  provisioned, 360 GB-hrs is about 180 instance-hours of memory time.
- **Terms**: Hobby is for non-commercial personal use. A portfolio or open-source demo is personal;
  a demo for Kanban Studios F.Z.E. sales purposes is arguably commercial and would need Pro.
- **Rate limiting is weak here**: the limiter is per instance and instances come and go, so use
  Vercel's firewall for real limits. (Hobby WAF: up to 3 custom rules.) I believe Vercel sets
  `X-Forwarded-For` to the client address, which would make `TAHDEED_TRUST_PROXY=1` with one hop
  correct, but that was not confirmed from the pages read.
- **Data shipping**: the bundle contains files "reachable at build time"; `data/` is gitignored, so
  a Git-connected deployment will not have it unless the build step creates it. `deploy/vercel/vercel.json`
  runs `python ../fetch_data.py --dest data` as the build command, relying on files outside the
  Root Directory being available at build time (Vercel's default project setting, not verified here).
  If that does not work, copy `fetch_data.py` into `deploy/vercel/` and change the command to
  `python fetch_data.py --dest data`. Whether a custom `buildCommand` is honoured for the Python
  framework preset was not confirmed from the pages read; if it is not, deploy with
  `vercel build && vercel deploy --prebuilt` from a checkout that already has `data/`.
- **Dashboard**: the Python function serves the API only; the dashboard ships
  inside the `tahdeed` package, so the same function serves it.
- No writable disk except `/tmp`; the service needs nothing else.

Ready files: `deploy/vercel/` (section 5.5), untested.

### Recommendation

- Want the **whole UAE** for free: Vercel Hobby, personal use, accept slow cold starts.
- Want a **plain always-reachable URL** on Render free: only with a **reduced region**; the full
  data does not fit 512 MB. Dubai+Sharjah+Ajman is the cheapest (about 175 MB); Abu Dhabi emirate is
  the largest region that leaves useful headroom.
- Render Starter (0.5 CPU, 512 MB) has the same memory ceiling as Free, so it does not help with the
  full data either; Standard (1 CPU, 2 GB) does. Pricing was not retrieved (the pricing page could
  not be read in this session).

### 5.3 Render: steps

1. Build a regional gazetteer and its own model (a model trained on the full data will be rejected
   by `TAHDEED_STRICT=1`, because the gazetteer hash differs):

   ```bash
   python deploy/make_region.py data/gazetteer.sqlite region/gazetteer.sqlite --preset north
   tahdeed train --db region/gazetteer.sqlite --out region/ranker.npz     # needs ".[train]"
   gzip -k region/gazetteer.sqlite
   sha256sum region/gazetteer.sqlite region/ranker.npz                    # the decompressed gazetteer
   ```

   Presets: `north` (Dubai, Hatta, Sharjah, Khor Fakkan, Kalba, Ajman), `abu-dhabi-emirate`,
   `abu-dhabi-city`, or `--cities "dubai,sharjah"`. Check the result with
   `tahdeed eval --db region/gazetteer.sqlite --model region/ranker.npz` (its benchmarks are built
   for Abu Dhabi and Dubai queries; adapt or hand-check for other regions) before you describe its
   accuracy to anyone.
2. Upload `gazetteer.sqlite.gz` and `ranker.npz` to a stable HTTPS URL, e.g. assets of a GitHub
   Release. That URL doubles as the ODbL offer (section 6).
3. In Render: New > Blueprint > this repository, with the blueprint path `deploy/render.yaml`
   (or copy it to the repo root as `render.yaml`). Fill the `sync: false` variables:
   `TAHDEED_GAZETTEER_URL`, `TAHDEED_GAZETTEER_SHA256`, `TAHDEED_MODEL_URL`, `TAHDEED_MODEL_SHA256`,
   `TAHDEED_DATA_OFFER_URL`, and optionally `TAHDEED_TILE_URL` and `TAHDEED_API_TOKEN`.
4. Commands (as in the blueprint):
   - build: `pip install --no-cache-dir -c constraints.txt . && python deploy/fetch_data.py --dest data`
   - start: `python -m uvicorn tahdeed.api:app_factory --factory --host 0.0.0.0 --port $PORT --no-server-header`
   - health check path: `/health`
5. Data the owner must supply: **two files**, `gazetteer.sqlite` (regional, optionally `.gz`) and
   `ranker.npz` trained on exactly that file. Nothing else is needed; no database service.

The blueprint's field names and the region name `frankfurt` come from knowledge of Render's
Blueprint format, **not** from the specification page, which could not be read in this session.
Validate the file in the dashboard before use.

### 5.4 Regional gazetteers (`deploy/make_region.py`)

Keeps all rows whose `city_key` is in the region, in all four tables, ids preserved, `meta`
copied plus a `region` row. Reads the source read-only, refuses to overwrite. A place outside the
region cannot be found; it falls back to the nearest listed city or an abstention. Sizes and
memory are in the table above: the 29%-of-streets, 12%-of-addresses, 68%-of-POIs split of the
northern emirates is why their file is 23% of the full size and their memory 36%, while the
Abu Dhabi emirate (87% of addresses) is 74% of the file and 74% of the memory.

### 5.5 Vercel: steps

1. In the Vercel project set Root Directory to `deploy/vercel`; replace `<TAG>` in
   `requirements.txt` with a release tag of the (public) repository.
2. Project environment variables: `TAHDEED_DB=data/gazetteer.sqlite`,
   `TAHDEED_MODEL=data/ranker.npz`, `TAHDEED_STRICT=1`, `TAHDEED_RATE_LIMIT`, the four fetch variables
   and `TAHDEED_DATA_OFFER_URL`. For the full UAE, use the full `gazetteer.sqlite.gz` and the
   model trained on it.
3. Build command (set in `vercel.json`): `python ../fetch_data.py --dest data`. Entrypoint:
   `app.py` (`app = create_app()`), which loads the data on each instance's first request.

### 5.6 Abu Dhabi emirate demo build (built, measured and deployed on the Render free plan)

Reproducible with one command on Linux, from a full gazetteer built by `tahdeed build`:

```bash
pip install -c constraints.txt -e ".[train]"
WORKERS=2 bash deploy/build_demo_region.sh data/gazetteer.sqlite region
```

It runs `deploy/make_region.py --preset abu-dhabi-emirate` (Abu Dhabi, Al Ain, Al Ruwais, Madinat
Zayed, Liwa), trains a model on exactly that file (`tahdeed train`, defaults: 30,000 training
queries, seed 0), measures memory with `deploy/measure_rss.py`, then writes
`region/gazetteer.sqlite.gz` and `region/SHA256SUMS`. Measured on the 2026-10-15 OSM extract
(`docs/region_rss.json`, Python 3.13):

| | Value |
|---|---|
| Rows (addresses / street segments / areas / POIs) | 127,705 / 46,660 / 1,798 / 13,925 |
| Interpreter with FastAPI and uvicorn imported, nothing loaded | 45.3 MB |
| Resident after loading gazetteer and model in strict mode (VmRSS) | 360.9 MB |
| Resident after 400 requests through the app (VmRSS) | 363.8 MB |
| Peak resident, whole run (VmHWM) | 371.6 MB |
| Load time | 3.7 s here; expect more on Render's 0.1 CPU |

The measurement process also imports the HTTP test client, so the server alone should be slightly
smaller. Peak 371.6 MB leaves about 140 MB under Render's 512 MB, for one worker. Concurrent
requests add little (each request allocates far less than 1 MB), but nothing above was measured
under concurrent load.

**Not measured:** the accuracy of the regional model. Its benchmarks (`tahdeed eval`) were not
run; Dubai POI queries cannot be answered by an Abu Dhabi only file by design. Say so on the demo
page.

**Deploy steps (Render, free).** A demo of this build runs at https://tahdeed-demo.onrender.com (free plan, it sleeps after 15 minutes without traffic and the first request after that is slow). The steps below recreate it.

1. Create a GitHub Release (for example `demo-ad-2026-10`) and upload `region/gazetteer.sqlite.gz`
   and `region/ranker.npz` as assets. This release is also the ODbL offer of the database (section 6).
2. In Render: New > Blueprint, select this repository, blueprint path `deploy/render.yaml`.
3. Set the `sync: false` variables: `TAHDEED_GAZETTEER_URL` (the `.gz` asset URL),
   `TAHDEED_GAZETTEER_SHA256` (the line for `gazetteer.sqlite`, the *decompressed* file, in
   `region/SHA256SUMS`), `TAHDEED_MODEL_URL`, `TAHDEED_MODEL_SHA256` (the `ranker.npz` line),
   `TAHDEED_DATA_OFFER_URL` (the release page). Leave `TAHDEED_TRUST_PROXY` unset.
4. Apply. Check `/health` returns `"status": "ok"` and `"degraded": false`; resolve one Abu Dhabi
   address on the dashboard; read Render's metrics page for memory under 512 MB.
5. Do not publish the URL until the page shows the ODbL notice (section 6) and the limits above.

## 6. Serving ODbL data publicly: what you owe

The gazetteer is built from an OpenStreetMap extract (see `data/NOTICE.md`) and is a database
derived from it; OpenStreetMap data are available under the Open Database Licence (ODbL) 1.0,
<https://opendatacommons.org/licenses/odbl/1-0/>. **This section paraphrases the licence from the
author's reading of §4.3 to §4.6; the licence and OSMF pages could not be fetched in this session,
so check the wording yourself. It is not legal advice.**

1. **Attribution (credit the source).** Anyone who publicly uses a work produced from the database
   must show a notice, reasonably visible to users, that the content comes from OpenStreetMap and is
   available under the ODbL. OSM's customary form is "© OpenStreetMap contributors" linking to
   <https://www.openstreetmap.org/copyright>. Put it on the page that shows results, and in the API
   docs. The map tiles need their own "© OpenStreetMap contributors".
2. **Share-alike and an offer of the data.** If you publicly use a derived database (the
   gazetteer SQLite is one: filtered, restructured, with computed columns), it must remain under
   the ODbL, and you must offer the public a machine-readable copy of it, or of the alterations
   and the method of making them, at no more than the cost of reproduction, for as long as you
   offer the service (and at least three years). For tahdeed this means: publish the built
   `gazetteer.sqlite` (a GitHub Release asset is enough), and say which OSM extract it came from
   (the `meta` table records `source` and `source_sha256`) with the code that rebuilds it
   (`tahdeed build`, MIT). Do the same for each regional file you serve.
3. **Code stays MIT.** The licence applies to the data, not the repository code. Do not put the
   database under the MIT licence.
4. The trained model learns from synthetic queries generated from the data; its status under the
   ODbL is a question for a lawyer if it matters. Offering it alongside the database avoids the issue.

Text for the demo page (footer, and `/docs`):

> Address data: Contains information from OpenStreetMap, © OpenStreetMap contributors, available
> under the [Open Database Licence (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
> The database behind this service is a derived database under the same licence; you can download
> it, with the code that rebuilds it from the OpenStreetMap extract, at **<TAHDEED_DATA_OFFER_URL>**.
> Map: © OpenStreetMap contributors. This is an experimental research service, not an official
> address system; it does not issue or verify Makani, Onwani or National Address codes. Queries are
> not stored; only a hash of the normalised query is logged.

The service exposes the first sentence as `attribution`, and the offer link as `data_offer_url`,
in `GET /config`, so the dashboard can render them. (`src/tahdeed/web/index.html` was not changed here; its
map layer already shows "© OpenStreetMap contributors".)

## 7. Data releases and `data/MANIFEST.json`

The gazetteer and the model are published as assets of a GitHub Release, next to a manifest that
lists them. `tahdeed.fetch.fetch_data(dest, base_url, manifest)` downloads the files named in the
manifest, writes each to a temporary file, and keeps it only if its SHA-256 equals the manifest
value (and its size, when given). On a mismatch it raises `FetchError` and removes the file.
Remote URLs must use HTTPS. Files already present with a matching hash are not downloaded again.

`base_url` is the directory that holds the assets. The default, used by `tahdeed fetch`, is the
`data` branch of the repository, `https://raw.githubusercontent.com/hudasol/tahdeed/data`, which is an
orphan branch with no shared history (the gazetteer is 50 MB, below GitHub's 100 MB file limit). A
release works the same way, for example `https://github.com/<owner>/tahdeed/releases/download/v2.1.0`.
Each file is requested at `<base_url>/<name>`.

Manifest schema (version 1):

```json
{
  "schema_version": 1,
  "version": "2.0.0",
  "source": "OpenStreetMap extract of 2026-10-09, (c) OpenStreetMap contributors, ODbL 1.0",
  "files": [
    {"name": "gazetteer.sqlite", "sha256": "<64 lowercase hex digits>", "size": 123456789},
    {"name": "ranker.npz", "sha256": "<64 lowercase hex digits>", "size": 1234567}
  ]
}
```

| Field | Required | Meaning |
|---|---|---|
| `schema_version` | yes | Integer, currently `1`. A different value is refused. |
| `version` | no | Release the files belong to. Informational. |
| `source` | no | Origin and licence statement for the data. Informational. |
| `files[].name` | yes | A plain file name with no directory part. Names that contain a path separator or start with a dot are refused. |
| `files[].sha256` | yes | SHA-256 of the file as published, 64 lowercase hex digits. |
| `files[].size` | no | Size in bytes, checked in addition to the hash. |

The model manifest embedded in `ranker.npz` records the SHA-256 of the gazetteer it was trained on, so
a matching pair also passes `tahdeed verify`. To produce the manifest after a build, hash the two
files with `sha256sum` and write the values into the JSON above.

`deploy/fetch_data.py` is the older, environment variable driven variant used by hosted builds. It
reads URLs and hashes from `TAHDEED_*` variables instead of a manifest.
