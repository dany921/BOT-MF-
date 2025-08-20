#!/usr/bin/env bash
set -e
if [ -d "venv" ]; then
  source venv/bin/activate
fi
export PYTHONUNBUFFERED=1
uvicorn main:app --reload --port ${PORT:-8000}
