use crate::sandbox::Sandbox;
use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::path::Path;
use tokio::fs;
use uuid::Uuid;

#[derive(Serialize, Deserialize, Debug)]
pub struct WriteResult {
    pub message: String,
    pub success: bool,
}

pub async fn write_file(sandbox: &Sandbox, path: &str, content: String) -> Result<String> {
    tracing::info!("write_file {}", path);
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
    let canon_filepath = canon_parent.join(filename);
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
    tracing::info!("Successfully wrote file: {}", &canon_filepath.display());
    Ok(format!(
        "Successfully wrote file to {}",
        &canon_filepath.display()
    ))
}

pub async fn create_directory(sandbox: &Sandbox, path: &str) -> Result<String> {
    tracing::info!("create directory '{}'", path);

    match fs::metadata(path).await {
        Ok(metadata) if metadata.is_file() => {
            tracing::warn!("Path '{}' is a file", path);
            anyhow::bail!("Path '{}' is a file", path);
        }
        _ => {}
    }

    if sandbox.resolve_path(path).await.is_ok() {
        tracing::warn!("Path '{}' already exists", path);
        anyhow::bail!("Path '{}' already exists", path);
    }

    if sandbox.check_new_folders(path).await? {
        fs::create_dir_all(path)
            .await
            .with_context(|| format!("Could not create dir {}", path))?;
        tracing::info!("Path '{}' created.", path);
    } else {
        tracing::warn!("Not authorized, path '{}' outside roots", path);
        anyhow::bail!("Not authorized, path '{}' outside roots", path);
    }
    Ok(format!("Path '{}' created.", path))
}

pub async fn move_file(
    sandbox: &Sandbox,
    source: &str,
    destination: &str,
) -> anyhow::Result<String> {
    let source_canon_path = sandbox.resolve_path(source).await?;

    let dest_path = Path::new(destination);
    let dest_filename = dest_path
        .file_name()
        .with_context(|| format!("Could not get filename from path: '{:?}'", dest_path))?;

    let dest_parent = dest_path
        .parent()
        .context("Invalid path: no parent directory")?;

    let dest_canon_parent = sandbox
        .resolve_path(
            dest_parent
                .to_str()
                .context("Invalid destination parent path")?,
        )
        .await?;

    tokio::fs::rename(&source_canon_path, dest_canon_parent.join(dest_filename))
        .await
        .with_context(|| {
            format!(
                "Could not move '{}' to '{}'",
                source_canon_path.display(),
                dest_filename.display()
            )
        })?;
    tracing::info!(
        "Moved file from {} to {}",
        &source_canon_path.display(),
        dest_canon_parent.join(dest_filename).display()
    );
    Ok(format!(
        "Successfully moved file from {} to {}",
        &source_canon_path.display(),
        dest_canon_parent.join(dest_filename).display()
    ))
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

    // Create directory tests

    #[tokio::test]
    async fn test_create_directory_success() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("newdir");
        let result = create_directory(&sandbox, path.to_str().unwrap()).await;

        assert!(result.is_ok());
        assert_eq!(
            result.unwrap(),
            format!("Path '{}' created.", path.display())
        );
    }

    #[tokio::test]
    async fn test_create_directory_nested() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("a/b/c");
        let result = create_directory(&sandbox, &path.to_str().unwrap()).await;

        assert_eq!(
            result.unwrap().to_string(),
            format!("Path '{}' created.", path.display())
        );
    }

    #[tokio::test]
    async fn test_create_directory_already_exists() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("existing");
        fs::create_dir(&path).await.unwrap();

        let result = create_directory(&sandbox, path.to_str().unwrap()).await;
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("already exists"));
        assert!(path.exists());
    }

    #[tokio::test]
    async fn test_create_directory_already_exists_as_file() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("file.txt");
        fs::write(&path, "data").await.unwrap();

        let result = create_directory(&sandbox, path.to_str().unwrap()).await;
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("is a file"));
    }

    #[tokio::test]
    async fn test_create_directory_with_trailing_slash() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = format!("{}/trailing/", temp_dir.path().to_string_lossy());
        let result = create_directory(&sandbox, &path).await.unwrap();

        let check_path = temp_dir.path().join("trailing");
        assert!(check_path.exists());
        assert_eq!(result, format!("Path '{}' created.", path));
    }

    #[tokio::test]
    async fn test_move_file_success() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let src_path = temp_dir.path().join("src.txt");
        fs::write(&src_path, "hello").await.unwrap();
        let dst_path = temp_dir.path().join("dst.txt");

        move_file(
            &sandbox,
            src_path.to_str().unwrap(),
            dst_path.to_str().unwrap(),
        )
        .await
        .expect("move_file should succeed");

        assert!(!src_path.exists());
        assert!(dst_path.exists());
        assert_eq!(fs::read_to_string(&dst_path).await.unwrap(), "hello");
    }

    #[tokio::test]
    async fn test_move_file_overwrite() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let src = temp_dir.path().join("src.txt");
        let dst = temp_dir.path().join("dst.txt");

        fs::write(&src, "new").await.unwrap();
        fs::write(&dst, "old").await.unwrap();

        move_file(&sandbox, src.to_str().unwrap(), dst.to_str().unwrap())
            .await
            .expect("move_file should overwrite");

        assert_eq!(fs::read_to_string(&dst).await.unwrap(), "new");
        assert!(!src.exists());
    }

    #[tokio::test]
    async fn test_move_file_nested_destination() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let nested_dir = temp_dir.path().join("subdir");
        fs::create_dir_all(&nested_dir).await.unwrap();

        let src = temp_dir.path().join("file.txt");
        let dst = nested_dir.join("file.txt");

        fs::write(&src, "data").await.unwrap();
        move_file(&sandbox, src.to_str().unwrap(), dst.to_str().unwrap())
            .await
            .unwrap();

        assert!(dst.exists());
        assert!(!src.exists());
    }

    #[tokio::test]
    async fn test_move_file_invalid_source() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let result = move_file(
            &sandbox,
            temp_dir.path().join("missing.txt").to_str().unwrap(),
            temp_dir.path().join("dst.txt").to_str().unwrap(),
        )
        .await;

        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_move_file_invalid_destination() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let src = temp_dir.path().join("src.txt");
        fs::write(&src, "data").await.unwrap();

        // Use root as destination filename (likely invalid)
        let dst = Path::new("/");

        let result = move_file(&sandbox, src.to_str().unwrap(), dst.to_str().unwrap()).await;
        assert!(result.is_err());
        assert!(src.exists()); // original file still exists
    }

    #[tokio::test]
    async fn test_move_file_destination_parent_missing() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let src = temp_dir.path().join("src.txt");
        fs::write(&src, "data").await.unwrap();

        let dst = temp_dir.path().join("missing_dir/dst.txt");

        let result = move_file(&sandbox, src.to_str().unwrap(), dst.to_str().unwrap()).await;
        assert!(result.is_err());
        assert!(src.exists());
    }
}
