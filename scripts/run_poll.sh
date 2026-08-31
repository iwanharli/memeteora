#!/bin/bash
# On-chain price for every pool: one RPC call, ~1s. Cheap enough to run often,
# and it is the only source with complete coverage - vendors have real gaps.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$ROOT/logs/poll.log"
mkdir -p "$ROOT/logs"
export MEMET_DSN="${MEMET_DSN:-dbname=db_memet}"
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/Applications/Postgres.app/Contents/Versions/18/bin:$PATH"
# launchd starts with a minimal environment, and /usr/bin/python3 has no
# psycopg2 - pick the first interpreter that can actually import it.
PYTHON=""
for c in "${MEMET_PYTHON:-}" /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3)"; do
    [ -n "$c" ] && [ -x "$c" ] && "$c" -c "import psycopg2" 2>/dev/null && { PYTHON="$c"; break; }
done
if [ -z "$PYTHON" ]; then
    echo "$(TZ=Asia/Jakarta date "+%FT%T WIB") no python3 with psycopg2 found" >> "$LOG"
    exit 1
fi

cd "$ROOT" || exit 1
[ -f "$LOG" ] && [ "$(stat -f%z "$LOG" 2>/dev/null || echo 0)" -gt 5000000 ] && mv "$LOG" "$LOG.1"
echo "$(TZ=Asia/Jakarta date "+%FT%T WIB") $("$PYTHON" ingest/main.py poll 2>&1 | tail -1)" >> "$LOG"
