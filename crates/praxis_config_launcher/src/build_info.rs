use std::fs::File;
use std::io::{BufReader, Read};
use std::path::Path;

use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::LauncherError;

pub const PRAXIS_REVISION: &str = "ed46eb5";
pub const PRAXIS_COMMIT: &str = "ed46eb5347d99b7aaf1fe67fa40f8c9178b7aa88";

#[derive(Debug, Serialize)]
pub struct BuildInfo {
    pub praxis_revision: &'static str,
    pub praxis_commit: &'static str,
    pub praxis_sha256: String,
    pub launcher_sha256: String,
}

pub fn collect(praxis_binary: &Path) -> Result<BuildInfo, LauncherError> {
    let launcher = std::env::current_exe().map_err(|_| LauncherError::BuildInfo)?;
    Ok(BuildInfo {
        praxis_revision: PRAXIS_REVISION,
        praxis_commit: PRAXIS_COMMIT,
        praxis_sha256: hash_file(praxis_binary)?,
        launcher_sha256: hash_file(&launcher)?,
    })
}

fn hash_file(path: &Path) -> Result<String, LauncherError> {
    let file = File::open(path).map_err(|_| LauncherError::BuildInfo)?;
    let mut reader = BufReader::new(file);
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 16 * 1024];
    loop {
        let count = reader
            .read(&mut buffer)
            .map_err(|_| LauncherError::BuildInfo)?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(format!("{:x}", digest.finalize()))
}
