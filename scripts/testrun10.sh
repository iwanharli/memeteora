#!/bin/bash
# Smallest possible live-path test: one 10 USDC position, entirely below the
# active price, so no SOL is needed for the liquidity itself.
#
# The economics are terrible on purpose - $5.91 of rent against $10 of capital -
# because this validates plumbing, not strategy. Nothing is signed or sent.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

: "${WALLET_PUBKEY:?set WALLET_PUBKEY to your wallet address (public key only)}"
USDC="${USDC:-10}"
POOL="${POOL:-}"
export DATABASE_URL="${DATABASE_URL:-postgres:///db_memet}"
PYTHON="${MEMET_PYTHON:-python3}"

# the deepest SOL-USDC pool: the safest thing to point a first test at
if [ -z "$POOL" ]; then
  POOL=$(psql -d db_memet -tAc "
    SELECT p.address FROM pools p
    JOIN LATERAL (SELECT tvl FROM snapshots s WHERE s.pool=p.address
                  ORDER BY ts DESC LIMIT 1) s ON TRUE
    WHERE p.name='SOL-USDC' ORDER BY s.tvl DESC LIMIT 1")
fi
NAME=$(psql -d db_memet -tAc "SELECT name||' BS'||bin_step FROM pools WHERE address='$POOL'")
echo "== pool: $NAME"
echo "== $USDC USDC, one-sided below the active bin (quote only)"

"$PYTHON" ingest/main.py poll >/dev/null

psql -d db_memet -q -c "
INSERT INTO intents (kind, pool, params, reason, dedupe_key)
VALUES ('open', '$POOL',
        jsonb_build_object('capital_usd', ${USDC}::numeric, 'shape','spot',
                           'bins', 30, 'side','quote'),
        'manual test: one-sided USDC below price',
        'testrun10-'||to_char(now(),'YYYYMMDDHH24MI'))
ON CONFLICT (dedupe_key) DO NOTHING;"

cd exec && npx tsx src/index.ts --dry-run --once

cd "$ROOT"
psql -d db_memet -c "
SELECT id, kind, pool_name, status, sim_units,
       ROUND(est_cost_usd::numeric,4) AS fee_usd,
       LEFT(COALESCE(error,'-'),58) AS detail
FROM v_intents WHERE reason LIKE 'manual test%' LIMIT 3;"
