#!/usr/bin/env bash
# Deploys the release branch when it changes. A systemd timer runs this every minute.
#
# The machine asks GitHub, so no keys are stored anywhere. The site keeps running during a build,
# and a release that fails is rolled back and not tried again. Local edits to tracked files on the
# machine are overwritten. Everything the app saves is in deploy/data, which git doesn't touch.
#
# The script is one function so `git reset` can't change the code bash is still reading.
set -euo pipefail

BRANCH=release

main() {
  cd "$(dirname "$0")"
  local git_dir failed old new
  git_dir=$(git rev-parse --absolute-git-dir)
  failed="$git_dir/tidecount-failed-commit"

  exec 9>"$git_dir/tidecount-update.lock"
  flock -n 9 || return 0

  git fetch --quiet origin "$BRANCH"
  old=$(git rev-parse HEAD)
  new=$(git rev-parse FETCH_HEAD)
  [ "$old" != "$new" ] || return 0
  [ "$(cat "$failed" 2>/dev/null)" != "$new" ] || return 0

  echo "Deploying ${new:0:7}"
  if deploy "$new" "$old"; then
    rm -f "$failed"
    docker image prune -f >/dev/null
    echo "Deployed ${new:0:7}"
    return 0
  fi

  echo "${new:0:7} failed, going back to ${old:0:7}"
  echo "$new" >"$failed"
  deploy "$old" "$new" || echo "The rollback failed too, so the site needs a look."
  return 1
}

# Moves to a commit and checks the site. The running containers stay until the build has worked.
deploy() {
  local target=$1 from=$2
  git reset --quiet --hard "$target" || return 1
  docker compose build || return 1
  docker compose up -d --remove-orphans || return 1
  # Caddy reads this file from the machine, so Compose can't see that it changed.
  if ! git diff --quiet "$from" "$target" -- Caddyfile; then
    docker compose restart caddy || return 1
  fi
  healthy
}

healthy() {
  local site url
  site=$(sed -n 's/^SITE_ADDRESS=//p' .env 2>/dev/null || true)
  site=${site%%,*}  # the first address, if there are several
  site=${site// /}
  url="${site:+https://$site}/api/videos"
  [ -n "$site" ] || url=http://127.0.0.1/api/videos
  for _ in $(seq 1 60); do
    curl -fsS -o /dev/null --max-time 5 ${site:+--resolve "$site:443:127.0.0.1"} "$url" && return 0
    sleep 2
  done
  echo "The site didn't come up."
  return 1
}

main "$@"
exit
