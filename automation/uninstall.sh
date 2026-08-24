#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.internshipwatch.daily"
DASH_LABEL="com.internshipwatch.ui"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
DASH_PLIST="$HOME/Library/LaunchAgents/${DASH_LABEL}.plist"
UID_NUM="$(id -u)"

launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"

launchctl bootout "gui/${UID_NUM}/${DASH_LABEL}" 2>/dev/null || true
launchctl unload "$DASH_PLIST" 2>/dev/null || true
rm -f "$DASH_PLIST"

if crontab -l 2>/dev/null | grep -q resume-internships; then
  crontab -l 2>/dev/null | grep -v resume-internships | crontab - || true
fi

echo "Removed ${LABEL} and ${DASH_LABEL}"
