-- 011: the boundary between deciding and executing.
--
-- Python writes intents; a separate process reads them, builds the transaction
-- and (eventually) signs it. The Python side never sees a private key - that is
-- an architectural constraint, not a convention: there is no Python SDK that
-- can build a DLMM position transaction, so the split is forced anyway.

CREATE TABLE IF NOT EXISTS intents (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind         TEXT NOT NULL,          -- open | close | rebalance
    pool         TEXT NOT NULL REFERENCES pools(address),
    position_id  BIGINT REFERENCES paper_positions(id),
    params       JSONB NOT NULL,         -- capital, shape, bins, offset...
    reason       TEXT NOT NULL,
    -- idempotency: one intent per position per decision, per cycle
    dedupe_key   TEXT NOT NULL UNIQUE,

    status       TEXT NOT NULL DEFAULT 'pending',
                 -- pending | simulating | simulated | rejected | sent | confirmed | failed
    picked_at    TIMESTAMPTZ,
    resolved_at  TIMESTAMPTZ,
    sim_units    INT,                    -- compute units the simulation consumed
    sim_logs     TEXT[],
    est_cost_usd NUMERIC,
    signature    TEXT,
    error        TEXT
);
CREATE INDEX IF NOT EXISTS idx_intents_pending ON intents(status, created_at)
    WHERE status = 'pending';

CREATE OR REPLACE VIEW v_intents AS
SELECT i.id, i.created_at, i.kind, po.name AS pool_name, i.pool,
       i.params, i.reason, i.status, i.sim_units, i.est_cost_usd,
       i.error, i.signature,
       ROUND(EXTRACT(EPOCH FROM (COALESCE(i.resolved_at, now()) - i.created_at)), 1) AS age_s
FROM intents i JOIN pools po ON po.address = i.pool
ORDER BY i.created_at DESC;

CREATE OR REPLACE VIEW v_intent_summary AS
SELECT kind, status, count(*) AS n,
       ROUND(AVG(sim_units)) AS avg_compute_units,
       ROUND(SUM(est_cost_usd), 4) AS est_cost_usd
FROM intents GROUP BY kind, status ORDER BY kind, status;
