#!/bin/bash
# Wrapper for the scheduler. Serialises runs, keeps one rotating log,
# and never lets a stuck cycle stack up behind the next one.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$ROOT/logs/ingest.log"
LOCK="$ROOT/logs/.ingest.lock"
mkdir -p "$ROOT/logs"

# mkdir is atomic on every filesystem we care about; macOS has no flock(1)
if ! mkdir "$LOCK" 2>/dev/null; then
    if [ -f "$LOCK/pid" ] && ! kill -0 "$(cat "$LOCK/pid")" 2>/dev/null; then
        echo "$(TZ=Asia/Jakarta date "+%FT%T WIB") clearing stale lock" >> "$LOG"
        rm -rf "$LOCK"; mkdir "$LOCK" || exit 0
    else
        echo "$(TZ=Asia/Jakarta date "+%FT%T WIB") previous run still going, skipping" >> "$LOG"
        exit 0
    fi
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

# keep the log from growing without bound
if [ -f "$LOG" ] && [ "$(stat -f%z "$LOG" 2>/dev/null || echo 0)" -gt 5000000 ]; then
    mv "$LOG" "$LOG.1"
fi

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
start=$(date +%s)
# metrics, then candles for anything with no recent history, then sigma/LVR.
# backfill is skipped unless something is actually missing, so it costs nothing
# once coverage is established.
out=$("$PYTHON" ingest/main.py ingest 2>&1)
rc=$?
back=$("$PYTHON" ingest/main.py backfill --limit 25 2>&1 | tail -1)
vol=$("$PYTHON" ingest/main.py volatility 2>&1 | tail -1)
echo "$(TZ=Asia/Jakarta date "+%FT%T WIB") rc=$rc $(( $(date +%s) - start ))s ${out} | ${back} | ${vol}" >> "$LOG"
exit $rc
