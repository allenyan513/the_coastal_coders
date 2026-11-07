# Demo

Everything we show the judges and Coastal Action: slides, screenshots, screen recordings and charts. The judges won't read our code, so this folder is where results become something people can see.

The other three folders build the product. This one presents it:

| Folder | Question it answers |
|---|---|
| `ml/` | Which data and models detect and track the fish? |
| `server/` | How does the service run those models and serve results? |
| `web/` | Is the tool easy for Coastal Action staff to use? |
| `demo/` | How do we show what it does and how well it works? |

## What goes here

| Kind | Where | In git? |
|---|---|---|
| Slides | `slides/` | Yes. Export a PDF next to the deck so it opens anywhere |
| Screenshots | `screenshots/` | Yes. Keep them under about 1 MB each |
| Charts | `charts/` | Yes, both the image and the script that makes it, so a chart can be redrawn when the numbers change |
| QR code | `qr/` | Yes. Made by `pnpm qr` in `web/`, and it opens `/start` on the public site |
| Screen recordings | `recordings/` | No. Share them through a drive link instead |

Create a subfolder when you first need it.

Chart scripts read from `data/` (the app's results and `data/bench/` score sheets) and should never retrain or rerun a model. If a number needs a model run, add that step to `ml/` and have the chart read its output.

## Footage rules

- The benchmark videos have the uploader's standard YouTube licence. Don't put frames or clips from them in a slide, screenshot or recording without asking the uploader. Simulated frames are fine. Public-dataset frames, such as Brackish, are fine if that dataset's licence allows it, with credit on the slide.
- Video files never go in git. `.gitignore` here blocks common video formats.
