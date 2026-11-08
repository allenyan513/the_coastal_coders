# Tideflow

From footage to findings, in one place. A local web workbench for reviewing underwater fish video. AI analyzes a video in advance and a technician confirms, corrects and counts. Only decisions a person made reach the summary.

This is an early prototype. The product was renamed from TideCount on 2026-11-07; the code package, folder and environment variables keep the old `tidecount` name. See the [PRD](https://github.com/allenyan513/RBC_HUBHACKS_2026/issues/13) and [technical design](https://github.com/allenyan513/RBC_HUBHACKS_2026/issues/14).

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

Open the home page, for example https://tideflow.ligangyan.com/. It says what Tideflow is, with one tap into a sample video and a way to join as a volunteer. The workspace people sign in to is at `/workspace`. Old `/start` links still land on the home page.

For slides and print, `pnpm qr` in `web/` writes `demo/qr/start.png` and `start.svg`, which open the home page. Pass another address to change where they lead: `pnpm qr https://example.com/`.

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

The app has three steps for a video: **Count frames**, **Find species**, which is optional, and **Report**.

**Count frames** follows Coastal Action's draft video analysis procedure. You choose a 15-minute analysis window, and the app suggests where it can start from how clear the water is. You check one frame every 60 seconds in the window, 15 in all, plus up to 5 peak frames, the moments with the highest AI count. At each frame you can watch 5 seconds either side at 0.25×, and record invertebrates, species, visibility and notes. **Export analysis sheet** gives one row per frame, with the results below. The window, the spacing and the context are in `[protocol]` in `settings.toml`, because the procedure is still a draft. It gives two standard measures that don't need fish identities, so a fish split into several tracks can't inflate them:

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

Then mark the fish in the app. On the Videos page, add each `data/bench/<id>/clip.mp4` by its file path, and put the video's id in the site field so you can tell the clips apart. When analysis has finished, open the snapshot count, choose **Count on my own**, and put one dot on each fish. The count now offers 15 frames per video, so a first score needs more videos. Then copy those counts into the benchmark and score:

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
| `pull` | Copies the frames counted on your own in the app into each video's `labels.json`. Only frames at the same times as `frames` match, and the app now takes its frames on Coastal Action's grid, so few will. Set `[protocol]` to `trim_start_s = 15` and `every_s = 30`, with a long `window_s`, to label for the benchmark. A frame that already has an answer keeps it |
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

Point the domain's A record at the machine first, and open ports 80 and 443. If you use Cloudflare, set the record to **DNS only**. Caddy then gets a certificate and serves HTTPS by itself, and uploads have no size limit. Leave out `.env` and the site is plain HTTP on port 80. To move to a new domain, set `SITE_ADDRESS` to it and put the old one in `REDIRECT_FROM`; Caddy then sends visitors from the old address on to the new one, with the same path.

The first start builds the image and downloads the model weights, about 4.2 GB, so it takes a while. Later starts skip both. Then open the site and import a video in **Fish Counter**, as you would locally. Everything is saved in `deploy/data/`, separate from the `tidecount/data/` that `start.sh` uses.

Run these from `deploy/` too:

| Task | Command |
|---|---|
| Rebuild after `git pull` | `docker compose up -d --build` |
| Stop, keeping the data | `docker compose down` |
| See what the app is doing | `docker compose logs -f app` |

The site has no login, so anyone with the link can upload and every visitor shares one set of data. The Summary only counts decisions a person made, so review a video before you share the link.

### Deploy automatically

The machine can deploy `main` by itself. Every merge into `main` is published: within a minute the machine pulls it, rebuilds and checks the site. The site stays up during the build and goes down for a few seconds when the containers change. If the deploy fails, the machine goes back to the previous commit and doesn't try that commit again. Data in `deploy/data/` is kept.

To turn this on, run these once on the machine. `tidecount-update.service` assumes the repo is at `/home/wsyanligang/the_coastal_coders`.

```bash
git switch main
chmod +x deploy/auto-update.sh
sudo cp deploy/tidecount-update.service deploy/tidecount-update.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tidecount-update.timer
```

To see what it's doing, run `journalctl -u tidecount-update -f`.

## Species wiki

Select a fish on the **Species wiki** page to open its entry in a drawer on the right, or a full-screen sheet on a phone. The address keeps the open fish, for example `/species?species=Gadus%20morhua`, so a link reopens it. The drawer has four tabs:

| Tab | What's in it |
|---|---|
| Overview | The photo gallery with credits beside a short description, at-a-glance facts (group, family, WoRMS habitat, status), how to recognise it and its conservation status; similar species below. Two columns on the full page, one in the drawer |
| Map | Where OBIS has occurrence records of the fish, plus opt-in eDNA water-sample evidence and net-survey non-detections, each by sampling site-date |
| Details & Sources | TideCount's own counts, the name check against WoRMS, the sources for the notes and the conservation status, photo credits and links to iNaturalist, OBIS, FishBase and GBIF |

Old links to `?tab=photos` and `?tab=identify` open Overview.

**Conservation status** comes from `server/tidecount/species_conservation.json`, written by hand from official sources (COSEWIC, the SARA registry, Nova Scotia's species-at-risk list) with the date it was checked. It starts with Atlantic Whitefish: Endangered under COSEWIC (confirmed December 2022), SARA Schedule 1 (2003) and Nova Scotia's Endangered Species Act (2002), in the three Petite Rivière lakes. An entry without a kind, a verification date and an https source is ignored. A species with no entry shows "no verified status", never a badge and never "not at risk". `kind: "invasive_ns"` is supported for fish verified as invasive in Nova Scotia; none has been added yet.

The drawer needs only a scientific name, so the review screen can later open the same one for a BioCLIP suggestion. None of this changes `species.csv`, which stays the list BioCLIP chooses from.

**The map** shows real OBIS occurrence records, not modelled ranges. Records are counted in OBIS's own grid cells, which get finer as you zoom, so the map never draws thousands of markers. Select a cell to list its records, with date, dataset, how the record was made and its licence. Shaded cells have records; unshaded water has no shared records, which is not evidence of absence. The numbers above the map count occurrence records, not individual fish. Records are not fish: acoustic tracking logs a tagged fish every time it passes a receiver, and for cod in Atlantic Canada one such cell holds about 970,000 of 2.2 million records. The drawer warns when tag detections make up a large share. The server fetches OBIS for the browser, caches each answer in `data/cache/obis/` for a week (within a size limit, below), and serves an older saved copy, marked as such, when OBIS can't be reached.

**The year range.** One slider with two handles (presets: All years, 2020s, 2010s, 2000s) picks single years, 1950 to now (say 2018–2022). The map opens on 2023–present, and the period chosen then stays for the session across fish and tabs; when it has no records, the map says older ones may still be there and offers All years. The legend's colour swatches change the grid's palette (kept in the browser; repainting asks OBIS for nothing). The left end is "Earlier" and the right end the current year, and a handle resting there means no limit, so All years includes records from before 1950 too. The map updates when you let go of a handle, not while dragging. The range goes to OBIS as `startdate`/`enddate`, so the grid and the record list are filtered by OBIS itself, through the same cache and budget as before. The record totals come from OBIS's records-per-year list, which is fetched once for all years, so a new range costs no request there. **eDNA follows the range** without new OBIS calls: it is computed once for all years and the sampling events are kept, and each range just counts the events inside it (a species with more than 30,000 events is not kept this way and says so). **Net and trawl non-detections, and the dataset list, do not follow the range**; they are labelled "(all years)" and the drawer says so when a range is active. The slider (`web/src/YearRangeSlider.tsx`, `yearRange.ts`) knows nothing about OBIS, so a GBIF map can reuse it.

**Filtering by method or dataset.** Under the year range, "Hide acoustic-tag detections" drops the telemetry datasets in one click, and "Filter by method or dataset" picks research surveys, acoustic telemetry, eDNA or "other or not stated", or one dataset. The map, the record lists and the totals follow, together with the year range; the eDNA and net-survey sections don't. OBIS has no field for how a record was made and can only include datasets, not exclude them, so the server lists every dataset holding the fish in the region (one cached request, opened only when the filter is), gives each a method from its own OBIS metadata, and sends OBIS the ids of the datasets to keep. The method is only what the metadata says: eDNA from the DNA extension or title, telemetry from the title or the Ocean Tracking Network as institute, research surveys from net, trawl or seine sampling with a title naming a survey, a research vessel or the gear (tagging databases are left out). Museum collections, FishBase, iNaturalist and compilations don't say how each record was made, so they stay under "other". A visitor names a method or one listed dataset, never ids of their own, and a filter keeping more than 150 datasets, or a region with more than 200, is refused rather than cut short. For mackerel in Atlantic Canada, hiding the 3 telemetry datasets takes the total from 88,955 records to 38,303; for winter flounder, 19 survey datasets hold 76,667 of its 85,463.

**Keeping the public site and OBIS safe.** The map and eDNA calls reach a free public service from a public website with no login, so they are limited. All of it lives in `server/tidecount/api_guard.py` and `api_cache.py`, which know nothing about fish, so a GBIF integration can reuse them (see the note at the bottom of `api_guard.py`). It assumes the Docker deployment's single process.

| Risk | Safeguard |
|---|---|
| Many different requests, each a new cache entry and OBIS call | Map views are rounded to the map's own steps, the year range to whole years from 1900 to 2100 (checked on the server; the browser asks only when a handle is let go, and each range is one cache entry), and records are listed only for real OBIS grid cells (all 85,618 cells in my test cache passed) |
| Disk filling | The OBIS cache keeps to 256 MB and 20,000 files (`TIDECOUNT_CACHE_MB`, `TIDECOUNT_CACHE_FILES`), evicts the least recently used first, keeps slow-to-rebuild eDNA answers longest, refuses an answer over 4 MB, and stops caching when less than 5 GB of disk is free (`TIDECOUNT_CACHE_MIN_FREE_GB`) |
| Too many requests to OBIS | One budget for the whole server: 4 requests in flight (2 kept for visitors, so a background job can't starve the maps), about 2 a second, 180 a minute and 2,000 an hour (background jobs may use three quarters of the volume). `TIDECOUNT_OBIS_PER_MINUTE` and the others change them |
| OBIS slow, down or rate-limiting | A visitor's request tries once. A background job retries timeouts, 429s and 5xx with backoff. A 429 pauses every OBIS request for its Retry-After, and five failures in a row pause them for 30 seconds or more. While paused, the older cached answer is served or the visitor is told to try again, so no request waits on a sick server |
| Expensive calculations | One eDNA or net-survey calculation runs at a time and four more may wait. A fifth is told to try again; a visitor may start 12 in ten minutes; identical requests share one calculation; each one stops after five minutes or 400 OBIS requests. Finished jobs are forgotten, since their answer is in the cache |
| One visitor, or a script | 300 map calls a minute each, then a 429 with Retry-After. Only 12 run at once, so the rest of the app, including video review, keeps its request threads. The address comes from Caddy's X-Forwarded-For only when Caddy is the direct peer, so it can't be spoofed |
| Two requests writing one cache file | Each write goes to its own temporary file and is renamed into place |

The cost is speed: a species that has never been opened takes about a minute for its eDNA non-detections, and several visitors opening new species at once queue up.

**eDNA water samples** have their own collapsed section under the map, fetched only when it is opened, because DNA found in filtered water is not a sighting or a catch and shouldn't be read like one. It reports *sampling events* (a site-date: latitude and longitude rounded to 4 decimals, about 10 m, plus the UTC date), never the DNA sequence rows OBIS stores. A **detection** is a site-date where a sample held the fish's DNA. A **non-detection** is a site-date from a dataset that publishes its zeros, where none was found, and where no dataset found it. OBIS repeats a zero for every sequence variant in every sample, including samples where the fish *was* found (for mackerel, 109,435 absence rows), so raw absence rows are never totalled. A sample published under both 12S and 16S counts once. The section shows both counts with dates and sites, a by-year table, the contributing datasets with their genetic marker, and, on request, the sampling sites on the map: solid teal dots where DNA was found at least once, dashed teal rings where it never was. Blue cells stay for occurrence records and orange rings for nets. Non-detections from general-purpose markers (COI, 18S) and zooplankton surveys are counted and withheld with the reason, because those markers miss many fish; their detections still count. The marker is read from the dataset title first, then its abstract, so a dataset whose metadata is vague may be classified wrongly.

**Net, trawl and seine surveys** that reported the fish as not detected are a separate collapsed section, also by site-date, with seabed-imagery and unclear-method datasets withheld with the reason. A trawl non-detection is not proof of absence either: gear catches some fish far better than others.

**How eDNA is fetched.** OBIS returns at most 10,000 rows a request, and mackerel has 109,435 non-detection rows. They are read one dataset at a time, two datasets at once, each paged the way OBIS documents (every page starts after the last id of the one before). That is gentle on a free public service and takes about a minute for mackerel. I also tried splitting OBIS's random ids into shards and reading them all at once, which took 20 seconds, but it leaned on how OBIS happens to order ids and sent many requests together, so it was dropped. The detections come back in about 5 seconds and are shown straight away; the non-detections are counted by a background job, the section polls it and shows progress, and the finished result is cached in `data/cache/obis/` for a month. An expired copy is served, marked, while a new one is built. To prepare named species ahead of time, run `python -m tidecount.occurrences atlantic-canada "Scomber scombrus"` from the `server` folder. There is deliberately no "all species" option. The cache keeps each site-date, and `occurrences.nearby_site_dates` returns the eDNA site-dates near a point and between two dates, with the caveats attached. Nothing calls it yet: it is where a "has this species also been detected by eDNA nearby?" check on a video would start. An eDNA sample reflects DNA in a volume of water over hours to days, a video reflects minutes at one camera, and a non-detection cannot contradict a fish seen on video, so the two should only be compared when place, dates and question genuinely overlap.

**Photos, notes and names** live in three files next to `species.csv`:

| File | What's in it | How it's made |
|---|---|---|
| `species_media.json` | Photos and their credits | `ml/species_media.py`, then a person picks from a contact sheet |
| `species_profiles.json` | Identification notes, look-alikes and sources | Written by hand from FishBase and field guides |
| `species_taxonomy.json` | Every listed name checked against WoRMS | `ml/species_media.py taxonomy` |

To add photos for a fish, from `server`:

```bash
uv run python ../ml/species_media.py candidates "Gadus morhua"
uv run python ../ml/species_media.py show "Gadus morhua"
uv run python ../ml/species_media.py add "Gadus morhua" 0:side 14:underwater:"Juvenile on a rocky reef"
uv run python ../ml/species_media.py check --links
```

`candidates` matches the name exactly on iNaturalist, GBIF and WoRMS, then collects openly licensed photos: research-grade iNaturalist observations of exactly that taxon, Atlantic Canada first, and Wikimedia Commons files in the species' category. It writes a numbered contact sheet to `data/species_media/<species>/sheet.jpg`. Look at every photo before adding it. Research-grade observations still show the wrong animal: some "haddock", "winter flounder" and "lumpfish" observations were photos of the gull or eagle that ate the fish. `check` rejects licences other than CC0, CC BY, CC BY-SA and public domain, missing credits, and look-alikes that aren't on the list. `--links` also fetches every image and source link, and asks iNaturalist whether each observation still exists, is still research grade and still names the same species, since identifications can change after a photo is picked.

## Sign-in and roles

Accounts live on the server, in `data/tidecount.db`. The server checks every request against the signed-in account. Nothing the browser says about its role counts.

| Who | Can |
|---|---|
| Anyone, signed in or not | Browse the Species wiki, its Media Library (verified photos only), OBIS maps and eDNA, and the water readings |
| Volunteer | View research recordings and results, upload videos, count and review fish, retry failed analysis. Pending photos are shown, marked as such |
| Manager | Everything, plus surveys and filing, other models, Reports, Accuracy, Model lab, the Media Library and the team |

**Signing up:** anyone can create an account at `/login`, with **Create an account**, or straight from `/login?register`. Enter a name and email and choose Volunteer or Manager.
- Anyone who signs up as a manager gets every manager permission. That's the team's choice for now.
- The server makes a random password, shows it once with a **Copy password** button, and signs the person in.
- Only the password's hash is stored. Change it any time in **Settings**.
- An email that already has an account can't sign up again, and nothing about the existing account changes.
- Sign-ups are limited to 20 an hour from one address (`TIDECOUNT_SIGNUPS_PER_HOUR`).

**Demo sign-in:** the sign-in page works as it always did. Pick Volunteer or Manager and press Sign in; no password is checked.
- It opens one shared demo account per role, `volunteer@tideflow.demo` or `manager@tideflow.demo`, made on first use.
- Each demo account has a random password nobody knows, so it can't be opened any other way, and nobody can sign up with a `@tideflow.demo` address.
- Roles and permissions are still checked on the server.
- Anyone who can reach the site can sign in as the demo manager. Set `TIDECOUNT_DEMO_SIGNIN=0` to turn the demo sign-in off, or switch a demo account off on the **Team** page.

**Command line:** `docker compose run --rm app .venv/bin/python -m tidecount.users create-manager you@example.org` still works. The same tool runs `reset-password EMAIL` and `list`.

**The team:** managers change roles and remove access from **Team**. **Copy sign-up link** gives the address to share. Invites by email and password reset links still work: Tideflow sends no email, so copy each link and send it yourself. A link works once, within 7 days. Removing someone's access signs them out at once.

**Sessions:** a session lasts 30 days without use and 90 days in all, and it survives restarts and redeploys. Team changes, permanent photo deletion and deleting survey items ask for the password again if it was last entered more than 10 minutes ago.

**Behind Caddy (HTTPS):** nothing to configure. The cookie is `__Host-tideflow_session`, marked Secure, HttpOnly and SameSite=Lax. Writes from other sites are refused.
- `TIDECOUNT_SECURE_COOKIES=1` or `0` overrides how HTTPS is detected.
- `TIDECOUNT_ALLOWED_ORIGINS` adds sites allowed to send writes, comma-separated.
- `TIDECOUNT_LOGIN_PER_10_MIN` sets the sign-in limit per address. The default is 10.

**Before upgrading a deployment,** copy `data/tidecount.db` somewhere safe. The upgrade only adds the `users`, `sessions` and `invites` tables.

## Known limits

- AI output is weak in murky water and on dense schools, so treat every box as a suggestion.
- School dots currently come from the detector, not a counting model.
- Species scores are not calibrated. They only rank the candidates.
- One fish is often split into several tracks, so "entries" can run high, and they're now a secondary estimate. Merge pieces in the track list. [Attempted fixes](https://github.com/allenyan513/RBC_HUBHACKS_2026/issues/14#track-fragments) were reverted.
- Long tracks that barely move, such as a bait bag, are flagged but not removed.
- A fish that isn't on the species list still gets confident-looking names from the list.
- The species model takes about 0.4 seconds per track on a laptop CPU. Set `TIDECOUNT_SPECIES_MODEL=hf-hub:imageomics/bioclip-2` for a model that takes about half the time.
- Video files and model weights must stay out of the public repo.
- Species wiki photos and notes have been checked by eye but not by a fish biologist, and each entry says so. Photos and map tiles load from iNaturalist, Wikimedia and OpenStreetMap, so the wiki doesn't work offline and those sites see the visit.
- OBIS is a marine database, so freshwater fish are thinly covered. *Gadus ogac* is on the AI list but WoRMS now treats it as *Gadus macrocephalus*, so its map shows every population of that species, Pacific included.
