use std::collections::VecDeque;
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use tokio::io::{AsyncReadExt as _, AsyncWriteExt as _};
use tokio::process::{Child, ChildStdout, Command};
use tokio::sync::{Mutex as AsyncMutex, oneshot};

use super::certificates::{ensure_openssl, generate_certificates};

static TLS_MOCK_LOCK: AsyncMutex<()> = AsyncMutex::const_new(());

pub struct MockResponse {
    pub status: u16,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
    pub rotate_token: Option<(PathBuf, String)>,
    pub declared_length: Option<usize>,
}

impl MockResponse {
    pub fn json(status: u16, etag: Option<&str>, body: serde_json::Value) -> Self {
        let body = serde_json::to_vec(&body).expect("test JSON");
        let mut headers = vec![("content-type".to_owned(), "application/json".to_owned())];
        if let Some(value) = etag {
            headers.push(("etag".to_owned(), format!("\"{value}\"")));
        }
        Self {
            status,
            headers,
            body,
            rotate_token: None,
            declared_length: None,
        }
    }
}

pub struct TlsMock {
    pub base_url: String,
    pub requests: Arc<Mutex<Vec<String>>>,
    certificates: tempfile::TempDir,
    _task: tokio::task::JoinHandle<()>,
}

impl TlsMock {
    pub async fn start(responses: Vec<MockResponse>) -> Self {
        let serial_guard = TLS_MOCK_LOCK.lock().await;
        ensure_openssl();
        let certificates = tempfile::tempdir().expect("TLS certificate tempdir");
        generate_certificates(certificates.path());
        let requests = Arc::new(Mutex::new(Vec::new()));
        let captured = Arc::clone(&requests);
        let certificate_path = certificates.path().to_path_buf();
        let response_count = responses.len();
        let (ready_tx, ready_rx) = oneshot::channel();
        let task = tokio::spawn(async move {
            let _serial_guard = serial_guard;
            let mut responses = VecDeque::from(responses);
            let (port, mut server) = spawn_ready_server(&certificate_path, response_count).await;
            ready_tx
                .send(port)
                .expect("signal OpenSSL listener readiness");
            let mut stdout = server.stdout.take().expect("OpenSSL stdout");
            let mut stdin = server.stdin.take().expect("OpenSSL stdin");
            while let Some(mut response) = responses.pop_front() {
                let request = read_request(&mut stdout).await;
                if request.is_empty() {
                    break;
                }
                captured.lock().expect("request lock").push(request);
                if let Some((path, token)) = response.rotate_token.take() {
                    tokio::fs::write(path, token).await.expect("rotate token");
                }
                stdin
                    .write_all(&response_bytes(response))
                    .await
                    .expect("write TLS response");
                stdin.flush().await.expect("flush TLS response");
            }
            stdin.shutdown().await.expect("close TLS server input");
            let status = server.wait().await.expect("wait for OpenSSL server");
            assert!(status.success(), "OpenSSL TLS server failed: {status}");
        });
        let port = ready_rx
            .await
            .expect("OpenSSL listener task stopped before readiness");
        Self {
            base_url: format!("https://localhost:{port}/praxis/v1"),
            requests,
            certificates,
            _task: task,
        }
    }

    pub fn ca_path(&self) -> PathBuf {
        self.certificates.path().join("ca.pem")
    }
}

fn spawn_server(port: u16, directory: &Path, connection_count: usize) -> Child {
    let mut command = Command::new("openssl");
    command
        .args([
            "s_server",
            "-quiet",
            "-accept",
            &format!("127.0.0.1:{port}"),
            "-cert",
            "server.pem",
            "-key",
            "server-key.pem",
            "-naccept",
            &connection_count.to_string(),
        ])
        .current_dir(directory)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true);
    command.spawn().expect("spawn OpenSSL TLS server")
}

async fn spawn_ready_server(directory: &Path, connection_count: usize) -> (u16, Child) {
    for _ in 0..10 {
        let reservation = TcpListener::bind("127.0.0.1:0").expect("reserve mock TLS port");
        let port = reservation.local_addr().expect("mock address").port();
        drop(reservation);
        let mut server = spawn_server(port, directory, connection_count);
        if await_listener(&mut server, port).await {
            return (port, server);
        }
        let _ = server.wait().await;
    }
    panic!("OpenSSL TLS listener failed to bind after 10 attempts");
}

async fn await_listener(server: &mut Child, port: u16) -> bool {
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            if server
                .try_wait()
                .expect("poll OpenSSL TLS server")
                .is_some()
            {
                return false;
            }
            match TcpListener::bind(("127.0.0.1", port)) {
                Err(error) if error.kind() == std::io::ErrorKind::AddrInUse => return true,
                Ok(listener) => drop(listener),
                Err(error) => panic!("probe OpenSSL listener: {error}"),
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap_or(false)
}

async fn read_request(stdout: &mut ChildStdout) -> String {
    let mut bytes = Vec::new();
    let mut chunk = [0u8; 2_048];
    loop {
        let read = stdout.read(&mut chunk).await.expect("read TLS request");
        if read == 0 {
            break;
        }
        bytes.extend_from_slice(&chunk[..read]);
        if request_complete(&bytes) {
            break;
        }
    }
    String::from_utf8(bytes).expect("HTTP request UTF-8")
}

fn request_complete(bytes: &[u8]) -> bool {
    let Some(header_end) = bytes.windows(4).position(|window| window == b"\r\n\r\n") else {
        return false;
    };
    let headers = String::from_utf8_lossy(&bytes[..header_end + 4]);
    let length = headers
        .lines()
        .find_map(|line| {
            line.to_ascii_lowercase()
                .strip_prefix("content-length:")
                .map(str::trim)
                .map(str::parse::<usize>)
        })
        .transpose()
        .expect("content length")
        .unwrap_or(0);
    bytes.len() >= header_end + 4 + length
}

fn response_bytes(response: MockResponse) -> Vec<u8> {
    let reason = match response.status {
        200 => "OK",
        304 => "Not Modified",
        401 => "Unauthorized",
        409 => "Conflict",
        302 => "Found",
        _ => "Error",
    };
    let content_length = response.declared_length.unwrap_or(response.body.len());
    let mut head = format!(
        "HTTP/1.1 {} {}\r\ncontent-length: {}\r\nconnection: close\r\n",
        response.status, reason, content_length
    );
    for (name, value) in response.headers {
        head.push_str(&format!("{name}: {value}\r\n"));
    }
    head.push_str("\r\n");
    let mut bytes = head.into_bytes();
    bytes.extend_from_slice(&response.body);
    bytes
}
