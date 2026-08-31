#!/bin/bash
# Installs both agents. Run manually - nothing here activates on its own.
#   com.memet.poll    every 5 min   on-chain price, all pools, 1 RPC call
#   com.memet.ingest  :00/:15/:30/:45  metrics + backfill + volatility
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UID_="$(id -u)"

for L in ingest poll; do
    DEST="$HOME/Library/LaunchAgents/com.memet.$L.plist"
    cp "$ROOT/scripts/com.memet.$L.plist" "$DEST"
    launchctl bootout "gui/$UID_/com.memet.$L" 2>/dev/null || true
    launchctl bootstrap "gui/$UID_" "$DEST"
    launchctl enable "gui/$UID_/com.memet.$L"
    echo "installed com.memet.$L"
done

echo
echo "run now:   launchctl kickstart gui/$UID_/com.memet.ingest"
echo "watch:     tail -f $ROOT/logs/ingest.log $ROOT/logs/poll.log"
echo "remove:    for L in ingest poll; do launchctl bootout gui/$UID_/com.memet.\$L; done"
