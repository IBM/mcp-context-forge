use anyhow::{Context, Result};
use tokio::fs;

static MAX_FILE_SIZE: u64 = 1 * 1024 * 1024; // 1 MiB

pub async fn read_file(path: &str) -> Result<String> {
    tracing::info!("Starting read file for {}", path);

    let metadata = fs::metadata(path)
        .await
        .with_context(|| format!("Could not read file {}", path))?;

    if !metadata.is_file() {
        tracing::warn!("path is not a regular file: '{path}'");
        anyhow::bail!("path is not a regular file: '{path}'");
    }

    if metadata.len() > MAX_FILE_SIZE {
        tracing::warn!(
            "file '{path}' exceeds size limit ({} bytes)",
            metadata.len()
        );
        anyhow::bail!(
            "file '{path}' exceeds size limit ({} bytes)",
            metadata.len()
        );
    }

    fs::read_to_string(path)
        .await
        .with_context(|| format!("failed to read file '{path}'"))
}
