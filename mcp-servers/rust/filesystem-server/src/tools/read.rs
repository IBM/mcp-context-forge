use crate::sandbox::Sandbox;
use anyhow::{Context, Result};
use futures::future::join_all;
use tokio::{fs, io::AsyncReadExt};

static MAX_FILE_SIZE: u64 = 1 * 1024 * 1024; // 1 MiB

pub async fn read_file(sandbox: &Sandbox, path: &str) -> Result<String> {
    tracing::info!("Starting read file for {}", path);

    // Resolve the path to its canonical form inside the sandbox
    let canon_path = sandbox.resolve_path(path).await?;

    let file = fs::File::open(&canon_path)
        .await
        .with_context(|| format!("failed to open file '{}'", canon_path.display()))?;

    let metadata = file
        .metadata()
        .await
        .with_context(|| format!("failed to read metadata for '{}'", canon_path.display()))?;

    if !metadata.is_file() {
        anyhow::bail!("'{}' is not a regular file", canon_path.display());
    }

    if metadata.len() > MAX_FILE_SIZE {
        anyhow::bail!(
            "File '{}' exceeds size limit ({} bytes)",
            canon_path.display(),
            metadata.len()
        );
    }

    let mut contents = String::with_capacity(metadata.len() as usize);

    file.take(MAX_FILE_SIZE + 1)
        .read_to_string(&mut contents)
        .await
        .with_context(|| format!("failed to read file '{}'", canon_path.display()))?;

    if contents.len() > MAX_FILE_SIZE as usize {
        anyhow::bail!("File exceeded size limit during read");
    }

    Ok(contents)
}

pub async fn read_multiple_files(sandbox: &Sandbox, paths: Vec<String>) -> Result<Vec<String>> {
    tracing::info!("Starting reading multiple files for {:?}", paths);
    let futures: Vec<_> = paths.iter().map(|item| read_file(sandbox, item)).collect();
    let future_results = join_all(futures).await;

    let mut results: Vec<String> = Vec::new();

    for (path, result) in paths.iter().zip(future_results.iter()) {
        match result {
            Ok(value) => results.push(value.clone()),
            Err(err) => {
                tracing::warn!("Error reading {}: {}", path, err);
            }
        }
    }

    Ok(results)
}
