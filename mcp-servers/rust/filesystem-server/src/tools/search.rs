use anyhow::{Context, Result};
use globset::{Glob, GlobSet, GlobSetBuilder};
use ignore::WalkBuilder;
use tokio::fs;

use crate::sandbox::Sandbox;

pub async fn search_files(
    sandbox: &Sandbox,
    path: &str,
    pattern: &str,
    exclude_patterns: Vec<String>,
) -> Result<Vec<String>> {
    tracing::info!(
        path = %path,
        include_pattern = %pattern,
        exclude_patterns = ?exclude_patterns,
        "starting directory search"
    );

    // Resolve path within sandbox
    let canon_path = sandbox.resolve_path(path).await?;

    let mut files = Vec::new();
    let patterns = build_patterns(pattern, exclude_patterns)
        .with_context(|| "Failed to build search patterns")?;

    let walker = WalkBuilder::new(&canon_path)
        .follow_links(false)
        .standard_filters(false)
        .build();

    for entry in walker {
        match entry {
            Ok(entry) => {
                if entry.file_type().map(|ft| ft.is_file()).unwrap_or(false) {
                    let file_name = entry.file_name().to_string_lossy().to_lowercase();
                    if patterns.include.is_match(&file_name)
                        && !patterns.exclude.is_match(&file_name)
                    {
                        files.push(entry.path().to_string_lossy().to_string());
                    }
                }
            }
            Err(err) => {
                tracing::warn!("{}", err);
                continue;
            }
        }
    }

    files.sort();
    Ok(files)
}

/// List immediate directory contents alphabetically
pub async fn list_directory(sandbox: &Sandbox, path: &str) -> Result<Vec<String>> {
    tracing::info!("Running list directory for {}", path);

    let canon_path = sandbox.resolve_path(path).await?;

    let mut entries = fs::read_dir(&canon_path).await.context(format!(
        "Failed to read directory: {}",
        canon_path.display()
    ))?;

    let mut results = Vec::new();
    while let Some(entry) = entries.next_entry().await? {
        let mut name = entry.file_name().to_string_lossy().to_string();

        let file_type = entry
            .file_type()
            .await
            .with_context(|| format!("Failed to get file type for {:?}", path))?;

        if file_type.is_symlink() {
            tracing::warn!("Skipping symlink {:?}", entry.path());
            continue;
        }
        if file_type.is_dir() {
            name.push('/');
        }
        results.push(name);
    }

    results.sort();
    Ok(results)
}

/// Helper struct to store compiled glob patterns
struct Patterns {
    include: GlobSet,
    exclude: GlobSet,
}

/// Compile include/exclude glob patterns
fn build_patterns(pattern: &str, exclude_patterns: Vec<String>) -> Result<Patterns> {
    let mut include_builder = GlobSetBuilder::new();
    let mut exclude_builder = GlobSetBuilder::new();

    include_builder.add(
        Glob::new(&pattern.to_lowercase())
            .with_context(|| format!("invalid include glob pattern: '{pattern}'"))?,
    );

    for exclude in exclude_patterns {
        exclude_builder.add(
            Glob::new(&exclude.to_lowercase())
                .with_context(|| format!("invalid exclude glob pattern: '{exclude}'"))?,
        );
    }

    Ok(Patterns {
        include: include_builder
            .build()
            .context("failed to build include glob set")?,
        exclude: exclude_builder
            .build()
            .context("failed to build exclude glob set")?,
    })
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
    async fn test_search_files_basic() {
        let temp_dir = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;
        let temp_path = temp_dir.path();

        std::fs::write(temp_path.join("test1.txt"), "content").unwrap();
        std::fs::write(temp_path.join("test2.txt"), "content").unwrap();
        std::fs::create_dir(temp_path.join("subdir")).unwrap();
        std::fs::write(temp_path.join("subdir/test3.txt"), "content").unwrap();

        let files = search_files(&sandbox, temp_path.to_str().unwrap(), "*.txt", vec![])
            .await
            .expect("search_files should succeed");

        assert_eq!(files.len(), 3);
        assert!(files.iter().all(|f| f.ends_with(".txt")));
    }

    #[tokio::test]
    async fn test_search_files_empty_folder() {
        let temp_dir = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;
        let temp_path = temp_dir.path();

        let files = search_files(&sandbox, temp_path.to_str().unwrap(), "*.txt", vec![])
            .await
            .expect("search_files should succeed");
        assert_eq!(files.len(), 0);
    }

    #[tokio::test]
    async fn test_search_files_excluding_patterns() {
        let temp_dir = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;
        let temp_path = temp_dir.path();

        std::fs::write(temp_path.join("test1.txt"), "content").unwrap();
        std::fs::write(temp_path.join("test3md.txt"), "content").unwrap();
        std::fs::write(temp_path.join("test4.md"), "content").unwrap();
        std::fs::create_dir(temp_path.join("subdir")).unwrap();
        std::fs::write(temp_path.join("subdir/test3.txt"), "content").unwrap();

        let files = search_files(
            &sandbox,
            temp_path.to_str().unwrap(),
            "*.txt",
            vec!["*md.txt".to_string(), "*.md".to_string()],
        )
        .await
        .expect("search_files should succeed");

        assert_eq!(files.len(), 2);
        assert!(files.iter().all(|f| f.ends_with(".txt")));
    }

    #[tokio::test]
    async fn test_search_files_case_insensitive_matching() {
        let temp_dir = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;
        let temp_path = temp_dir.path();

        std::fs::write(temp_path.join("TEST.TXT"), "content").unwrap();

        let files = search_files(&sandbox, temp_path.to_str().unwrap(), "*.txt", vec![])
            .await
            .unwrap();

        assert_eq!(files.len(), 1);
    }

    #[tokio::test]
    async fn test_search_files_outside_roots() {
        let temp_dir = tempfile::tempdir().unwrap();
        let out_temp_dir = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let results = search_files(
            &sandbox,
            out_temp_dir.path().to_str().unwrap(),
            "*.txt",
            vec![],
        )
        .await;

        assert_ne!(temp_dir.path(), out_temp_dir.path());
        assert!(results.is_err());
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn test_symlink_inside_root_pointing_outside_is_rejected() {
        use std::os::unix::fs::symlink;

        let root = tempfile::tempdir().unwrap();
        let outside = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&root).await;

        // outside/secret.txt
        std::fs::write(outside.path().join("secret.txt"), "nope").unwrap();

        // root/link -> outside
        symlink(outside.path(), root.path().join("link")).unwrap();

        let result = search_files(&sandbox, root.path().to_str().unwrap(), "*.txt", vec![]).await;

        // MUST NOT leak outside files
        assert!(result.is_err() || result.unwrap().is_empty());
    }

    #[tokio::test]
    async fn test_path_glob_does_not_match() {
        let root = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&root).await;

        std::fs::create_dir(root.path().join("sub")).unwrap();
        std::fs::write(root.path().join("sub/a.txt"), "x").unwrap();

        let files = search_files(&sandbox, root.path().to_str().unwrap(), "sub/*.txt", vec![])
            .await
            .unwrap();

        assert!(files.is_empty());
    }

    #[tokio::test]
    async fn test_dot_dot_path_is_rejected() {
        let root = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&root).await;

        let path = format!("{}/..", root.path().display());

        let result = search_files(&sandbox, &path, "*.txt", vec![]).await;

        assert!(result.is_err());
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn test_symlinked_file_inside_root_is_skipped() {
        use std::os::unix::fs::symlink;

        let root = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&root).await;

        let real = root.path().join("real.txt");
        let link = root.path().join("link.txt");

        std::fs::write(&real, "x").unwrap();
        symlink(&real, &link).unwrap();

        let files = search_files(&sandbox, root.path().to_str().unwrap(), "*.txt", vec![])
            .await
            .unwrap();

        // decide and enforce policy
        assert_eq!(files.len(), 1);
    }
    #[cfg(unix)]
    #[tokio::test]
    async fn test_permission_denied_is_non_fatal() {
        use std::os::unix::fs::PermissionsExt;

        let root = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&root).await;

        let private = root.path().join("private");
        std::fs::create_dir(&private).unwrap();
        std::fs::set_permissions(&private, std::fs::Permissions::from_mode(0o000)).unwrap();

        let result = search_files(&sandbox, root.path().to_str().unwrap(), "*", vec![]).await;

        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_invalid_include_glob_errors() {
        let root = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&root).await;

        let result = search_files(&sandbox, root.path().to_str().unwrap(), "[abc", vec![]).await;

        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_hidden_files_are_included() {
        let temp_dir = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;
        let temp_path = temp_dir.path();

        std::fs::write(temp_path.join(".test.txt"), "content").unwrap();

        let files = search_files(&sandbox, temp_path.to_str().unwrap(), "*.txt", vec![])
            .await
            .unwrap();

        assert_eq!(files.len(), 1);
    }

    #[tokio::test]
    async fn test_list_directory_alfabetically() {
        let temp_dir = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let temp_path = temp_dir.path();
        std::fs::write(temp_path.join("bfile.txt"), "content1").unwrap();
        std::fs::write(temp_path.join("afile.txt"), "content2").unwrap();
        std::fs::create_dir(temp_path.join("subdir")).unwrap();

        let response = list_directory(&sandbox, temp_path.to_str().unwrap())
            .await
            .expect("list_directory should succeed");

        assert_eq!(response, vec!["afile.txt", "bfile.txt", "subdir/"]);
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn test_list_directory_skips_symlink() {
        use std::os::unix::fs::symlink;

        let root = tempfile::tempdir().unwrap();
        let outside = tempfile::tempdir().unwrap();
        let sandbox = setup_sandbox(&root).await;

        std::fs::write(outside.path().join("secret.txt"), "nope").unwrap();
        std::fs::write(root.path().join("file.txt"), "content").unwrap();

        symlink(outside.path(), root.path().join("link")).unwrap();

        let response = list_directory(&sandbox, root.path().to_str().unwrap())
            .await
            .expect("list_directory should succeed");

        assert_eq!(response, vec!["file.txt"]);
    }
}
