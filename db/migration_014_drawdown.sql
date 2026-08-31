-- 014: sustained price collapse, measured from our own series.
--
-- The engine read STACY-SOL as the best opportunity in the book - edge
-- +31.5%/day - while the token was down 83%. During a collapse, panic volume
-- and the dynamic fee send fee/TVL through the roof, so `edge` looks superb
-- exactly when the asset being accumulated is dying.
--
-- The existing `collapsing` signal came from DexScreener and only raised the
-- risk score; it never blocked, and for STACY there was no vendor row at all
-- even though our own prices table held 182 points.

CREATE OR REPLACE VIEW v_drawdown AS
WITH w AS (
    SELECT p.pool, p.ts, p.price,
           first_value(p.price) OVER (PARTITION BY p.pool ORDER BY p.ts) AS first_price,
           last_value(p.price) OVER (PARTITION BY p.pool ORDER BY p.ts
               ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS last_price,
           max(p.price) OVER (PARTITION BY p.pool) AS peak,
           count(*) OVER (PARTITION BY p.pool) AS n
    FROM prices p
    WHERE p.ts > now() - interval '72 hours' AND p.price > 0
)
SELECT DISTINCT pool, n AS n_obs,
       ROUND(((last_price / NULLIF(first_price,0)) - 1) * 100, 1) AS change_72h_pct,
       ROUND(((last_price / NULLIF(peak,0)) - 1) * 100, 1) AS from_peak_pct
FROM w;
