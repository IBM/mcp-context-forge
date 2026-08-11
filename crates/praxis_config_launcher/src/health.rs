use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use tokio::io::{AsyncReadExt as _, AsyncWriteExt as _};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::RwLock;
use tokio::time::timeout;

use crate::error::LauncherError;

const MAX_REQUEST_BYTES: usize = 1_024;
const REQUEST_TIMEOUT: Duration = Duration::from_secs(1);
const OK: &[u8] = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";
const UNREADY: &[u8] =
    b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";
const NOT_FOUND: &[u8] =
    b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";
const TOO_LARGE: &[u8] =
    b"HTTP/1.1 413 Payload Too Large\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";
const TIMED_OUT: &[u8] =
    b"HTTP/1.1 408 Request Timeout\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";

#[derive(Clone, Debug, Default)]
pub struct HealthState {
    inner: Arc<RwLock<Readiness>>,
}

#[derive(Clone, Debug, Default)]
struct Readiness {
    generation: Option<String>,
}

impl HealthState {
    pub async fn ready(&self, generation: &str) {
        self.inner.write().await.generation = Some(generation.to_owned());
    }

    pub async fn unready(&self) {
        self.inner.write().await.generation = None;
    }

    #[must_use]
    pub async fn active_generation(&self) -> Option<String> {
        self.inner.read().await.generation.clone()
    }

    async fn is_ready(&self) -> bool {
        self.inner.read().await.generation.is_some()
    }
}

pub fn validate_listen_address(address: SocketAddr) -> Result<SocketAddr, LauncherError> {
    if address.ip().is_loopback() {
        Ok(address)
    } else {
        Err(LauncherError::Config(
            "health listen address must be loopback",
        ))
    }
}

pub async fn serve(listener: TcpListener, state: HealthState) -> std::io::Result<()> {
    loop {
        let (stream, _) = listener.accept().await?;
        let _ = respond(stream, &state).await;
    }
}

async fn respond(mut stream: TcpStream, state: &HealthState) -> std::io::Result<()> {
    let response = match timeout(REQUEST_TIMEOUT, read_request(&mut stream)).await {
        Err(_) => TIMED_OUT,
        Ok(Ok(Request::Live)) => OK,
        Ok(Ok(Request::Ready)) if state.is_ready().await => OK,
        Ok(Ok(Request::Ready)) => UNREADY,
        Ok(Ok(Request::Unsupported)) => NOT_FOUND,
        Ok(Ok(Request::TooLarge)) => TOO_LARGE,
        Ok(Err(error)) => return Err(error),
    };
    stream.write_all(response).await?;
    stream.shutdown().await
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Request {
    Live,
    Ready,
    Unsupported,
    TooLarge,
}

async fn read_request(stream: &mut TcpStream) -> std::io::Result<Request> {
    let mut bytes = [0_u8; MAX_REQUEST_BYTES];
    let mut length = 0;
    loop {
        let read = stream.read(&mut bytes[length..]).await?;
        if read == 0 {
            return Ok(Request::Unsupported);
        }
        length += read;
        if bytes[..length]
            .windows(4)
            .any(|window| window == b"\r\n\r\n")
        {
            return Ok(match bytes[..length].split(|byte| *byte == b'\r').next() {
                Some(b"GET /livez HTTP/1.1") => Request::Live,
                Some(b"GET /readyz HTTP/1.1") => Request::Ready,
                Some(_) | None => Request::Unsupported,
            });
        }
        if length == MAX_REQUEST_BYTES {
            return Ok(Request::TooLarge);
        }
    }
}
