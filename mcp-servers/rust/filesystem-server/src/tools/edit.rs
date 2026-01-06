use anyhow::{Context, Result};
use tokio::fs;

pub async fn move_file(source: &str, destination: &str) -> Result<()> {
    if !fs::try_exists(source).await? {
        anyhow::bail!("Source file '{}' does not exist", source);
    }

    if fs::try_exists(destination).await? {
        anyhow::bail!("Destination file '{}' already exists", destination);
    }

    fs::rename(source, destination)
        .await
        .with_context(|| format!("Could not move '{}' to '{}'", source, destination))?;

    Ok(())
}
