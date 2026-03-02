#!/bin/sh
set -e

echo "[nova] Running migrations..."
python -m alembic upgrade head

echo "[nova] Starting server..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
