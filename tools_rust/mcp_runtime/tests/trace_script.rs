// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

use std::{path::PathBuf, process::Command};

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|path| path.parent())
        .expect("repo root")
        .to_path_buf()
}

#[test]
fn moved_trace_script_parses_and_makefile_points_to_it() {
    let repo_root = repo_root();
    let script_path = repo_root.join("scripts/generate-dial9-trace.sh");
    assert!(script_path.exists(), "trace script should exist at {script_path:?}");

    let bash_check = Command::new("bash")
        .arg("-n")
        .arg(&script_path)
        .current_dir(repo_root.join("tools_rust/mcp_runtime"))
        .output()
        .expect("run bash -n for trace script");
    assert!(
        bash_check.status.success(),
        "trace script should parse cleanly: {}",
        String::from_utf8_lossy(&bash_check.stderr)
    );

    let make_dry_run = Command::new("make")
        .arg("-n")
        .arg("generate-trace")
        .current_dir(repo_root.join("tools_rust/mcp_runtime"))
        .output()
        .expect("run make -n generate-trace");
    let make_output = String::from_utf8_lossy(&make_dry_run.stdout);
    assert!(
        make_output.contains("../../scripts/generate-dial9-trace.sh"),
        "make generate-trace should call the moved script, output was: {make_output}"
    );
}

#[test]
fn telemetry_make_targets_thread_tokio_unstable() {
    let repo_root = repo_root();
    let runtime_dir = repo_root.join("tools_rust/mcp_runtime");

    for target in ["build-telemetry", "test-telemetry", "check-telemetry"] {
        let output = Command::new("make")
            .arg("-n")
            .arg(target)
            .current_dir(&runtime_dir)
            .output()
            .unwrap_or_else(|error| panic!("run make -n {target}: {error}"));
        let stdout = String::from_utf8_lossy(&output.stdout);
        assert!(
            stdout.contains("--cfg tokio_unstable"),
            "{target} should thread tokio_unstable through RUSTFLAGS, output was: {stdout}"
        );
    }
}
