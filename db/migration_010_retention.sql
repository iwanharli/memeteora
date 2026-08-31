-- 010: retention. Faster polling is only safe if the raw series is bounded.
--
-- Volatility is computed over a 72h window, so raw prices older than that are
-- only useful for auditing. Keep a week, then drop - and keep an hourly roll-up
-- indefinitely so long-horizon questions remain answerable.

CREATE TABLE IF NOT EXISTS prices_hourly (
    pool      TEXT NOT NULL REFERENCES pools(address),
    hour      TIMESTAMPTZ NOT NULL,
    open      NUMERIC, high NUMERIC, low NUMERIC, close NUMERIC,
    n_obs     INT,
    PRIMARY KEY (pool, hour)
);

CREATE OR REPLACE FUNCTION roll_up_prices() RETURNS void AS $$
BEGIN
    INSERT INTO prices_hourly (pool, hour, open, high, low, close, n_obs)
    SELECT pool, date_trunc('hour', ts) AS hour,
           (array_agg(price ORDER BY ts))[1],
           max(price), min(price),
           (array_agg(price ORDER BY ts DESC))[1],
           count(*)
    FROM prices
    WHERE ts < date_trunc('hour', now())
    GROUP BY pool, date_trunc('hour', ts)
    ON CONFLICT (pool, hour) DO UPDATE
      SET high = GREATEST(prices_hourly.high, EXCLUDED.high),
          low  = LEAST(prices_hourly.low, EXCLUDED.low),
          close = EXCLUDED.close, n_obs = EXCLUDED.n_obs;

    DELETE FROM prices WHERE ts < now() - interval '7 days';
END;
$$ LANGUAGE plpgsql;
