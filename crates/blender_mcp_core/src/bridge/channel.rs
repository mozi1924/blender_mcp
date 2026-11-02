use crossbeam_channel::{bounded, Receiver, Sender, TrySendError};
use once_cell::sync::OnceCell;
use serde::{Deserialize, Serialize};
use tokio::sync::oneshot;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum ToolContent {
    #[serde(rename = "text")]
    Text { text: String },
    #[serde(rename = "image")]
    Image {
        data: String,
        #[serde(rename = "mimeType")]
        mime_type: String,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolCallResponse {
    #[serde(rename = "isError")]
    pub is_error: bool,
    pub content: Vec<ToolContent>,
}

impl ToolCallResponse {
    pub fn text(msg: impl Into<String>) -> Self {
        Self {
            is_error: false,
            content: vec![ToolContent::Text { text: msg.into() }],
        }
    }

    pub fn json(val: &serde_json::Value) -> Self {
        let text = serde_json::to_string_pretty(val).unwrap_or_else(|_| val.to_string());
        Self::text(text)
    }

    pub fn error(err: impl Into<String>) -> Self {
        Self {
            is_error: true,
            content: vec![ToolContent::Text {
                text: format!("Error: {}", err.into()),
            }],
        }
    }

    /// Error response that preserves the runtime's structured diagnostics.
    pub fn json_error(val: &serde_json::Value) -> Self {
        let text = serde_json::to_string_pretty(val).unwrap_or_else(|_| val.to_string());
        Self {
            is_error: true,
            content: vec![ToolContent::Text { text }],
        }
    }

    pub fn image(data_base64: String, mime_type: String, caption: Option<String>) -> Self {
        let mut content = Vec::new();
        if let Some(cap) = caption {
            content.push(ToolContent::Text { text: cap });
        }
        content.push(ToolContent::Image {
            data: data_base64,
            mime_type,
        });
        Self {
            is_error: false,
            content,
        }
    }
}

pub struct ToolCallRequest {
    pub tool_name: String,
    pub arguments: serde_json::Value,
    pub responder: oneshot::Sender<ToolCallResponse>,
}

static BRIDGE: OnceCell<(Sender<ToolCallRequest>, Receiver<ToolCallRequest>)> = OnceCell::new();

fn get_bridge() -> &'static (Sender<ToolCallRequest>, Receiver<ToolCallRequest>) {
    BRIDGE.get_or_init(|| bounded(128))
}

pub fn send_request(
    tool_name: String,
    arguments: serde_json::Value,
) -> Result<oneshot::Receiver<ToolCallResponse>, String> {
    let (tx, rx) = oneshot::channel();
    let req = ToolCallRequest {
        tool_name,
        arguments,
        responder: tx,
    };
    let bridge = get_bridge();
    bridge.0.try_send(req).map_err(|e| match e {
        TrySendError::Full(_) => "Blender main thread is busy (request queue full, 128 pending). \
                 Wait for the current tool call to finish and retry."
            .to_string(),
        TrySendError::Disconnected(_) => {
            "Failed to send tool request to Blender main thread: bridge disconnected".to_string()
        }
    })?;
    Ok(rx)
}

pub fn recv_requests(max_batch: usize) -> Vec<ToolCallRequest> {
    let bridge = get_bridge();
    let mut batch = Vec::with_capacity(max_batch);
    while batch.len() < max_batch {
        match bridge.1.try_recv() {
            Ok(req) => batch.push(req),
            Err(_) => break,
        }
    }
    batch
}
