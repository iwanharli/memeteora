-- 015: daily PnL, so the book can be watched day by day rather than only as a
-- running total.
--
-- Computed per position and then summed, not as a difference of book totals:
-- positions open and close on any day, and differencing the total would read
-- an opening as a gain and a closing as a loss.

CREATE OR REPLACE VIEW v_daily_pnl AS
WITH eod AS (
    -- last mark of each day, per position, in the display timezone
    SELECT DISTINCT ON (position_id, day)
           position_id, day, net_pnl, fees_usd
    FROM (SELECT position_id, ts,
                 (ts AT TIME ZONE 'Asia/Jakarta')::date AS day,
                 -- net_pnl was added later, so the earliest marks have none
                 COALESCE(net_pnl, pnl_vs_hold, 0) AS net_pnl,
                 COALESCE(fees_usd, 0) AS fees_usd
          FROM paper_marks) x
    ORDER BY position_id, day, ts DESC
), delta AS (
    SELECT day, position_id,
           net_pnl  - COALESCE(lag(net_pnl)  OVER (PARTITION BY position_id ORDER BY day), 0) AS d_pnl,
           fees_usd - COALESCE(lag(fees_usd) OVER (PARTITION BY position_id ORDER BY day), 0) AS d_fees
    FROM eod
)
SELECT day,
       ROUND(SUM(d_pnl), 4)  AS pnl,
       ROUND(SUM(d_fees), 4) AS fees,
       COUNT(*)              AS positions
FROM delta
GROUP BY day
ORDER BY day;
