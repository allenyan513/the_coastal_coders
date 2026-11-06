# CLAUDE.md

Allen's personal prep repo for RBC HubHacks 2026 (Nov 5–9). Only Allen uses it. It is not a team repo and nothing here goes into the competition: the team creates a separate repo on kickoff day.

## Current goal

Our team was assigned **Coastal Action** (Problem #2), and the product is TideCount. Requirements and design live in [GitHub Issues](https://github.com/allenyan513/RBC_HUBHACKS_2026/issues): the PRD draft is #13 and the technical design draft is #14. Neither is decided until the team agrees.

## Working rules

- Write repo content (docs, code comments, commit messages) in English. Chat with Allen in Chinese.
- Allen is new to machine learning and video analysis. The first time a technical term comes up in a conversation, explain it from zero in plain language: what it is, and why it matters for the decision at hand. Never use jargon as shorthand. Allen can't judge a recommendation without understanding it, and teaching from scratch is always welcome.
- Track requirements, plans and research in GitHub Issues, not in repo documents. Write issues in English.
- In `tidecount/ml`, show progress with `tqdm.auto.tqdm` on every loop that does real work: downloads, decoding, data preparation, training and inference. Skip it on loops that only draw charts.
- Don't wait for Coastal Action's footage, and don't suggest asking them for it. Use our own stand-in: a long underwater video nobody on the team has seen, such as a one-hour video from YouTube, and treat it as theirs. Keep it out of git.
- Coastal Action will upgrade their compute. Don't raise their current hardware, GPU access or AI guideline as a limit on plans or recommendations.
