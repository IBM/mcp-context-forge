use anyhow::{Context, Result};
use tokio::fs;
use futures::future::join_all;

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


pub async fn read_multiple_files(paths: Vec<String>) -> Result<Vec<String>> {
    tracing::info!("Starting reading multiple files for {:?}", paths);
    let futures: Vec<_> = paths.iter().map(|item| read_file(&item)).collect();
    let future_results = join_all(futures).await;

    let mut results: Vec<String> = vec![];
    for result in future_results {
        match result {
            Ok(value) => results.push(value),
            Err(err) => tracing::warn!("Error: {}", err),
        }
    }
    Ok(results)
}
