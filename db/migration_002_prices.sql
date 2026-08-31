-- 002: price collection + volatility, the inputs LVR needs.

-- High-frequency exact price straight from the LbPair account.
-- One RPC call covers every tracked pool, so this can run far more often
-- than the metrics ingest.
CREATE TABLE IF NOT EXISTS prices (
    pool        TEXT NOT NULL REFERENCES pools(address),
    ts          TIMESTAMPTZ NOT NULL,
    active_id   INT,
    price       NUMERIC,          -- quote per base, decimal-adjusted
    source      TEXT NOT NULL DEFAULT 'onchain',
    PRIMARY KEY (pool, ts)
);
CREATE INDEX IF NOT EXISTS idx_prices_pool_ts ON prices(pool, ts DESC);

-- Backfilled candles, used to seed volatility before our own series matures.
CREATE TABLE IF NOT EXISTS ohlcv (
    pool        TEXT NOT NULL REFERENCES pools(address),
    ts          TIMESTAMPTZ NOT NULL,
    open NUMERIC, high NUMERIC, low NUMERIC, close NUMERIC, volume NUMERIC,
    source      TEXT NOT NULL,
    PRIMARY KEY (pool, ts)
);
CREATE INDEX IF NOT EXISTS idx_ohlcv_pool_ts ON ohlcv(pool, ts DESC);

-- Realised volatility and the LVR floor it implies.
CREATE TABLE IF NOT EXISTS volatility (
    pool          TEXT NOT NULL REFERENCES pools(address),
    ts            TIMESTAMPTZ NOT NULL,
    window_hours  INT NOT NULL,
    sigma_daily   NUMERIC,        -- fraction, e.g. 0.2576 = 25.76%/day
    lvr_daily_pct NUMERIC,        -- sigma^2/8 as a % of TVL per day
    n_obs         INT,
    source        TEXT NOT NULL,  -- 'onchain' | 'dexpaprika' | 'geckoterminal'
    PRIMARY KEY (pool, ts, window_hours)
);
CREATE INDEX IF NOT EXISTS idx_vol_pool_ts ON volatility(pool, ts DESC);

-- LVR is the real cost of providing liquidity; IL was only ever a proxy.
ALTER TABLE scores ADD COLUMN IF NOT EXISTS sigma_daily      NUMERIC;
ALTER TABLE scores ADD COLUMN IF NOT EXISTS lvr_daily_pct    NUMERIC;
ALTER TABLE scores ADD COLUMN IF NOT EXISTS edge_lvr_pct     NUMERIC;
ALTER TABLE scores ADD COLUMN IF NOT EXISTS breakeven_turnover NUMERIC;
ALTER TABLE scores ADD COLUMN IF NOT EXISTS vol_source       TEXT;

DROP VIEW IF EXISTS v_latest_scores;
CREATE VIEW v_latest_scores AS
SELECT DISTINCT ON (s.pool)
       s.ts, p.name, s.pool, s.opportunity, s.risk, s.adjusted,
       s.fee_day_pct, s.floor_pct, s.cv, s.momentum, s.turnover,
       s.il_est_pct, s.edge_pct,
       s.sigma_daily, s.lvr_daily_pct, s.edge_lvr_pct,
       s.breakeven_turnover, s.vol_source,
       p.bin_step, p.base_fee_pct, s.risk_flags
FROM scores s JOIN pools p ON p.address = s.pool
ORDER BY s.pool, s.ts DESC;

-- How much price history do we have per pool yet?
CREATE OR REPLACE VIEW v_price_coverage AS
SELECT p.address, p.name,
       count(pr.ts)                                   AS points,
       min(pr.ts)                                     AS first_point,
       max(pr.ts)                                     AS last_point,
       ROUND(EXTRACT(EPOCH FROM (max(pr.ts) - min(pr.ts)))/3600, 1) AS span_hours
FROM pools p LEFT JOIN prices pr ON pr.pool = p.address
GROUP BY p.address, p.name;
