#!/usr/bin/env bash
# Publish the website to the whosees.app server.
#   tools/site-deploy.sh soon   public site = coming-soon page (full site only on the LAN preview)
#   tools/site-deploy.sh live   public site = full site
# The LAN preview (http://<server>:8080) always shows the full site.
set -euo pipefail
[ -f "$(dirname "$0")/local.env" ] && . "$(dirname "$0")/local.env"  # your machines; see tools/local.env.example
MODE="${1:-}"; HOST="${WT_SITE_HOST:?set WT_SITE_HOST (user@web-server) in tools/local.env}"
[[ "$MODE" == soon || "$MODE" == live ]] || { echo "usage: $0 soon|live" >&2; exit 2; }
cd "$(dirname "$0")/../website"
rsync -a --delete --exclude soon.html ./ "$HOST:whosees-site/full/"
rsync -a --delete --include 'soon.html' --include 'fonts/***' --include 'img/' \
  --include 'img/icon.png' --include 'img/favicon.png' --include 'img/og.png' --include 'img/world.webp' --exclude '*' \
  ./ "$HOST:whosees-site/soon/"
ssh "$HOST" "MODE=$MODE bash -s" <<'REMOTE'
set -euo pipefail
src=~/whosees-site/full/
if [[ $MODE == soon ]]; then mv ~/whosees-site/soon/soon.html ~/whosees-site/soon/index.html; src=~/whosees-site/soon/; fi
rsync -a --delete --chmod=D755,F644 ~/whosees-site/full/ /var/www/whosees.app-preview/
rsync -a --delete --chmod=D755,F644 "$src" /var/www/whosees.app/
echo "public: $(curl -s -H 'Host: whosees.app' http://127.0.0.1/ | grep -o '<title>[^<]*')"
echo "preview: $(curl -s http://127.0.0.1:8080/ | grep -o '<title>[^<]*')"
REMOTE
