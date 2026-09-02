-- 017: fees measured from the chain's own accumulators, at paper size.
--
-- Until now fee_accrual() projected a pool-wide rate onto our capital. The
-- rate was real - Meteora's fee/TVL over 24h - but it was an average dollar's
-- return over a whole day, applied to a position marked every two minutes.
--
-- The DLMM program itself settles a claim as
--
--     claimable = (bin.feeAmountPerTokenStored - checkpoint) * liquidity_share
--
-- and both terms on the right are readable on chain. So we store the
-- accumulator per bin, checkpoint it per position, and multiply the delta by
-- the share our paper liquidity WOULD have held. The numerator is the fee the
-- pool actually earned; only the size of the position is hypothetical.
--
-- The modelled figure is kept alongside rather than replaced. Switching the
-- series mid-flight would leave one column half-modelled and half-measured,
-- and the two need to be compared before either is trusted.

CREATE TABLE IF NOT EXISTS bin_fees (
    pool             TEXT        NOT NULL,
    bin_id           INTEGER     NOT NULL,
    ts               TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- u128 accumulators, Q64.64. NUMERIC because they overflow bigint and the
    -- delta must stay exact: a float64 loses the low bits that a two-minute
    -- interval actually moves.
    fee_x_per_token  NUMERIC     NOT NULL,
    fee_y_per_token  NUMERIC     NOT NULL,
    liquidity_supply NUMERIC     NOT NULL,
    amount_x         NUMERIC     NOT NULL,
    amount_y         NUMERIC     NOT NULL,
    PRIMARY KEY (pool, bin_id)
);

CREATE INDEX IF NOT EXISTS bin_fees_ts ON bin_fees (ts);

-- Where each position last settled. Rows appear only for bins the position
-- actually holds liquidity in, so a 1099-bin position costs 1099 rows and a
-- narrow one costs a handful.
CREATE TABLE IF NOT EXISTS paper_fee_checkpoints (
    position_id     BIGINT      NOT NULL REFERENCES paper_positions(id) ON DELETE CASCADE,
    bin_id          INTEGER     NOT NULL,
    fee_x_per_token NUMERIC     NOT NULL,
    fee_y_per_token NUMERIC     NOT NULL,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (position_id, bin_id)
);

-- Running totals, in the same shape as fees_usd so the two can be read side by
-- side. claim_x/claim_y are raw token amounts: what a claimFee call would have
-- transferred, before any price is applied.
ALTER TABLE paper_positions
    ADD COLUMN IF NOT EXISTS claim_x         NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS claim_y         NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS claim_fees_usd  NUMERIC NOT NULL DEFAULT 0,
    -- null until the first sync covers the position; distinguishes "measured
    -- zero fees" from "never measured"
    ADD COLUMN IF NOT EXISTS claim_synced_at TIMESTAMPTZ;

ALTER TABLE paper_marks
    ADD COLUMN IF NOT EXISTS claim_fees_usd NUMERIC,
    ADD COLUMN IF NOT EXISTS claim_net_pnl  NUMERIC;

-- Expose both fee series side by side. claim_ratio is the number to watch
-- while the two run in parallel: 1.0 means the model was right, and a
-- persistent departure from 1.0 says which way it was wrong.
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
       m.claim_fees_usd, m.claim_net_pnl,
       p.claim_x, p.claim_y, p.claim_synced_at,
       ROUND(m.claim_fees_usd / NULLIF(m.fees_usd,0), 3) AS claim_ratio,
       ROUND(m.claim_net_pnl / NULLIF(p.capital_usd,0) * 100, 3) AS claim_pnl_pct,
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
