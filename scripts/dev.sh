#!/usr/bin/env bash
# scripts/dev.sh — launch the PFE Marketing Agent dev stack (Linux/macOS/WSL/Git-Bash).
#
# Runs backend, frontend, and the Python scraper in parallel in one terminal,
# interleaving their logs. Ctrl+C kills them all.
#
# Flags:
#   --no-backend     skip backend
#   --no-frontend    skip frontend
#   --no-scraper     skip Python scraper

set -euo pipefail

NO_BACKEND=0
NO_FRONTEND=0
NO_SCRAPER=0
for arg in "$@"; do
  case "$arg" in
    --no-backend)  NO_BACKEND=1 ;;
    --no-frontend) NO_FRONTEND=1 ;;
    --no-scraper)  NO_SCRAPER=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Unknown flag: $arg" >&2; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
echo "▶ Repo root: $REPO_ROOT"

PIDS=()
cleanup() {
  echo ""
  echo "▶ Stopping all services…"
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
  echo "✔ Stopped."
}
trap cleanup INT TERM EXIT

# Colored prefix for interleaved logs
prefix() {
  local label="$1" color="$2"
  sed -u "s/^/$(printf '\033[%sm[%s]\033[0m ' "$color" "$label")/"
}

if [ "$NO_BACKEND" -eq 0 ]; then
  echo "▶ Starting backend…"
  ( cd "$REPO_ROOT/backend" && npm run dev 2>&1 | prefix "backend " "32" ) &
  PIDS+=($!)
fi

if [ "$NO_FRONTEND" -eq 0 ]; then
  echo "▶ Starting frontend…"
  ( cd "$REPO_ROOT/frontend" && npm run dev 2>&1 | prefix "frontend" "35" ) &
  PIDS+=($!)
fi

if [ "$NO_SCRAPER" -eq 0 ]; then
  if command -v uv >/dev/null 2>&1; then
    echo "▶ Starting scraper…"
    (
      cd "$REPO_ROOT/backend/scraper"
      uv sync --quiet
      uv run uvicorn scraper_service:app --reload --port 8000 2>&1 | prefix "scraper " "33"
    ) &
    PIDS+=($!)
  else
    echo "⚠ uv not on PATH — scraper skipped. Install: https://docs.astral.sh/uv/"
  fi
fi

echo ""
echo "✅ Services running (Ctrl+C to stop):"
echo "   • Backend  → http://localhost:5000"
echo "   • Frontend → http://localhost:5173"
echo "   • Scraper  → http://localhost:8000/health"
echo ""

wait
