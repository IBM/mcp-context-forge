use crate::sandbox::Sandbox;
use anyhow::{Context, Result};
use futures::future::join_all;
use tokio::{fs, io::AsyncReadExt};

static MAX_FILE_SIZE: u64 = 1 * 1024 * 1024; // TODO: move to config

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
            MAX_FILE_SIZE
        );
    }

    let mut contents = String::with_capacity(metadata.len() as usize);

    file.take(MAX_FILE_SIZE + 1)
        .read_to_string(&mut contents)
        .await
        .with_context(|| format!("failed to read file '{}'", canon_path.display()))?;

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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sandbox::Sandbox;
    use std::sync::Arc;
    use tempfile::TempDir;

    async fn setup_sandbox(temp_dir: &TempDir) -> Arc<Sandbox> {
        let root = temp_dir.path().to_string_lossy().to_string();
        let sandbox = Sandbox::new(vec![root]).await.expect("sandbox init failed");
        Arc::new(sandbox)
    }

    #[tokio::test]
    async fn test_read_file() {
        let temp_dir = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;
        let temp_filepath = temp_dir.path().join("test1.txt");
        std::fs::write(&temp_filepath, "content").unwrap();
        let result = read_file(&sandbox, temp_filepath.to_str().unwrap())
            .await
            .expect("search_files should succeed");
        assert_eq!(result, "content".to_string());
    }

    #[tokio::test]
    async fn test_read_file_no_file() {
        let temp_dir = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;
        let result = read_file(&sandbox, temp_dir.path().to_str().unwrap()).await;
        let err = &result.unwrap_err().to_string();

        assert_eq!(
            err,
            &format!(
                "'{}' is not a regular file",
                temp_dir.path().to_str().unwrap()
            )
        );
    }
    #[tokio::test]
    async fn test_read_empty_file() {
        let temp_dir = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;
        let path = temp_dir.path().join("empty.txt");

        std::fs::write(&path, "").unwrap();

        let result = read_file(&sandbox, path.to_str().unwrap()).await.unwrap();
        assert_eq!(result, "");
    }

    #[tokio::test]
    async fn test_read_file_outside_roots() {
        let temp_dir = tempfile::tempdir().unwrap();
        let out_temp_dir = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let result = read_file(&sandbox, out_temp_dir.path().to_str().unwrap()).await;
        assert_ne!(temp_dir.path(), out_temp_dir.path());
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_read_file_bigger_than_max_size() {
        let temp_dir = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;
        let temp_filepath = temp_dir.path().join("test1.txt");
        std::fs::write(
            &temp_filepath,
            "content ".repeat(usize::try_from(MAX_FILE_SIZE).unwrap()),
        )
        .unwrap();

        let result = read_file(&sandbox, temp_filepath.to_str().unwrap()).await;
        let err = &result.unwrap_err().to_string();

        assert_eq!(
            err,
            &format!(
                "File '{}' exceeds size limit ({} bytes)",
                temp_filepath.to_str().unwrap(),
                MAX_FILE_SIZE
            )
        );
    }

    #[tokio::test]
    async fn test_read_multiple_files() {
        let temp_dir = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let file1 = temp_dir.path().join("test1.txt");
        let file2 = temp_dir.path().join("test2.txt");

        std::fs::write(&file1, "content1").unwrap();
        std::fs::write(&file2, "content2").unwrap();

        let results = read_multiple_files(
            &sandbox,
            vec![
                file1.to_str().unwrap().to_string(),
                file2.to_str().unwrap().to_string(),
            ],
        )
        .await
        .expect("read_multiple_files should succeed");

        assert_eq!(results.len(), 2);
        assert_eq!(results[0], "content1");
        assert_eq!(results[1], "content2");
    }

    #[tokio::test]
    async fn test_read_multiple_files_partial_failure() {
        let temp_dir = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let good = temp_dir.path().join("good.txt");
        let bad = temp_dir.path().join("bad.txt");

        std::fs::write(&good, "content").unwrap();
        // bad does not exist

        let results = read_multiple_files(
            &sandbox,
            vec![
                good.to_str().unwrap().to_string(),
                bad.to_str().unwrap().to_string(),
            ],
        )
        .await
        .unwrap();

        assert_eq!(results.len(), 1);
        assert_eq!(results[0], "content");
    }
}
