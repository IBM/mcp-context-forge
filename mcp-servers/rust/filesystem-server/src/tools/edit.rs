use anyhow::{Context, Error, Result};
use rmcp::schemars;
use serde::{Deserialize, Serialize};
use similar::{ChangeTag, TextDiff};
use tokio::fs;

pub async fn move_file(source: &str, destination: &str) -> Result<()> {
    if !fs::try_exists(source).await? {
        anyhow::bail!("Source file '{}' does not exist", source);
    }

    if fs::try_exists(destination).await? {
        anyhow::bail!("Destination file '{}' already exists", destination);
    }

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
    // this behaviour will be in sandbox
    if !fs::try_exists(&path).await? {
        anyhow::bail!("File '{}' does not exist", &path);
    }
    let file_content = fs::read_to_string(&path)
        .await
        .with_context(|| format!("Could not read file '{}'", path))?;

    let new_content = apply_edits(file_content.clone(), edits);
    let diffs = get_diffs(&file_content, &new_content);
    let diff = diffs.join("");

    if !dry_run {
        tracing::info!("Writing edits to file, '{}'", path);
        fs::write(&path, &new_content)
            .await
            .with_context(|| format!("Could not write file '{}'", path))?;
    }

    Ok(EditResult {
        diff,
        applied: !dry_run,
    })
}
