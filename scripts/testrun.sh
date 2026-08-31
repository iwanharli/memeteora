#!/bin/bash
# One-position live-path test on a small budget.
#
# Everything here is dry-run: intents are queued, the executor builds the real
# transaction and simulates it against mainnet, and nothing is signed or sent.
# The reserve parameters are relaxed because they are sized for a real book -
# at $88 the standard $66.67 cash floor consumes the budget before a single
# position can be opened.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

: "${WALLET_PUBKEY:?set WALLET_PUBKEY to your wallet address (public key only)}"
BUDGET="${BUDGET:-88}"

export MEMET_GAS_BUFFER="${MEMET_GAS_BUFFER:-3}"
export MEMET_MAX_RENT_SHARE="${MEMET_MAX_RENT_SHARE:-0.10}"
export MEMET_DSN="${MEMET_DSN:-dbname=db_memet}"
export DATABASE_URL="${DATABASE_URL:-postgres:///db_memet}"

PYTHON="${MEMET_PYTHON:-python3}"

echo "== refreshing prices"
"$PYTHON" ingest/main.py poll

echo "== planning a \$$BUDGET book and queueing intents"
"$PYTHON" ingest/main.py manage --budget "$BUDGET" --max-positions 1 \
    --posture stability --emit-intents

echo "== queued"
psql -d db_memet -c "SELECT id, kind, pool_name, status, (params->>'capital_usd')::numeric AS usd FROM v_intents WHERE status='pending';"

echo "== simulating (builds real transactions, signs nothing)"
cd exec && npx tsx src/index.ts --dry-run --once

echo "== results"
psql -d db_memet -c "SELECT id, kind, pool_name, status, sim_units, LEFT(COALESCE(error,'-'),64) AS detail FROM v_intents LIMIT 5;"
