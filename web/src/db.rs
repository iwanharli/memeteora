//! Queries against db_memet. Read-only: the Python worker owns all writes.
use anyhow::Result;
use sqlx::postgres::{PgPool, PgPoolOptions};

use crate::models::{Filters, HistoryPoint, PoolDetail, PoolScore, Stats};

pub async fn pool(url: &str) -> Result<PgPool> {
    Ok(PgPoolOptions::new().max_connections(5).connect(url).await?)
}

pub async fn latest_scores(db: &PgPool, f: &Filters) -> Result<Vec<PoolScore>> {
    // order_sql() is a fixed whitelist, never user text
    let sql = format!(
        "SELECT ts, name, pool,
                opportunity::float8   AS opportunity,
                risk::float8          AS risk,
                adjusted::float8      AS adjusted,
                fee_day_pct::float8   AS fee_day_pct,
                floor_pct::float8     AS floor_pct,
                cv::float8            AS cv,
                momentum::float8      AS momentum,
                turnover::float8      AS turnover,
                il_est_pct::float8    AS il_est_pct,
                edge_pct::float8      AS edge_pct,
                sigma_daily::float8       AS sigma_daily,
                lvr_daily_pct::float8     AS lvr_daily_pct,
                edge_lvr_pct::float8      AS edge_lvr_pct,
                breakeven_turnover::float8 AS breakeven_turnover,
                vol_source,
                bin_step,
                base_fee_pct::float8  AS base_fee_pct,
                quote_only_fees,
                risk_flags
         FROM v_latest_scores
         WHERE risk <= $1 AND opportunity >= $2
           AND ($3 = FALSE OR edge_pct > 0)
           AND ($4 = FALSE OR edge_lvr_pct > 0)
           AND ($5 = FALSE OR quote_only_fees)
         ORDER BY {} LIMIT $6",
        f.order_sql()
    );
    Ok(sqlx::query_as::<_, PoolScore>(&sql)
        .bind(f.max_risk())
        .bind(f.min_opp())
        .bind(f.positive_edge())
        .bind(f.positive_lvr_edge())
        .bind(f.quote_only())
        .bind(f.limit())
        .fetch_all(db)
        .await?)
}

pub async fn pool_detail(db: &PgPool, addr: &str) -> Result<Option<PoolDetail>> {
    Ok(sqlx::query_as::<_, PoolDetail>(
        "SELECT p.address, p.name, p.quote_symbol, p.bin_step,
                p.base_fee_pct::float8 AS base_fee_pct,
                p.max_fee_pct::float8  AS max_fee_pct,
                p.created_at,
                t.symbol AS base_symbol, t.holders, t.is_verified
         FROM pools p LEFT JOIN tokens t ON t.mint = p.base_mint
         WHERE p.address = $1",
    )
    .bind(addr)
    .fetch_optional(db)
    .await?)
}

pub async fn latest_score_for(db: &PgPool, addr: &str) -> Result<Option<PoolScore>> {
    Ok(sqlx::query_as::<_, PoolScore>(
        "SELECT ts, name, pool, opportunity::float8 AS opportunity, risk::float8 AS risk,
                adjusted::float8 AS adjusted, fee_day_pct::float8 AS fee_day_pct,
                floor_pct::float8 AS floor_pct, cv::float8 AS cv,
                momentum::float8 AS momentum, turnover::float8 AS turnover,
                il_est_pct::float8 AS il_est_pct, edge_pct::float8 AS edge_pct,
                sigma_daily::float8 AS sigma_daily, lvr_daily_pct::float8 AS lvr_daily_pct,
                edge_lvr_pct::float8 AS edge_lvr_pct,
                breakeven_turnover::float8 AS breakeven_turnover, vol_source,
                bin_step, base_fee_pct::float8 AS base_fee_pct, quote_only_fees, risk_flags
         FROM v_latest_scores WHERE pool = $1",
    )
    .bind(addr)
    .fetch_optional(db)
    .await?)
}

pub async fn history(db: &PgPool, addr: &str, limit: i64) -> Result<Vec<HistoryPoint>> {
    Ok(sqlx::query_as::<_, HistoryPoint>(
        "SELECT s.ts,
                s.tvl::float8      AS tvl,
                s.ftr_24h::float8  AS fee_day,
                s.vol_24h::float8  AS vol_24h,
                sc.adjusted::float8 AS adjusted,
                sc.risk::float8     AS risk,
                pa.price_usd::float8 AS price
         FROM snapshots s
         LEFT JOIN scores sc ON sc.pool = s.pool AND sc.ts = s.ts
         LEFT JOIN price_action pa ON pa.pool = s.pool AND pa.ts = s.ts
         WHERE s.pool = $1
         ORDER BY s.ts DESC LIMIT $2",
    )
    .bind(addr)
    .bind(limit)
    .fetch_all(db)
    .await?)
}

pub async fn stats(db: &PgPool) -> Result<Stats> {
    Ok(sqlx::query_as::<_, Stats>(
        "SELECT (SELECT count(*) FROM pools)     AS pools,
                (SELECT count(*) FROM snapshots) AS snapshots,
                (SELECT max(ts)  FROM snapshots) AS last_run,
                (SELECT count(*) FROM v_latest_scores) AS scored",
    )
    .fetch_one(db)
    .await?)
}


pub async fn paper_positions(db: &PgPool) -> Result<Vec<crate::models::PaperPosition>> {
    Ok(sqlx::query_as::<_, crate::models::PaperPosition>(
        "SELECT v.id, v.pool, v.name, v.strategy, v.shape, v.n_bins,
                v.capital_usd::float8   AS capital_usd,
                v.opened_at,
                v.hours_open::float8    AS hours_open,
                v.marked_at,
                v.price::float8         AS price,
                v.in_range,
                v.value_usd::float8     AS value_usd,
                v.fees_usd::float8      AS fees_usd,
                v.hold_usd::float8      AS hold_usd,
                v.pnl_vs_hold::float8   AS pnl_vs_hold,
                v.gas_usd::float8       AS gas_usd,
                v.rent_usd::float8      AS rent_usd,
                v.net_pnl::float8       AS net_pnl,
                v.pnl_pct::float8       AS pnl_pct,
                v.rebalances,
                v.tx_count,
                p.notes,
                s.edge_lvr_pct::float8  AS edge_lvr_pct,
                s.blocked,
                v.exit_urgency, v.exit_reasons,
                v.hours_out::float8 AS hours_out, v.out_side,
                v.bin_step, v.base_fee_pct::float8 AS base_fee_pct,
                v.base_symbol, v.quote_symbol,
                v.base_amt::float8 AS base_amt, v.quote_amt::float8 AS quote_amt,
                v.center_bin, v.min_bin, v.max_bin,
                v.min_price::float8 AS min_price, v.max_price::float8 AS max_price,
                v.active_id
         FROM v_paper_latest v
         JOIN paper_positions p ON p.id = v.id
         LEFT JOIN v_latest_scores s ON s.pool = v.pool
         WHERE v.closed_at IS NULL
         ORDER BY v.strategy, v.pnl_pct DESC NULLS LAST",
    )
    .fetch_all(db)
    .await?)
}


pub async fn closed_positions(db: &PgPool, limit: i64)
    -> Result<Vec<crate::models::ClosedPosition>> {
    Ok(sqlx::query_as::<_, crate::models::ClosedPosition>(
        "SELECT id, pool, name, strategy, shape, n_bins,
                capital_usd::float8   AS capital_usd,
                closed_at,
                hours_held::float8    AS hours_held,
                realized_pnl::float8  AS realized_pnl,
                realized_fees::float8 AS realized_fees,
                close_reason, generation
         FROM v_closed LIMIT $1",
    )
    .bind(limit)
    .fetch_all(db)
    .await?)
}


pub async fn book_state(db: &PgPool) -> Result<Option<crate::models::BookState>> {
    Ok(sqlx::query_as::<_, crate::models::BookState>(
        "SELECT ts, budget::float8 AS budget, deployed::float8 AS deployed,
                rent_locked::float8 AS rent_locked, cash::float8 AS cash,
                cash_usdc::float8 AS cash_usdc, cash_sol::float8 AS cash_sol,
                idle::float8 AS idle, sol_price::float8 AS sol_price
         FROM v_book",
    )
    .fetch_optional(db)
    .await?)
}
