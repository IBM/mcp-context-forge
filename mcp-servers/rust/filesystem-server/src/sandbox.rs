use anyhow::{Context, Result};
use std::path::{Path, PathBuf};
use tokio::fs;

#[derive(Clone)]
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
        self.roots.iter().map(|r| format!("{}", r.display())).collect()
    }

    /// Returns the canonicalized path or an error if outside roots.
    pub async fn resolve_path(&self, path: &str) -> Result<PathBuf> {
        let canon = fs::canonicalize(path)
            .await
            .with_context(|| format!("Could not canonicalize path '{}'", path))?;

        for root in &self.roots {
            if canon.starts_with(root) {
                return Ok(canon);
            }
        }
        anyhow::bail!("Path '{}' is outside sandbox roots", path);
    }
}
