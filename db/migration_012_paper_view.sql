-- 012: bring v_paper_latest into a migration.
--
-- The bin_step, fee tier and token-composition columns were added to this view
-- by hand during development and never written down, so a fresh deployment got
-- the older definition from migration 007 and the portfolio page failed with
-- "column v.bin_step does not exist". Schema changes only exist if they are in
-- a migration.

DROP VIEW IF EXISTS v_paper_latest;
CREATE VIEW v_paper_latest AS
SELECT DISTINCT ON (m.position_id)
       p.id, p.pool, po.name, p.strategy, p.shape, p.n_bins,
       p.capital_usd, p.opened_at, p.notes, p.closed_at,
       po.bin_step, po.base_fee_pct, po.quote_symbol,
       tb.symbol AS base_symbol,
       ROUND(EXTRACT(EPOCH FROM (m.ts - p.opened_at))/3600, 1) AS hours_open,
       m.ts AS marked_at, m.price, m.in_range, m.value_usd, m.fees_usd,
       m.hold_usd, m.pnl_vs_hold, m.gas_usd, m.rent_usd, m.net_pnl,
       m.base_amt, m.quote_amt,
       ROUND(m.net_pnl / NULLIF(p.capital_usd,0) * 100, 3) AS pnl_pct,
       p.rebalances, p.tx_count, p.rent_sol, p.gas_sol,
       p.out_side, p.exit_reasons, p.exit_urgency,
       ROUND(EXTRACT(EPOCH FROM (m.ts - p.out_since))/3600, 1) AS hours_out
FROM paper_positions p
JOIN paper_marks m ON m.position_id = p.id
JOIN pools po ON po.address = p.pool
LEFT JOIN tokens tb ON tb.mint = po.base_mint
ORDER BY m.position_id, m.ts DESC;

-- ever_in_range was added the same way: a flank deliberately placed outside the
-- range has never "fallen out" of it, and the exit rules need to tell them apart
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS ever_in_range BOOLEAN NOT NULL DEFAULT FALSE;


-- v_closed did not expose the pool address, so the closed table could not link
-- out to the venue for a position it had just shut
DROP VIEW IF EXISTS v_closed;
CREATE VIEW v_closed AS
SELECT p.id, p.pool, po.name, p.strategy, p.shape, p.n_bins, p.capital_usd,
       p.opened_at, p.closed_at,
       ROUND(EXTRACT(EPOCH FROM (p.closed_at - p.opened_at))/3600, 1) AS hours_held,
       p.realized_pnl, p.realized_fees, p.close_reason, p.generation, p.parent_id
FROM paper_positions p JOIN pools po ON po.address = p.pool
WHERE p.closed_at IS NOT NULL
ORDER BY p.closed_at DESC;
