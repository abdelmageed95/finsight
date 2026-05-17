#!/usr/bin/env bash
# ============================================================
#  FinSight — Dev mode (hot-reload)
#
#  Usage:
#    ./scripts/dev.sh          # Start everything
#    ./scripts/dev.sh stop     # Stop infrastructure
#    ./scripts/dev.sh infra    # Start only databases
#    ./scripts/dev.sh api      # Start only the backend
#    ./scripts/dev.sh web      # Start only the frontend
# ============================================================

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Colors
G='\033[0;32m'; Y='\033[0;33m'; C='\033[0;36m'; R='\033[0m'

# ---------- helpers ----------
start_infra() {
  # Stop Docker app/frontend if running — they hold ports 8000/3000
  echo -e "${Y}Stopping Docker app/frontend if running...${R}"
  docker compose -f docker/docker-compose.yml stop app frontend 2>/dev/null || true

  echo -e "${C}Starting databases (postgres, redis, chromadb)...${R}"
  docker compose -f docker/docker-compose.yml up -d postgres redis chromadb
  echo -e "${G}Databases ready.${R}"
}

start_api() {
  echo -e "${C}Starting FastAPI backend (hot-reload)...${R}"

  # Activate venv if it exists
  if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
  fi

  # Load .env
  set -a; source .env 2>/dev/null; set +a

  # Run migrations
  echo -e "${Y}Running alembic migrations...${R}"
  alembic upgrade head

  # Start uvicorn with --reload
  echo -e "${G}API running at http://localhost:8000 (auto-reload on file changes)${R}"
  uvicorn api.main:app --reload --host 0.0.0.0 --port 8000 &
  API_PID=$!
  echo $API_PID > /tmp/finsight-api.pid
}

start_web() {
  echo -e "${C}Starting Next.js frontend (hot-reload)...${R}"
  cd "$ROOT/frontend"
  echo -e "${G}Frontend running at http://localhost:3000 (auto-reload on file changes)${R}"
  NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev &
  WEB_PID=$!
  echo $WEB_PID > /tmp/finsight-web.pid
  cd "$ROOT"
}

stop_all() {
  echo -e "${Y}Stopping dev processes...${R}"
  [ -f /tmp/finsight-api.pid ] && kill "$(cat /tmp/finsight-api.pid)" 2>/dev/null && rm /tmp/finsight-api.pid && echo "  API stopped"
  [ -f /tmp/finsight-web.pid ] && kill "$(cat /tmp/finsight-web.pid)" 2>/dev/null && rm /tmp/finsight-web.pid && echo "  Frontend stopped"
  docker compose -f docker/docker-compose.yml stop postgres redis chromadb 2>/dev/null && echo "  Databases stopped"
  echo -e "${G}Done.${R}"
}

# ---------- main ----------
case "${1:-all}" in
  stop)
    stop_all
    ;;
  infra)
    start_infra
    ;;
  api)
    start_api
    wait
    ;;
  web)
    start_web
    wait
    ;;
  all)
    start_infra

    # Wait for postgres to be healthy
    echo -e "${Y}Waiting for postgres...${R}"
    until docker compose -f docker/docker-compose.yml exec -T postgres pg_isready -U finsight > /dev/null 2>&1; do
      sleep 1
    done

    start_api
    start_web

    echo ""
    echo -e "${G}============================================${R}"
    echo -e "${G}  Dev mode running (hot-reload enabled)${R}"
    echo -e "${G}  API:      http://localhost:8000${R}"
    echo -e "${G}  Frontend: http://localhost:3000${R}"
    echo -e "${G}  Swagger:  http://localhost:8000/docs${R}"
    echo -e "${G}============================================${R}"
    echo -e "${Y}  Press Ctrl+C to stop${R}"
    echo ""

    # Wait for both and handle Ctrl+C
    trap 'stop_all; exit 0' INT TERM
    wait
    ;;
  *)
    echo "Usage: $0 {all|stop|infra|api|web}"
    exit 1
    ;;
esac
