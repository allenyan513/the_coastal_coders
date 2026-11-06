# CLAUDE.md

Allen's personal prep repo for RBC HubHacks 2026 (Nov 5–9). Only Allen uses it. It is not a team repo and nothing here goes into the competition: the team creates a separate repo on kickoff day.

## Current goal

Our team was assigned **Coastal Action** (Problem #2), and the product is TideCount. Requirements and design live in [GitHub Issues](https://github.com/allenyan513/RBC_HUBHACKS_2026/issues): the PRD draft is #13 and the technical design draft is #14. Neither is decided until the team agrees.

## Working rules

- Write repo content (docs, code comments, commit messages) in English. Chat with Allen in Chinese.
- Commit straight to `main`. No PRs or feature branches.
- Track requirements, plans and research in GitHub Issues, not in repo documents. Write issues in English.
- In `tidecount/ml`, show progress with `tqdm.auto.tqdm` on every loop that does real work: downloads, decoding, data preparation, training and inference. Skip it on loops that only draw charts.
- Don't try to unlock the access-code pages on rbchubhacks.com.
