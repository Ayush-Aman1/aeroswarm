#!/usr/bin/env bash
# Usage: tools/notify.sh "Title" "Message"
# macOS notification + optional phone push (ntfy) + log line in runs/NOTIFICATIONS.log
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TITLE="${1:-Agent}"; MSG="${2:-Done}"
[ -f "$ROOT/config/notify.env" ] && set -a && . "$ROOT/config/notify.env" && set +a
mkdir -p "$ROOT/runs"
echo "[$(date '+%F %T')] $TITLE — $MSG" >> "$ROOT/runs/NOTIFICATIONS.log"
if command -v osascript >/dev/null 2>&1; then
  T=${TITLE//\"/\'}; M=${MSG//\"/\'}
  osascript -e "display notification \"$M\" with title \"$T\" sound name \"Glass\"" >/dev/null 2>&1 || true
fi
if [ -n "${NTFY_TOPIC:-}" ]; then
  curl -s -m 10 -H "Title: $TITLE" -d "$MSG" "https://ntfy.sh/$NTFY_TOPIC" >/dev/null 2>&1 || true
fi
exit 0
