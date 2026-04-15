// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

use std::process::Command;

#[test]
fn binary_starts_and_exits_cleanly_for_http_listener() {
    let output = Command::new(env!("CARGO_BIN_EXE_contextforge-a2a-runtime")) // pragma: allowlist secret
        .arg("--listen-http")
        .arg("127.0.0.1:0")
        .arg("--exit-after-startup-ms")
        .arg("5")
        .arg("--max-concurrent")
        .arg("1")
        .arg("--max-queued")
        .arg("4")
        .output()
        .expect("spawn binary");

    assert!(
        output.status.success(),
        "binary should exit cleanly, stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn binary_exits_non_zero_for_invalid_http_listener() {
    let binary = env!("CARGO_BIN_EXE_contextforge-a2a-runtime"); // pragma: allowlist secret
    let output = Command::new(binary)
        .arg("--listen-http")
        .arg("not-an-addr")
        .output()
        .expect("spawn binary");

    assert!(
        !output.status.success(),
        "binary should fail for invalid listen-http"
    );
    assert!(
        String::from_utf8_lossy(&output.stderr).contains("failed"),
        "stderr should contain failure message: {}",
        String::from_utf8_lossy(&output.stderr)
    );
}
