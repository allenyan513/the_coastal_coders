# TideCount

A local web workbench for reviewing underwater fish video. AI analyzes a video in advance and a technician confirms, corrects and counts. Only decisions a person made reach the summary.

This is an early prototype. See the [PRD](https://github.com/allenyan513/RBC_HUBHACKS_2026/issues/13) and [technical design](https://github.com/allenyan513/RBC_HUBHACKS_2026/issues/14).

## Run it

You need [uv](https://docs.astral.sh/uv/) and [Node.js](https://nodejs.org/) with [pnpm](https://pnpm.io/).

**macOS or Linux:**

```bash
./start.sh
```

**Windows:** double-click `start.bat`.

Then open http://localhost:8000. The first run installs dependencies and downloads the detector, about 120 MB, and the species model, about 3.7 GB, the first time a video is analyzed.

## Using it

1. Import a video in **Fish Counter** and choose a model. Analysis runs in the background.
2. Open it when it's **Ready to review**.
3. Work through the queue. Confirm, correct or reject each AI track, and add fish AI missed. Tick tracks to merge pieces of one fish or decide several at once.
4. Use **Freeze frame and count school** for dense schools.
5. Open **Summary** and export a CSV.

## Comparing models

Use **Run model…** in the video list to run another model on the same video. Each run keeps its own results and decisions. **Compare** then plays the runs side by side, with their tracks, boxes and speed.

All models are on by default. Megalodon and the NOAA model use Ultralytics checkpoints, which are full pickle files that can run code when loaded. To turn them off:

```bash
TIDECOUNT_ALLOW_YOLO=0 ./start.sh
```

The Ultralytics package is AGPL-3.0. Models run on Apple GPU or CUDA when available. Set `TIDECOUNT_DEVICE=cpu` to force the CPU.

## Learning notebooks

`ml/01_brackish_classification.ipynb` walks through data splitting, transfer learning and evaluation on the public Brackish dataset, step by step.

`ml/02_classifier_experiments.ipynb` measures how far those scores can be trusted, with bootstrap intervals and several seeds. Run `01` first, because it builds the crops.

`ml/03_detector_baseline.ipynb` scores all five detectors on a 10-minute underwater clip. You mark the fish by hand with one click each, and it reports recall, precision and how much footage a person would still watch.

Open it in VS Code and choose the **TideCount** kernel, or run:

```bash
cd tidecount/server && uv run jupyter lab ../ml
```

To use your own virtual environment instead:

```bash
pip install -r tidecount/ml/requirements.txt
```

## Keyboard

| Key | Action |
|---|---|
| Space | Play or pause |
| ← → | Step one frame |
| C / X | Confirm / not a fish |
| 1, 2, 3 | Choose a species |
| U | Fish, unidentified |
| Z | Undo |
| A | Add a missed fish |
| G / B | Grid / AI boxes |
| N | Mark reviewed, next |

## How it works

| Stage | What happens |
|---|---|
| Playable copy | ffmpeg makes a 540p H.264 proxy. The original isn't changed |
| Fish | The chosen model runs at 2 fps, with ByteTrack |
| Species | BioCLIP 2.5 suggests three species from `server/tidecount/species.csv`, using the largest view of each fish, cut from the original video. Fish under 64 pixels on their shorter side get no suggestion |
| Queue | Footage with AI detections goes into review, plus a random audit of the rest |

Everything is stored in `data/`, which git ignores. Settings are in `server/tidecount/config.py`, and every threshold is a placeholder until we test on real footage.

## Known limits

- AI output is weak in murky water and on dense schools, so treat every box as a suggestion.
- School dots currently come from the detector, not a counting model.
- Species scores are not calibrated. They only rank the candidates.
- One fish is often split into several tracks, so "entries" can run high. Merge pieces in the track list. [Attempted fixes](https://github.com/allenyan513/RBC_HUBHACKS_2026/issues/14#track-fragments) were reverted.
- Long tracks that barely move, such as a bait bag, are flagged but not removed.
- A fish that isn't on the species list still gets confident-looking names from the list.
- The species model takes about 0.4 seconds per track on a laptop CPU. Set `TIDECOUNT_SPECIES_MODEL=hf-hub:imageomics/bioclip-2` for a model that takes about half the time.
- Video files and model weights must stay out of the public repo.
