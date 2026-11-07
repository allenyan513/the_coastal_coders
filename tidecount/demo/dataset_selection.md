# Demo dataset selection

Research completed 2026-11-07 for the Tideflow dataset showcase. This step changes no product code and runs no model.

## Recommendation

Use the **Luderick Seagrass / Griffith Seagrass Fish dataset** for the public dataset demo, with the app's existing **`cfd-nano`** detector.

Build one reproducible **2:00 benchmark clip** from the **Jack Evans A** split:

1. Group frames by their original source-video prefix (the part before `_5fps_`).
2. Order frames by the numeric frame suffix.
3. Take the longest sequence; if it is under two minutes, append the next sequence from the same site/split with a visible hard cut.
4. Stop at exactly 600 frames (120 seconds at 5 fps).
5. Carry the source COCO boxes forward with the same frame offset.

The archive contains 76 trimmed sequences of 3–70 seconds, so a short compilation is necessary to meet the requested 2–10 minute demo length. The cuts must be disclosed as a dataset compilation, not presented as one continuous deployment. Before freezing the clip, inspect the selected sequences for missing frames, incomplete boxes and a useful mix of fish and empty/background frames.

Why this is the best fit:

- Real fixed-camera coastal footage in unconstrained seagrass habitat.
- 1920×1080 frames at 5 fps with per-frame COCO boxes and segmentation polygons.
- CC BY 4.0, with clear attribution requirements.
- Moderate, visually complex coastal water rather than aquarium imagery.
- It is listed under **datasets added to CFDv2**, not among the 17 source datasets described for the February 2026 Nano model. This avoids known training leakage for Tideflow's `cfd-nano` checkpoint.
- The existing Tideflow pipeline can analyse the encoded clip normally, and the published boxes remain separate benchmark ground truth.

Required credit:

> Ditria, E. M., Connolly, R. M., Jinks, E. L., & Lopez-Marcano, S. (2021). Annotated video footage for automated identification and counting of fish in unconstrained marine environments. PANGAEA. https://doi.org/10.1594/PANGAEA.926930 — CC BY 4.0.

## Candidate comparison

| Dataset | Licence and required credit | Annotation format | Clip / rate / resolution | In Tideflow CFD Nano training? | Turbidity by eye | Decision |
|---|---|---|---|---|---|---|
| **Luderick Seagrass (recommended)** | CC BY 4.0; credit Ditria et al. (2021) and DOI 10.1594/PANGAEA.926930 | COCO JSON and CSV; boxes and instance polygons on extracted frames | 76 source sequences, 3–70 s; extracted at 5 fps; 1920×1080. Compile 600 frames into a disclosed 2:00 reel | **No known leakage for the February 2026 Nano checkpoint.** It appears under “added to CFDv2,” not the original 17-source list | Moderate and variable; seagrass clutter and visible coastal haze | Best balance of rights, labels, realism and Nano independence |
| **Brackish** | CC BY-SA 4.0; credit Pedersen et al. (2019) | AAU, YOLO and COCO boxes; fish plus five non-fish classes | 89 short H.264 videos; up to 30 fps and 1920×1080; exact individual lengths are not published on the project page | **Yes** | Strongest turbidity match; visibility ranges from clear to notably murky | Excellent visual match, but unsuitable for an honest Nano accuracy headline |
| **FishTrack23** | CC BY 4.0; credit Dawkins et al. (2024) and contributing collections | VIAME CSV tracks/boxes; 155 labels | 576 sequences; annotations at 5–30 Hz; 1280×720 to 1920×1200 | **Yes** | Highly mixed: clear reef, baited camera, lake, trawl and some degraded footage | Rich continuous video, but known training leakage |
| **DeepFish** | CC BY 4.0; credit Saleh et al. (2020) | Classification, point labels and 620 segmentation images; CFD derived 374 boxes from 310 masks | 39,766 still frames, 1920×1080; source video rate/continuous clip mapping is not packaged as the main benchmark | **Yes** | Mixed habitat; published examples include mangrove/seagrass haze, though collection targeted relatively low turbidity | Fails the per-frame box-video requirement and leaks |
| **SFISHTRACK** | CC BY 4.0; credit Sánchez Cano et al. (2026), DOI 10.5281/zenodo.20617667 | COCO boxes, masks and track IDs on every frame | 54 videos, average 15.13 s, 30 fps, 1920×1080 | **No for the February Nano model**; released after its checkpoint | Mixed clear-to-moderate visibility with varied backgrounds and some haze | Promising leakage-free backup, but CFD's dataset inventory flags an annotation/frame alignment problem; validate before use |

“Turbidity by eye” is a qualitative reading of the publishers' example frames, not a measured water-quality variable.

## Leakage check

The Community Fish Detector model card says its models were trained on a Community Fish Detection Dataset combining **17 open source datasets**. The source inventory has 16 headings because “Marine Detect” combines two source datasets, FishInv and MegaFauna.

The 17 sources documented for the original compilation are:

1. NOAA Puget Sound Nearshore Fish 2017–2018
2. MIT Sea Grant River Herring
3. Tasmanian Orange Roughy Stereo Image Machine Learning Dataset (TORSI)
4. Project Natick Underwater Video
5. Roboflow Fish Dataset
6. DeepFish
7. Deep Vision Fish Dataset
8. The Brackish Dataset
9. F4K Detection and Tracking
10. FishCLEF-2015
11. VIAME FishTrack / FishTrack23
12. Tropical freshwater fish in northern Australia / Kakadu
13. AAU Zebrafish Re-Identification Dataset
14. FathomNet
15. Marine Detect — FishInv
16. Marine Detect — MegaFauna
17. Salmon Computer Vision

The app's `cfd-nano` checkpoint is dated **2026-02-02** and the model card describes the 17-source compilation. The Luderick Seagrass dataset appears in the separate “Datasets added to CFDv2” section, so it is not a known source for that Nano checkpoint. Do not generalize this conclusion to the later May 2026 Small/Medium models without verifying their exact training snapshot.

Brackish, FishTrack23 and DeepFish are explicitly in the original source list. Metrics on those datasets would need the statement:

> The detector may have seen this dataset, or frames from the same source footage, during training; these results are a product demonstration, not an independent generalization benchmark.

## Risks to verify before Step 2

- Confirm the chosen Jack Evans A sequence grouping and exact frame continuity after downloading the archive.
- Visually inspect the 600 selected frames and source boxes before encoding.
- Ensure the clip contains background/empty intervals. The published dataset page says every exported image has at least one fish, which may make review-queue share look unrealistically high; if so, reconsider the clip or use SFISHTRACK after proving its alignment.
- Evaluate only frames carrying published labels. Do not treat unlabeled source-video frames as negatives.
- Keep the dataset labels separate from Tideflow's staff-count and human-decision tables.
- Pin the demo to `cfd-nano`; later CFD models may have seen the CFDv2 additions.

## Sources

- [Community Fish Detector model card](https://github.com/filippovarini/community-fish-detector)
- [Community Fish Detection Dataset source inventory](https://github.com/filippovarini/community-fish-detector-dataset)
- [Luderick Seagrass dataset page](https://globalwetlands.github.io/luderick-seagrass/)
- [Luderick Seagrass PANGAEA record and licence](https://doi.org/10.1594/PANGAEA.926930)
- [Brackish official dataset page](https://vap.aau.dk/the-brackish-dataset/)
- [FishTrack23 paper](https://openaccess.thecvf.com/content/WACV2024/html/Dawkins_FishTrack23_An_Ensemble_Underwater_Dataset_for_Multi-Object_Tracking_WACV_2024_paper.html)
- [DeepFish official dataset page](https://alzayats.github.io/DeepFish/)
- [SFISHTRACK paper](https://www.nature.com/articles/s41597-026-07786-z)
- [SFISHTRACK dataset repository](https://github.com/JosepSanchezCano/SFISHTRACK)
