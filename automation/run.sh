#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$HOME/.local/bin:/Applications/Cursor.app/Contents/Resources/app/bin:/Library/TeX/texbin:/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.10/bin:/usr/bin:/bin:$PATH"
# Cursor IDE sets CURSOR_AGENT=1 as a flag, not a binary path.
if [ "${CURSOR_AGENT:-}" = "1" ] || [ "${CURSOR_AGENT:-}" = "true" ]; then
  unset CURSOR_AGENT
fi
cd "$ROOT"
mkdir -p "$ROOT/automation/logs" "$ROOT/automation/state" "$ROOT/automation/reports"
exec python3 "$ROOT/automation/daily_run.py" "$@"
