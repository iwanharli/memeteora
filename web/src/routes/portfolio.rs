use axum::extract::State;
use axum::response::Html;

use crate::routes::AppError;
use crate::{db, views, AppState};

pub async fn get(State(st): State<AppState>) -> Result<Html<String>, AppError> {
    let rows = db::paper_positions(&st.db).await?;
    let closed = db::closed_positions(&st.db, 40).await?;
    let book = db::book_state(&st.db).await?;
    let daily = db::daily_pnl(&st.db, 120).await?;
    Ok(Html(views::portfolio::page(&rows, &closed, book.as_ref(), &daily).into_string()))
}
