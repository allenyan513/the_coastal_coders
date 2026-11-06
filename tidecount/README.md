# TideCount

A local web workbench for reviewing underwater fish video. AI analyzes a video in advance and a technician confirms, corrects and counts. Only decisions a person made reach the summary.

This is an early prototype. See the [PRD](https://github.com/allenyan513/RBC_HUBHACKS_2026/issues/13) and [technical design](https://github.com/allenyan513/RBC_HUBHACKS_2026/issues/14).

## Folders

| Folder | What's in it |
|---|---|
| `ml/` | Detection, tracking and species experiments, notebooks and the benchmark |
| `server/` | The FastAPI service that runs the models and stores results |
| `web/` | The React UI |
| [`demo/`](demo/README.md) | Slides, screenshots and charts for the pitch |

## Run it

You need [uv](https://docs.astral.sh/uv/) and [Node.js](https://nodejs.org/) with [pnpm](https://pnpm.io/).

**macOS or Linux:**

```bash
./start.sh
```

**Windows:** double-click `start.bat`.

Then open http://localhost:8000. The first run installs dependencies and downloads the detector, about 120 MB, and the species model, about 3.7 GB, the first time a video is analyzed.

## On a phone

Open `/start`, for example https://coastalaction.ligangyan.com/start. It says what TideCount is and has one tap into a sample video, a sample report or an upload.

On a computer, **Open on phone** in the sidebar shows a large QR code for that page, so a room can scan it from the screen. For slides and print, `pnpm qr` in `web/` writes `demo/qr/start.png` and `start.svg`. Pass another address to change where they lead: `pnpm qr https://example.com/start`.

A phone has to reach the site, so scan from the public address, not `localhost`.

## Using it

1. Import a video in **Fish Counter** and choose a model. Analysis runs in the background.
2. Open it when it's **Ready to review**.
3. Open **All tracks** to clear false tracks and name real ones in bulk, one thumbnail per track. This decides tracks, but it doesn't mark any footage as reviewed.
4. Work through the queue. Confirm, correct or reject each AI track. Tick tracks to merge pieces of one fish or decide several at once.
   - For a fish AI missed, press **A** and drag a box around it. AI follows the fish through the video for up to five seconds each way, so it gets a track, a thumbnail and species suggestions like AI's own. It counts straight away as "Fish, unidentified", and the report says how many fish were added this way.
   - When AI can't follow the fish, the box marks that one moment. Following is least reliable in a dense school, where the box can slip onto a neighbour.
5. Use **Freeze frame and count school** for dense schools.
6. Open **Summary** and export a CSV.

## Comparing models

Use **Run model…** in the video list to run another model on the same video. Each run keeps its own results and decisions. **Compare** then plays the runs side by side, with their tracks, boxes and speed.

All models are on by default. Megalodon and the NOAA model use Ultralytics checkpoints, which are full pickle files that can run code when loaded. To turn them off:

```bash
TIDECOUNT_ALLOW_YOLO=0 ./start.sh
```

The Ultralytics package is AGPL-3.0. Models run on Apple GPU or CUDA when available. Set `TIDECOUNT_DEVICE=cpu` to force the CPU.

## Snapshot counts

**Snapshot count**, in the Workspace and the Summary, is a fixed job: about 120 frames per video hour. You check one frame every 30 seconds, plus up to 5 peak frames, the moments with the highest AI count. It gives two standard measures that don't need fish identities, so a fish split into several tracks can't inflate them:

- **MeanCount** is the average count over the evenly spaced frames. Peak frames aren't evenly spaced, so they never feed it.
- **MaxN** is the largest count in any one frame, including saved school counts. Until every snapshot frame is done, the app calls it "Largest count in checked frames", because MaxN isn't reported from a partial review.

When you start from AI's dots, each frame opens with dots read from the saved analysis, so no model runs and it works on a CPU-only PC. The dots are every box the detector drew on that frame at `dot_threshold`, whether or not the fish was tracked. Tracks are stricter, because they feed the review queue, and in a busy frame most fish never get one. A video analysed before boxes were saved shows tracked fish only, until it's analysed again. Dots count only once you save the frame. A checked frame with no dots means zero fish. Could not see is left out and never counts as zero. Hiding AI dots takes them out of the count, so every dot in a saved total was on screen.

Each time you open the snapshot count you choose how to count:

- **Count on my own** hides AI's dots. It's slower, and those frames also measure the AI: the AI accuracy page shows how many of your fish it had boxed. Frames come in a fixed random order, so stopping early still covers the whole video.
- **Start from AI's dots** shows AI's dots for you to correct. It's faster, but a person who sees AI's dots first tends to keep them, so these frames can't measure the AI.

Once a frame has shown AI's dots it can't measure the AI, even if you count it again on your own. Peak frames are counted either way and never measure the AI, because AI chose them.

| Key | Action |
|---|---|
| N | Save, next open frame |
| U | Could not see, next open frame |
| B | Back one frame |
| Z | Undo the last dot change |
| D / G | AI dots / grid totals |
| Space | Play 2 seconds around the frame |

## Learning notebooks

`ml/01_brackish_classification.ipynb` walks through data splitting, transfer learning and evaluation on the public Brackish dataset, step by step.

`ml/02_classifier_experiments.ipynb` measures how far those scores can be trusted, with bootstrap intervals and several seeds. Run `01` first, because it builds the crops.

`ml/water.py` turns clear frames into simulated tea-coloured and murky ones, because no public footage of fish in tannin water exists. It is a stress test, not proof of how real tea water behaves. Its commands are at the top of the file, and results go to `data/simulated-water`.

`ml/03_detector_baseline.ipynb` scores all five detectors on a 10-minute underwater clip. You mark the fish by hand with one click each, and it reports recall, precision and how much footage a person would still watch.

Open it in VS Code and choose the **TideCount** kernel, or run:

```bash
cd tidecount/server && uv run jupyter lab ../ml
```

To use your own virtual environment instead:

```bash
pip install -r tidecount/ml/requirements.txt
```

## Benchmark

`ml/bench.py` scores detector setups on long videos nobody has labelled, as a stand-in for Coastal Action's footage. The plan behind it is in [#49](https://github.com/allenyan513/RBC_HUBHACKS_2026/issues/49).

`ml/bench_videos.csv` lists the videos. `dev` videos are for choosing models and thresholds. `locked` videos are scored once at the end, and nobody who tunes a model looks at them before that. `todo` videos need work before they can be used. The `dev` videos have been checked by eye. The `locked` ones were picked from titles and descriptions only, so they stay unseen.

From `tidecount/server`:

```bash
uv run python ../ml/bench.py list --split all
```

```bash
uv run python ../ml/bench.py fetch --split dev
```

```bash
uv run python ../ml/bench.py frames --split dev
```

Then mark the fish in the app. On the Videos page, add each `data/bench/<id>/clip.mp4` by its file path, and put the video's id in the site field so you can tell the clips apart. When analysis has finished, open the snapshot count, choose **Count on my own**, and put one dot on each fish. About 30 to 40 frames per video is enough for a first score. Then copy those counts into the benchmark and score:

```bash
uv run python ../ml/bench.py pull --split dev
```

```bash
uv run python ../ml/bench.py detect --split dev
```

```bash
uv run python ../ml/bench.py score --split dev
```

| Step | What it does |
|---|---|
| `fetch` | Downloads each video at up to 1080p and cuts the clip. The `dev` downloads total about 8 GB, and the three `locked` ones about 5.4 GB |
| `frames` | Saves one full-size frame every 30 seconds |
| `pull` | Copies the frames counted on your own in the app into each video's `labels.json`. The app's snapshot frames are at the same times, so the names match. A frame that already has an answer keeps it |
| `detect` | Runs five setups on those frames: today's app, CFD Small, CFD Medium, and Nano and Medium with tiles |
| `scan` | Optional and slow. Runs a setup over the whole clip at the app's frame rate, so the score sheet shows how much footage lands in the review queue |
| `score` | Writes `data/bench/scores-dev.md`. On `dev` it also freezes each setup's thresholds, and `--split locked` reuses them |
| `run` | All four steps. Use `--file PATH` for a video that isn't in the list |

The videos have the uploader's standard YouTube licence, so use them for private testing. Don't publish them or show them in the pitch without asking.

**360° videos:** the Nova Scotia river videos come from a 360° camera. The optional `height` and `flatten` columns in `ml/bench_videos.csv` download them at 2160p and flatten them to one ordinary view. `ns-river-fish-2` is set up this way. The other two are marked `todo`, because each needs a viewing direction chosen first.

**Not built yet:** there's no tracking, species or SAM 3 comparison in the benchmark.

**Queue rules and per-video students:** these use the boxes that `scan` saves. The flicker rule is now in the app as well, in `server/tidecount/tracking.py`, with its values under `[flicker]` in `settings.toml`. The still rule and the students aren't in the app. Results are in [#49](https://github.com/allenyan513/RBC_HUBHACKS_2026/issues/49).

```bash
uv run python ../ml/still.py
```

`ml/still.py` tests two rules that stop false alarms filling the review queue. `ml/adapt.py` teaches Nano one video from Medium's boxes. Its commands are at the top of the file.

Tests: `uv run pytest ../ml`.

## Settings

`settings.toml` holds every value an experiment may change: the default detector, frame rate, each detector's width and thresholds, the tracker, the flicker rule, the review queue and the species model. Change a value there, not in the code.

- **Applying a change:** restart the app. New values apply to new analysis runs only. Earlier runs keep their results.
- **Checking a change:** run `uv run python -m tidecount.settings` from `server`. A misspelt key, a value out of range or an unknown detector stops the app and names the problem. A missing file or field uses the defaults in `server/tidecount/settings.py`.
- **Knowing what a result used:** every run saves its full settings and a short hash. The hash appears in the run's notes, in the exported CSV and on benchmark score sheets.
- **Trying other values:** set `TIDECOUNT_SETTINGS=/path/to/other.toml`.

## Keyboard

| Key | Action |
|---|---|
| Space | Play or pause |
| ← → | Step one frame |
| C / X | Confirm / not a fish. On a fish you added, X removes it |
| 1, 2, 3 | Choose a species |
| U | Fish, unidentified |
| Z | Undo the last decision or added fish |
| A / Esc | Start / stop adding missed fish. Drag a box around each |
| G / B | Grid / AI boxes |
| N | Mark reviewed, next |

On **All tracks**, a decision applies to the selected tracks, or to the track under the cursor if none are selected.

| Key | Action |
|---|---|
| Arrows | Move the cursor |
| Shift + arrows | Extend the selection |
| Space | Select or unselect |
| Shift-click | Select a range |
| Cmd/Ctrl + A | Select all shown |
| Esc | Clear the selection |
| C / X | Confirm with each track's top suggestion / not a fish |
| 1 to 5 | Choose a species from the picker |
| U | Fish, unidentified |
| M | Merge the selected tracks into one fish |
| Z | Undo the last action, including a merge |
| Enter or O | Watch the track in the video |
| F | Undecided or all |
| S | Next sort order |

## How it works

| Stage | What happens |
|---|---|
| Playable copy | ffmpeg makes a 540p H.264 proxy. The original isn't changed |
| Fish | The chosen model runs at 2 fps, with ByteTrack |
| Species | BioCLIP 2.5 suggests three species from `server/tidecount/species.csv`, using the largest view of each fish, cut from the original video. Fish under 64 pixels on their shorter side get no suggestion |
| Queue | Footage with AI detections goes into review, plus a random audit of the rest. A box that comes and goes doesn't count: it needs a box nearby on 2 of the frames within 2 seconds of it, because false alarms flicker and fish stay in view |

Everything is stored in `data/`, which git ignores. Settings are in `server/tidecount/config.py`, and every threshold is a placeholder until we test on real footage.

## Server layout

Each feature has its own router, so people working on different features edit different files.

| File | What's in it |
|---|---|
| `server/tidecount/app.py` | Builds the app from the routers. Folders, the database and the analysis worker start when uvicorn starts it, not on import |
| `server/tidecount/routes/` | The HTTP endpoints, one module per feature: videos, tracks, review, schools, snapshots, summary, and `web.py` for the built UI |
| `server/tidecount/worker.py` | The analysis pipeline, run in its own process for each queued video |
| `server/tidecount/models.py` | Detector and species model adapters |
| `server/tidecount/snapshots.py`, `merge.py`, `summary.py` | Rules behind the endpoints, as plain functions on a database connection, so they can be tested without HTTP |
| `server/tidecount/db.py`, `config.py`, `video.py` | Storage, paths and models, and ffmpeg helpers |
| `settings.toml`, `server/tidecount/settings.py` | The values an experiment may change, and the code that reads and checks them |

For UI work you can run the API without analysing queued videos:

```bash
cd server && TIDECOUNT_WORKER=0 uv run uvicorn tidecount.app:app --port 8000
```

Then run `pnpm dev` in `web/` and open http://localhost:5183. It sends `/api` requests to port 8000.

Each test gets a fresh database from `server/tests/conftest.py`, so tests don't need to clean up. CI runs the server tests, the `ml` tests and the web build on every pull request that touches `tidecount/`.

## Deploy a public demo

You need a machine with [Docker](https://docs.docker.com/engine/install/) and about 30 GB free. The demo runs on the CPU and starts with an empty database. Run this:

```bash
git clone https://github.com/allenyan513/the_coastal_coders.git
cd the_coastal_coders/deploy
echo "SITE_ADDRESS=your.domain" > .env
docker compose up -d
```

Point the domain's A record at the machine first, and open ports 80 and 443. If you use Cloudflare, set the record to **DNS only**. Caddy then gets a certificate and serves HTTPS by itself, and uploads have no size limit. Leave out `.env` and the site is plain HTTP on port 80.

The first start builds the image and downloads the model weights, about 4.2 GB, so it takes a while. Later starts skip both. Then open the site and import a video in **Fish Counter**, as you would locally. Everything is saved in `deploy/data/`, separate from the `tidecount/data/` that `start.sh` uses.

Run these from `deploy/` too:

| Task | Command |
|---|---|
| Rebuild after `git pull` | `docker compose up -d --build` |
| Stop, keeping the data | `docker compose down` |
| See what the app is doing | `docker compose logs -f app` |

The site has no login, so anyone with the link can upload and every visitor shares one set of data. The Summary only counts decisions a person made, so review a video before you share the link.

## Known limits

- AI output is weak in murky water and on dense schools, so treat every box as a suggestion.
- School dots currently come from the detector, not a counting model.
- Species scores are not calibrated. They only rank the candidates.
- One fish is often split into several tracks, so "entries" can run high, and they're now a secondary estimate. Merge pieces in the track list. [Attempted fixes](https://github.com/allenyan513/RBC_HUBHACKS_2026/issues/14#track-fragments) were reverted.
- Long tracks that barely move, such as a bait bag, are flagged but not removed.
- A fish that isn't on the species list still gets confident-looking names from the list.
- The species model takes about 0.4 seconds per track on a laptop CPU. Set `TIDECOUNT_SPECIES_MODEL=hf-hub:imageomics/bioclip-2` for a model that takes about half the time.
- Video files and model weights must stay out of the public repo.
