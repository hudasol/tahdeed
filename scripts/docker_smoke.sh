#!/usr/bin/env bash
# Build the image and smoke-test it against a tiny gazetteer + model made from the test fixture.
#
#   scripts/docker_smoke.sh
#
# Needs: docker, curl, python3 with `pip install -e ".[train]"` (to train the tiny model).
# Env:   IMAGE (tahdeed:smoke)  SMOKE_PORT (18000)  SMOKE_PORT2 (18001)  SMOKE_TIMEOUT (120 s)
#        SMOKE_LOG_DIR (smoke-logs; container logs are always written here)  SMOKE_SKIP_BUILD=1
#        PYTHON (python3)
#
# What it proves (all against the real image, run read-only with all capabilities dropped):
#   1. strict-mode start from `-v DIR:/data:ro` and a passing HEALTHCHECK, /health ok + not degraded
#   2. /resolve returns coordinates for a fixture address, and for an Arabic query
#   3. a phone number and an e-mail in a query never appear in `docker logs` (also with
#      TAHDEED_LOG_RAW=1), while audit lines do appear (so the absence is meaningful)
#   4. the process is non-root (uid 10001), has no capabilities, and cannot write / or /data
#   5. with a low TAHDEED_RATE_LIMIT a burst gets HTTP 429 + Retry-After, and /health is exempt
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE=${IMAGE:-tahdeed:smoke}
PORT=${SMOKE_PORT:-18000}
PORT2=${SMOKE_PORT2:-18001}
TIMEOUT=${SMOKE_TIMEOUT:-120}
LOG_DIR=${SMOKE_LOG_DIR:-smoke-logs}
PYTHON=${PYTHON:-python3}
export PYTHONUTF8=1
C1="tahdeed-smoke-main-$$"
C2="tahdeed-smoke-limit-$$"
DATA=$(mktemp -d)
HDR_BODY=$(mktemp)

fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }
ok() { echo "ok   - $*"; }

cleanup() {
  local rc=$?
  mkdir -p "$LOG_DIR"
  for c in "$C1" "$C2"; do
    docker logs "$c" >"$LOG_DIR/$c.log" 2>&1 || true
    docker inspect "$c" >"$LOG_DIR/$c.inspect.json" 2>&1 || true
  done
  docker rm -f "$C1" "$C2" >/dev/null 2>&1 || true
  rm -rf "$DATA" "$HDR_BODY"
  if [ "$rc" -ne 0 ]; then echo "smoke test FAILED (logs in $LOG_DIR/)" >&2; fi
  exit "$rc"
}
trap cleanup EXIT

# json_check JSON PYTHON_EXPR MESSAGE: PYTHON_EXPR sees the parsed document as `j`.
json_check() {
  printf '%s' "$1" | "$PYTHON" -c 'import json, sys; j = json.load(sys.stdin); sys.exit(0 if eval(sys.argv[1]) else 1)' "$2" \
    || fail "$3 -- response: ${1:0:500}"
}

wait_health() { # wait_health PORT CONTAINER
  local deadline=$((SECONDS + TIMEOUT))
  until curl -fsS --max-time 3 "http://127.0.0.1:$1/health" >/dev/null 2>&1; do
    [ "$(docker inspect -f '{{.State.Running}}' "$2" 2>/dev/null)" = true ] \
      || { docker logs "$2" 2>&1 | tail -30 >&2 || true; fail "container $2 exited before becoming healthy"; }
    [ "$SECONDS" -lt "$deadline" ] || fail "container $2 not healthy after ${TIMEOUT}s"
    sleep 1
  done
}

post_resolve() { # post_resolve PORT ADDRESS -> body on stdout
  "$PYTHON" -c 'import json, sys; print(json.dumps({"address": sys.argv[1]}, ensure_ascii=False))' "$2" \
    | curl -sS --max-time 15 -X POST "http://127.0.0.1:$1/resolve" \
        -H 'Content-Type: application/json; charset=utf-8' --data-binary @-
}

run_container() { # run_container NAME PORT [docker run args...]
  local name=$1 port=$2; shift 2
  docker run -d --name "$name" \
    --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m \
    --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 1g \
    --health-interval 5s --health-start-period 5s \
    -v "$DATA":/data:ro -p "127.0.0.1:$port:8000" "$@" "$IMAGE" >/dev/null
}

PII_PHONE_A="+971 50 987 6543"
PII_PHONE_B="0509876543"
PII_MAIL="smoke.pii@example.com"
PII_QUERY="29 Shabib Bin Saeed Al Muhairi Street, Al Khalidiyah call $PII_PHONE_A or $PII_PHONE_B mail $PII_MAIL"
assert_no_pii() { # assert_no_pii TEXT WHERE
  for needle in "987 6543" "9876543" "$PII_MAIL" "smoke.pii"; do
    case "$1" in *"$needle"*) fail "PII '$needle' found in $2" ;; esac
  done
}

echo "== 1. smoke data from the committed fixture"
"$PYTHON" scripts/make_smoke_model.py "$DATA"
# the container user (uid 10001) is not the owner of this directory: make it world-readable
chmod 755 "$DATA"; chmod 644 "$DATA"/*

echo "== 2. build image"
if [ "${SMOKE_SKIP_BUILD:-0}" != 1 ]; then docker build -t "$IMAGE" .; fi

echo "== 3. main container (rate limit high enough not to interfere)"
run_container "$C1" "$PORT" -e TAHDEED_RATE_LIMIT=600
wait_health "$PORT" "$C1"

H=$(curl -sS --max-time 10 "http://127.0.0.1:$PORT/health")
json_check "$H" 'j["status"] == "ok" and j["degraded"] is False and j["degraded_reason"] is None' "/health not ok or degraded"
json_check "$H" 'j["gazetteer_stats"]["addresses"] > 1000 and len(j["model"]) > 0' "/health: gazetteer/model not loaded"
ok "/health ok, not degraded, strict-mode model loaded"

deadline=$((SECONDS + 60))
until [ "$(docker inspect -f '{{.State.Health.Status}}' "$C1")" = healthy ]; do
  [ "$SECONDS" -lt "$deadline" ] || fail "docker HEALTHCHECK never became healthy"
  sleep 2
done
ok "docker HEALTHCHECK reports healthy"

R=$(post_resolve "$PORT" "29 Shabib Bin Saeed Al Muhairi Street, Al Khalidiyah")
json_check "$R" 'j["best"] and 24.45 < j["best"]["lat"] < 24.50 and 54.32 < j["best"]["lon"] < 54.38' "/resolve: no coordinates near the fixture address"
json_check "$R" 'j["best"]["standard"]["ar"] != "" and j["calibrated"] is True' "/resolve: missing Arabic form or not calibrated"
ok "/resolve returns coordinates for a known address"

R=$(post_resolve "$PORT" "الخالدية أبوظبي")
json_check "$R" 'j["best"] and 24.45 < j["best"]["lat"] < 24.50 and 54.32 < j["best"]["lon"] < 54.38' "Arabic query did not resolve to Al Khalidiyah"
ok "Arabic query resolves"

code=$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/")
[ "$code" = 200 ] || fail "dashboard / returned HTTP $code"
ok "dashboard served"

R=$(post_resolve "$PORT" "$PII_QUERY")
json_check "$R" 'j["best"] is not None' "/resolve with PII in the query failed"
assert_no_pii "$R" "the /resolve response"
LOGS=$(docker logs "$C1" 2>&1)
case "$LOGS" in *q_sha256_16*) ;; *) fail "no audit line in docker logs (logging not wired up?)" ;; esac
case "$LOGS" in *Shabib*) fail "raw query text in logs although TAHDEED_LOG_RAW is unset" ;; esac
assert_no_pii "$LOGS" "docker logs"
ok "PII absent from response and logs; audit lines present; no raw text by default"

uid=$(docker exec "$C1" id -u)
[ "$uid" = 10001 ] || fail "container runs as uid $uid, expected 10001"
[ "$(docker inspect -f '{{.Config.User}}' "$C1")" != "" ] || fail "image has no USER"
caps=$(docker exec "$C1" sh -c 'grep CapEff /proc/1/status' | awk '{print $2}')
[ "$caps" = 0000000000000000 ] || fail "effective capabilities not empty: $caps"
if docker exec "$C1" sh -c 'touch /x' 2>/dev/null; then fail "root filesystem is writable"; fi
if docker exec "$C1" sh -c 'touch /data/x' 2>/dev/null; then fail "/data is writable"; fi
docker exec "$C1" sh -c 'touch /tmp/x' || fail "/tmp (tmpfs) is not writable"
ok "non-root uid 10001, no capabilities, read-only rootfs and /data"

echo "== 4. rate-limit container (TAHDEED_RATE_LIMIT=20 -> burst 5; TAHDEED_LOG_RAW=1)"
run_container "$C2" "$PORT2" -e TAHDEED_RATE_LIMIT=20 -e TAHDEED_LOG_RAW=1
wait_health "$PORT2" "$C2"
R=$(post_resolve "$PORT2" "$PII_QUERY")
json_check "$R" 'j["best"] is not None' "first request after start was refused or failed"
codes=""
for _ in $(seq 1 15); do
  codes="$codes $(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$PORT2/resolve" \
    -H 'Content-Type: application/json' -d '{"address":"Al Khalidiyah"}')"
done
case "$codes" in *429*) ;; *) fail "no HTTP 429 after a burst of 16 requests at limit 20/min; codes:$codes" ;; esac
hdrs=$(curl -sS --max-time 10 -D - -o "$HDR_BODY" -X POST "http://127.0.0.1:$PORT2/resolve" \
  -H 'Content-Type: application/json' -d '{"address":"Al Khalidiyah"}')
case "$hdrs" in HTTP/*" 429"*) ;; *) fail "expected 429 on the next request, got: ${hdrs%%$'\r'*}" ;; esac
printf '%s' "$hdrs" | grep -qi '^retry-after: [0-9]' || fail "429 without a Retry-After header"
json_check "$(cat "$HDR_BODY")" 'j["error"] == "rate limit exceeded"' "429 body is not the expected JSON"
rm -f "$HDR_BODY"
[ "$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT2/health")" = 200 ] \
  || fail "/health is rate limited"
ok "burst gets 429 + Retry-After (codes:$codes); /health exempt"

LOGS=$(docker logs "$C2" 2>&1)
case "$LOGS" in *Shabib*) ;; *) fail "TAHDEED_LOG_RAW=1 did not log the query text (expected the redacted text)" ;; esac
assert_no_pii "$LOGS" "docker logs with TAHDEED_LOG_RAW=1"
ok "with TAHDEED_LOG_RAW=1 the query is logged but phone/e-mail are still redacted"

echo "smoke test passed"
