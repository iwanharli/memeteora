-- 008: acting on the signals, not just raising them.

ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS realized_pnl  NUMERIC;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS realized_fees NUMERIC;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS parent_id     BIGINT REFERENCES paper_positions(id);
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS generation    INT NOT NULL DEFAULT 0;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS auto          BOOLEAN NOT NULL DEFAULT FALSE;

-- an append-only journal: what was done, when, why, and what it cost
CREATE TABLE IF NOT EXISTS actions (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind        TEXT NOT NULL,          -- open | close | rebalance | add
    position_id BIGINT REFERENCES paper_positions(id),
    new_position_id BIGINT REFERENCES paper_positions(id),
    pool        TEXT REFERENCES pools(address),
    reason      TEXT NOT NULL,
    capital_usd NUMERIC,
    pnl_usd     NUMERIC,
    gas_usd     NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_actions_ts ON actions(ts DESC);

CREATE OR REPLACE VIEW v_closed AS
SELECT p.id, po.name, p.strategy, p.shape, p.n_bins, p.capital_usd,
       p.opened_at, p.closed_at,
       ROUND(EXTRACT(EPOCH FROM (p.closed_at - p.opened_at))/3600, 1) AS hours_held,
       p.realized_pnl, p.realized_fees, p.close_reason, p.generation, p.parent_id
FROM paper_positions p JOIN pools po ON po.address = p.pool
WHERE p.closed_at IS NOT NULL
ORDER BY p.closed_at DESC;

-- did acting on the signal actually help?
CREATE OR REPLACE VIEW v_action_summary AS
SELECT kind, count(*) AS n,
       ROUND(SUM(pnl_usd), 2) AS realized_pnl,
       ROUND(SUM(gas_usd), 3) AS gas,
       ROUND(AVG(pnl_usd), 2) AS avg_pnl
FROM actions GROUP BY kind ORDER BY kind;
