#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.internshipwatch.daily"
DASH_LABEL="com.internshipwatch.ui"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
DASH_PLIST="$HOME/Library/LaunchAgents/${DASH_LABEL}.plist"
UID_NUM="$(id -u)"

HOUR=$(python3 -c "import json; print(json.load(open('$ROOT/automation/config.json'))['hour'])")
MINUTE=$(python3 -c "import json; print(json.load(open('$ROOT/automation/config.json'))['minute'])")

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/automation/logs" "$ROOT/automation/state" "$ROOT/automation/reports"
chmod +x "$ROOT/automation/run.sh" "$ROOT/automation/daily_run.py"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${ROOT}/automation/run.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>${HOUR}</integer>
    <key>Minute</key>
    <integer>${MINUTE}</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${ROOT}/automation/logs/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>${ROOT}/automation/logs/launchd.err.log</string>
  <key>RunAtLoad</key>
  <false/>
  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
EOF

launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
launchctl unload "$PLIST" 2>/dev/null || true
if launchctl bootstrap "gui/${UID_NUM}" "$PLIST" 2>/dev/null; then
  :
elif launchctl load "$PLIST"; then
  :
else
  echo "launchd load failed; adding a user crontab fallback instead"
  (crontab -l 2>/dev/null | grep -v resume-internships || true; echo "${MINUTE} ${HOUR} * * * /bin/bash ${ROOT}/automation/run.sh >> ${ROOT}/automation/logs/cron.log 2>&1") | crontab -
fi

cat > "$DASH_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${DASH_LABEL}</string>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${ROOT}/automation/run.sh</string>
    <string>--dashboard</string>
    <string>--daemon</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${ROOT}/automation/logs/dashboard.out.log</string>
  <key>StandardErrorPath</key>
  <string>${ROOT}/automation/logs/dashboard.err.log</string>
  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
EOF

launchctl bootout "gui/${UID_NUM}/${DASH_LABEL}" 2>/dev/null || true
launchctl unload "$DASH_PLIST" 2>/dev/null || true
if launchctl bootstrap "gui/${UID_NUM}" "$DASH_PLIST" 2>/dev/null; then
  :
elif launchctl load "$DASH_PLIST"; then
  :
else
  echo "Could not load ${DASH_LABEL}; start the UI with: make internships-dashboard"
fi

echo "Installed ${LABEL}"
echo "Runs daily at ${HOUR}:$(printf '%02d' "$MINUTE") local time."
echo "Dashboard stays up at http://127.0.0.1:8765/ (login + KeepAlive)."
echo "Tailoring uses Cursor Agent CLI (not Claude). Login once: agent login"
case "$ROOT" in
  "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*)
    echo
    echo "This repo is under Desktop/Documents/Downloads. launchd cannot read those folders"
    echo "unless /bin/bash has Full Disk Access (System Settings → Privacy & Security →"
    echo "Full Disk Access → + → /bin/bash). Without that, 8:00 fails with exit 126."
    echo "Alternatively, move the repo out of Desktop (e.g. ~/src/resume)."
    ;;
esac
if [ "${SKIP_SEED:-}" != "1" ]; then
  echo "Seeding listings older than 24h (so the first night does not tailor hundreds of old postings)..."
  /bin/bash "$ROOT/automation/run.sh" --dry-run
fi
echo
echo "Run now:     make internships-now"
echo "Dry run:     make internships-dry"
echo "Uninstall:   make internships-uninstall"
