#!/usr/bin/env bash
# Local Mac demo: venv + deps + .env, then API (default port 8686 — see core.config Settings.api_port).
# Redis is external — set REDIS_URL in .env (see .env.example).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

usage() {
  echo "Usage: ./start.sh [--reset]"
  echo "  --reset   remove .venv and recreate (full reinstall)"
  exit 0
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
fi

if [[ "${1:-}" == "--reset" ]]; then
  rm -rf .venv
  echo "[start] removed .venv (clean slate)"
  shift || true
fi

if [[ -n "${1:-}" ]]; then
  echo "Unknown option: $1"
  usage
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "[start] error: python3 not found (install Python 3.11+)"
  exit 1
fi

if [[ ! -d .venv ]]; then
  echo "[start] creating .venv …"
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# pip needs a writable temp dir; macOS sometimes has TMPDIR/TMP pointing at missing paths.
mkdir -p "${ROOT}/.tmp"
export TMPDIR="${ROOT}/.tmp"
export TMP="${ROOT}/.tmp"
export TEMP="${ROOT}/.tmp"

echo "[start] upgrading pip & installing package …"
python -m pip install -q -U pip
python -m pip install -q -e ".[dev]"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[start] created .env from .env.example — set REDIS_URL to your Redis 8.4+ endpoint."
else
  echo "[start] using existing .env"
fi

if [[ -n "${DEMO_HOST:-}" ]]; then
  HOST="$DEMO_HOST"
else
  HOST="$(python -c "from core.config import get_settings; print(get_settings().api_host)")"
fi
if [[ -n "${DEMO_PORT:-}" ]]; then
  PORT="$DEMO_PORT"
else
  PORT="$(python -c "from core.config import get_settings; print(get_settings().api_port)")"
fi

# True if nothing is accepting TCP on 127.0.0.1 at this port (demo bind check).
_port_is_free() {
  python -c "import socket,sys; p=int(sys.argv[1]); s=socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(0.2); busy=(s.connect_ex(('127.0.0.1', p))==0); s.close(); raise SystemExit(0 if not busy else 1)" "$1"
}

_pick_listening_port() {
  local orig="$1" cand attempt
  orig="${orig//[^0-9]/}"
  [[ -z "$orig" ]] && orig=8686
  for attempt in $(seq 0 31); do
    cand=$((orig + attempt))
    if _port_is_free "$cand"; then
      PORT="$cand"
      if [[ "$attempt" -gt 0 ]]; then
        echo "[start] port ${orig} is in use — using ${PORT} instead (set API_PORT or DEMO_PORT in .env to pin)."
      fi
      return 0
    fi
  done
  echo "[start] error: no free TCP port from ${orig} to $((orig + 31)) (everything looks busy)."
  if command -v lsof >/dev/null 2>&1; then
    echo "[start] processes on ${orig}:"
    lsof -nP -iTCP:"${orig}" -sTCP:LISTEN 2>/dev/null || true
  fi
  echo "[start] stop the other server (e.g. old uvicorn) or set DEMO_PORT=<free> ./start.sh"
  return 1
}

if [[ "${START_SH_STRICT_PORT:-}" == "1" ]]; then
  if ! _port_is_free "$PORT"; then
    echo "[start] error: port ${PORT} is already in use (bind will fail with Errno 48)."
    if command -v lsof >/dev/null 2>&1; then
      lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true
    fi
    echo "[start] unset START_SH_STRICT_PORT to auto-pick the next free port, or free this port."
    exit 1
  fi
else
  _pick_listening_port "$PORT" || exit 1
fi

echo "[start] open http://127.0.0.1:${PORT} — index + synonyms load on boot; seed catalog from Admin if empty."
echo "[start] Ctrl+C to stop"
exec uvicorn api.main:app --reload --host "$HOST" --port "$PORT"
