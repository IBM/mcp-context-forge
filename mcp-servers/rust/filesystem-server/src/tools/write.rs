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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sandbox::Sandbox;
    use std::sync::Arc;
    use tempfile::TempDir;
    use tokio::fs;

    async fn setup_sandbox(temp_dir: &TempDir) -> Arc<Sandbox> {
        let root = temp_dir.path().to_string_lossy().to_string();
        let sandbox = Sandbox::new(vec![root]).await.expect("sandbox init failed");
        Arc::new(sandbox)
    }

    #[tokio::test]
    async fn test_write_file_success() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("test.txt");
        write_file(
            &sandbox,
            path.to_str().unwrap(),
            "Hello, World!".to_string(),
        )
        .await
        .expect("write_file should succeed");

        let content = fs::read_to_string(&path).await.unwrap();
        assert_eq!(content, "Hello, World!");
    }

    #[tokio::test]
    async fn test_write_file_empty_content() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("empty.txt");
        write_file(&sandbox, path.to_str().unwrap(), "".to_string())
            .await
            .expect("write_file should succeed");

        let content = fs::read_to_string(&path).await.unwrap();
        assert_eq!(content, "");
    }

    #[tokio::test]
    async fn test_write_file_large_content() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("large.txt");
        let content = "x".repeat(1_000_000);
        write_file(&sandbox, path.to_str().unwrap(), content.clone())
            .await
            .expect("write_file should succeed");

        let read_content = fs::read_to_string(&path).await.unwrap();
        assert_eq!(read_content.len(), content.len());
    }

    #[tokio::test]
    async fn test_write_file_overwrite_existing() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("overwrite.txt");
        fs::write(&path, "initial").await.unwrap();

        write_file(&sandbox, path.to_str().unwrap(), "updated".to_string())
            .await
            .expect("write_file should succeed");

        let content = fs::read_to_string(&path).await.unwrap();
        assert_eq!(content, "updated");
    }

    #[tokio::test]
    async fn test_write_file_nested_subdir() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let subdir = temp_dir.path().join("sub");
        fs::create_dir_all(&subdir).await.unwrap();

        let path = subdir.join("nested.txt");
        write_file(&sandbox, path.to_str().unwrap(), "nested".to_string())
            .await
            .expect("write_file should succeed");

        let content = fs::read_to_string(&path).await.unwrap();
        assert_eq!(content, "nested");
    }

    #[tokio::test]
    async fn test_write_file_multiple_dots_in_filename() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("file.backup.tar.gz");
        write_file(&sandbox, path.to_str().unwrap(), "data".to_string())
            .await
            .expect("write_file should succeed");

        let content = fs::read_to_string(&path).await.unwrap();
        assert_eq!(content, "data");
    }

    #[tokio::test]
    async fn test_write_file_no_extension() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("README");
        write_file(&sandbox, path.to_str().unwrap(), "content".to_string())
            .await
            .expect("write_file should succeed");

        let content = fs::read_to_string(&path).await.unwrap();
        assert_eq!(content, "content");
    }

    #[tokio::test]
    async fn test_create_directory_success() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("newdir");
        let result = create_directory(&sandbox, path.to_str().unwrap())
            .await
            .unwrap();

        assert_eq!(result, "");
        assert!(path.exists());
    }

    #[tokio::test]
    async fn test_create_directory_nested() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("a/b/c");
        create_directory(&sandbox, path.to_str().unwrap())
            .await
            .unwrap();

        assert!(path.exists());
    }

    #[tokio::test]
    async fn test_create_directory_already_exists() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("existing");
        fs::create_dir(&path).await.unwrap();

        let result = create_directory(&sandbox, path.to_str().unwrap())
            .await
            .unwrap();
        assert!(result.contains("already exists"));
        assert!(path.exists());
    }

    #[tokio::test]
    async fn test_create_directory_already_exists_as_file() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("file.txt");
        fs::write(&path, "data").await.unwrap();

        let result = create_directory(&sandbox, path.to_str().unwrap())
            .await
            .unwrap();
        assert!(result.contains("already exists"));
    }

    #[tokio::test]
    async fn test_create_directory_with_trailing_slash() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = format!("{}/trailing/", temp_dir.path().to_string_lossy());
        create_directory(&sandbox, &path).await.unwrap();

        let check_path = temp_dir.path().join("trailing");
        assert!(check_path.exists());
    }
}
