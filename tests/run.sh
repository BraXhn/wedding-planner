#!/usr/bin/env bash
# Kör hela testsviten mot en riktig server med tom databas och en lokal test-SMTP.
# Användning: tests/run.sh   (från repots rot)
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${TEST_PORT:-8099}"; export TEST_PORT="$PORT"
WORK="$(mktemp -d)"; SERVER_PID=""; SMTP_PID=""
cleanup() { [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null || true
            [ -n "$SMTP_PID" ] && kill "$SMTP_PID" 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT

python tests/fake_smtp.py "$WORK/mail.txt" & SMTP_PID=$!

start_server() {
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null && wait "$SERVER_PID" 2>/dev/null || true
  rm -rf "$WORK/data"; mkdir -p "$WORK/data"; : > "$WORK/mail.txt"
  DATA_DIR="$WORK/data" ADMIN_USERNAME=testadmin \
  SMTP_HOST=127.0.0.1 SMTP_PORT=2525 SMTP_SECURITY=none SMTP_FROM=brollop@example.se SMTP_FROM_NAME="Anna & Erik" \
  SMTP_DELAY_SECONDS=0.1 API_CORS_ORIGINS=http://hemmahub.lan:3000 \
  python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --no-server-header \
    --proxy-headers --forwarded-allow-ips 127.0.0.1 > "$WORK/server.log" 2>&1 &
  SERVER_PID=$!
  for _ in $(seq 1 50); do curl -fs "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && return 0; sleep 0.2; done
  echo "Servern startade inte:"; cat "$WORK/server.log"; exit 1
}

status=0
echo "== Grundtester =="; start_server
python tests/test_basic.py "$WORK/server.log" || status=1
echo; echo "== Funktionstester =="; start_server
python tests/test_features.py "$WORK/server.log" "$WORK" || status=1
if grep -qE "ERROR|Traceback" "$WORK/server.log"; then echo "Fel i serverloggen:"; grep -E "ERROR|Traceback" -A10 "$WORK/server.log"; status=1; fi
exit $status
