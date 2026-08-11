use std::path::Path;
use std::process::{Command, Stdio};

use crate::LauncherError;

pub fn validate(praxis_binary: &Path, bundle_root: &Path) -> Result<(), LauncherError> {
    if !bundle_root.is_dir() || !bundle_root.join("praxis.yaml").is_file() {
        return Err(LauncherError::Process("bundle root is invalid"));
    }
    let status = Command::new(praxis_binary)
        .args(["--validate", "--config", "praxis.yaml"])
        .current_dir(bundle_root)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map_err(|_| LauncherError::Process("failed to execute Praxis validator"))?;
    if status.success() {
        Ok(())
    } else {
        Err(LauncherError::Process("Praxis rejected the bundle"))
    }
}
