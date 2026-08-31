// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

use std::{net::TcpListener, process::Command};

fn free_tcp_addr() -> String {
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind ephemeral port");
    let addr = listener.local_addr().expect("local addr");
    drop(listener);
    addr.to_string()
}

#[test]
fn binary_can_start_and_exit_cleanly_with_hidden_shutdown_flag() {
    let output = Command::new(env!("CARGO_BIN_EXE_contextforge_mcp_runtime"))
        .arg("--listen-http")
        .arg(free_tcp_addr())
        .arg("--backend-rpc-url")
        .arg("http://127.0.0.1:4444/rpc")
        .arg("--log-filter")
        .arg("error")
        .arg("--exit-after-startup-ms")
        .arg("10")
        .env("AUTH_ENCRYPTION_SECRET", "test-auth-encryption-secret")
        .output()
        .expect("run runtime binary");

    assert!(
        output.status.success(),
        "expected success, stderr was: {}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn binary_exits_with_failure_for_invalid_listen_address() {
    let output = Command::new(env!("CARGO_BIN_EXE_contextforge_mcp_runtime"))
        .arg("--listen-http")
        .arg("not-an-addr")
        .arg("--backend-rpc-url")
        .arg("http://127.0.0.1:4444/rpc")
        .arg("--log-filter")
        .arg("error")
        .env("AUTH_ENCRYPTION_SECRET", "test-auth-encryption-secret")
        .output()
        .expect("run runtime binary");

    assert!(!output.status.success(), "expected non-zero exit status");
    assert!(
        String::from_utf8_lossy(&output.stderr).contains("contextforge-mcp-runtime failed"),
        "stderr was: {}",
        String::from_utf8_lossy(&output.stderr)
    );
}
