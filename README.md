# memet

Meteora DLMM pool screener. Ranks pools by *durable* fee generation discounted
by risk — not by headline APR, which is the fastest route into the pools that
hurt most.

Python worker writes, Rust web layer reads. Postgres (`db_memet`) is the only
thing between them.

```
ingest (Python, cron)  ──writes──▶  db_memet  ◀──reads──  web (Rust/Axum)
```

## Layout

```
db/schema.sql      tables + views
ingest/            Python worker: fetch, gate, score, persist
  sources.py         Meteora datapi + DexScreener
  onchain.py         exact price from the LbPair account - 100% coverage, 1 RPC call
  ohlcv.py           vendor candles: DexPaprika -> GeckoTerminal fallback
  volatility.py      realised sigma, LVR, breakeven turnover
  gates.py           hard filters (remove, never score)
  scoring.py         opportunity + risk, kept separate
  db.py              upserts and bulk inserts
  main.py            CLI: poll | ingest | backfill | volatility | top | history
exec/              TypeScript executor: builds and simulates transactions, never signs
web/               Rust read layer
  src/db.rs          queries (read-only)
  src/models.rs      row types, querystring filters
  src/routes/        dashboard, pool detail, JSON api
  src/views/         maud templates + CSS
```

## Setup

```bash
createdb db_memet
psql -f db/schema.sql db_memet
pip install -r ingest/requirements.txt
```

## Run

```bash
python3 ingest/main.py ingest        # one cycle: fetch, score, persist
python3 ingest/main.py top --limit 20
python3 ingest/main.py history <pool_address>

cd web && cargo run --release        # http://127.0.0.1:8080
```

Config via env (see `.env.example`): `MEMET_DSN` for Python,
`DATABASE_URL` + `BIND_ADDR` for Rust.

## Scheduling

Snapshots only become useful in series — one snapshot tells you nothing about
persistence. A cycle costs ~5s and ~6 API calls, so cadence is limited by what
the data can tell you, not by cost.

### pm2 (portable - use this on a VPS)

`worker` is a single long-running process that runs both cadences on a
wall-clock grid and logs one line per tick to stdout. It never daemonises and
never writes its own log files, so pm2 (or systemd, or docker) owns the
lifecycle.

```bash
cargo build --release --manifest-path web/Cargo.toml
pm2 start ecosystem.config.js
pm2 logs memet-worker
pm2 save && pm2 startup      # survive reboot
```

| Task inside the worker | Every | Cost |
|---|---|---|
| `poll` | 5 min (`--poll-interval`) | 1 RPC call, ~1s |
| `pipeline` (ingest + backfill + volatility) | 15 min (`--ingest-interval`) | ~6s |

Run exactly one worker. Two would double-write every snapshot and skew the
series. On SIGTERM it finishes the current tick and exits 0.

### launchd (macOS only, alternative)

```bash
./scripts/install_scheduler.sh
tail -f logs/ingest.log logs/poll.log
for L in ingest poll; do launchctl bootout gui/$(id -u)/com.memet.$L; done   # remove
```

Do not run the launchd agents and the pm2 worker at the same time.

## Where volatility comes from

No vendor indexes every Meteora pool. Measured over 73 gated pools:
DexPaprika 71% (the rest are genuine 404s), GeckoTerminal covers a *different*
subset, and the two together reach ~99% with backoff. The on-chain LbPair
account reaches **100% in a single `getMultipleAccounts` call**, so vendor
candles are only a seed: once `poll` has ~24h of history, sigma is computed
from our own series and the vendors stop mattering.

15 minutes is the default because the shortest metric window Meteora exposes is
30m — two samples per window. Faster buys little: consecutive `ftr_24h` values
15 min apart already share 96% of their underlying window.

**Consequence for analysis:** rolling-window snapshots are heavily
autocorrelated. When backtesting against `v_score_followthrough`, compare points
at least 24h apart, or you are measuring the same trades several dozen times and
mistaking it for confirmation.

## Reading the numbers

| Column | Meaning |
|---|---|
| `opportunity` | 0–100, quality and durability of the fee flow |
| `risk` | 0–100, how likely the pool hurts you; see `risk_flags` |
| `adjusted` | `opportunity × (1 − risk/100)` — the ranking column |
| `fee/d` | today's fees as % of TVL |
| `floor` | worst of six windows (30m…24h) as a daily rate — the conservative read |
| `cv` | dispersion across those windows; low = steady, high = one hot hour |
| `sigma` | realised daily volatility, from real timestamps (irregular sampling is handled) |
| `LVR` | `sigma²/8` — the adverse-selection cost, in % of TVL per day |
| `EDGE` | `fee/d − LVR`. **The column that decides profit.** |
| `brkevn` | turnover needed to cover LVR at this fee tier |
| `Q` | fees paid in the quote token only (`collect_fee_mode = 1`) |

Risk prices volatility as LVR, not impermanent loss. IL compares two endpoints
and is blind to the path taken between them, which is exactly where LPs get
charged; on this pool set the two disagreed in direction often enough that IL
was actively misleading. `il_est_pct` is still recorded so older rows stay
readable, but nothing reads it.

Opportunity and risk stay separate on purpose. A pool can be genuinely
lucrative and genuinely dangerous at once; collapsing that into one number
hides the thing you need in order to decide.

## Caveats

- `risk` correlates −0.55 with EDGE, so it earns its place. `opportunity` does
  not (r ≈ −0.04) — its weights are still untested judgement. Rank by EDGE.
  `v_score_followthrough` exists to fix this once there is enough history.
- sigma comes from vendor candles until `poll` has ~2h of its own history per
  pool; `vol_source` says which was used for every row.
- LVR's sigma²/8 is derived for a constant-product pool. For a concentrated
  position both fee income and LVR scale with the same concentration factor,
  so the sign of EDGE holds but the magnitude does not.
- Estimates from public data. Not investment advice.
