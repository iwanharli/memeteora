pub mod api;
pub mod dashboard;
pub mod pool;
pub mod portfolio;

use axum::http::StatusCode;
use axum::response::{Html, IntoResponse, Response};

/// Anything that fails in a handler becomes a 500 with the cause logged,
/// never a leaked SQL string in the browser.
pub struct AppError(anyhow::Error);

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        tracing::error!("request failed: {:#}", self.0);
        (StatusCode::INTERNAL_SERVER_ERROR,
         Html("<h1>500</h1><p>Something broke. Check the server log.</p>")).into_response()
    }
}

impl<E: Into<anyhow::Error>> From<E> for AppError {
    fn from(e: E) -> Self { Self(e.into()) }
}
