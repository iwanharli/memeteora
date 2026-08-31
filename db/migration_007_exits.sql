-- 007: exit signals. Choosing a pool and choosing when to leave one are
-- different jobs; the engine only did the first.

ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS entry_sigma   NUMERIC;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS entry_edge    NUMERIC;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS out_since     TIMESTAMPTZ;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS out_side      TEXT;  -- above | below
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS exit_reasons  TEXT[];
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS exit_urgency  TEXT;  -- none | soft | hard
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS close_reason  TEXT;

DROP VIEW IF EXISTS v_paper_latest;
CREATE VIEW v_paper_latest AS
SELECT DISTINCT ON (m.position_id)
       p.id, p.pool, po.name, p.strategy, p.shape, p.n_bins,
       p.capital_usd, p.opened_at, p.notes, p.closed_at,
       ROUND(EXTRACT(EPOCH FROM (m.ts - p.opened_at))/3600, 1) AS hours_open,
       m.ts AS marked_at, m.price, m.in_range, m.value_usd, m.fees_usd,
       m.hold_usd, m.pnl_vs_hold, m.gas_usd, m.rent_usd, m.net_pnl,
       ROUND(m.net_pnl / NULLIF(p.capital_usd,0) * 100, 3) AS pnl_pct,
       p.rebalances, p.tx_count, p.rent_sol, p.gas_sol,
       p.out_side, p.exit_reasons, p.exit_urgency,
       ROUND(EXTRACT(EPOCH FROM (m.ts - p.out_since))/3600, 1) AS hours_out
FROM paper_positions p
JOIN paper_marks m ON m.position_id = p.id
JOIN pools po ON po.address = p.pool
ORDER BY m.position_id, m.ts DESC;
