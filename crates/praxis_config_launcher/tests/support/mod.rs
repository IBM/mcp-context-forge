mod certificates;
mod tls;

pub use tls::{MockResponse, TlsMock};

use std::path::PathBuf;

pub fn write_token(directory: &tempfile::TempDir, token: &str) -> PathBuf {
    let path = directory.path().join("token");
    std::fs::write(&path, token).expect("write token fixture");
    path
}

pub fn canonical_archive(manifest: &serde_json::Value) -> Vec<u8> {
    let body = serde_json::to_vec(manifest).expect("manifest JSON");
    let mut header = [0u8; 512];
    header[..20].copy_from_slice(b"render-manifest.json");
    header[100..108].copy_from_slice(b"0000600\0");
    header[108..116].copy_from_slice(b"0000000\0");
    header[116..124].copy_from_slice(b"0000000\0");
    let size = format!("{:011o}\0", body.len());
    header[124..136].copy_from_slice(size.as_bytes());
    header[136..148].copy_from_slice(b"00000000000\0");
    header[148..156].fill(b' ');
    header[156] = b'0';
    header[257..263].copy_from_slice(b"ustar\0");
    header[263..265].copy_from_slice(b"00");
    let checksum: u32 = header.iter().map(|byte| u32::from(*byte)).sum();
    header[148..156].copy_from_slice(format!("{checksum:06o}\0 ").as_bytes());
    let mut archive = header.to_vec();
    archive.extend_from_slice(&body);
    archive.resize(archive.len().div_ceil(512) * 512, 0);
    archive.extend_from_slice(&[0u8; 1_024]);
    archive
}
