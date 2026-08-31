-- 004: paper positions. Validate the engine before any capital is at risk.

CREATE TABLE IF NOT EXISTS paper_positions (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pool          TEXT NOT NULL REFERENCES pools(address),
    strategy      TEXT NOT NULL,        -- why this position exists
    shape         TEXT NOT NULL,        -- spot | curve | bidask
    n_bins        INT  NOT NULL,
    center_bin    INT  NOT NULL,        -- active_id at entry
    capital_usd   NUMERIC NOT NULL,
    entry_price   NUMERIC NOT NULL,     -- quote per base
    opened_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at     TIMESTAMPTZ,
    -- per-bin holdings, {bin_id: [base, quote]}; walked forward on every mark
    bins          JSONB NOT NULL,
    entry_base    NUMERIC NOT NULL,     -- for the hold benchmark
    entry_quote   NUMERIC NOT NULL,
    fees_usd      NUMERIC NOT NULL DEFAULT 0,
    rebalances    INT NOT NULL DEFAULT 0,
    last_active   INT,
    notes         TEXT
);
CREATE INDEX IF NOT EXISTS idx_paper_open ON paper_positions(closed_at) WHERE closed_at IS NULL;

CREATE TABLE IF NOT EXISTS paper_marks (
    position_id   BIGINT NOT NULL REFERENCES paper_positions(id) ON DELETE CASCADE,
    ts            TIMESTAMPTZ NOT NULL,
    price         NUMERIC,
    active_id     INT,
    in_range      BOOLEAN,
    base_amt      NUMERIC,
    quote_amt     NUMERIC,
    value_usd     NUMERIC,       -- position marked to market, fees excluded
    fees_usd      NUMERIC,       -- cumulative
    hold_usd      NUMERIC,       -- same tokens, never deployed
    pnl_vs_hold   NUMERIC,       -- value + fees - hold  <- the only number that matters
    PRIMARY KEY (position_id, ts)
);

CREATE OR REPLACE VIEW v_paper_latest AS
SELECT DISTINCT ON (m.position_id)
       p.id, p.pool, po.name, p.strategy, p.shape, p.n_bins,
       p.capital_usd, p.opened_at,
       ROUND(EXTRACT(EPOCH FROM (m.ts - p.opened_at))/3600, 1) AS hours_open,
       m.ts AS marked_at, m.price, m.in_range, m.value_usd, m.fees_usd,
       m.hold_usd, m.pnl_vs_hold,
       ROUND(m.pnl_vs_hold / NULLIF(p.capital_usd,0) * 100, 3) AS pnl_pct,
       p.rebalances
FROM paper_positions p
JOIN paper_marks m ON m.position_id = p.id
JOIN pools po ON po.address = p.pool
ORDER BY m.position_id, m.ts DESC;
