use axum::extract::{Query, State};
use axum::response::Html;

use crate::models::Filters;
use crate::routes::AppError;
use crate::{db, views, AppState};

pub async fn get(
    State(st): State<AppState>,
    Query(fl): Query<Filters>,
) -> Result<Html<String>, AppError> {
    let rows = db::latest_scores(&st.db, &fl).await?;
    let stats = db::stats(&st.db).await?;
    Ok(Html(views::dashboard::page(&rows, &stats, &fl).into_string()))
}
