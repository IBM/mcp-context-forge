use anyhow::{Context, Result};
use std::path::Path;
use tokio::fs;
use uuid::Uuid;

pub async fn write_file(path: &str, content: String) -> Result<()> {
    tracing::info!("Running write_file {}", path);

    let filepath = Path::new(path);
    let temp_name = filepath
        .parent()
        .unwrap()
        .join(format!("tempfile-{}", Uuid::new_v4()));

    if let Err(e) = fs::write(&temp_name, &content).await {
        tracing::error!("Failed to write temp file: {}", e);
        anyhow::bail!("Failed to write temp file: {}", e);
    }

    if let Err(e) = fs::rename(&temp_name, filepath).await {
        tracing::error!("Failed to rename temp file: {}", e);
        // Attempt to clean up temp file
        let _ = fs::remove_file(&temp_name).await;
        anyhow::bail!("Failed to rename temp file: {}", e);
    }
    Ok(())
}

pub async fn create_directory(path: &str) -> Result<()> {
    tracing::info!("Running create_directory '{}'", path);
    fs::create_dir_all(path).await.with_context(|| format!("Could not create dir {}", path))?;
    Ok(())
}
