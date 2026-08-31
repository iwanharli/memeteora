-- 003: collect_fee_mode, and LVR-based risk.
--
-- collect_fee_mode = 1 means fees accrue only in the quote token. In a
-- memecoin pool that is the difference between income and more exposure to
-- the asset you are already forced to accumulate.

ALTER TABLE pools ADD COLUMN IF NOT EXISTS collect_fee_mode SMALLINT;

DROP VIEW IF EXISTS v_latest_scores;
CREATE VIEW v_latest_scores AS
SELECT DISTINCT ON (s.pool)
       s.ts, p.name, s.pool, s.opportunity, s.risk, s.adjusted,
       s.fee_day_pct, s.floor_pct, s.cv, s.momentum, s.turnover,
       s.il_est_pct, s.edge_pct,
       s.sigma_daily, s.lvr_daily_pct, s.edge_lvr_pct,
       s.breakeven_turnover, s.vol_source,
       p.bin_step, p.base_fee_pct, p.collect_fee_mode,
       (p.collect_fee_mode = 1) AS quote_only_fees,
       s.risk_flags
FROM scores s JOIN pools p ON p.address = s.pool
ORDER BY s.pool, s.ts DESC;

-- Pools where fees are paid in the quote leg only.
CREATE OR REPLACE VIEW v_quote_only AS
SELECT name, pool, adjusted, risk, fee_day_pct, lvr_daily_pct, edge_lvr_pct, bin_step
FROM v_latest_scores
WHERE quote_only_fees
ORDER BY edge_lvr_pct DESC NULLS LAST;
