use anyhow::{Context, Result};
use std::path::{Path, PathBuf};
use tokio::fs;

#[derive(Clone, Debug)]
pub struct Sandbox {
    roots: Vec<PathBuf>,
}

impl Sandbox {
    /// Create a sandbox from root paths.
    /// Roots are canonicalized (symlinks resolved) and stored.
    pub async fn new(roots: Vec<String>) -> Result<Self> {
        let mut canon_roots = Vec::with_capacity(roots.len());

        for root in roots {
            let path = PathBuf::from(&root);
            let canon = fs::canonicalize(&path).await.with_context(|| {
                format!("Could use path '{}'. Please check if path is correct", root)
            })?;

            let meta = fs::metadata(&canon)
                .await
                .with_context(|| format!("Could not read metadata for root '{}'", root))?;

            if !meta.is_dir() {
                anyhow::bail!("Root path '{}' is not a directory", root);
            }
            canon_roots.push(canon);
        }

        Ok(Self { roots: canon_roots })
    }

    // Iterate over parents of new folders to check if it is inside a root
    pub async fn check_new_folders(&self, path: &str) -> Result<bool> {
        let path = Path::new(path);
        for ancestor in path.ancestors() {
            if fs::canonicalize(ancestor).await.is_err() {
                continue;
            } else {
                let canon = fs::canonicalize(ancestor).await?;
                return Ok(self.roots.iter().any(|root| canon.starts_with(root)));
            }
        }
        Ok(false)
    }

    pub fn get_roots(&self) -> Vec<String> {
        self.roots
            .iter()
            .map(|r| format!("{}", r.display()))
            .collect()
    }

    /// Returns the canonicalized path or an error if outside roots.
    pub async fn resolve_path(&self, path: &str) -> Result<PathBuf> {
        let canon = fs::canonicalize(path)
            .await
            .with_context(|| format!("Could not find path '{}'", path))?;

        for root in &self.roots {
            if canon.starts_with(root) {
                return Ok(canon);
            }
        }
        anyhow::bail!("Path '{}' is outside sandbox roots", path);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sandbox::Sandbox;
    use std::fs as stdfs;
    use tempfile::TempDir;

    #[tokio::test]
    async fn test_new_valid_root() {
        let temp_dir = TempDir::new().unwrap();
        let path = temp_dir.path().to_string_lossy().to_string();

        let sandbox = Sandbox::new(vec![path.clone()]).await.unwrap();
        let roots = sandbox.get_roots();
        assert_eq!(roots.len(), 1);
        assert!(roots[0].ends_with(temp_dir.path().file_name().unwrap().to_str().unwrap()));
    }

    #[tokio::test]
    async fn test_new_invalid_root_not_dir() {
        use std::fs::File;

        let temp_dir = TempDir::new().unwrap();
        let file_path = temp_dir.path().join("file.txt");

        // create a file instead of a directory
        File::create(&file_path).unwrap();

        let res = Sandbox::new(vec![file_path.to_string_lossy().to_string()]).await;
        assert!(res.is_err());
        assert!(res.unwrap_err().to_string().contains("not a directory"));
    }

    #[tokio::test]
    async fn test_new_nonexistent_root() {
        let path = "/nonexistent/root/path".to_string();
        let res = Sandbox::new(vec![path.clone()]).await;
        assert!(res.is_err());
        assert!(
            res.unwrap_err()
                .to_string()
                .contains("Please check if path is correct")
        );
    }

    #[tokio::test]
    async fn test_resolve_path_inside_root() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = Sandbox::new(vec![temp_dir.path().to_string_lossy().to_string()])
            .await
            .unwrap();

        let file_path = temp_dir.path().join("file.txt");
        stdfs::write(&file_path, "content").unwrap();

        let canon = sandbox
            .resolve_path(file_path.to_str().unwrap())
            .await
            .unwrap();
        assert!(canon.starts_with(temp_dir.path()));
    }

    #[tokio::test]
    async fn test_resolve_path_outside_root() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = Sandbox::new(vec![temp_dir.path().to_string_lossy().to_string()])
            .await
            .unwrap();

        // Create a path outside the sandbox
        let outside_dir = TempDir::new().unwrap();
        let file_path = outside_dir.path().join("file.txt");
        stdfs::write(&file_path, "content").unwrap();

        let res = sandbox.resolve_path(file_path.to_str().unwrap()).await;
        assert!(res.is_err());
        assert!(
            res.unwrap_err()
                .to_string()
                .contains("outside sandbox roots")
        );
    }

    #[tokio::test]
    async fn test_check_new_folders_inside_root() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = Sandbox::new(vec![temp_dir.path().to_string_lossy().to_string()])
            .await
            .unwrap();

        let new_folder = temp_dir.path().join("newfolder/sub");
        let result = sandbox
            .check_new_folders(new_folder.to_str().unwrap())
            .await
            .unwrap();

        assert!(result);
    }

    #[tokio::test]
    async fn test_check_new_folders_outside_root() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = Sandbox::new(vec![temp_dir.path().to_string_lossy().to_string()])
            .await
            .unwrap();

        let outside_folder = Path::new("/tmp/this_should_fail");
        let result = sandbox
            .check_new_folders(outside_folder.to_str().unwrap())
            .await
            .unwrap();

        assert!(!result);
    }

    #[tokio::test]
    async fn test_get_roots_multiple() {
        let temp_dir1 = TempDir::new().unwrap();
        let temp_dir2 = TempDir::new().unwrap();

        let sandbox = Sandbox::new(vec![
            temp_dir1.path().to_string_lossy().to_string(),
            temp_dir2.path().to_string_lossy().to_string(),
        ])
        .await
        .unwrap();

        let roots = sandbox.get_roots();
        assert_eq!(roots.len(), 2);
    }

    #[tokio::test]
    async fn test_check_new_folders_nonexistent_path() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = Sandbox::new(vec![temp_dir.path().to_string_lossy().to_string()])
            .await
            .unwrap();

        let nonexistent = temp_dir.path().join("nonexistent/path");
        let result = sandbox
            .check_new_folders(nonexistent.to_str().unwrap())
            .await
            .unwrap();
        assert!(result);
    }

    #[tokio::test]
    async fn test_resolve_path_symlink_inside_root() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = Sandbox::new(vec![temp_dir.path().to_string_lossy().to_string()])
            .await
            .unwrap();

        let target_file = temp_dir.path().join("target.txt");
        stdfs::write(&target_file, "hi").unwrap();
        let symlink_path = temp_dir.path().join("link.txt");
        #[cfg(unix)]
        std::os::unix::fs::symlink(&target_file, &symlink_path).unwrap();

        let canon = sandbox
            .resolve_path(symlink_path.to_str().unwrap())
            .await
            .unwrap();
        assert!(canon.ends_with("target.txt"));
    }

    #[tokio::test]
    async fn test_check_new_folders_with_unresolvable_ancestor() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = Sandbox::new(vec![temp_dir.path().to_string_lossy().to_string()])
            .await
            .unwrap();

        // Include some nonsense path
        let bad_path = Path::new("/this/path/does/not/exist");
        let result = sandbox
            .check_new_folders(bad_path.to_str().unwrap())
            .await
            .unwrap();
        assert!(!result);
    }
}
