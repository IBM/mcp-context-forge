use anyhow::{Context, Result};
use globset::{Glob, GlobSet, GlobSetBuilder};
use ignore::WalkBuilder;
use std::path::Path;
use tokio::fs;

pub async fn search_files(
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

    let mut files = Vec::new();
    let path = Path::new(path);
    let patterns = build_patterns(pattern, exclude_patterns)
        .with_context(|| format!("Failed to build search patterns"))?;

    // Build a walk builder
    let walker = WalkBuilder::new(path).standard_filters(false).build();

    for entry in walker {
        match entry {
            Ok(entry) => {
                let file_type = entry.file_type();
                if file_type.map(|ft| ft.is_file()).unwrap_or(false) {
                    let file_name = &entry.file_name().to_string_lossy().to_string().to_lowercase();
                    // Match *.rs and exclude files with "test" in name
                    if patterns.include.is_match(file_name) && !patterns.exclude.is_match(file_name)
                    {
                        files.push(String::from(entry.path().to_str().unwrap_or_default()));
                    }
                }
            }
            Err(why) => {
                tracing::warn!("{}", why);
                continue;
            }
        }
    }
    files.sort();
    Ok(files)
}

struct Patterns {
    include: GlobSet,
    exclude: GlobSet,
}

fn build_patterns(pattern: &str, exclude_patterns: Vec<String>) -> Result<Patterns> {
    let mut include_builder = GlobSetBuilder::new();
    let mut exclude_builder = GlobSetBuilder::new();

    include_builder.add(
        Glob::new(&pattern.to_lowercase()).with_context(|| format!("invalid include glob pattern: '{pattern}'"))?,
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

pub async fn list_directory(path: &str) -> Result<Vec<String>> {
    // List content of a folder and return the files and folders inside alfabetically
    tracing::info!("Running list directory for {}", path);
    let mut entries = fs::read_dir(path)
        .await
        .context(format!("Failed to read directory: {}", path))?;

    let mut results = Vec::new();

    while let Some(entry) = entries.next_entry().await? {
        let mut name = entry.file_name().to_string_lossy().to_string();

        let file_type = entry.file_type().await?;
        if file_type.is_dir() {
            name.push('/');
        }
        results.push(name);
    }
    results.sort();

    Ok(results)
}
