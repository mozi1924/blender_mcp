use crate::server::mcp_router::handle_rpc_request;
use crate::server::protocol::JsonRpcRequest;
use axum::{
    extract::State,
    http::StatusCode,
    response::{
        sse::{Event, KeepAlive, Sse},
        IntoResponse,
    },
    routing::{get, post},
    Json, Router,
};
use futures_util::stream::Stream;
use serde_json::json;
use std::convert::Infallible;
use tokio::sync::broadcast;
use tower_http::cors::CorsLayer;

#[derive(Clone)]
pub struct AppState {
    pub sse_sender: broadcast::Sender<String>,
}

pub fn create_router() -> Router {
    let (tx, _rx) = broadcast::channel(100);
    let state = AppState { sse_sender: tx };

    Router::new()
        .route("/health", get(health_handler))
        .route("/mcp", post(mcp_post_handler))
        .route("/messages", post(mcp_post_handler))
        .route("/sse", get(sse_handler))
        .layer(CorsLayer::permissive())
        .with_state(state)
}

async fn health_handler() -> impl IntoResponse {
    Json(json!({
        "status": "ok",
        "server": "blender-mcp-rust",
        "version": env!("CARGO_PKG_VERSION"),
        "blender_active": true
    }))
}

async fn mcp_post_handler(
    State(state): State<AppState>,
    Json(req): Json<JsonRpcRequest>,
) -> impl IntoResponse {
    let resp = handle_rpc_request(req).await;
    match resp {
        Some(response) => {
            if let Ok(json_str) = serde_json::to_string(&response) {
                let _ = state.sse_sender.send(json_str);
            }
            (StatusCode::OK, Json(json!(response))).into_response()
        }
        None => (StatusCode::NO_CONTENT, ()).into_response(),
    }
}

async fn sse_handler(
    State(state): State<AppState>,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    let mut rx = state.sse_sender.subscribe();

    let initial_stream = async_stream::stream! {
        yield Ok(Event::default().event("endpoint").data("/messages"));
        while let Ok(msg) = rx.recv().await {
            yield Ok(Event::default().event("message").data(msg));
        }
    };

    Sse::new(initial_stream).keep_alive(KeepAlive::default())
}
