# Feasibility Spike (2026-11-05)

Throwaway scripts from the kickoff-day tests behind the [TideCount proposal](https://github.com/allenyan513/RBC_HUBHACKS_2026/issues/16). They're kept as a record of how the measured numbers were produced, not as code to build on.

Everything ran on a Mac with an Apple M5, using public data and simulated tannin. None of it tested Coastal Action's hardware or footage.

| Files | What they cover |
|---|---|
| `infer.py`, `infer_res.py`, `evaluate.py` | Community Fish Detector inference and scoring per dataset |
| `eval_all.txt` | Raw scoring output, including AP50, precision, recall and count errors |
| `cpu_bench.py`, `pipe.py`, `stages.py` | CPU timing of the detector, the full pipeline and the non-detector stages |
| `track.py`, `motion.py` | ByteTrack and background-subtraction checks |
| `dense.py`, `cells.py`, `small.py` | Crowded frames, partial grid counts and tiny fish |
| `herring_meta.py` | How frame sampling affects fast fish |
| `subset.py`, `seq.py`, `dense_meta.py`, `inspect_meta.py`, `scan_pickle.py` | Dataset selection and inspection helpers |
| `species/` | Draft Nova Scotia species list (`ns_species.csv`), its label data and the scripts that built it |

The datasets, model weights and virtual environment were about 5 GB in a temporary folder, so they aren't committed. The scripts use paths relative to that working folder and won't run from here as they stand.
