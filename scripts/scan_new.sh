#!/bin/sh
# After roasters are added (world.yml, listings.yml): if today's scan has already gone by, or is running, scan just the
# new ones now instead of tomorrow. $1 is roasters.json from before the run; GH_TOKEN needs Actions write.
NEW=$(python3 scripts/new_roasters.py "$1" data/roasters.json)
[ -z "$NEW" ] && { echo "No new roasters"; exit 0; }
git fetch -q origin main
done_today=$(git log origin/main --since="30 hours ago" --format=%s | grep -cx "Roaster scan $(date -u +'%d %b %Y')" || true)
running=$(gh run list -R "$GITHUB_REPOSITORY" --workflow scan.yml --json status -q '[.[] | select(.status != "completed")] | length')
if [ "$done_today" != "0" ] || [ "$running" != "0" ]; then
  gh workflow run scan.yml -R "$GITHUB_REPOSITORY" -f only="$NEW" && echo "Scanning the new roasters now: $NEW"
else
  echo "Today's scan hasn't started yet: it will read them ($NEW)"
fi
