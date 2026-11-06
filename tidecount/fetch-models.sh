#!/usr/bin/env bash
# Builds the app, then downloads the open model weights from their public sources into ./data.
# Run once before `docker compose up -d`. It's safe to run again.
set -euo pipefail
cd "$(dirname "$0")"
docker compose run --rm --no-deps app .venv/bin/python -m tidecount.fetch_models
