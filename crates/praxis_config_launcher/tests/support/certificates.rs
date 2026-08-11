use std::path::Path;
use std::process::{Command, Stdio};

pub(super) fn ensure_openssl() {
    let status = Command::new("openssl")
        .arg("version")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .expect("openssl executable is required for launcher TLS tests");
    assert!(status.success(), "openssl version check failed");
}

pub(super) fn generate_certificates(directory: &Path) {
    run_openssl(
        directory,
        &[
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=Praxis Launcher Test CA",
            "-keyout",
            "ca-key.pem",
            "-out",
            "ca.pem",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
        ],
    );
    run_openssl(
        directory,
        &[
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            "/CN=localhost",
            "-keyout",
            "server-key.pem",
            "-out",
            "server.csr",
            "-addext",
            "subjectAltName=DNS:localhost",
        ],
    );
    run_openssl(
        directory,
        &[
            "x509",
            "-req",
            "-sha256",
            "-days",
            "1",
            "-in",
            "server.csr",
            "-CA",
            "ca.pem",
            "-CAkey",
            "ca-key.pem",
            "-CAcreateserial",
            "-out",
            "server.pem",
            "-copy_extensions",
            "copy",
        ],
    );
}

fn run_openssl(directory: &Path, arguments: &[&str]) {
    let status = Command::new("openssl")
        .args(arguments)
        .current_dir(directory)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .expect("run openssl certificate command");
    assert!(status.success(), "openssl certificate command failed");
}
