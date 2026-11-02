pub mod http;
pub mod mcp_router;
pub mod protocol;
pub mod session;

use once_cell::sync::Lazy;
use std::net::IpAddr;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;
use tokio::sync::oneshot;

static RUNNING: AtomicBool = AtomicBool::new(false);
static SHUTDOWN_TX: Lazy<Mutex<Option<oneshot::Sender<()>>>> = Lazy::new(|| Mutex::new(None));

pub fn is_running() -> bool {
    RUNNING.load(Ordering::SeqCst)
}

pub fn start(
    host: &str,
    port: u16,
    auth_token: Option<String>,
    tool_timeout: Duration,
) -> Result<(), String> {
    if is_running() {
        return Err("Server is already running".to_string());
    }

    let token_required = auth_token
        .as_deref()
        .map(|token| !token.trim().is_empty())
        .unwrap_or(false);
    let host_is_loopback = host == "localhost"
        || host
            .parse::<IpAddr>()
            .map(|address| address.is_loopback())
            .unwrap_or(false);
    if !host_is_loopback && !token_required {
        eprintln!(
            "[Blender MCP Rust] WARNING: binding to non-loopback host '{}' without an auth token. \
             Anyone who can reach this port can execute Blender operations.",
            host
        );
    }

    let addr_str = format!("{}:{}", host, port);
    let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();

    {
        let mut guard = SHUTDOWN_TX.lock().unwrap();
        *guard = Some(shutdown_tx);
    }

    let host_owned = host.to_string();

    thread::Builder::new()
        .name("blender-mcp-tokio".to_string())
        .spawn(move || {
            let rt = match tokio::runtime::Builder::new_multi_thread()
                .worker_threads(2)
                .enable_all()
                .build()
            {
                Ok(rt) => rt,
                Err(err) => {
                    eprintln!("Failed to build Tokio runtime for MCP: {}", err);
                    RUNNING.store(false, Ordering::SeqCst);
                    return;
                }
            };

            rt.block_on(async move {
                let app = http::create_router(auth_token, tool_timeout);
                let listener = match tokio::net::TcpListener::bind(&addr_str).await {
                    Ok(l) => l,
                    Err(err) => {
                        eprintln!("Failed to bind TCP listener on {}: {}", addr_str, err);
                        RUNNING.store(false, Ordering::SeqCst);
                        return;
                    }
                };

                println!("[Blender MCP Rust] Listening on http://{}", addr_str);
                RUNNING.store(true, Ordering::SeqCst);

                let server = axum::serve(listener, app).with_graceful_shutdown(async {
                    let _ = shutdown_rx.await;
                    println!("[Blender MCP Rust] Shutting down server");
                });

                if let Err(err) = server.await {
                    eprintln!("Blender MCP server error: {}", err);
                }

                RUNNING.store(false, Ordering::SeqCst);
            });
        })
        .map_err(|e| format!("Failed to spawn Tokio background thread: {}", e))?;

    // Wait briefly to confirm start
    std::thread::sleep(std::time::Duration::from_millis(50));
    if is_running() {
        Ok(())
    } else {
        Err(format!("Server failed to start on {}:{}", host_owned, port))
    }
}

pub fn stop() -> Result<(), String> {
    if !is_running() {
        return Ok(());
    }

    let mut guard = SHUTDOWN_TX.lock().unwrap();
    if let Some(tx) = guard.take() {
        let _ = tx.send(());
    }
    RUNNING.store(false, Ordering::SeqCst);
    Ok(())
}
