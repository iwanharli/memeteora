-- 009: the book's capital structure, recorded by the allocator that produced it.
--
-- The alternative was to recompute the split in the web layer from the same
-- constants, but two implementations of one rule drift apart. This is written
-- once per manage cycle by the code that actually did the allocating.

CREATE TABLE IF NOT EXISTS book_state (
    ts            TIMESTAMPTZ PRIMARY KEY DEFAULT now(),
    budget        NUMERIC NOT NULL,
    deployed      NUMERIC NOT NULL,
    rent_locked   NUMERIC NOT NULL,   -- SOL, refunded when positions close
    cash          NUMERIC NOT NULL,
    cash_usdc     NUMERIC NOT NULL,
    cash_sol      NUMERIC NOT NULL,
    idle          NUMERIC NOT NULL,
    sol_price     NUMERIC,
    sleeves       JSONB                -- per-sleeve share, placed, target
);

CREATE OR REPLACE VIEW v_book AS
SELECT * FROM book_state ORDER BY ts DESC LIMIT 1;
