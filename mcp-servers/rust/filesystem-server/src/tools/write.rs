use anyhow::{Context, Result};
use tokio::fs;
use uuid::Uuid;

use crate::SANDBOX;

pub async fn write_file(path: &str, content: String) -> Result<()> {
    tracing::info!("Running write_file {}", path);

    let sandbox = SANDBOX
        .get()
        .expect("Sandbox must be initialized before use");
    let canon_path = sandbox.resolve_path(path).await?;

    let parent = canon_path
        .parent()
        .context("Invalid path: no parent directory")?;

    let canon_parent = sandbox
        .resolve_path(parent.to_str().context("Invalid parent path")?)
        .await?;

    let temp_name = canon_parent.join(format!("tempfile-{}", Uuid::new_v4()));

    if let Err(e) = fs::write(&temp_name, &content).await {
        tracing::error!("Failed to write temp file: {}", e);
        let _ = fs::remove_file(&temp_name).await;
        anyhow::bail!("Failed to write temp file: {}", e);
    }

    if let Err(e) = fs::rename(&temp_name, &canon_path).await {
        tracing::error!("Failed to rename temp file: {}", e);
        let _ = fs::remove_file(&temp_name).await;
        anyhow::bail!("Failed to rename temp file: {}", e);
    }

    tracing::info!("Successfully wrote file: {}", canon_path.display());
    Ok(())
}

pub async fn create_directory(path: &str) -> Result<()> {
    tracing::info!("Running create_directory '{}'", path);
    let sandbox = SANDBOX
        .get()
        .expect("Sandbox must be initialized before use");

    if sandbox.check_new_folders(path).await? {
        fs::create_dir_all(path)
            .await
            .with_context(|| format!("Could not create dir {}", path))?;
    }
    Ok(())
}
