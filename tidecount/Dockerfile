FROM node:22-slim AS web
RUN npm install -g pnpm@10
WORKDIR /web
COPY web/ ./
RUN pnpm install --frozen-lockfile && pnpm build

FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv

WORKDIR /app/tidecount/server
# Models stay out of the image: they're downloaded into ./data by fetch-models.sh.
ENV UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1 HF_HOME=/app/tidecount/data/huggingface PYTHONUNBUFFERED=1

# Dependencies come before the code, so a code change doesn't repeat them.
COPY server/pyproject.toml server/uv.lock server/.python-version ./
RUN uv sync --frozen --no-dev

COPY server/ ./
COPY settings.toml /app/tidecount/settings.toml
COPY --from=web /web/dist /app/tidecount/web/dist

EXPOSE 8000
CMD [".venv/bin/python", "-m", "uvicorn", "tidecount.app:app", "--host", "0.0.0.0", "--port", "8000"]
