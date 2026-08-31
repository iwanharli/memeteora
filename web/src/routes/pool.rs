use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::{Html, IntoResponse, Response};

use crate::routes::AppError;
use crate::{db, views, AppState};

pub async fn get(
    State(st): State<AppState>,
    Path(addr): Path<String>,
) -> Result<Response, AppError> {
    let Some(detail) = db::pool_detail(&st.db, &addr).await? else {
        return Ok((StatusCode::NOT_FOUND,
                   Html("<h1>404</h1><p>Unknown pool.</p>")).into_response());
    };
    let score = db::latest_score_for(&st.db, &addr).await?;
    let hist = db::history(&st.db, &addr, 200).await?;
    Ok(Html(views::detail::page(&detail, score.as_ref(), &hist).into_string()).into_response())
}
