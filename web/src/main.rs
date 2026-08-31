//! memet-web — read-only dashboard over db_memet.
//! The Python worker in ../ingest owns every write; this process only reads.

mod db;
mod models;
mod routes;
mod views;

use anyhow::{Context, Result};
use axum::routing::get;
use axum::Router;
use sqlx::postgres::PgPool;
use tower_http::compression::CompressionLayer;
use tower_http::trace::TraceLayer;

#[derive(Clone)]
pub struct AppState {
    pub db: PgPool,
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(std::env::var("RUST_LOG").unwrap_or_else(|_| "memet_web=info,tower_http=warn".into()))
        .init();

    let url = std::env::var("DATABASE_URL").unwrap_or_else(|_| "postgres:///db_memet".into());
    let bind = std::env::var("BIND_ADDR").unwrap_or_else(|_| "127.0.0.1:8080".into());

    let pool = db::pool(&url).await.with_context(|| format!("connecting to {url}"))?;
    let stats = db::stats(&pool).await.context("db_memet reachable but schema missing? run db/schema.sql")?;
    tracing::info!("db_memet: {} pools, {} snapshots, last ingest {:?}",
                   stats.pools, stats.snapshots, stats.last_run);

    let app = Router::new()
        .route("/", get(routes::dashboard::get))
        .route("/portfolio", get(routes::portfolio::get))
        .route("/pool/{addr}", get(routes::pool::get))
        .route("/api/scores", get(routes::api::scores))
        .route("/api/pool/{addr}/history", get(routes::api::history))
        .route("/healthz", get(routes::api::health))
        .layer(CompressionLayer::new())
        .layer(TraceLayer::new_for_http())
        .with_state(AppState { db: pool });

    let listener = tokio::net::TcpListener::bind(&bind).await
        .with_context(|| format!("binding {bind}"))?;
    tracing::info!("listening on http://{bind}");
    axum::serve(listener, app).with_graceful_shutdown(shutdown()).await?;
    Ok(())
}

async fn shutdown() {
    let _ = tokio::signal::ctrl_c().await;
    tracing::info!("shutting down");
}
