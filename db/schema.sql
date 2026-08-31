-- db_memet : Meteora DLMM pool screening store
-- Design: pools/tokens are slowly-changing dimensions; snapshots are an append-only
-- fact table. Scores are recomputed per snapshot so weight changes can be backtested.

CREATE TABLE IF NOT EXISTS tokens (
    mint                TEXT PRIMARY KEY,
    symbol              TEXT,
    name                TEXT,
    decimals            SMALLINT,
    is_verified         BOOLEAN,
    freeze_disabled     BOOLEAN,
    holders             BIGINT,
    total_supply        NUMERIC,
    first_seen          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pools (
    address             TEXT PRIMARY KEY,
    name                TEXT,
    mint_x              TEXT REFERENCES tokens(mint),
    mint_y              TEXT REFERENCES tokens(mint),
    base_mint           TEXT REFERENCES tokens(mint),   -- the risk-bearing leg
    quote_symbol        TEXT,
    bin_step            INT,
    base_fee_pct        NUMERIC,
    max_fee_pct         NUMERIC,
    protocol_fee_pct    NUMERIC,
    launchpad           TEXT,
    created_at          TIMESTAMPTZ,
    is_blacklisted      BOOLEAN DEFAULT FALSE,
    first_seen          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pools_base ON pools(base_mint);

-- append-only facts; one row per pool per polling cycle
CREATE TABLE IF NOT EXISTS snapshots (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts                  TIMESTAMPTZ NOT NULL,
    pool                TEXT NOT NULL REFERENCES pools(address),
    tvl                 NUMERIC,
    current_price       NUMERIC,
    token_x_amount      NUMERIC,
    token_y_amount      NUMERIC,
    dynamic_fee_pct     NUMERIC,
    base_mcap           NUMERIC,
    base_price          NUMERIC,
    vol_30m NUMERIC, vol_1h NUMERIC, vol_2h NUMERIC,
    vol_4h NUMERIC, vol_12h NUMERIC, vol_24h NUMERIC,
    fee_30m NUMERIC, fee_1h NUMERIC, fee_2h NUMERIC,
    fee_4h NUMERIC, fee_12h NUMERIC, fee_24h NUMERIC,
    ftr_30m NUMERIC, ftr_1h NUMERIC, ftr_2h NUMERIC,
    ftr_4h NUMERIC, ftr_12h NUMERIC, ftr_24h NUMERIC,
    cum_volume          NUMERIC,
    cum_fees            NUMERIC,
    UNIQUE (pool, ts)
);
CREATE INDEX IF NOT EXISTS idx_snap_ts   ON snapshots(ts DESC);
CREATE INDEX IF NOT EXISTS idx_snap_pool ON snapshots(pool, ts DESC);

-- price action pulled from DexScreener for the shortlist (IL side of the trade)
CREATE TABLE IF NOT EXISTS price_action (
    ts                  TIMESTAMPTZ NOT NULL,
    pool                TEXT NOT NULL REFERENCES pools(address),
    price_usd           NUMERIC,
    chg_5m NUMERIC, chg_1h NUMERIC, chg_6h NUMERIC, chg_24h NUMERIC,
    buys_24h INT, sells_24h INT,
    liquidity_usd       NUMERIC,
    fdv                 NUMERIC,
    PRIMARY KEY (pool, ts)
);

-- scores are derived, versioned by weight-set so old runs stay comparable
CREATE TABLE IF NOT EXISTS scores (
    ts                  TIMESTAMPTZ NOT NULL,
    pool                TEXT NOT NULL REFERENCES pools(address),
    weights_version     TEXT NOT NULL,
    opportunity         NUMERIC,        -- 0-100, how good the fee flow is
    risk                NUMERIC,        -- 0-100, how likely you get hurt
    adjusted            NUMERIC,        -- opportunity discounted by risk
    fee_day_pct         NUMERIC,
    floor_pct           NUMERIC,
    cv                  NUMERIC,
    momentum            NUMERIC,
    turnover            NUMERIC,
    il_est_pct          NUMERIC,
    edge_pct            NUMERIC,
    risk_flags          TEXT[],
    PRIMARY KEY (pool, ts, weights_version)
);
CREATE INDEX IF NOT EXISTS idx_scores_adj ON scores(ts DESC, adjusted DESC);

-- latest score per pool, joined to identity
CREATE OR REPLACE VIEW v_latest_scores AS
SELECT DISTINCT ON (s.pool)
       s.ts, p.name, s.pool, s.opportunity, s.risk, s.adjusted,
       s.fee_day_pct, s.floor_pct, s.cv, s.momentum, s.turnover,
       s.il_est_pct, s.edge_pct,
       p.bin_step, p.base_fee_pct, s.risk_flags
FROM scores s JOIN pools p ON p.address = s.pool
ORDER BY s.pool, s.ts DESC;

-- did the pool keep earning after we flagged it? the backtest hook.
CREATE OR REPLACE VIEW v_score_followthrough AS
SELECT s.pool, p.name, s.ts AS scored_at, s.adjusted, s.fee_day_pct AS fee_at_score,
       later.ts AS checked_at,
       ROUND(EXTRACT(EPOCH FROM (later.ts - s.ts))/3600, 1) AS hours_later,
       later.ftr_24h AS fee_later,
       later.tvl AS tvl_later
FROM scores s
JOIN pools p ON p.address = s.pool
JOIN LATERAL (
    SELECT * FROM snapshots n
    WHERE n.pool = s.pool AND n.ts > s.ts
    ORDER BY n.ts DESC LIMIT 1
) later ON TRUE;
