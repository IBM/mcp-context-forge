use std::io::Write;

use anyhow::{Context, Result};
use rmcp::schemars;
use serde::{Deserialize, Serialize};
use similar::{ChangeTag, TextDiff};
use tempfile::NamedTempFile;
use tokio::fs;
use tracing_subscriber::fmt::format;

pub async fn move_file(source: &str, destination: &str) -> Result<()> {
    fs::rename(source, destination)
        .await
        .with_context(|| format!("Could not move '{}' to '{}'", source, destination))?;
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

pub async fn edit_file(path: &str, edits: Vec<Edit>, dry_run: bool) -> Result<EditResult> {
    let original = fs::read_to_string(path).await?;
    let new_content = apply_edits(original.clone(), edits);
    let diff = get_diffs(&original, &new_content).join("");

    if !dry_run {
        tracing::info!("Writing edits to file, '{}'", path);
        let dir = std::path::Path::new(path)
            .parent()
            .ok_or_else(|| anyhow::anyhow!("Invalid path"))?;
        let mut tmp = NamedTempFile::new_in(dir)?;
        std::io::Write::write_all(&mut tmp, new_content.as_bytes())?;
        tmp.flush()?;
        tmp.persist(path)?;
    }

    Ok(EditResult {
        diff,
        applied: !dry_run,
    })
}
