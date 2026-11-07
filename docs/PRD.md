# Tideflow — Product Requirements

*From footage to findings, in one place.*

**Status:** draft 2, 2026-11-07, for review by the team and our mentor.
**Scope of this document:** the whole platform we are designing. Section 11 says which parts the hackathon proof-of-concept builds, which it only designs, and why.

---

## 1. Summary

Coastal Action monitors fish and fish habitat on Nova Scotia's South Shore with stationary underwater video. Every video is analysed by hand, following their draft *FFH Video Analysis Protocol*: a person watches a 15-minute window in real time to list species, counts fish at 15 sub-sample points, and a second person blind-recounts a sample for quality control. The results live in Excel; the footage lives in folders; the work is coordinated by email.

**Tideflow is the workspace for that whole job.** It keeps the footage, runs the protocol step by step, assigns work to volunteers and validators, and produces the analysis sheet and the season-over-season comparison the organisation needs. AI runs locally on their own hardware and only *assists*: it suggests where to start, highlights the moments worth watching, and proposes counts and species that a person accepts, corrects or ignores. **Every number in a report is one a named person recorded**, and the tool records whether AI was shown before they recorded it.

The product is designed so that Coastal Action can adopt it under their current rule (no publicly hosted AI) and switch to stronger open-source models when their hardware and AI guidelines arrive.

## 2. Background

### 2.1 The partner and the survey

Coastal Action (charity, Mahone Bay, founded 1993) runs remote underwater video (RUV) surveys: an unbaited camera on a stand records about 20 minutes at a station on a transect (footage names like `T1-STAT2 411.MP4`). Surveys repeat at the same stations over seasons so that change at a site can be measured. The same team runs water-quality monitoring in local rivers.

### 2.2 How a video is analysed today

From the draft protocol and the reviewers' comments on it:

| Step | What a person does | Our time estimate* |
|---|---|---|
| Trim | Drop the first and last minute (sediment, retrieval), pick a 15-minute window, record its start and end | 2 min |
| Visibility | 2–3 observers independently rate visibility in four bands (<0.5, 0.5–1.0, 1.0–1.5, >1.5 m); note changes ≥0.5 m | 5 min |
| Species pass | Watch the whole window in real time and list every species to the lowest taxonomic level | 15 min |
| MeanCount | One point every 60 s (15 points). At each: watch ±5 s at 0.25×, count only fish in that second, needing ≥2 of 4 identifying characteristics; record 7 fields | 15–30 min |
| QC | A second person blind-recounts ≥10 % of points (6–12); >6 % difference → third count; <95 % agreement → re-annotate the video | 10–20 min of a second person |
| Record | Type everything into the Excel template | 10 min |

\*Estimates from the protocol text, not measured with Coastal Action. We measure our own timings in the PoC (section 11).

So one 20-minute video costs roughly an hour of a trained person plus a second person's time, in three programs (a video player, a spreadsheet, a file manager), with handoffs by message.

### 2.3 The pain points, in the partner's words

> Current issues around fish monitoring with video surveys include:
> - Outdated species list, especially with climate change drivers.
> - Low visibility and high interference from natural materials in the water (algae, sediment, grass, etc.)
> - Reliance on human detection and associated errors and fatigue.
> - Staff cost of analyzing video data.

And the constraint:

> Due to environmental concerns, our use of AI is heavily restricted. At this time, we would not be able to support a publicly hosted AI model. However, we may be able to support an open-source model hosted locally, once we have the hardware to implement the system and more developed guidelines around the use of AI at Coastal Action.

### 2.4 The protocol is still a draft

The reviewers' comments disagree on the parameters: 15 points every 60 s versus the earlier 60 points every 12 s, ±5 s versus ±10 s of context, 10 % versus 15–20 % QC, whether MeanCount inflates zeros, whether to also report MaxN. We build to the current draft (15 points every 60 s, ±5 s of context, 10 % QC) and keep those numbers on one settings page, so however they settle it, it is a change of settings, not of software.

## 3. Users and roles

| Role | Who | What they need |
|---|---|---|
| **Volunteer** (annotator) | Students and community volunteers, trained on the protocol, often on their own laptop | A guided, unambiguous workflow; keyboard-driven; hard to do the wrong thing |
| **Validator** | A second trained person, sometimes staff | Blind recounts of a sample, without seeing the first count; a clear verdict |
| **Coordinator** | Coastal Action staff running the monitoring program | Assign videos, watch progress, settle disagreements, approve results, export |
| **Viewer** | Scientists, board, funders, partner organisations | Trends by site and season; the methods used; downloads |

Assumption to confirm with Coastal Action: the volunteer / validator / coordinator split exists informally today; we heard volunteers and spot-checkers mentioned.

## 4. Goals and non-goals

### Goals

1. **Cut the person-time per video** without changing what a person is responsible for.
2. **Make every number traceable**: who recorded it, when, whether AI was shown first, and how QC went.
3. **Follow the protocol exactly**, and make its parameters something Coastal Action can change and compare.
4. **Run entirely on Coastal Action's own hardware**, with open-source models, no data leaving the site.
5. **Turn single-video results into site-level answers**: is this station changing over seasons?

### How we would measure success in a pilot

| Measure | Today (estimate) | Target |
|---|---|---|
| Minutes of person-time per video, first count | ~60 | ≤30 |
| Points with a blind second count | ≥10 % by rule, unknown in practice | 100 % of videos meet the rule, enforced |
| Numbers in a report without a named person | — | 0 |
| Time from last video of a season to a site comparison | weeks (Excel) | same day |
| Agreement between first and second counts | unknown | reported per video and per person |

### Non-goals

- **Automatic counts.** AI never writes a number into a report; a person does.
- **A cloud service.** No hosted AI, no telemetry, no footage leaving the deployment.
- **A general fish classifier for Nova Scotia.** Species identification stays with the person; AI suggests, and the species catalogue grows from confirmed records.
- **Replacing the protocol.** The tool implements the protocol Coastal Action chooses; it does not define one.

## 5. Product principles

1. **The protocol is the UI.** Screens follow the manual's steps in order; the unit of work is the sub-sample point; the export has the manual's column names.
2. **AI is advisory and visible as such.** Suggestions are labelled, can be hidden, and by default appear *after* the person has recorded, so a person who sees AI first cannot anchor on it without the record saying so.
3. **A name on every number.** Counts, species records, visibility ratings and validations each carry who and when.
4. **Conservative by design.** Where the protocol says underestimate rather than overestimate, the tool does the same: a fish AI saw but the person did not count stays uncounted, and is logged as a disagreement.
5. **Local first.** Works offline on a laptop for one person; the same software serves a team on a server.

## 6. Modules

Each module lists requirements (MUST / SHOULD / COULD), the AI assistance it uses, and its status: **Built** (works in the current app), **Partial**, **Prototype** (working front-end in `tidecount/prototype/`, not wired to storage), **Designed** (this document only).

### 6.1 Footage library

*Replaces folders on a Windows PC.* Pain points: staff cost; visibility.

The survey structure lives in Tideflow, not in folder names. A coordinator maintains Sites → Transects → Stations and the Surveys (site + date) once; everyone else drags footage in and picks where it belongs. The same tree then drives the library, the workflow board and the reports. Footage is copied into Tideflow's own storage, so the system owns what it analyses and a moved folder cannot break a record.

- MUST provide create / edit / archive for Sites, Transects and Stations (name, coordinates, depth, treatment or reference flag) and for Surveys (site, date, tide, weather, crew), for coordinators only. Nothing can be deleted while a video refers to it; archiving hides it from new imports and keeps old records whole. **Designed**
- MUST import a video by drag-and-drop (or from a path on the PC for files too large to upload), choosing the survey and station it belongs to; the file is copied into Tideflow's storage with a checksum and a browser-playable proxy, and the original is left untouched. **Partial** (import and proxy built; site only, no station picker)
- SHOULD pre-fill the station from the filename when it follows Coastal Action's convention (`T1-STAT2 411.MP4` → transect 1, station 2, clip 411), as a suggestion the person confirms. **Prototype** (parsed for display)
- MUST list and search videos by site, transect, station, survey date, state and assignee. **Prototype** (grouped by transect and station)
- SHOULD import a whole SD card or folder in one go, each file landing in the station picker with its pre-filled suggestion. **Designed**
- SHOULD stitch GoPro chapters of one deployment into one video, and split a long recording into deployments, with the originals kept. **Designed**
- COULD store footage on a NAS or object store with the database holding paths and checksums. **Designed**
- AI: on import, run detection, tracking and water-clarity estimation in the background, so the analysis workflow opens with suggestions ready. **Built**

### 6.2 Workflow, assignment and audit

*Replaces email handoffs.* Pain points: fatigue and errors; staff cost.

Each video moves through fixed states:

`Imported → Analysed (AI) → Set up → Species listed → Counted → In validation → Recount needed → Approved → Archived`

- MUST show every video's state, assignee and due date on one board; a coordinator assigns a video to a volunteer and a validator. **Prototype** (state only)
- MUST stop a validator from seeing the first count, and stop the same person from validating their own count. **Prototype** (hides first counts; same-person rule designed)
- MUST keep an audit log: every state change and every saved record, with who and when. **Designed**
- SHOULD let a coordinator reopen an approved video with a reason, which creates a new version rather than editing the old one. **Designed**
- COULD notify by email when work is assigned or a recount is needed. **Designed**

### 6.3 Analyse a video (the protocol workflow)

Pain points: all four. This is the core of the product and the part the PoC demonstrates end to end.

#### 6.3.1 Set up

- MUST show the AI-suggested analysis-window start (first clear stretch after the trimmed minute) with the reason, and let the person move it on a slider with the frame shown. **Prototype**
- MUST record the visibility band, and allow 2–3 independent ratings per video, each with a name. **Prototype** (one rating)
- MUST record juveniles present / absent for the video (optional in the protocol). **Prototype**
- SHOULD show water clarity over the whole video as a strip, so murky stretches are visible before choosing a start. **Prototype**
- AI: per-second clarity score and suggested start. **Built**

#### 6.3.2 Species pass

- MUST let the person watch the whole window in real time, or jump between AI-flagged active segments, and record which mode they used (the protocol asks for the whole window; the tool must not hide that a shortcut was taken). **Prototype**
- MUST record each species with time, a frame capture, the person's name and a note; one key to record, one key to jump to the next segment. **Prototype** (captures not yet stored)
- MUST allow "unknown / unable to identify" as a record, with the capture, so it lands in the unidentified gallery (6.5). **Designed**
- SHOULD show AI's top-3 species suggestions for a boxed fish, from the local species model, labelled as suggestions. **Built** (track review) / **Designed** (in this screen)
- AI: active-segment flags from detections; species suggestions (BioCLIP, local). **Built**

#### 6.3.3 MeanCount (sub-sample points)

- MUST generate the 15 points from the window start, one every 60 s. **Prototype**
- MUST, for each point, play the context clip (±5 s by default) at 0.25× automatically, highlight the counting second, and offer replay, jump-to-second and frame stepping by keyboard. **Prototype**
- MUST record the 7 protocol fields per point: visibility change, total fish, invertebrates, per-species counts, unknown/unable to ID, notes, and "could not see" (left out, never a zero). **Prototype**
- MUST save the counting person's name and time with each point. **Prototype**
- MUST support AI suggestions for total count, visibility change and species, with this rule: **by default the suggestion and AI's boxes appear only after the person saves**; a setting may switch to "show first". Each saved point records whether AI was shown before the count and whether its number was accepted. Points counted without seeing AI also measure the AI's accuracy; points that saw AI first never do. **Prototype** (show-after) / **Built** (accuracy measurement from blind frames)
- SHOULD let the person step away and resume; order of points is fixed random so a partial count still covers the window. **Built**
- COULD support a frozen-frame school count for dense frames. **Built**
- AI: per-second detection counts and boxes at the counting second. **Built**

#### 6.3.4 Validation (quality control)

- MUST open only when all points are counted, draw a random sample of max(6, 10 %) points, and show the validator the same clips without the first counts. **Prototype**
- MUST compute per-point difference as |a−b| / mean, flag >6 %, compute agreement, and set the video to *Recount needed* when a third count is required or agreement is <95 %. **Prototype**
- MUST record the validator's name and the third counter's name. **Prototype**
- SHOULD report agreement per person over time, so training needs show up. **Designed**

#### 6.3.5 Approve and store

- MUST let a coordinator approve the video, which freezes the record and writes the final per-point values (average of first and second count where both exist). **Designed**
- MUST export the analysis sheet with the protocol's columns and trailing rows (MeanCount, species seen, visibility, who counted, agreement). **Prototype** (CSV) / **Built** (older sheet)
- SHOULD export the whole survey or season as one file and as a Darwin-Core-style species occurrence file. **Designed**

### 6.4 Protocol settings

One settings screen, nothing more.

- MUST show the protocol numbers on one settings page (trim, window, point spacing, context seconds, QC share and minimum, difference and agreement thresholds). One set of values for the whole deployment; the report prints them so a reader knows what was applied. **Prototype**

### 6.5 Species catalogue and unidentified gallery

Pain point: outdated species list.

- MUST keep a species list seeded from Coastal Action's current list, each entry with common and scientific name, status (native / invasive / unexpected), and reference captures taken from their own footage. **Partial** (reference page exists)
- MUST grow the list from confirmed records: first-seen date and station per species. **Designed**
- MUST collect "unknown / unable to identify" captures into a gallery where an expert can identify them later, in bulk, and the identification flows back to the point and species record. **Designed**
- SHOULD show AI's suggestion beside each gallery capture and let the expert accept it. **Designed**

### 6.6 Reports and trends

Pain point: the reason the surveys exist.

- MUST show, per station and per survey date: MeanCount, MaxN, species richness, visibility, who analysed, QC agreement. **Partial** (per video)
- MUST compare stations on a transect and the same station across seasons. **Designed**
- SHOULD compare a treatment site (e.g. a living shoreline) with its reference site over time. **Designed**
- SHOULD let a viewer download the underlying rows for any chart. **Designed**

### 6.7 Environmental context (river and water monitoring)

Coastal Action's water-quality program produces continuous data; Ethan prototyped a forecast on it during research. We treat it as a data source in the same workspace, so counts can be read beside temperature, salinity, turbidity and flow.

- SHOULD import water-quality series per site and plot them beside survey results. **Designed**
- COULD surface Ethan's forecast as a module with its own page. **Designed** (inputs to be confirmed with Ethan)

### 6.8 Accounts, roles and permissions

- MUST run with no login on one laptop (single-user mode), with the person's name typed once. **Prototype**
- MUST, in team mode, provide email + password login with the four roles in section 3; permissions follow the workflow (a validator cannot edit first counts; a viewer cannot edit anything). **Designed**
- SHOULD support invitation links for volunteers and a coordinator-managed user list. **Designed**

### 6.9 Deployment, data sovereignty and security

This is our answer to the constraint in section 2.3, and it is one slide in the pitch:

> **Tideflow is self-hosted. Code, models, footage and results all sit on one computer that Coastal Action owns.** Nothing is sent to a cloud service, no AI runs outside that machine, and the code is public on GitHub for anyone to audit. The team works together on it the same way they would on a shared drive: on the office network, over a VPN, or over the internet behind HTTPS and a login, whichever their IT is comfortable with.

- MUST run as one Docker Compose deployment on a server Coastal Action owns, or with one command on a laptop (`start.sh` / `start.bat`). **Built**
- MUST make no outbound calls at run time; open-source models are downloaded once at install or bundled for an offline install. **Partial** (no cloud calls; models download on first analysis)
- MUST keep footage and results on that machine; a backup is a copy of one folder; everything exports in open formats. **Built**
- MUST support three access patterns, chosen at deployment: office network only; VPN; or internet with HTTPS, login and roles (6.8). **Partial** (HTTPS via Caddy on the demo; login designed)

### 6.10 In-app manual (low priority)

- COULD show the protocol text for the current step beside the screen. **Designed**

### Pain points covered

| Partner pain point | Module | Status |
|---|---|---|
| Outdated species list | 6.3.2 captures, 6.5 catalogue and gallery | Prototype / Designed |
| Low visibility, interference | 6.3.1 clarity strip and suggested start, 6.4 sensitivity | Prototype |
| Human error and fatigue | 6.3.3 AI shown after, 6.3.4 enforced blind QC, 6.2 audit | Prototype |
| Staff cost | 6.3.2 flagged segments, 6.3.3 auto-play at 0.25×, 6.2 one place for the job | Prototype |
| No publicly hosted AI | 6.9 local, open-source, bundled models | Built |

## 7. AI capabilities

All models are open source, run locally, and are replaceable. Each analysis run stores the model and settings it used.

| Capability | Model | Used in | Status | How we check it |
|---|---|---|---|---|
| Fish detection | RF-DETR fine-tuned by the Community Fish Detector project (nano / small / medium); YOLO11 checkpoints (Megalodon, NOAA) optional | Segments, counting second, suggested counts | Built | Blind-counted points vs AI boxes (AI accuracy page); benchmark videos in `ml/bench.py` |
| Tracking | ByteTrack | Track review, species thumbnails | Built | Track review decisions |
| Species suggestion | BioCLIP 2.5 (ViT-H/14), zero-shot top-3 | Species pass, gallery | Built (tracks) | Expert acceptance rate in the gallery |
| Water clarity | Per-second image statistics (no learned model) | Set up, sensitivity | Built | Agreement with recorded visibility bands |
| Suggested window start | Rule on clarity (first stretch ≥ half the video's usual clarity, lasting 2 min) | Set up | Built | How often the person keeps it |

Honest limits, stated in the pitch: the detector is not tuned on Coastal Action footage; AI counts used in charts are unverified until blind points exist; species suggestions are zero-shot and not validated for Nova Scotia; the model will be swapped when hardware and labelled footage exist.

## 8. Data model

Entities, each with id, created-by and created-at:

- **Site → Transect → Station** (location, treatment/reference flag)
- **Survey** (site, date, tide, weather, crew)
- **Video** (station, survey, file, duration, checksum, proxy, chapters)
- **AnalysisRun** (video, detector, settings used, per-second counts and clarity, boxes, tracks)
- **Analysis** (video, state, assignee, validator, window start, visibility ratings, juveniles)
- **SpeciesRecord** (analysis, species or "unknown", time, capture, person, note)
- **Point** (analysis, index, time, 7 fields, person, time saved, AI shown first?, AI count, accepted?)
- **Validation** (analysis, sample of points, second counts, third counts, differences, agreement, verdict, persons)
- **Species** (names, status, references, first seen)
- **User** (name, email, role) and **AuditEvent**

## 9. Architecture

**Today:** FastAPI + SQLite service (`tidecount/server`) that imports footage, runs models in a background worker and serves results; React + TypeScript UI (`tidecount/web`); ML experiments and benchmarks (`tidecount/ml`); Docker Compose with Caddy for the public demo (`deploy/`). The new protocol workflow exists as a single-file front-end prototype (`tidecount/prototype/`) against the service's video endpoint.

**Target:** the same service with the prototype's screens moved into the React app and its state moved into the database; Postgres as an option for a team server; a job queue for model runs so a GPU box can serve several laptops; authentication and roles; footage on local disk or a NAS. No component requires the internet.

## 10. Non-functional requirements

- Runs on a 2020-era laptop CPU for everything except model runs, which may take longer than real time; analysis runs in the background.
- Keyboard-first for annotation screens; works on a phone for viewing reports.
- Every write is attributable; approved analyses are immutable; exports are reproducible from stored records.
- Open formats throughout: MP4 proxies, CSV exports, SQLite/Postgres, JSON settings.
- Footage never leaves the deployment; no analytics or telemetry.

## 11. Scope of the hackathon proof-of-concept (submission 2026-11-08)

The judges score the presentation first and read the code to verify it. The PoC therefore proves the core workflow end to end on real footage and designs the rest.

| Module | PoC delivers |
|---|---|
| 6.3 Analyse a video | Full flow on the `T1-STAT2 411` footage: set up → species pass → 15 points → blind validation → report → CSV, wired to the service for video, AI data and saved results |
| 6.4 Protocol settings | One settings page with the protocol numbers |
| 6.5 Species | Captures per record; unidentified gallery page |
| 6.1 Library | Site → Transect → Station setup page; drag-in import picks the station, with the filename pre-filling it; AI analysis as today |
| 6.2 Workflow | States and names, no accounts |
| 6.6 Reports | Per-video report; a season comparison shown as a design mock, clearly labelled |
| 6.7–6.10 | Designed in this document only |
| Evidence | Our own timed comparison: species pass watched in full vs with flagged segments, same person, same video |

## 12. Open decisions for the team

1. **Product name: decided, Tideflow.** Renamed from TideCount on 2026-11-07 to say what it is: one flow from footage to findings, not a counter. The code package and folder are still called `tidecount`; renaming them is not worth the risk before the submission. Subtitle: "From footage to findings, in one place."
2. **AI suggestions in counting: shown after save by default (recommended) or before.** Before is faster; after keeps counts independent and lets blind points measure the AI. Either way the record stores which happened.
3. **Species pass shortcut.** Jumping between flagged segments does not follow the protocol's "watch the whole window". Recommendation: allow it, record it, and let a setting forbid it.
4. **How far the PoC wires to the service.** Prototype screens reading and writing through the API (recommended) versus porting them into React now.
5. **Ethan's river module.** Include as a designed page with one real chart if the data is at hand; otherwise a paragraph.

## 13. Questions for Coastal Action

1. How many videos per season, how many stations, and how many people analyse them?
2. What is the current list of sites, transects and stations, and is the `T#-STAT# <clip>` naming used on every file?
3. Who are the volunteers, validators and coordinators today, and how is work handed over?
4. Which parameters of the draft will be adopted (points, context, QC share), and would a comparison on their footage help decide?
5. What species list do they use now, and how are unexpected species recorded today?
6. What hardware could host the system, and what would an AI guideline need to say for them to use local models?
7. Which site comparison matters most (station over seasons, treatment versus reference)?

## 14. Roadmap

| Phase | When | Outcome |
|---|---|---|
| Proof of concept | 2026-11-08 | Section 11 |
| Pilot | Winter 2026–27 | Re-analyse one past season with Tideflow beside the Excel results; measure time and agreement |
| Season 1 | 2027 survey season | Team mode with accounts, assignment and the species gallery; reports by station |
| Season 2 | 2028 | Detector fine-tuned on Coastal Action's own labelled footage; environmental context; multi-organisation use |
