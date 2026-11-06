# TideCount

Our project for RBC HubHacks 2026 (Nov 5–9, Halifax), built for Coastal Action.

## Background

Coastal Action monitors fish with underwater video in Nova Scotia's high-tide, turbid waters. A person watches the footage and counts fish by hand, which is slow and tiring, and low visibility, algae and sediment make it error-prone.

TideCount is a local web workbench for that review. AI analyzes a video in advance, and a technician confirms, corrects and counts. Only decisions a person made reach the summary.

## Getting started

You need [uv](https://docs.astral.sh/uv/) and [Node.js](https://nodejs.org/) with [pnpm](https://pnpm.io/).

Run the app:

```bash
cd tidecount && ./start.sh
```

On Windows, double-click `tidecount/start.bat`. Then open http://localhost:8000. The first run installs dependencies and downloads the detector, about 120 MB. The species model, about 3.7 GB, downloads the first time a video is analyzed.

## Development

Run the server and the UI in two terminals, so code changes reload on their own.

```bash
cd tidecount/server && uv sync && uv run python -m tidecount.setup && uv run uvicorn tidecount.app:app --port 8000 --reload
```

```bash
cd tidecount/web && pnpm install && pnpm dev
```

Then open http://localhost:5183. The UI sends `/api` requests to the server on port 8000.

Run the checks that CI runs:

```bash
cd tidecount/server && uv run pytest -q && uv run pytest -q ../ml
```

```bash
cd tidecount/web && pnpm build
```

See [`tidecount/README.md`](tidecount/README.md) for how to use the app, the models and the benchmark.
