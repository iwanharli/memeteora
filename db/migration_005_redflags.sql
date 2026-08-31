-- 005: red flags. A score demotes a pool; a red flag refuses it.
--
-- Two separate ideas deliberately kept apart:
--   hard flags      - the token or pool can hurt you in ways no yield offsets
--   structural flags- the economics simply do not work at the moment

ALTER TABLE tokens ADD COLUMN IF NOT EXISTS token_program     TEXT;
ALTER TABLE tokens ADD COLUMN IF NOT EXISTS mint_auth_active  BOOLEAN;
ALTER TABLE tokens ADD COLUMN IF NOT EXISTS freeze_auth_active BOOLEAN;
ALTER TABLE tokens ADD COLUMN IF NOT EXISTS extensions        TEXT[];
ALTER TABLE tokens ADD COLUMN IF NOT EXISTS transfer_fee_bps  INT;
ALTER TABLE tokens ADD COLUMN IF NOT EXISTS mint_checked_at   TIMESTAMPTZ;

ALTER TABLE pools ADD COLUMN IF NOT EXISTS blocked       BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE pools ADD COLUMN IF NOT EXISTS block_reasons TEXT[];
ALTER TABLE pools ADD COLUMN IF NOT EXISTS blocked_at    TIMESTAMPTZ;

DROP VIEW IF EXISTS v_quote_only;
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
       p.blocked, p.block_reasons,
       s.risk_flags
FROM scores s JOIN pools p ON p.address = s.pool
ORDER BY s.pool, s.ts DESC;

CREATE VIEW v_quote_only AS
SELECT name, pool, adjusted, risk, fee_day_pct, lvr_daily_pct, edge_lvr_pct, bin_step
FROM v_latest_scores WHERE quote_only_fees AND NOT blocked
ORDER BY edge_lvr_pct DESC NULLS LAST;

-- what you would actually consider deploying into
CREATE OR REPLACE VIEW v_tradeable AS
SELECT * FROM v_latest_scores
WHERE NOT blocked AND edge_lvr_pct > 0 AND turnover >= breakeven_turnover
ORDER BY edge_lvr_pct DESC NULLS LAST;

CREATE OR REPLACE VIEW v_blocked AS
SELECT name, pool, block_reasons, round(risk,1) AS risk,
       round(fee_day_pct,2) AS fee_day_pct, round(edge_lvr_pct,2) AS edge_lvr_pct
FROM v_latest_scores WHERE blocked
ORDER BY fee_day_pct DESC NULLS LAST;
