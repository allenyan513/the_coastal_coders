# Tideflow

**From footage to findings, in one place.** Tideflow is a web workbench for counting fish in underwater video. AI watches a video first and finds the fish. A technician then confirms, corrects and counts, and only decisions a person made reach the report.

Built by **The Coastal Coders** for [RBC HubHacks 2026](https://rbchubhacks.com/) with [Coastal Action](https://www.coastalaction.org/), who count fish in the LaHave River estuary in Nova Scotia from fixed underwater cameras. Today that means watching hours of murky footage by hand. Tideflow turns it into a review queue.

- **Live demo:** https://tideflow.ligangyan.com (sign in as a demo Volunteer or Manager, no password; everyone shares one set of data, so review before you share a link)
- **Product details:** [tidecount/README.md](tidecount/README.md) covers every feature, the keyboard, the count method, the benchmark and the deploy setup
- **Code:** this repository. The product was renamed from TideCount on 2026-11-07, so the folder, Python package and environment variables keep the old `tidecount` name

## What it does

| Step | What happens |
|---|---|
| Surveys | A manager sees every site, its stations and how much footage is counted, and imports video under a station |
| Import a video | ffmpeg makes a playable copy. The original isn't changed |
| AI analysis | A fish detector runs on every frame at 2 fps and a tracker follows each fish, so one fish becomes one track with a thumbnail |
| Species suggestions | BioCLIP suggests three species for each track from a list of fish found in Atlantic Canada |
| Review | A person confirms, corrects or rejects each track, adds fish the AI missed, and counts dense schools frame by frame |
| Count frames | Coastal Action's analysis procedure, one frame every 60 seconds in a 15-minute window, with AI dots to start from |
| Validate | A second person blind-counts a random sample of the counted frames. Counts too far apart are counted again, and a manager approves the video |
| Report | MeanCount, MaxN and species totals from decisions a person made, exported as CSV |
| Data analysis | A station report with stations picked on a map, and fish counts next to LaHave water readings over time |
| Water Quality Index | A CCME score from 0 to 100 for each water sampling site and year, like Coastal Action's report cards |
| Species wiki | Photos, identification notes, conservation status and a live map of OBIS occurrence records and eDNA samples for every fish on the list |
| Media library | Reference photos people upload and attach to species. Uploads stay pending until a person reviews them |

There are two roles. A **Volunteer** gets **My tasks**: the videos to review and count. A **Manager** gets **Surveys**, imports video, approves validation, and sees the station report, the team and the model pages. The home page at `/` explains the project; the workspace is at `/workspace`.

## Run it on your computer

You need three tools:

| Tool | Why | Install |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | Runs the Python server and fetches Python 3.11 for it | `curl -LsSf https://astral.sh/uv/install.sh \| sh` or `brew install uv` |
| [Node.js](https://nodejs.org/) 22 | Builds the web UI | nodejs.org or `brew install node` |
| [pnpm](https://pnpm.io/) 10 | Installs the web UI's packages | `npm install -g pnpm` |

ffmpeg is bundled with the Python packages, so you don't install it. Everything runs on your CPU, or on an Apple or NVIDIA GPU when it finds one.

Then:

```bash
git clone https://github.com/allenyan513/the_coastal_coders.git
```

```bash
cd the_coastal_coders/tidecount
```

**macOS or Linux:**

```bash
./start.sh
```

**Windows:** double-click `tidecount\start.bat`.

Open http://localhost:8000. The script installs the Python and web dependencies, builds the UI, downloads the default detector (about 120 MB) and starts the server. The species model (about 3.7 GB) downloads the first time a video is analysed. Both go to `tidecount/data/`, which git ignores, so later starts are quick.

To try it, sign in as the Manager, open **Surveys**, choose **Import video** and pick a model. The demo site has sample footage if you have none. Analysis runs in the background, and the video shows as **Ready to review** when it's done.

If a GPU gives trouble, run `TIDECOUNT_DEVICE=cpu ./start.sh`. For editing the code, tests and the other settings, see [Server layout](tidecount/README.md#server-layout) and [Settings](tidecount/README.md#settings) in the product README.

## Run it with Docker

For a server anyone can reach. You need [Docker](https://docs.docker.com/engine/install/) and about 30 GB of disk.

```bash
git clone https://github.com/allenyan513/the_coastal_coders.git
```

```bash
cd the_coastal_coders/deploy
```

```bash
docker compose up -d
```

The first start builds the image and downloads every model (about 4.2 GB), so it takes a while. Then the site is on port 80. Put `SITE_ADDRESS=your.domain` in `deploy/.env` and Caddy fetches a certificate and serves HTTPS. Data lives in `deploy/data/`.

The demo server deploys `main` by itself within a minute of a change and rolls back when the site doesn't come up. See [Deploy a public demo](tidecount/README.md#deploy-a-public-demo) for the setup.

## Repository layout

| Folder | What's in it |
|---|---|
| [`tidecount/server/`](tidecount/server) | FastAPI service: video import, the analysis worker, review, counts, reports, the species wiki and water readings. SQLite storage |
| [`tidecount/web/`](tidecount/web) | React and TypeScript UI, built with Vite |
| [`tidecount/ml/`](tidecount/ml) | Model experiments, the detector benchmark, water-colour simulation and three learning notebooks |
| [`tidecount/demo/`](tidecount/demo) | The pitch deck, brand assets, the QR code and research notes |
| [`tidecount/settings.toml`](tidecount/settings.toml) | Every value an experiment may change: detector, frame rate, thresholds, tracker, protocol |
| [`deploy/`](deploy) | Dockerfile, Compose file, Caddy config and the auto-deploy timer |
| [`.github/workflows/`](.github/workflows) | CI |

## Models

Tideflow runs open models and trains none of its own. They download on first use and stay out of the repository.

| Model | Used for | Source |
|---|---|---|
| Community Fish Detector Nano, Small, Medium | Finding fish. Nano is the default | [WildHackers](https://github.com/WildHackers/community-fish-detector), RF-DETR |
| FathomNet Megalodon | All marine objects, for comparison | [FathomNet](https://huggingface.co/FathomNet/megalodon-2024-yolov11), YOLO11 |
| NOAA grayscale | Fish in low-colour water, for comparison | [akridge](https://huggingface.co/akridge/yolo11-fish-detector-grayscale), YOLO11 |
| BioCLIP 2.5 | Species suggestions | [Imageomics](https://huggingface.co/imageomics) |
| ByteTrack | Following each fish between frames | [trackers](https://github.com/roboflow/trackers) |

The Ultralytics package behind the two YOLO models is AGPL-3.0.

## Known limits

- AI is weak in murky water and on dense schools. Every box is a suggestion until a person decides.
- One fish is often split into several tracks. Merge them in **All tracks**.
- Species scores rank the candidates but aren't calibrated, and a fish not on the list still gets names from the list.
- Sign-in only picks a role. There are no passwords or server accounts, so the server trusts the role the browser sends, and everyone on the public demo shares one set of data.
- The Water Quality Index guidelines are our own starting point, matched to Coastal Action's published LaHave scores, not their official list.

The full list is in [Known limits](tidecount/README.md#known-limits).

## Working on the code

1. Branch from `main`, commit, push and open a pull request.
2. Someone else reviews it. Merge with **Squash and merge**, so `main` has one commit per change.
3. Merging into `main` publishes it. The server picks it up within a minute and rolls back if the site does not come up.
4. Check https://tideflow.ligangyan.com.

Docs, commits and pull requests are in English. Video files and model weights never go in git.

## Team

The Coastal Coders, RBC HubHacks 2026, Halifax.
