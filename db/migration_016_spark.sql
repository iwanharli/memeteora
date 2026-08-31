-- 016: a 24-hour price series per pool, downsampled for drawing.
--
-- Every pool already has one in `prices`; nothing on the screener used it. A
-- sparkline answers at a glance what a volatility number cannot: whether the
-- pool is drifting, ranging, or falling off a cliff - which is exactly the
-- distinction the collapse red flag exists to catch.

CREATE OR REPLACE VIEW v_spark AS
WITH b AS (
    SELECT pool,
           -- 24 buckets, one per hour, so every pool yields the same shape
           date_trunc('hour', ts) AS bucket,
           avg(price) AS price
    FROM prices
    WHERE ts > now() - interval '24 hours' AND price > 0
    GROUP BY pool, date_trunc('hour', ts)
)
SELECT pool,
       array_agg(price ORDER BY bucket)::float8[] AS series,
       count(*) AS points,
       min(price) AS lo,
       max(price) AS hi
FROM b GROUP BY pool;
