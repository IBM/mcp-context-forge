use anyhow::{Context, Result};
use std::path::PathBuf;
use tokio::fs;

pub struct Sandbox {
    roots: Vec<PathBuf>,
}

impl Sandbox {
    pub async fn new(roots: Vec<String>) -> Result<Self> {
        let mut out = Vec::with_capacity(roots.len());

        for root in roots {
            let path = PathBuf::from(&root);

            let canon = fs::canonicalize(&path)
                .await
                .with_context(|| format!("Could not use path {:?} as root", root))?;

            out.push(canon);
        }

        Ok(Self { roots: out })
    }
}
