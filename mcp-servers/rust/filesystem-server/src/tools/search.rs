use anyhow::{Context, Result};
use globset::{Glob, GlobSet, GlobSetBuilder};
use ignore::WalkBuilder;
use tokio::fs;

use crate::sandbox::Sandbox;

/// Recursively search files under a directory with include/exclude glob patterns
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
        .hidden(true)
        .build();

    for entry in walker {
        match entry {
            Ok(entry) => {
                if entry.file_type().map(|ft| ft.is_file()).unwrap_or(false) {
                    let file_name = entry.file_name().to_string_lossy().to_lowercase();
                    if patterns.include.is_match(&file_name) && !patterns.exclude.is_match(&file_name)
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

    let mut entries = fs::read_dir(&canon_path)
        .await
        .context(format!("Failed to read directory: {}", canon_path.display()))?;

    let mut results = Vec::new();
    while let Some(entry) = entries.next_entry().await? {
        let mut name = entry.file_name().to_string_lossy().to_string();

        let file_type = entry.file_type().await?;
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
        include: include_builder.build().context("failed to build include glob set")?,
        exclude: exclude_builder.build().context("failed to build exclude glob set")?,
    })
}
