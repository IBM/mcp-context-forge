// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! SSE stream handler for forwarding agent streaming responses to clients.
//!
//! Provides two main functions:
//!
//! - [`forward_agent_sse`] reads an SSE byte stream from an agent endpoint,
//!   stores events in the [`EventStore`], and yields them as
//!   [`axum::response::sse::Event`] items.
//!
//! - [`replay_from_store`] replays previously stored events from the
//!   [`EventStore`] after a given sequence number (for Last-Event-ID
//!   reconnect support).

use crate::event_store::EventStore;
use axum::response::sse::{Event, Sse};
use futures::StreamExt;
use futures::stream::Stream;
use std::convert::Infallible;
use std::sync::Arc;
use tokio_stream::wrappers::ReceiverStream;
use tracing::{debug, warn};

// ---------------------------------------------------------------------------
// SSE line parser state
// ---------------------------------------------------------------------------

/// Intermediate state for parsing SSE events from a byte stream.
///
/// SSE events are delimited by blank lines (`\n\n`).  Within an event,
/// lines beginning with `id:`, `event:`, and `data:` set the corresponding
/// fields.  We accumulate lines into a buffer and dispatch when a blank
/// line is encountered.
struct SseParseState {
    event_id: Option<String>,
    event_type: Option<String>,
    data_buf: String,
}

impl SseParseState {
    fn new() -> Self {
        Self {
            event_id: None,
            event_type: None,
            data_buf: String::new(),
        }
    }

    /// Process a single line of SSE text.
    ///
    /// Returns `Some(...)` when a blank line is encountered and the data
    /// buffer is non-empty, indicating a complete event.
    fn feed_line(&mut self, line: &str) -> Option<ParsedSseEvent> {
        if line.is_empty() {
            // Blank line = dispatch if we have data.
            if self.data_buf.is_empty() {
                return None;
            }
            let event = ParsedSseEvent {
                id: self.event_id.take(),
                event_type: self.event_type.take(),
                data: self.data_buf.clone(),
            };
            self.data_buf.clear();
            return Some(event);
        }

        if let Some(value) = line.strip_prefix("id:") {
            self.event_id = Some(value.trim_start().to_string());
        } else if let Some(value) = line.strip_prefix("event:") {
            self.event_type = Some(value.trim_start().to_string());
        } else if let Some(value) = line.strip_prefix("data:") {
            if !self.data_buf.is_empty() {
                self.data_buf.push('\n');
            }
            self.data_buf.push_str(value.trim_start());
        }
        // Lines starting with `:` are comments — ignore.
        // Unknown field names — ignore per SSE spec.

        None
    }
}

/// A fully parsed SSE event ready to be forwarded.
#[derive(Debug, Clone)]
struct ParsedSseEvent {
    id: Option<String>,
    event_type: Option<String>,
    data: String,
}

// ---------------------------------------------------------------------------
// Forward agent SSE
// ---------------------------------------------------------------------------

/// Forward an agent's SSE response to the client, storing events in the
/// event store along the way.
///
/// The returned [`Sse`] wraps a `Send` stream that yields one [`Event`]
/// per SSE event parsed from the agent response.  If `event_store` is
/// `Some`, each event is also stored in Redis for reconnect replay.
///
/// Internally, a background Tokio task reads from the agent byte stream,
/// parses SSE events, stores them, and sends them through a channel.
/// The channel's receiver is wrapped as the output stream, ensuring the
/// stream type is `Send`.
pub fn forward_agent_sse(
    agent_response: reqwest::Response,
    event_store: Option<Arc<EventStore>>,
    task_id: String,
) -> Sse<impl Stream<Item = Result<Event, Infallible>> + Send> {
    let (tx, rx) = tokio::sync::mpsc::channel::<Result<Event, Infallible>>(256);

    // Spawn a background task to read the agent stream, parse SSE events,
    // store them, and forward to the channel.
    tokio::spawn(async move {
        let mut byte_stream = agent_response.bytes_stream();
        let mut parser = SseParseState::new();
        let mut line_buf = String::new();
        let mut seq: i64 = 0;

        loop {
            match byte_stream.next().await {
                Some(Ok(chunk)) => {
                    let text = String::from_utf8_lossy(&chunk);
                    line_buf.push_str(&text);

                    // Process all complete lines.
                    while let Some(pos) = line_buf.find('\n') {
                        let line = line_buf[..pos].trim_end_matches('\r').to_string();
                        line_buf = line_buf[pos + 1..].to_string();

                        if let Some(parsed) = parser.feed_line(&line) {
                            seq += 1;
                            let axum_event = build_axum_event(&parsed, &task_id, seq);
                            store_event(&event_store, &task_id, &parsed).await;
                            if tx.send(Ok(axum_event)).await.is_err() {
                                // Client disconnected.
                                mark_complete(&event_store, &task_id).await;
                                return;
                            }
                        }
                    }
                }
                Some(Err(e)) => {
                    warn!("error reading agent SSE stream: {e}");
                    mark_complete(&event_store, &task_id).await;
                    return;
                }
                None => {
                    // Stream ended.  Flush any remaining partial event.
                    if !line_buf.is_empty() {
                        let line = line_buf.trim_end_matches('\r').to_string();
                        let _ = parser.feed_line(&line);
                    }
                    if let Some(parsed) = parser.feed_line("") {
                        seq += 1;
                        let axum_event = build_axum_event(&parsed, &task_id, seq);
                        store_event(&event_store, &task_id, &parsed).await;
                        let _ = tx.send(Ok(axum_event)).await;
                    }
                    mark_complete(&event_store, &task_id).await;
                    return;
                }
            }
        }
    });

    Sse::new(ReceiverStream::new(rx))
}

/// Build an axum SSE [`Event`] from a parsed event.
fn build_axum_event(parsed: &ParsedSseEvent, task_id: &str, seq: i64) -> Event {
    let mut event = Event::default().data(parsed.data.clone());
    if let Some(ref et) = parsed.event_type {
        event = event.event(et.clone());
    }
    // Use agent-provided ID if available, otherwise generate one.
    let id = parsed
        .id
        .clone()
        .unwrap_or_else(|| format!("{task_id}:{seq}"));
    event = event.id(id);
    event
}

/// Store the event in the event store (best-effort).
async fn store_event(
    event_store: &Option<Arc<EventStore>>,
    task_id: &str,
    parsed: &ParsedSseEvent,
) {
    if let Some(store) = event_store {
        let event_type = parsed.event_type.as_deref().unwrap_or("message");
        // Parse data as JSON or wrap as string value.
        let payload = serde_json::from_str::<serde_json::Value>(&parsed.data)
            .unwrap_or_else(|_| serde_json::Value::String(parsed.data.clone()));
        if let Some((eid, seq)) = store.store_event(task_id, event_type, &payload).await {
            debug!(task_id, event_id = %eid, seq, "stored SSE event");
        }
    }
}

/// Mark the stream as complete in the event store.
async fn mark_complete(event_store: &Option<Arc<EventStore>>, task_id: &str) {
    if let Some(store) = event_store {
        store.mark_stream_complete(task_id).await;
    }
}

// ---------------------------------------------------------------------------
// Replay from store (reconnect)
// ---------------------------------------------------------------------------

/// Replay events from the event store after the given sequence number.
///
/// This is used for `Last-Event-ID` reconnect support.  The returned
/// stream yields all stored events with a sequence greater than
/// `after_sequence`, then closes.
pub fn replay_from_store(
    event_store: Arc<EventStore>,
    task_id: String,
    after_sequence: i64,
) -> Sse<impl Stream<Item = Result<Event, Infallible>> + Send> {
    let (tx, rx) = tokio::sync::mpsc::channel::<Result<Event, Infallible>>(256);

    tokio::spawn(async move {
        let events = event_store.replay_after(&task_id, after_sequence).await;
        for stored in events {
            let mut event = Event::default().data(stored.payload);
            event = event.id(format!("{}:{}", stored.event_id, stored.sequence));
            if stored.event_type != "unknown" {
                event = event.event(stored.event_type);
            }
            if tx.send(Ok(event)).await.is_err() {
                return; // Client disconnected.
            }
        }
    });

    Sse::new(ReceiverStream::new(rx))
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_state_simple_event() {
        let mut parser = SseParseState::new();
        assert!(parser.feed_line("event: status_update").is_none());
        assert!(parser.feed_line("data: {\"status\":\"working\"}").is_none());
        assert!(parser.feed_line("id: ev-001").is_none());
        let event = parser.feed_line("").expect("should dispatch on blank line");
        assert_eq!(event.event_type.as_deref(), Some("status_update"));
        assert_eq!(event.data, "{\"status\":\"working\"}");
        assert_eq!(event.id.as_deref(), Some("ev-001"));
    }

    #[test]
    fn parse_state_multi_line_data() {
        let mut parser = SseParseState::new();
        parser.feed_line("data: line1");
        parser.feed_line("data: line2");
        let event = parser.feed_line("").unwrap();
        assert_eq!(event.data, "line1\nline2");
    }

    #[test]
    fn parse_state_blank_line_without_data_does_not_dispatch() {
        let mut parser = SseParseState::new();
        assert!(parser.feed_line("").is_none());
    }

    #[test]
    fn parse_state_comment_lines_ignored() {
        let mut parser = SseParseState::new();
        parser.feed_line(": this is a comment");
        parser.feed_line("data: hello");
        let event = parser.feed_line("").unwrap();
        assert_eq!(event.data, "hello");
        assert!(event.event_type.is_none());
    }

    #[test]
    fn parse_state_id_resets_between_events() {
        let mut parser = SseParseState::new();
        parser.feed_line("id: first");
        parser.feed_line("data: one");
        let ev1 = parser.feed_line("").unwrap();
        assert_eq!(ev1.id.as_deref(), Some("first"));

        parser.feed_line("data: two");
        let ev2 = parser.feed_line("").unwrap();
        assert!(ev2.id.is_none(), "id should not carry over between events");
    }

    #[test]
    fn parse_state_handles_no_space_after_colon() {
        let mut parser = SseParseState::new();
        parser.feed_line("data:no-space");
        let event = parser.feed_line("").unwrap();
        assert_eq!(event.data, "no-space");
    }

    #[test]
    fn build_axum_event_uses_agent_id_when_present() {
        let parsed = ParsedSseEvent {
            id: Some("agent-id-42".to_string()),
            event_type: Some("status".to_string()),
            data: "test".to_string(),
        };
        let _event = build_axum_event(&parsed, "task-4", 1);
        // Verify it doesn't panic; the Event type is opaque.
    }

    #[test]
    fn build_axum_event_generates_id_when_absent() {
        let parsed = ParsedSseEvent {
            id: None,
            event_type: None,
            data: "no-id".to_string(),
        };
        let _event = build_axum_event(&parsed, "task-5", 1);
        // Verify it doesn't panic.
    }
}
