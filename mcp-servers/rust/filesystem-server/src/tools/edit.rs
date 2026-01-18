use crate::Sandbox;
use anyhow::{Context, Result};
use rmcp::schemars;
use serde::{Deserialize, Serialize};
use similar::{ChangeTag, TextDiff};
use std::{io::Write, path::Path};
use tempfile::NamedTempFile;
use tokio::fs;

pub async fn move_file(sandbox: &Sandbox, source: &str, destination: &str) -> anyhow::Result<()> {
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

    Ok(())
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct Edit {
    old: String,
    new: String,
}

fn apply_edits(mut content: String, edits: Vec<Edit>) -> String {
    for edit in edits {
        if !content.contains(&edit.old) {
            tracing::error!("Content not found in file {}", &edit.old);
        } else {
            content = content.replace(&edit.old, &edit.new);
        }
    }
    content
}

fn get_diffs(old_content: &str, new_content: &str) -> Vec<String> {
    let mut result: Vec<String> = vec![];
    let diff = TextDiff::from_lines(old_content, new_content);
    for change in diff.iter_all_changes() {
        let sign = match change.tag() {
            ChangeTag::Delete => "-",
            ChangeTag::Insert => "+",
            ChangeTag::Equal => " ",
        };
        result.push(format!("{}{}", sign, change));
    }
    result
}

#[derive(Debug, Serialize, schemars::JsonSchema)]
pub struct EditResult {
    pub diff: String,
    pub applied: bool,
}

pub async fn edit_file(
    sandbox: &Sandbox,
    path: &str,
    edits: Vec<Edit>,
    dry_run: bool,
) -> Result<EditResult> {
    let canon_path = sandbox.resolve_path(path).await?;

    let original: String = fs::read_to_string(&canon_path)
        .await
        .with_context(|| format!("Could not read file '{}'", canon_path.display()))?;

    let new_content = apply_edits(original.clone(), edits);
    let diff = get_diffs(&original, &new_content).join("");

    if !dry_run {
        let dir = canon_path
            .parent()
            .ok_or_else(|| anyhow::anyhow!("Invalid path"))?;
        let mut tmp = NamedTempFile::new_in(dir)
            .with_context(|| format!("Could not create temp file in '{}'", dir.display()))?;

        std::io::Write::write_all(&mut tmp, new_content.as_bytes())
            .with_context(|| format!("Could not write to temp file in '{}'", dir.display()))?;
        tmp.flush()?;

        tmp.persist(&canon_path)
            .with_context(|| format!("Could not persist edits to '{}'", canon_path.display()))?;
    }

    Ok(EditResult {
        diff,
        applied: !dry_run,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Sandbox;
    use std::sync::Arc;
    use tempfile::TempDir;
    use tokio::fs;

    async fn setup_sandbox(temp_dir: &TempDir) -> Arc<Sandbox> {
        let root = temp_dir.path().to_string_lossy().to_string();
        Arc::new(Sandbox::new(vec![root]).await.expect("sandbox init failed"))
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

    #[tokio::test]
    async fn test_edit_file_no_edits_dry_run() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("file.txt");
        fs::write(&path, "content").await.unwrap();

        let result = edit_file(&sandbox, path.to_str().unwrap(), vec![], true)
            .await
            .unwrap();

        assert_eq!(result.diff, " content\n"); // diff returns original
        assert!(!result.applied); // dry run
        assert_eq!(fs::read_to_string(&path).await.unwrap(), "content");
    }

    #[tokio::test]
    async fn test_edit_file_apply_edits() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("file.txt");
        fs::write(&path, "hello world").await.unwrap();

        let edits = vec![Edit {
            old: "world".to_string(),
            new: "Rust".to_string(),
        }];

        let result = edit_file(&sandbox, path.to_str().unwrap(), edits, false)
            .await
            .unwrap();

        assert!(result.applied);
        let content = fs::read_to_string(&path).await.unwrap();
        assert_eq!(content, "hello Rust");
        assert!(result.diff.contains("+hello Rust") || result.diff.contains("-hello world"));
    }

    #[tokio::test]
    async fn test_edit_file_partial_match() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("file.txt");
        fs::write(&path, "abc123").await.unwrap();

        let edits = vec![Edit {
            old: "xyz".to_string(), // does not exist in content
            new: "123".to_string(),
        }];

        let result = edit_file(&sandbox, path.to_str().unwrap(), edits, false)
            .await
            .unwrap();

        // File content should remain unchanged
        let content = fs::read_to_string(&path).await.unwrap();
        assert_eq!(content, "abc123");

        // applied is still true because dry_run = false, even though no change occurred
        assert!(result.applied);

        // Diff should indicate no actual changes
        assert!(result.diff.contains(" abc123"));
    }

    #[tokio::test]
    async fn test_edit_file_multiple_edits() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("file.txt");
        fs::write(&path, "line1\nline2\nline3").await.unwrap();

        let edits = vec![
            Edit {
                old: "line1".to_string(),
                new: "L1".to_string(),
            },
            Edit {
                old: "line3".to_string(),
                new: "L3".to_string(),
            },
        ];

        let result = edit_file(&sandbox, path.to_str().unwrap(), edits, false)
            .await
            .unwrap();

        let content = fs::read_to_string(&path).await.unwrap();
        assert_eq!(content, "L1\nline2\nL3");
        assert!(result.diff.contains("-line1") && result.diff.contains("+L1"));
        assert!(result.diff.contains("-line3") && result.diff.contains("+L3"));
    }

    #[tokio::test]
    async fn test_edit_file_unicode_content() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("file.txt");
        fs::write(&path, "你好世界 🦀").await.unwrap();

        let edits = vec![Edit {
            old: "世界".to_string(),
            new: "Rust".to_string(),
        }];

        let result = edit_file(&sandbox, path.to_str().unwrap(), edits, false)
            .await
            .unwrap();

        let content = fs::read_to_string(&path).await.unwrap();
        assert_eq!(content, "你好Rust 🦀");
        assert!(result.diff.contains("-你好世界 🦀") || result.diff.contains("+你好Rust 🦀"));
    }

    #[tokio::test]
    async fn test_edit_file_dry_run_applied_false() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("file.txt");
        fs::write(&path, "original").await.unwrap();

        let edits = vec![Edit {
            old: "original".to_string(),
            new: "changed".to_string(),
        }];

        let result = edit_file(&sandbox, path.to_str().unwrap(), edits, true)
            .await
            .unwrap();

        assert!(!result.applied);
        assert_eq!(fs::read_to_string(&path).await.unwrap(), "original");
    }
    #[tokio::test]
    async fn test_apply_edits_some_missing() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let path = temp_dir.path().join("file.txt");
        fs::write(&path, "abc def").await.unwrap();

        let edits = vec![
            Edit {
                old: "abc".into(),
                new: "ABC".into(),
            },
            Edit {
                old: "xyz".into(),
                new: "XYZ".into(),
            }, // does not exist
        ];

        let result = edit_file(&sandbox, path.to_str().unwrap(), edits, false)
            .await
            .unwrap();

        let content = fs::read_to_string(&path).await.unwrap();
        assert_eq!(content, "ABC def"); // only "abc" replaced
        assert!(result.diff.contains("-abc def") || result.diff.contains("+ABC def"));
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn test_edit_file_temp_write_error() {
        use std::os::unix::fs::PermissionsExt;

        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;
        let path = temp_dir.path().join("file.txt");

        fs::write(&path, "content").await.unwrap();

        // Make parent dir read-only
        let mut perms = fs::metadata(temp_dir.path()).await.unwrap().permissions();
        perms.set_mode(0o555);
        fs::set_permissions(temp_dir.path(), perms).await.unwrap();

        let edits = vec![Edit {
            old: "content".into(),
            new: "new".into(),
        }];
        let result = edit_file(&sandbox, path.to_str().unwrap(), edits, false).await;

        assert!(result.is_err());

        // Restore permissions for cleanup
        let mut perms = fs::metadata(temp_dir.path()).await.unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(temp_dir.path(), perms).await.unwrap();
    }
    #[tokio::test]
    async fn test_edit_file_empty_file() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;
        let path = temp_dir.path().join("empty.txt");

        fs::write(&path, "").await.unwrap();

        let edits = vec![Edit {
            old: "foo".into(),
            new: "bar".into(),
        }];
        let result = edit_file(&sandbox, path.to_str().unwrap(), edits, false)
            .await
            .unwrap();

        assert_eq!(fs::read_to_string(&path).await.unwrap(), "");
        assert!(result.applied);
    }

    #[tokio::test]
    async fn test_edit_file_invalid_path() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;

        let result = edit_file(&sandbox, "/invalid/path.txt", vec![], true).await;
        assert!(result.is_err());
    }
}
