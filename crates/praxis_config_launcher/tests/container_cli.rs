use std::fs;
use std::os::unix::fs::PermissionsExt as _;
use std::process::Command;

#[test]
fn build_info_is_machine_readable_and_stable() {
    // Given
    let temporary = tempfile::tempdir().expect("temporary binaries");
    let praxis = temporary.path().join("praxis");
    fs::write(&praxis, b"praxis fixture").expect("write Praxis fixture");

    // When
    let first = build_info(&praxis);
    let second = build_info(&praxis);

    // Then
    assert_eq!(first, second);
    let info: serde_json::Value = serde_json::from_slice(&first).expect("build info JSON");
    assert_eq!(info["praxis_revision"], "ed46eb5");
    assert_eq!(
        info["praxis_commit"],
        "ed46eb5347d99b7aaf1fe67fa40f8c9178b7aa88"
    );
    for field in ["praxis_sha256", "launcher_sha256"] {
        assert_eq!(info[field].as_str().expect("digest").len(), 64);
    }
    assert!(info.get("timestamp").is_none());
    assert!(info.get("path").is_none());
}

#[test]
fn validate_bundle_propagates_native_validator_failure() {
    // Given
    let temporary = tempfile::tempdir().expect("temporary validator");
    let praxis = temporary.path().join("praxis");
    fs::write(&praxis, "#!/bin/sh\nexit 23\n").expect("write validator");
    fs::set_permissions(&praxis, fs::Permissions::from_mode(0o755)).expect("chmod validator");

    // When
    let output = Command::new(env!("CARGO_BIN_EXE_praxis_config_launcher"))
        .args([
            "--validate-bundle",
            temporary.path().to_str().expect("UTF-8 path"),
        ])
        .env("PRAXIS_BINARY", &praxis)
        .output()
        .expect("run launcher validator");

    // Then
    assert!(!output.status.success());
}

fn build_info(praxis: &std::path::Path) -> Vec<u8> {
    let output = Command::new(env!("CARGO_BIN_EXE_praxis_config_launcher"))
        .arg("--build-info")
        .env("PRAXIS_BINARY", praxis)
        .output()
        .expect("run build info");
    assert!(output.status.success());
    output.stdout
}
