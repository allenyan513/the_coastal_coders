# CLAUDE.md

## Git workflow

1. Create a branch for your task.
2. Commit and push to your branch.
3. Open a pull request.
4. Someone reviews it, then merges it into `main`.
5. Merge into `main` with **Squash and merge**. The branch is deleted afterwards, so one commit per change keeps `main` easy to read.

## Release

The server deploys the `release` branch by itself, within a minute of a change, and rolls back if the site doesn't come up.

1. Open a pull request from `main` into `release`.
2. Merge it with **Create a merge commit**. Never squash or rebase this one: either gives `release` commits that `main` doesn't have, and the next `main` → `release` pull request then conflicts.
3. Check the live site at https://tideflow.ligangyan.com.
