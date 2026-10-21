#!/usr/bin/env bash
# Run a long job DETACHED so the agent session can end; notifies when it finishes.
# Usage: tools/bg.sh <label> "<command>"
# Creates runs/<label>/{job.sh,runner.sh,STATUS,PID,log.txt}. STATUS = RUNNING | DONE | FAILED:<code>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
LABEL="$1"; shift
DIR="$ROOT/runs/$LABEL"; mkdir -p "$DIR"
if [ -f "$DIR/STATUS" ] && [ "$(cat "$DIR/STATUS")" = "RUNNING" ] && kill -0 "$(cat "$DIR/PID" 2>/dev/null)" 2>/dev/null; then
  echo "'$LABEL' is already running (pid $(cat "$DIR/PID")). Not starting a second copy."; exit 1
fi
printf '#!/usr/bin/env bash\ncd %q\n[ -f .venv/bin/activate ] && source .venv/bin/activate\n%s\n' "$ROOT" "$*" > "$DIR/job.sh"
cat > "$DIR/runner.sh" <<RUNNER
#!/usr/bin/env bash
cd "$ROOT"
echo RUNNING > "$DIR/STATUS"
date '+%F %T' > "$DIR/STARTED"
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -i bash "$DIR/job.sh" > "$DIR/log.txt" 2>&1
else
  bash "$DIR/job.sh" > "$DIR/log.txt" 2>&1
fi
code=\$?
date '+%F %T' > "$DIR/ENDED"
if [ "\$code" -eq 0 ]; then
  echo DONE > "$DIR/STATUS"
  "$ROOT/tools/notify.sh" "$LABEL finished" "OK. Log: runs/$LABEL/log.txt"
else
  echo "FAILED:\$code" > "$DIR/STATUS"
  "$ROOT/tools/notify.sh" "$LABEL FAILED" "Exit \$code. Log: runs/$LABEL/log.txt"
fi
RUNNER
chmod +x "$DIR/job.sh" "$DIR/runner.sh"
nohup "$DIR/runner.sh" >/dev/null 2>&1 &
echo $! > "$DIR/PID"
echo "Started '$LABEL' in background (pid $!)."
echo "Check: cat runs/$LABEL/STATUS   |   tail -n 40 runs/$LABEL/log.txt"
