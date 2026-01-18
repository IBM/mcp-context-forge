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
