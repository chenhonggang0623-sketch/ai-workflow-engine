#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-8080}"

echo "==> Stopping AI Workflow Engine..."

# 1. Kill processes on backend/frontend ports (children too)
for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  pids="$(lsof -ti :"$port" 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    echo "==> Stopping process(es) on port $port: $pids"
    # Kill children first so --reload watchers don't respawn, then the parent
    for pid in $pids; do
      pkill -P "$pid" 2>/dev/null || true
      kill "$pid" 2>/dev/null || true
    done
  else
    echo "     Nothing running on port $port."
  fi
done

# 2. Wait a moment and confirm ports are free
sleep 1
for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  if lsof -ti :"$port" &>/dev/null; then
    echo "ERROR: port $port still in use — killing remaining PIDs."
    lsof -ti :"$port" | xargs kill -9 2>/dev/null || true
  else
    echo "     Port $port is free."
  fi
done

echo "==> All services stopped."