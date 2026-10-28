#!/usr/bin/env bash
# Install (or remove) a daily macOS study reminder via launchd.
#
#   ./scheduling/install_reminder.sh            # daily at 19:00
#   ./scheduling/install_reminder.sh 9 30       # daily at 09:30
#   ./scheduling/install_reminder.sh --uninstall
#
# launchd is built into macOS, no n8n, no cron, no daemon of our own.

set -euo pipefail

LABEL="com.explainback.tutor.reminder"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Reminder uninstalled."
  exit 0
fi

HOUR="${1:-19}"
MINUTE="${2:-0}"

# Prefer the project venv so `rich` and friends are importable.
if [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  PYTHON="$PROJECT_DIR/.venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON}</string>
    <string>${PROJECT_DIR}/scheduling/remind.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${PROJECT_DIR}</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>${HOUR}</integer>
    <key>Minute</key><integer>${MINUTE}</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${PROJECT_DIR}/data/reminder.log</string>
  <key>StandardErrorPath</key>
  <string>${PROJECT_DIR}/data/reminder.log</string>
</dict>
</plist>
PLIST_EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

printf 'Reminder installed: daily at %02d:%02d\n' "$HOUR" "$MINUTE"
echo "Test it now:  $PYTHON $PROJECT_DIR/scheduling/remind.py"
echo "Remove it:    $0 --uninstall"
