#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
(cd web && pnpm install --frozen-lockfile && pnpm build)
cd server
uv sync
uv run python -m tidecount.setup
uv run uvicorn tidecount.app:app --port 8000
