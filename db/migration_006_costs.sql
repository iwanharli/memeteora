-- 006: the costs a simulator that ignores them will happily hide.
--
-- Position rent is refundable on close, so it is not a loss - but it is capital
-- locked up, and at $100 a position it is 6% of the deployment. Transaction
-- fees are not refundable and scale with how often you rebalance.

ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS rent_sol   NUMERIC NOT NULL DEFAULT 0;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS tx_count   INT     NOT NULL DEFAULT 0;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS gas_sol    NUMERIC NOT NULL DEFAULT 0;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS was_in_range BOOLEAN;

ALTER TABLE paper_marks ADD COLUMN IF NOT EXISTS gas_usd    NUMERIC;
ALTER TABLE paper_marks ADD COLUMN IF NOT EXISTS rent_usd   NUMERIC;
ALTER TABLE paper_marks ADD COLUMN IF NOT EXISTS net_pnl    NUMERIC;

DROP VIEW IF EXISTS v_paper_latest;
CREATE VIEW v_paper_latest AS
SELECT DISTINCT ON (m.position_id)
       p.id, p.pool, po.name, p.strategy, p.shape, p.n_bins,
       p.capital_usd, p.opened_at, p.notes,
       ROUND(EXTRACT(EPOCH FROM (m.ts - p.opened_at))/3600, 1) AS hours_open,
       m.ts AS marked_at, m.price, m.in_range, m.value_usd, m.fees_usd,
       m.hold_usd, m.pnl_vs_hold,
       m.gas_usd, m.rent_usd, m.net_pnl,
       ROUND(m.net_pnl / NULLIF(p.capital_usd,0) * 100, 3) AS pnl_pct,
       p.rebalances, p.tx_count, p.rent_sol, p.gas_sol
FROM paper_positions p
JOIN paper_marks m ON m.position_id = p.id
JOIN pools po ON po.address = p.pool
ORDER BY m.position_id, m.ts DESC;
