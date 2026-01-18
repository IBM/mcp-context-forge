use anyhow::{Context, Result};
use std::os::unix::fs::PermissionsExt;
use tokio::fs;
use chrono::{DateTime, Local};
use crate::sandbox::Sandbox;


#[derive(Debug, serde::Serialize)]
struct MetadataResults {
    permissions: String,
    size: u64,
    created: Option<String>,
    modified: Option<String>,
}

fn format_system_time(time: std::time::SystemTime) -> String {
    DateTime::<Local>::from(time).format("%b %d %H:%M").to_string()
}


pub async fn get_file_info(sandbox: &Sandbox, path: &str) -> Result<String> {
    tracing::info!(path = %path, "getting file metadata");

    let canon_path = sandbox.resolve_path(path).await?;

    let metadata = fs::metadata(&canon_path)
        .await
        .with_context(|| format!("failed to read metadata for '{}'", canon_path.display()))?;

    let permissions = format!("{:o}", metadata.permissions().mode() & 0o777);
    let size = metadata.len();

    let created = metadata.created().ok().map(format_system_time);
    let modified = metadata.modified().ok().map(format_system_time);

    let result = MetadataResults {
        permissions,
        size,
        created,
        modified,
    };

    Ok(serde_json::to_string(&result)
        .context("failed to serialize file metadata to JSON")?)
}
