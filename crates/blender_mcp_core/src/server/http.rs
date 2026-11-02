// SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
// SPDX-License-Identifier: GPL-3.0-or-later

//! Streamable HTTP + legacy HTTP/SSE transport.
//!
//! * `POST /mcp`          JSON-RPC request; response as JSON or SSE
//! * `GET /mcp`           per-session server-sent event stream
//! * `DELETE /mcp`        terminate a session
//! * `GET /sse`           legacy HTTP+SSE endpoint event
//! * `POST /messages`     legacy HTTP+SSE request tunnel
//!
//! Responses are never broadcast globally: each request is answered on its own
//! exchange, and each session owns a private notification channel.

use crate::server::mcp_router::{handle_rpc_request, RpcContext};
use crate::server::protocol::{
    negotiate_protocol_version, JsonRpcRequest, JsonRpcResponse, RequestId,
    LATEST_PROTOCOL_VERSION, PROTOCOL_HEADER, SESSION_HEADER,
};
use crate::server::session::SessionStore;
use axum::{
    extract::{Query, State},
    http::{header, HeaderMap, HeaderName, HeaderValue, Method, StatusCode},
    response::{
        sse::{Event, KeepAlive, Sse},
        IntoResponse, Response,
    },
    routing::{get, post},
    Json, Router,
};
use serde_json::{json, Value};
use std::{collections::HashMap, convert::Infallible, sync::Arc, time::Duration};
use tower_http::cors::{AllowOrigin, CorsLayer};

#[derive(Clone)]
pub struct AppState {
    pub sessions: Arc<SessionStore>,
    pub auth_token: Option<Arc<String>>,
    pub tool_timeout: Duration,
}

pub fn create_router(auth_token: Option<String>, tool_timeout: Duration) -> Router {
    let state = AppState {
        sessions: Arc::new(SessionStore::new()),
        auth_token: auth_token
            .filter(|value| !value.trim().is_empty())
            .map(Arc::new),
        tool_timeout,
    };

    Router::new()
        .route("/health", get(health_handler))
        .route(
            "/mcp",
            get(mcp_get_handler)
                .post(mcp_post_handler)
                .delete(mcp_delete_handler),
        )
        .route("/messages", post(legacy_messages_handler))
        .route("/sse", get(legacy_sse_handler))
        .layer(cors_layer())
        .with_state(state)
}

fn cors_layer() -> CorsLayer {
    CorsLayer::new()
        .allow_origin(AllowOrigin::predicate(|origin, _request| {
            is_local_origin(origin)
        }))
        .allow_methods([Method::GET, Method::POST, Method::DELETE, Method::OPTIONS])
        .allow_headers([
            header::CONTENT_TYPE,
            header::ACCEPT,
            header::AUTHORIZATION,
            HeaderName::from_static("last-event-id"),
            HeaderName::from_static(SESSION_HEADER),
            HeaderName::from_static(PROTOCOL_HEADER),
        ])
        .expose_headers([HeaderName::from_static(SESSION_HEADER)])
}

/// Browser origins are restricted to loopback.  Non-browser MCP clients do not
/// send `Origin`, so this does not affect them.
fn is_local_origin(origin: &HeaderValue) -> bool {
    let Ok(text) = origin.to_str() else {
        return false;
    };
    let Ok(uri) = text.parse::<axum::http::Uri>() else {
        return false;
    };
    matches!(uri.scheme_str(), Some("http") | Some("https"))
        && matches!(
            uri.host(),
            Some("localhost") | Some("127.0.0.1") | Some("::1")
        )
}

fn is_authorized(state: &AppState, headers: &HeaderMap) -> bool {
    match &state.auth_token {
        None => true,
        Some(expected) => headers
            .get(header::AUTHORIZATION)
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.strip_prefix("Bearer "))
            .map(|value| value == expected.as_str())
            .unwrap_or(false),
    }
}

fn unauthorized() -> Response {
    let body = JsonRpcResponse::error(
        None,
        -32001,
        "Unauthorized: missing or invalid bearer token",
    );
    (
        StatusCode::UNAUTHORIZED,
        [(header::WWW_AUTHENTICATE, HeaderValue::from_static("Bearer"))],
        Json(body),
    )
        .into_response()
}

fn session_id(headers: &HeaderMap) -> Option<String> {
    headers
        .get(SESSION_HEADER)
        .and_then(|value| value.to_str().ok())
        .map(str::to_string)
}

fn with_session_header(mut response: Response, session_id: &str) -> Response {
    if let Ok(value) = HeaderValue::from_str(session_id) {
        response
            .headers_mut()
            .insert(HeaderName::from_static(SESSION_HEADER), value);
    }
    response
}

fn jsonrpc_http(
    status: StatusCode,
    id: Option<RequestId>,
    code: i32,
    message: impl Into<String>,
) -> Response {
    (status, Json(JsonRpcResponse::error(id, code, message))).into_response()
}

fn parse_request(value: Value) -> Result<JsonRpcRequest, Box<Response>> {
    if value.is_array() {
        return Err(Box::new(jsonrpc_http(
            StatusCode::BAD_REQUEST,
            None,
            -32600,
            "Batch requests are not supported; send one JSON-RPC message per request",
        )));
    }
    let request: JsonRpcRequest = serde_json::from_value(value).map_err(|error| {
        Box::new(jsonrpc_http(
            StatusCode::BAD_REQUEST,
            None,
            -32700,
            format!("JSON-RPC parse error: {error}"),
        ))
    })?;
    if request.jsonrpc != "2.0" {
        return Err(Box::new(jsonrpc_http(
            StatusCode::BAD_REQUEST,
            request.id.clone(),
            -32600,
            "Invalid JSON-RPC version; expected '2.0'",
        )));
    }
    Ok(request)
}

fn accepts_event_stream(headers: &HeaderMap) -> bool {
    headers
        .get(header::ACCEPT)
        .and_then(|value| value.to_str().ok())
        .map(|value| {
            value.contains("text/event-stream")
                && !value.contains("application/json")
                && !value.contains("*/*")
        })
        .unwrap_or(false)
}

fn sse_single_response(response: JsonRpcResponse) -> Response {
    let data = serde_json::to_string(&response).unwrap_or_else(|_| "{}".to_string());
    let stream = async_stream::stream! {
        yield Ok::<_, Infallible>(Event::default().event("message").data(data));
    };
    Sse::new(stream)
        .keep_alive(KeepAlive::default())
        .into_response()
}

async fn health_handler(State(state): State<AppState>) -> impl IntoResponse {
    Json(json!({
        "status": "ok",
        "server": "blender-mcp-rust",
        "version": env!("CARGO_PKG_VERSION"),
        "blender_active": true,
        "sessions": state.sessions.count(),
        "auth_required": state.auth_token.is_some(),
        "tool_timeout_secs": state.tool_timeout.as_secs(),
    }))
}

async fn mcp_post_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Response {
    if !is_authorized(&state, &headers) {
        return unauthorized();
    }

    let request = match parse_request(body) {
        Ok(request) => request,
        Err(response) => return *response,
    };

    let is_initialize = request.method == "initialize";

    let (session_id, context) = if is_initialize {
        let protocol_version = negotiate_protocol_version(request.params.as_ref());
        let session = state.sessions.create(protocol_version.clone(), false);
        let context = RpcContext {
            protocol_version,
            session_id: Some(session.id.clone()),
            tool_timeout: state.tool_timeout,
        };
        (Some(session.id), context)
    } else {
        let Some(id) = session_id(&headers) else {
            return jsonrpc_http(
                StatusCode::BAD_REQUEST,
                request.id.clone(),
                -32000,
                format!("Missing {SESSION_HEADER} header; call initialize first"),
            );
        };
        let Some(session) = state.sessions.get(&id) else {
            return jsonrpc_http(
                StatusCode::NOT_FOUND,
                request.id.clone(),
                -32000,
                "Unknown or expired MCP session",
            );
        };
        if let Some(version) = headers
            .get(PROTOCOL_HEADER)
            .and_then(|value| value.to_str().ok())
        {
            if version != session.protocol_version {
                return jsonrpc_http(
                    StatusCode::BAD_REQUEST,
                    request.id.clone(),
                    -32000,
                    format!(
                        "Unsupported MCP protocol version '{version}'; session negotiated '{}'",
                        session.protocol_version
                    ),
                );
            }
        }
        let context = RpcContext {
            protocol_version: session.protocol_version.clone(),
            session_id: Some(session.id.clone()),
            tool_timeout: state.tool_timeout,
        };
        (Some(session.id), context)
    };

    let response = handle_rpc_request(request, &context).await;
    match response {
        Some(response) => {
            let mut http_response = if accepts_event_stream(&headers) {
                sse_single_response(response)
            } else {
                Json(response).into_response()
            };
            if let Some(id) = session_id {
                http_response = with_session_header(http_response, &id);
            }
            http_response
        }
        None => {
            let mut http_response = StatusCode::ACCEPTED.into_response();
            if let Some(id) = session_id {
                http_response = with_session_header(http_response, &id);
            }
            http_response
        }
    }
}

async fn mcp_get_handler(State(state): State<AppState>, headers: HeaderMap) -> Response {
    if !is_authorized(&state, &headers) {
        return unauthorized();
    }
    let Some(id) = session_id(&headers) else {
        return jsonrpc_http(
            StatusCode::BAD_REQUEST,
            None,
            -32000,
            format!("Missing {SESSION_HEADER} header"),
        );
    };
    let Some(session) = state.sessions.get(&id) else {
        return jsonrpc_http(
            StatusCode::NOT_FOUND,
            None,
            -32000,
            "Unknown or expired MCP session",
        );
    };

    let mut receiver = session.sender.subscribe();
    let stream = async_stream::stream! {
        yield Ok::<_, Infallible>(Event::default().comment("connected"));
        while let Ok(message) = receiver.recv().await {
            yield Ok(Event::default().event("message").data(message));
        }
    };

    let response = Sse::new(stream)
        .keep_alive(KeepAlive::default())
        .into_response();
    with_session_header(response, &session.id)
}

async fn mcp_delete_handler(State(state): State<AppState>, headers: HeaderMap) -> Response {
    if !is_authorized(&state, &headers) {
        return unauthorized();
    }
    let Some(id) = session_id(&headers) else {
        return jsonrpc_http(
            StatusCode::BAD_REQUEST,
            None,
            -32000,
            format!("Missing {SESSION_HEADER} header"),
        );
    };
    if state.sessions.remove(&id) {
        StatusCode::NO_CONTENT.into_response()
    } else {
        jsonrpc_http(
            StatusCode::NOT_FOUND,
            None,
            -32000,
            "Unknown or expired MCP session",
        )
    }
}

async fn legacy_sse_handler(State(state): State<AppState>, headers: HeaderMap) -> Response {
    if !is_authorized(&state, &headers) {
        return unauthorized();
    }

    let session = state
        .sessions
        .create(LATEST_PROTOCOL_VERSION.to_string(), true);
    let mut receiver = session.sender.subscribe();
    let endpoint = format!("/messages?sessionId={}", session.id);
    let stream = async_stream::stream! {
        yield Ok::<_, Infallible>(Event::default().event("endpoint").data(endpoint));
        while let Ok(message) = receiver.recv().await {
            yield Ok(Event::default().event("message").data(message));
        }
    };

    let response = Sse::new(stream)
        .keep_alive(KeepAlive::default())
        .into_response();
    with_session_header(response, &session.id)
}

async fn legacy_messages_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(query): Query<HashMap<String, String>>,
    Json(body): Json<Value>,
) -> Response {
    if !is_authorized(&state, &headers) {
        return unauthorized();
    }

    let Some(id) = query.get("sessionId").cloned() else {
        return jsonrpc_http(
            StatusCode::BAD_REQUEST,
            None,
            -32000,
            "Missing sessionId query parameter",
        );
    };
    let Some(session) = state.sessions.get(&id) else {
        return jsonrpc_http(
            StatusCode::NOT_FOUND,
            None,
            -32000,
            "Unknown or expired MCP session",
        );
    };
    let request = match parse_request(body) {
        Ok(request) => request,
        Err(response) => return *response,
    };
    let context = RpcContext {
        protocol_version: session.protocol_version.clone(),
        session_id: Some(session.id.clone()),
        tool_timeout: state.tool_timeout,
    };

    if let Some(response) = handle_rpc_request(request, &context).await {
        if let Ok(text) = serde_json::to_string(&response) {
            let _ = session.sender.send(text);
        }
    }

    StatusCode::ACCEPTED.into_response()
}
