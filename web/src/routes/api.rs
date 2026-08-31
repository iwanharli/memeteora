//! JSON mirror of the dashboard, for scripting against the same filters.
use axum::extract::{Path, Query, State};
use axum::Json;
use serde_json::json;

use crate::models::Filters;
use crate::routes::AppError;
use crate::{db, AppState};

pub async fn scores(
    State(st): State<AppState>,
    Query(fl): Query<Filters>,
) -> Result<Json<serde_json::Value>, AppError> {
    let rows = db::latest_scores(&st.db, &fl).await?;
    let stats = db::stats(&st.db).await?;
    Ok(Json(json!({ "last_run": stats.last_run, "count": rows.len(), "pools": rows })))
}

pub async fn history(
    State(st): State<AppState>,
    Path(addr): Path<String>,
) -> Result<Json<serde_json::Value>, AppError> {
    let hist = db::history(&st.db, &addr, 500).await?;
    Ok(Json(json!({ "pool": addr, "points": hist })))
}

pub async fn health(State(st): State<AppState>) -> Result<Json<serde_json::Value>, AppError> {
    let s = db::stats(&st.db).await?;
    Ok(Json(json!({ "ok": true, "pools": s.pools, "snapshots": s.snapshots,
                    "last_run": s.last_run })))
}
