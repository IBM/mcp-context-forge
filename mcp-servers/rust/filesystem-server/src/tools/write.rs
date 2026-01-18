use crate::sandbox::Sandbox;
use anyhow::{Context, Result};
use std::path::Path;
use tokio::fs;
use uuid::Uuid;

pub async fn write_file(sandbox: &Sandbox, path: &str, content: String) -> Result<()> {
    tracing::info!("Running write_file {}", path);

    let pathname = Path::new(path);
    let filename = pathname
        .file_name()
        .with_context(|| format!("Could not get filename from path: '{}'", path))?;

    let parent = pathname
        .parent()
        .context("Invalid path: no parent directory")?;

    let canon_parent = sandbox
        .resolve_path(parent.to_str().context("Invalid parent path")?)
        .await?;

    let temp_name = canon_parent.join(format!("tempfile-{}", Uuid::new_v4()));
    let canon_filepath = canon_parent.join(&filename);

    if let Err(e) = fs::write(&temp_name, &content).await {
        tracing::error!("Failed to write temp file: {}", e);
        let _ = fs::remove_file(&temp_name).await;
        anyhow::bail!("Failed to write temp file: {}", e);
    }

    if let Err(e) = fs::rename(&temp_name, &canon_filepath).await {
        tracing::error!("Failed to rename temp file: {}", e);
        let _ = fs::remove_file(&temp_name).await;
        anyhow::bail!("Failed to rename temp file: {}", e);
    }

    tracing::info!("Successfully wrote file: {}", canon_filepath.display());
    Ok(())
}

pub async fn create_directory(sandbox: &Sandbox, path: &str) -> Result<String> {
    tracing::info!("Running create_directory '{}'", path);

    if !Path::new(&path).exists() && sandbox.check_new_folders(path).await? {
        fs::create_dir_all(path)
            .await
            .with_context(|| format!("Could not create dir {}", path))?;
    } else {
        tracing::warn!("Path '{}' already exists", path);
        return Ok(format!("Path '{}' already exists", path));
    }
    Ok(String::new())
}
