use crate::sandbox::Sandbox;
use anyhow::{Context, Result};
use chrono::{DateTime, Local};
use serde::{Deserialize, Serialize};
use std::os::unix::fs::PermissionsExt;
use tokio::fs;

#[derive(Debug, Serialize, Deserialize)]
pub struct MetadataResults {
    pub permissions: String,
    pub size: u64,
    pub created: Option<String>,
    pub modified: Option<String>,
}
#[derive(Debug, Serialize, Deserialize)]
pub struct InfoResult {
    pub message: String,
    pub metadata: Option<MetadataResults>,
    pub success: bool,
}

fn format_system_time(time: std::time::SystemTime) -> String {
    DateTime::<Local>::from(time)
        .format("%b %d %H:%M")
        .to_string()
}

pub async fn get_file_info(sandbox: &Sandbox, path: &str) -> Result<MetadataResults> {
    tracing::info!(path = %path, "getting file metadata");

    let canon_path = sandbox.resolve_path(path).await?;

    let metadata = fs::metadata(&canon_path)
        .await
        .with_context(|| format!("failed to read metadata for '{}'", canon_path.display()))?;

    let permissions = format!("{:o}", metadata.permissions().mode() & 0o777);
    let size = metadata.len();

    let created = metadata.created().ok().map(format_system_time);
    let modified = metadata.modified().ok().map(format_system_time);

    let result = MetadataResults {
        permissions,
        size,
        created,
        modified,
    };

    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;
    use std::sync::Arc;
    use tempfile::TempDir;
    use tokio::fs as async_fs;

    async fn setup_sandbox(temp_dir: &TempDir) -> Arc<Sandbox> {
        let root = temp_dir.path().to_string_lossy().to_string();
        let sandbox = Sandbox::new(vec![root]).await.expect("sandbox init failed");
        Arc::new(sandbox)
    }

    #[tokio::test]
    async fn test_get_file_info_basic() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;
        let file_path = temp_dir.path().join("test.txt");

        async_fs::write(&file_path, b"hello").await.unwrap();

        let metadata = get_file_info(&sandbox, file_path.to_str().unwrap())
            .await
            .unwrap();

        assert_eq!(metadata.size, 5);
        assert!(metadata.permissions.len() > 0);
        assert!(metadata.created.is_some() || metadata.modified.is_some());
    }

    #[tokio::test]
    async fn test_get_file_info_symlink() {
        use std::os::unix::fs::symlink;

        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;
        let target = temp_dir.path().join("target.txt");
        let link = temp_dir.path().join("link.txt");

        async_fs::write(&target, b"content").await.unwrap();
        symlink(&target, &link).unwrap();

        // Should follow symlink
        let metadata = get_file_info(&sandbox, link.to_str().unwrap())
            .await
            .unwrap();

        assert_eq!(metadata.size, 7);
    }

    #[tokio::test]
    async fn test_get_file_info_file_not_found() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;
        let missing = temp_dir.path().join("missing.txt");

        let result = get_file_info(&sandbox, missing.to_str().unwrap()).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_get_file_info_permissions() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;
        let file_path = temp_dir.path().join("perm.txt");

        async_fs::write(&file_path, b"x").await.unwrap();
        let mut perms = async_fs::metadata(&file_path).await.unwrap().permissions();
        perms.set_mode(0o644);
        async_fs::set_permissions(&file_path, perms).await.unwrap();

        let metadata = get_file_info(&sandbox, file_path.to_str().unwrap())
            .await
            .unwrap();

        assert_eq!(metadata.permissions, "644");
    }
}
