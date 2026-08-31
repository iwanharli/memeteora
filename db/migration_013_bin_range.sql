-- 013: expose the bin range a position actually occupies.
--
-- n_bins alone does not say where the position sits. The bin ids and, more
-- usefully, the prices they correspond to are what let you check a position
-- against the chart: price = (1 + bin_step/1e4)^bin_id, adjusted for decimals.

DROP VIEW IF EXISTS v_paper_latest;
CREATE VIEW v_paper_latest AS
SELECT DISTINCT ON (m.position_id)
       p.id, p.pool, po.name, p.strategy, p.shape, p.n_bins,
       p.capital_usd, p.opened_at, p.notes, p.closed_at,
       po.bin_step, po.base_fee_pct, po.quote_symbol,
       tb.symbol AS base_symbol,
       p.center_bin,
       p.center_bin - p.n_bins / 2 AS min_bin,
       p.center_bin + p.n_bins / 2 AS max_bin,
       power(1 + po.bin_step / 10000.0, p.center_bin - p.n_bins / 2)
         * power(10, tx.decimals - ty.decimals) AS min_price,
       power(1 + po.bin_step / 10000.0, p.center_bin + p.n_bins / 2)
         * power(10, tx.decimals - ty.decimals) AS max_price,
       ROUND(EXTRACT(EPOCH FROM (m.ts - p.opened_at))/3600, 1) AS hours_open,
       m.ts AS marked_at, m.price, m.active_id, m.in_range, m.value_usd, m.fees_usd,
       m.hold_usd, m.pnl_vs_hold, m.gas_usd, m.rent_usd, m.net_pnl,
       m.base_amt, m.quote_amt,
       ROUND(m.net_pnl / NULLIF(p.capital_usd,0) * 100, 3) AS pnl_pct,
       p.rebalances, p.tx_count, p.rent_sol, p.gas_sol,
       p.out_side, p.exit_reasons, p.exit_urgency,
       ROUND(EXTRACT(EPOCH FROM (m.ts - p.out_since))/3600, 1) AS hours_out
FROM paper_positions p
JOIN paper_marks m ON m.position_id = p.id
JOIN pools po ON po.address = p.pool
JOIN tokens tx ON tx.mint = po.mint_x
JOIN tokens ty ON ty.mint = po.mint_y
LEFT JOIN tokens tb ON tb.mint = po.base_mint
ORDER BY m.position_id, m.ts DESC;
