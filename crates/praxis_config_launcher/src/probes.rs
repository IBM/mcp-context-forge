use std::net::{SocketAddr, TcpListener};
use std::path::Path;
use std::process::Stdio;
use std::time::Duration;

use serde::Deserialize;
use tokio::io::{AsyncReadExt as _, AsyncWriteExt as _};
use tokio::net::TcpStream;
use tokio::process::Command;
use tokio::time::{Instant, sleep, timeout};

use crate::models::FailureCategory;
use crate::process::{ManagedProcess, ProcessSpec};

#[derive(Clone, Copy, Debug)]
pub struct ProbeTimings {
    pub activation_timeout: Duration,
    pub interval: Duration,
}

impl Default for ProbeTimings {
    fn default() -> Self {
        Self {
            activation_timeout: Duration::from_secs(30),
            interval: Duration::from_millis(100),
        }
    }
}

#[derive(Debug, Deserialize)]
struct RootConfig {
    listeners: Vec<ListenerConfig>,
}

#[derive(Debug, Deserialize)]
struct ListenerConfig {
    address: SocketAddr,
}

pub fn listener_address(generation: &Path) -> Result<SocketAddr, FailureCategory> {
    let bytes = std::fs::read(generation.join("praxis.yaml"))
        .map_err(|_| FailureCategory::ConfigValidation)?;
    let config: RootConfig =
        serde_json::from_slice(&bytes).map_err(|_| FailureCategory::ConfigValidation)?;
    match config.listeners.as_slice() {
        [listener] => Ok(listener.address),
        [] | [_, ..] => Err(FailureCategory::ConfigValidation),
    }
}

pub fn policy_canary_path(generation: &Path) -> Result<String, FailureCategory> {
    let bytes = std::fs::read(generation.join("praxis.yaml"))
        .map_err(|_| FailureCategory::ConfigValidation)?;
    let value: serde_json::Value =
        serde_json::from_slice(&bytes).map_err(|_| FailureCategory::ConfigValidation)?;
    let server_id = find_server_id(&value).ok_or(FailureCategory::ConfigValidation)?;
    if server_id.is_empty()
        || server_id.len() > 128
        || !server_id
            .as_bytes()
            .first()
            .is_some_and(u8::is_ascii_alphanumeric)
        || !server_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(FailureCategory::ConfigValidation);
    }
    Ok(format!("/servers/{server_id}/mcp"))
}

fn find_server_id(value: &serde_json::Value) -> Option<&str> {
    match value {
        serde_json::Value::Object(map) => map
            .get("server_id")
            .and_then(serde_json::Value::as_str)
            .or_else(|| map.values().find_map(find_server_id)),
        serde_json::Value::Array(items) => items.iter().find_map(find_server_id),
        serde_json::Value::Null
        | serde_json::Value::Bool(_)
        | serde_json::Value::Number(_)
        | serde_json::Value::String(_) => None,
    }
}

pub async fn validate_config(
    spec: &ProcessSpec,
    generation: &Path,
    duration: Duration,
) -> Result<(), FailureCategory> {
    let mut command = Command::new(&spec.program);
    command
        .args(&spec.args)
        .arg("--validate")
        .current_dir(generation)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .kill_on_drop(true);
    let status = timeout(duration, command.status())
        .await
        .map_err(|_| FailureCategory::Timeout)?
        .map_err(|_| FailureCategory::Spawn)?;
    if status.success() {
        Ok(())
    } else {
        Err(FailureCategory::ConfigValidation)
    }
}

pub fn old_listener_closed(address: SocketAddr) -> Result<(), FailureCategory> {
    TcpListener::bind(address)
        .map(drop)
        .map_err(|_| FailureCategory::Listener)
}

pub async fn wait_for_listener(
    process: &mut ManagedProcess,
    address: SocketAddr,
    timings: ProbeTimings,
) -> Result<(), FailureCategory> {
    let deadline = Instant::now() + timings.activation_timeout;
    loop {
        if process
            .try_wait()
            .map_err(|_| FailureCategory::EarlyExit)?
            .is_some()
        {
            return Err(FailureCategory::EarlyExit);
        }
        if TcpStream::connect(address).await.is_ok() {
            return Ok(());
        }
        if Instant::now() >= deadline {
            return Err(FailureCategory::Timeout);
        }
        sleep(timings.interval).await;
    }
}

pub async fn policy_canary(
    address: SocketAddr,
    path: &str,
    duration: Duration,
) -> Result<(), FailureCategory> {
    let probe = async {
        let mut stream = TcpStream::connect(address)
            .await
            .map_err(|_| FailureCategory::Listener)?;
        let body = b"{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"__praxis_canary_denied__\",\"arguments\":{}}}";
        let headers = format!(
            "POST {path} HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            body.len()
        );
        stream
            .write_all(headers.as_bytes())
            .await
            .map_err(|_| FailureCategory::PolicyCanary)?;
        stream
            .write_all(body)
            .await
            .map_err(|_| FailureCategory::PolicyCanary)?;
        let mut response = [0_u8; 128];
        let read = stream
            .read(&mut response)
            .await
            .map_err(|_| FailureCategory::PolicyCanary)?;
        let status = response.get(..read).unwrap_or_default();
        if status.starts_with(b"HTTP/1.1 401") || status.starts_with(b"HTTP/1.1 403") {
            Ok(())
        } else {
            Err(FailureCategory::PolicyCanary)
        }
    };
    timeout(duration, probe)
        .await
        .map_err(|_| FailureCategory::Timeout)?
}
