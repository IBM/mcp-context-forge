use anyhow::{Context, Result};
use tokio::fs;

pub async fn list_directory(path: &str) -> Result<Vec<String>> {
    // List content of a folder and return the files and folders inside alfabetically
    tracing::info!("Running list directory for {}", path);
    let mut entries = fs::read_dir(path)
        .await
        .context(format!("Failed to read directory: {}", path))?;

    let mut results = Vec::new();

    while let Some(entry) = entries.next_entry().await? {
        let mut name = entry.file_name().to_string_lossy().to_string();

        let file_type = entry.file_type().await?;
        if file_type.is_dir() {
            name.push('/');
        }
        results.push(name);
    }
    results.sort();

    Ok(results)
}
