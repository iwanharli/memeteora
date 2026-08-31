//! Row types. Every NUMERIC is cast to float8 in SQL so we avoid a decimal crate
//! and get plain f64 here - screening tolerances are nowhere near that precision.
use chrono::{DateTime, Utc};
use serde::Serialize;

#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct PoolScore {
    pub ts: DateTime<Utc>,
    pub name: String,
    pub pool: String,
    pub opportunity: f64,
    pub risk: f64,
    pub adjusted: f64,
    pub fee_day_pct: Option<f64>,
    pub floor_pct: Option<f64>,
    pub cv: Option<f64>,
    pub momentum: Option<f64>,
    pub turnover: Option<f64>,
    pub il_est_pct: Option<f64>,
    pub edge_pct: Option<f64>,
    pub sigma_daily: Option<f64>,
    pub lvr_daily_pct: Option<f64>,
    pub edge_lvr_pct: Option<f64>,
    pub breakeven_turnover: Option<f64>,
    pub vol_source: Option<String>,
    pub bin_step: Option<i32>,
    pub base_fee_pct: Option<f64>,
    pub quote_only_fees: Option<bool>,
    pub risk_flags: Option<Vec<String>>,
    /// 24h hourly price series, for the sparkline. Empty when the pool is new.
    pub series: Option<Vec<f64>>,
}

#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct PoolDetail {
    pub address: String,
    pub name: Option<String>,
    pub quote_symbol: Option<String>,
    pub bin_step: Option<i32>,
    pub base_fee_pct: Option<f64>,
    pub max_fee_pct: Option<f64>,
    pub created_at: Option<DateTime<Utc>>,
    pub base_symbol: Option<String>,
    pub holders: Option<i64>,
    pub is_verified: Option<bool>,
}

#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct HistoryPoint {
    pub ts: DateTime<Utc>,
    pub tvl: Option<f64>,
    pub fee_day: Option<f64>,
    pub vol_24h: Option<f64>,
    pub adjusted: Option<f64>,
    pub risk: Option<f64>,
    pub price: Option<f64>,
}

#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct Stats {
    pub pools: i64,
    pub snapshots: i64,
    pub last_run: Option<DateTime<Utc>>,
    pub scored: i64,
}

/// Filters coming off the dashboard querystring.
#[derive(Debug, serde::Deserialize)]
pub struct Filters {
    pub max_risk: Option<f64>,
    pub min_opp: Option<f64>,
    pub positive_edge: Option<bool>,
    pub positive_lvr_edge: Option<bool>,
    pub quote_only: Option<bool>,
    pub sort: Option<String>,
    pub limit: Option<i64>,
}

impl Filters {
    pub fn max_risk(&self) -> f64 { self.max_risk.unwrap_or(100.0) }
    pub fn min_opp(&self) -> f64 { self.min_opp.unwrap_or(0.0) }
    pub fn positive_edge(&self) -> bool { self.positive_edge.unwrap_or(false) }
    pub fn positive_lvr_edge(&self) -> bool { self.positive_lvr_edge.unwrap_or(false) }
    pub fn quote_only(&self) -> bool { self.quote_only.unwrap_or(false) }
    pub fn limit(&self) -> i64 { self.limit.unwrap_or(40).clamp(1, 300) }

    /// Whitelisted so the sort key can never reach SQL as user text.
    pub fn order_sql(&self) -> &'static str {
        match self.sort.as_deref() {
            // qualified: the sparkline join brings a second `pool` into scope
            Some("opportunity") => "v.opportunity DESC NULLS LAST",
            Some("risk") => "v.risk ASC NULLS LAST",
            Some("fee") => "v.fee_day_pct DESC NULLS LAST",
            Some("floor") => "v.floor_pct DESC NULLS LAST",
            Some("edge") => "v.edge_pct DESC NULLS LAST",
            Some("edge_lvr") => "v.edge_lvr_pct DESC NULLS LAST",
            Some("lvr") => "v.lvr_daily_pct ASC NULLS LAST",
            Some("sigma") => "v.sigma_daily ASC NULLS LAST",
            _ => "v.adjusted DESC NULLS LAST",
        }
    }
    pub fn sort_key(&self) -> &str { self.sort.as_deref().unwrap_or("adjusted") }
}


/// One simulated position, marked to the latest on-chain price.
#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct PaperPosition {
    pub id: i64,
    pub pool: String,
    pub name: String,
    pub strategy: String,
    pub shape: String,
    pub n_bins: i32,
    pub capital_usd: f64,
    pub opened_at: DateTime<Utc>,
    pub hours_open: Option<f64>,
    pub marked_at: DateTime<Utc>,
    pub price: Option<f64>,
    pub in_range: Option<bool>,
    pub value_usd: Option<f64>,
    pub fees_usd: Option<f64>,
    pub hold_usd: Option<f64>,
    pub pnl_vs_hold: Option<f64>,
    pub gas_usd: Option<f64>,
    pub rent_usd: Option<f64>,
    pub net_pnl: Option<f64>,
    pub pnl_pct: Option<f64>,
    pub rebalances: i32,
    pub tx_count: i32,
    pub notes: Option<String>,
    pub edge_lvr_pct: Option<f64>,
    pub blocked: Option<bool>,
    pub exit_urgency: Option<String>,
    pub exit_reasons: Option<Vec<String>>,
    pub hours_out: Option<f64>,
    pub out_side: Option<String>,
    pub bin_step: Option<i32>,
    pub base_fee_pct: Option<f64>,
    pub base_symbol: Option<String>,
    pub quote_symbol: Option<String>,
    pub base_amt: Option<f64>,
    pub quote_amt: Option<f64>,
    pub center_bin: Option<i32>,
    pub min_bin: Option<i32>,
    pub max_bin: Option<i32>,
    pub min_price: Option<f64>,
    pub max_price: Option<f64>,
    pub active_id: Option<i32>,
}

impl PaperPosition {
    /// Where the price sits inside the range, 0 at the lower bound and 1 at the
    /// upper. Outside those bounds it clamps, and `in_range` says which side.
    pub fn range_position(&self) -> Option<f64> {
        let (lo, hi, p) = (self.min_price?, self.max_price?, self.price?);
        (hi > lo).then(|| ((p - lo) / (hi - lo)).clamp(0.0, 1.0))
    }

    /// What fraction of the position's value currently sits in the base token.
    /// A DLMM position converts as the price walks through its bins, so this is
    /// not the deposit split - it is what the market has made of it since.
    pub fn base_share(&self) -> Option<f64> {
        let (b, q, p) = (self.base_amt?, self.quote_amt?, self.price?);
        let bv = b * p;
        let total = bv + q;
        (total > 0.0).then(|| bv / total)
    }
}

impl PaperPosition {
}


/// A position that has been closed - realised, not marked to market.
#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct ClosedPosition {
    pub id: i64,
    pub pool: String,
    pub name: String,
    pub strategy: String,
    pub shape: String,
    pub n_bins: i32,
    pub capital_usd: f64,
    pub closed_at: DateTime<Utc>,
    pub hours_held: Option<f64>,
    pub realized_pnl: Option<f64>,
    pub realized_fees: Option<f64>,
    pub close_reason: Option<String>,
    pub generation: i32,
}


/// How the budget is split. Written by the allocator, not recomputed here -
/// two implementations of one rule drift apart.
#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct BookState {
    pub ts: DateTime<Utc>,
    pub budget: f64,
    pub deployed: f64,
    pub rent_locked: f64,
    pub cash: f64,
    pub cash_usdc: f64,
    pub cash_sol: f64,
    pub idle: f64,
    pub sol_price: Option<f64>,
}


/// One day of the book: how much it made, in fees, across how many positions.
#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct DailyPnl {
    pub day: chrono::NaiveDate,
    pub pnl: Option<f64>,
    pub fees: Option<f64>,
    pub positions: i64,
}
