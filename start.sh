#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

# Ensure CLI tools from /usr/local/bin (e.g. Codex) and Homebrew are on PATH
# for backend subprocesses (uvicorn inherits this env).
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-8080}"

cleanup() {
  echo ""
  echo "==> Shutting down..."
  [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null
  [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null
  wait
  echo "     Done."
}
trap cleanup SIGINT SIGTERM

echo "==> Starting AI Workflow Engine..."

# 1. Docker infrastructure
if ! docker info &>/dev/null; then
  echo "ERROR: Docker not running. Start Docker first."
  exit 1
fi

echo "==> Starting PostgreSQL, Redis, Qdrant..."
docker compose up -d
echo ""

# 2. Wait for PG
echo "==> Waiting for PostgreSQL..."
for i in $(seq 1 30); do
  if docker compose exec -T postgres pg_isready -U postgres &>/dev/null; then
    echo "     PostgreSQL ready."
    break
  fi
  sleep 1
done

# 3. Backend
echo "==> Installing Python dependencies..."
cd "$ROOT_DIR/backend"
pip3 install -e ".[dev]" --quiet 2>&1 | tail -1

echo "==> Running DB migrations..."
alembic upgrade head 2>/dev/null || echo "     (first run — tables created on startup)"

echo ""
echo "==> Starting backend (uvicorn) on port $BACKEND_PORT..."
# --reload-exclude: agent 运行时会在 generated_projects 写 .py 文件（如 Flutter 生成的
# flutter_lldb_helper.py），若不排除会把正在执行的 worker 触发重启，导致进行中的节点任务被杀死。
# 注意：必须传「绝对路径目录」。watchfiles 回调拿到的是绝对路径，而 Path.match 的 `*` 不跨
# 目录分隔符，`app/generated_projects/*` 只匹配一层、嵌套子目录下的 .py 会漏网触发 reload。
GENERATED_PROJECTS_DIR="$ROOT_DIR/backend/app/generated_projects"
uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload --reload-exclude "$GENERATED_PROJECTS_DIR" &
BACKEND_PID=$!

# 4. Frontend
echo "==> Installing Node dependencies..."
cd "$ROOT_DIR/frontend"
npm install --silent 2>&1 | tail -1

echo ""
echo "==> Starting frontend (Next.js) on port $FRONTEND_PORT..."
npm run dev -- -p "$FRONTEND_PORT" &
FRONTEND_PID=$!

# 5. Wait for both to be ready
echo ""
echo "==> Waiting for backend..."
for i in $(seq 1 30); do
  if curl -sf "http://localhost:$BACKEND_PORT/health" >/dev/null 2>&1; then
    echo "     Backend ready at http://localhost:$BACKEND_PORT"
    break
  fi
  sleep 1
done

echo ""
echo "==> AI Workflow Engine is running!"
echo "     Backend:  http://localhost:$BACKEND_PORT"
echo "     API docs: http://localhost:$BACKEND_PORT/docs"
echo "     Frontend: http://localhost:$FRONTEND_PORT"
echo ""
echo "     Press Ctrl+C to stop all services."
echo ""

wait
