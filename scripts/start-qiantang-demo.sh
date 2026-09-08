#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="${QIANTANG_DEMO_BACKEND_PORT:-8011}"
FRONTEND_PORT="${QIANTANG_DEMO_FRONTEND_PORT:-5174}"
BACKEND_URL="http://$BACKEND_HOST:$BACKEND_PORT"
FRONTEND_URL="http://$BACKEND_HOST:$FRONTEND_PORT"
RUNTIME_DIR="$REPO_ROOT/backend/data/pilot_demo/qt_by_xiasha_pilot_001/runtime"
LOG_DIR="${TMPDIR:-/tmp}/trafficmind-qiantang-demo"
BACKEND_PID=""
FRONTEND_PID=""

if [[ ! -f "$REPO_ROOT/backend/app.py" || ! -f "$REPO_ROOT/frontend/package.json" ]]; then
  echo "Error: run this launcher from the TrafficMind repository checkout." >&2
  exit 1
fi

PYTHON_BIN="$REPO_ROOT/backend/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Error: backend virtual environment is missing: $PYTHON_BIN" >&2
  exit 1
fi
if [[ ! -x "$REPO_ROOT/frontend/node_modules/.bin/vite" ]]; then
  echo "Error: frontend dependencies are missing. Run npm install in frontend/." >&2
  exit 1
fi

port_is_available() {
  "$PYTHON_BIN" - "$BACKEND_HOST" "$1" <<'PY'
import socket
import sys

with socket.socket() as sock:
    try:
        sock.bind((sys.argv[1], int(sys.argv[2])))
    except OSError:
        raise SystemExit(1)
PY
}

for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  if ! port_is_available "$port"; then
    echo "Error: port $port is already in use; Qiantang Demo was not started." >&2
    exit 1
  fi
done

cleanup() {
  trap - EXIT INT TERM HUP
  [[ -n "$FRONTEND_PID" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
  [[ -n "$BACKEND_PID" ]] && kill "$BACKEND_PID" 2>/dev/null || true
  [[ -n "$FRONTEND_PID" ]] && wait "$FRONTEND_PID" 2>/dev/null || true
  [[ -n "$BACKEND_PID" ]] && wait "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 0' INT TERM HUP

cd "$REPO_ROOT"
mkdir -p "$LOG_DIR"

SOURCE_DIGEST="$($PYTHON_BIN - "$REPO_ROOT" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
paths = [
    root / "backend/tools/materialize_qiantang_demo.py",
    root / "backend/tools/qiantang_demo_runtime.py",
    root / "backend/data/pilot_demo/qt_by_xiasha_pilot_001/demo_manifest.json",
]
for relative in (
    "backend/data/pilot_regions/qt_by_xiasha_pilot_001",
    "backend/data/pilot_knowledge/qt_by_xiasha_pilot_001",
    "backend/data/pilot_history/qt_by_xiasha_pilot_001",
    "backend/data/pilot_history_public/qt_by_xiasha_pilot_001",
    "backend/data/pilot_holdout/qt_by_xiasha_pilot_001",
):
    paths.extend(path for path in (root / relative).rglob("*") if path.is_file())
digest = hashlib.sha256()
for path in sorted(paths):
    digest.update(str(path.relative_to(root)).encode())
    digest.update(path.read_bytes())
print(digest.hexdigest())
PY
)"

runtime_matches_snapshot() {
  "$PYTHON_BIN" - "$RUNTIME_DIR" <<'PY'
import json
import sqlite3
import sys
from pathlib import Path

from backend.tools.materialize_qiantang_demo import _database_snapshot

root = Path(sys.argv[1])
report = json.loads((root / "materialization_report.json").read_text(encoding="utf-8"))
if _database_snapshot(root / "trafficmind_demo.db") != report.get("businessSnapshot"):
    raise SystemExit(1)
with sqlite3.connect(root / "rag" / "rag_v2.db") as connection:
    document_count = connection.execute("SELECT COUNT(*) FROM rag_documents WHERE status='active'").fetchone()[0]
    chunk_count = connection.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
    active = connection.execute(
        "SELECT embedding_model, embedding_dimension FROM rag_index_versions "
        "WHERE status='active' ORDER BY committed_at DESC LIMIT 1"
    ).fetchone()
with sqlite3.connect(root / "vector" / "chroma.sqlite3") as connection:
    vector_count = connection.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
if (
    document_count != report.get("knowledgeDocumentCount")
    or chunk_count != vector_count
    or active != ("Qwen/Qwen3-Embedding-0.6B", 1024)
):
    raise SystemExit(1)
PY
}

STAMP="$RUNTIME_DIR/.source-digest"
if [[ "${QIANTANG_DEMO_RESET:-0}" == "1" || ! -f "$RUNTIME_DIR/trafficmind_demo.db" || ! -f "$RUNTIME_DIR/materialization_report.json" || ! -f "$STAMP" || "$(cat "$STAMP")" != "$SOURCE_DIGEST" ]] || ! runtime_matches_snapshot; then
  echo "Materializing isolated Qiantang Pilot snapshot..."
  "$PYTHON_BIN" -m backend.tools.materialize_qiantang_demo --runtime-dir "$RUNTIME_DIR" --reset
  printf '%s\n' "$SOURCE_DIGEST" > "$STAMP"
else
  echo "Using verified Qiantang Pilot snapshot: $RUNTIME_DIR"
fi

BACKEND_LOG="$LOG_DIR/backend-$BACKEND_PORT.log"
FRONTEND_LOG="$LOG_DIR/frontend-$FRONTEND_PORT.log"
"$PYTHON_BIN" -m backend.tools.run_qiantang_demo --runtime-dir "$RUNTIME_DIR" --host "$BACKEND_HOST" --port "$BACKEND_PORT" >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

for _ in {1..120}; do
  if curl -fsS "$BACKEND_URL/health" >/dev/null 2>&1; then break; fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "Error: demo backend exited. See $BACKEND_LOG" >&2
    exit 1
  fi
  sleep 0.25
done
if ! curl -fsS "$BACKEND_URL/health" >/dev/null 2>&1; then
  echo "Error: demo backend did not become ready. See $BACKEND_LOG" >&2
  exit 1
fi

"$PYTHON_BIN" - "$BACKEND_URL" <<'PY'
import json
import sys
from urllib.request import urlopen

with urlopen(f"{sys.argv[1]}/history?limit=500", timeout=15) as response:
    records = json.load(response)["records"]
legacy = ("人民路", "解放路", "中山路", "南京路", "演示大道", "string", "test")
legacy_count = sum(any(token.lower() in json.dumps(row, ensure_ascii=False).lower() for token in legacy) for row in records)
current_count = sum(row.get("sourceType") == "synthetic_validation_holdout" for row in records)
if legacy_count or current_count != 8:
    raise SystemExit(f"Demo API verification failed: current={current_count}, legacy={legacy_count}")
print(f"Demo API verified: current events={current_count}, legacy test events={legacy_count}")
PY

(
  cd "$REPO_ROOT/frontend"
  export VITE_RUNTIME_PROFILE="qiantang-demo"
  export VITE_PROXY_TARGET="$BACKEND_URL"
  exec ./node_modules/.bin/vite --host "$BACKEND_HOST" --port "$FRONTEND_PORT" --strictPort
) >"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

for _ in {1..120}; do
  if curl -fsS "$FRONTEND_URL" >/dev/null 2>&1; then break; fi
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    echo "Error: demo frontend exited. See $FRONTEND_LOG" >&2
    exit 1
  fi
  sleep 0.25
done
if ! curl -fsS "$FRONTEND_URL" >/dev/null 2>&1; then
  echo "Error: demo frontend did not become ready. See $FRONTEND_LOG" >&2
  exit 1
fi

cat <<EOF

TrafficMind Qiantang Pilot Demo
Frontend:   $FRONTEND_URL
Backend:    $BACKEND_URL
Traffic DB: $RUNTIME_DIR/trafficmind_demo.db
Knowledge:  $RUNTIME_DIR/rag
Vector:     $RUNTIME_DIR/vector
Map:        OpenFreeMap Positron (OSM fallback)
Profile:    钱塘 Pilot · 验证数据环境

Press Ctrl+C to stop this demo.
EOF

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done
echo "A demo process exited unexpectedly. Logs: $LOG_DIR" >&2
exit 1
