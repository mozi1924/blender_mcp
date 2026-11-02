// SPDX-FileCopyrightText: 2026 Blender Authors & MCP Contributors
// SPDX-License-Identifier: GPL-3.0-or-later

//! Per-client MCP sessions.
//!
//! A session owns the negotiated protocol version and a private broadcast
//! channel for server-initiated SSE messages.  Tool responses are returned on
//! the requesting HTTP exchange, never broadcast to other clients.

use std::collections::HashMap;
use std::sync::RwLock;
use std::time::{Duration, Instant};

use tokio::sync::broadcast;

pub const SESSION_TTL: Duration = Duration::from_secs(24 * 60 * 60);

#[derive(Clone)]
pub struct Session {
    pub id: String,
    pub protocol_version: String,
    pub created_at: Instant,
    pub last_seen: Instant,
    pub sender: broadcast::Sender<String>,
    /// True for the legacy HTTP+SSE transport (`GET /sse` + `POST /messages`).
    pub legacy: bool,
}

pub struct SessionStore {
    sessions: RwLock<HashMap<String, Session>>,
}

impl Default for SessionStore {
    fn default() -> Self {
        Self::new()
    }
}

impl SessionStore {
    pub fn new() -> Self {
        Self {
            sessions: RwLock::new(HashMap::new()),
        }
    }

    pub fn create(&self, protocol_version: String, legacy: bool) -> Session {
        let (sender, _receiver) = broadcast::channel(128);
        let now = Instant::now();
        let session = Session {
            id: uuid::Uuid::new_v4().to_string(),
            protocol_version,
            created_at: now,
            last_seen: now,
            sender,
            legacy,
        };

        let mut sessions = self
            .sessions
            .write()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        sessions.retain(|_, item| item.last_seen.elapsed() < SESSION_TTL);
        sessions.insert(session.id.clone(), session.clone());
        session
    }

    pub fn get(&self, id: &str) -> Option<Session> {
        let mut sessions = self
            .sessions
            .write()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let session = sessions.get_mut(id)?;
        if session.last_seen.elapsed() >= SESSION_TTL {
            sessions.remove(id);
            return None;
        }
        session.last_seen = Instant::now();
        Some(session.clone())
    }

    pub fn remove(&self, id: &str) -> bool {
        self.sessions
            .write()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .remove(id)
            .is_some()
    }

    pub fn count(&self) -> usize {
        self.sessions
            .read()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .len()
    }
}
