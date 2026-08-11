use std::collections::{BTreeMap, BTreeSet};

use serde_json::Value;
use sha2::{Digest as _, Sha256};

use crate::artifact::{
    ArtifactManifest, VerifiedArtifact, launcher_version_satisfies, recompute_generation_id,
};
use crate::error::LauncherError;

mod ustar;

pub(super) const MANIFEST_PATH: &str = "render-manifest.json";

#[derive(Debug)]
pub(super) struct Document {
    pub(super) path: String,
    pub(super) content: Vec<u8>,
}

#[derive(Debug)]
pub(super) struct ParsedArchive {
    pub(super) generation_id: String,
    pub(super) documents: Vec<Document>,
    pub(super) manifest_bytes: Vec<u8>,
}

pub(super) fn validate(artifact: &VerifiedArtifact) -> Result<ParsedArchive, LauncherError> {
    let actual_hash = format!("{:x}", Sha256::digest(artifact.bytes()));
    if actual_hash != artifact.content_hash() {
        return Err(LauncherError::ArtifactHashMismatch);
    }
    let entries = ustar::parse_entries(artifact.bytes())?;
    let manifest_bytes = entries
        .get(MANIFEST_PATH)
        .ok_or(LauncherError::LocalStore("archive manifest is missing"))?;
    let manifest: ArtifactManifest = serde_json::from_slice(manifest_bytes)
        .map_err(|_| LauncherError::LocalStore("archive manifest is invalid"))?;
    if &manifest != artifact.manifest()
        || serde_json::to_vec(
            &serde_json::from_slice::<Value>(manifest_bytes)
                .map_err(|_| LauncherError::LocalStore("archive manifest is invalid"))?,
        )
        .map_err(|_| LauncherError::LocalStore("archive manifest is invalid"))?
            != *manifest_bytes
    {
        return Err(LauncherError::LocalStore(
            "archive manifest is noncanonical or changed",
        ));
    }
    validate_manifest(&manifest, &entries)?;
    let documents = manifest
        .documents
        .iter()
        .map(|descriptor| Document {
            path: descriptor.path.clone(),
            content: entries[&descriptor.path].clone(),
        })
        .collect();
    Ok(ParsedArchive {
        generation_id: manifest.generation_id.as_str().to_owned(),
        documents,
        manifest_bytes: manifest_bytes.to_vec(),
    })
}

pub(super) fn validate_published(
    manifest_bytes: &[u8],
    entries: &BTreeMap<String, Vec<u8>>,
) -> Result<String, LauncherError> {
    let manifest: ArtifactManifest = serde_json::from_slice(manifest_bytes)
        .map_err(|_| LauncherError::LocalStore("published manifest is invalid"))?;
    let canonical = serde_json::to_vec(
        &serde_json::from_slice::<Value>(manifest_bytes)
            .map_err(|_| LauncherError::LocalStore("published manifest is invalid"))?,
    )
    .map_err(|_| LauncherError::LocalStore("published manifest is invalid"))?;
    if canonical != manifest_bytes {
        return Err(LauncherError::LocalStore(
            "published manifest is noncanonical",
        ));
    }
    validate_manifest(&manifest, entries)?;
    Ok(manifest.generation_id.as_str().to_owned())
}

fn validate_manifest(
    manifest: &ArtifactManifest,
    entries: &BTreeMap<String, Vec<u8>>,
) -> Result<(), LauncherError> {
    if manifest.manifest_schema != "praxis-render-manifest/v1"
        || manifest.bundle_schema != "praxis-bundle/v1"
        || manifest.cpex_contract_version != "cpex/v1"
        || manifest.mcp_protocol_version != "2025-11-25"
        || manifest.praxis_revision != "ed46eb5"
        || !launcher_version_satisfies(&manifest.minimum_launcher_version)
        || recompute_generation_id(manifest)? != manifest.generation_id
    {
        return Err(LauncherError::Incompatible(
            "local artifact compatibility failed",
        ));
    }
    let paths: Vec<_> = manifest
        .documents
        .iter()
        .map(|item| item.path.as_str())
        .collect();
    if paths.is_empty()
        || paths.windows(2).any(|pair| pair[0] >= pair[1])
        || entries.len() != paths.len() + 1
        || paths.contains(&MANIFEST_PATH)
    {
        return Err(LauncherError::LocalStore(
            "manifest document set is invalid",
        ));
    }
    for descriptor in &manifest.documents {
        ustar::validate_path(&descriptor.path)?;
        let content = entries
            .get(&descriptor.path)
            .ok_or(LauncherError::LocalStore(
                "manifest references a missing document",
            ))?;
        if format!("{:x}", Sha256::digest(content)) != descriptor.sha256.as_str() {
            return Err(LauncherError::LocalStore(
                "manifest document hash is invalid",
            ));
        }
    }
    validate_payload_hash(manifest, entries)?;
    validate_references(&paths, entries)
}

fn validate_payload_hash(
    manifest: &ArtifactManifest,
    entries: &BTreeMap<String, Vec<u8>>,
) -> Result<(), LauncherError> {
    let mut preimage = Vec::new();
    for descriptor in &manifest.documents {
        for field in [
            descriptor.path.as_bytes(),
            entries[&descriptor.path].as_slice(),
        ] {
            let length = u32::try_from(field.len())
                .map_err(|_| LauncherError::LocalStore("payload field exceeds limit"))?;
            preimage.extend_from_slice(&length.to_be_bytes());
            preimage.extend_from_slice(field);
        }
    }
    if format!("{:x}", Sha256::digest(preimage)) != manifest.payload_hash.as_str() {
        return Err(LauncherError::LocalStore(
            "manifest payload hash is invalid",
        ));
    }
    Ok(())
}

fn validate_references(
    paths: &[&str],
    entries: &BTreeMap<String, Vec<u8>>,
) -> Result<(), LauncherError> {
    let root = entries
        .get("praxis.yaml")
        .ok_or(LauncherError::LocalStore("praxis root document is missing"))?;
    let value: Value = serde_json::from_slice(root)
        .map_err(|_| LauncherError::LocalStore("praxis root document is invalid"))?;
    let mut references = BTreeSet::new();
    collect_config_paths(&value, &mut references)?;
    let documents: BTreeSet<_> = paths
        .iter()
        .filter(|path| **path != "praxis.yaml")
        .copied()
        .collect();
    if references != documents || documents.iter().any(|path| !path.starts_with("cpex/")) {
        return Err(LauncherError::LocalStore(
            "praxis document references are invalid",
        ));
    }
    Ok(())
}

fn collect_config_paths<'a>(
    value: &'a Value,
    found: &mut BTreeSet<&'a str>,
) -> Result<(), LauncherError> {
    match value {
        Value::Object(map) => {
            for (key, nested) in map {
                if key == "config_path" {
                    let path = nested.as_str().ok_or(LauncherError::LocalStore(
                        "praxis config path is not a string",
                    ))?;
                    ustar::validate_path(path)?;
                    if !found.insert(path) {
                        return Err(LauncherError::LocalStore(
                            "praxis config path is duplicated",
                        ));
                    }
                }
                collect_config_paths(nested, found)?;
            }
        }
        Value::Array(items) => {
            for nested in items {
                collect_config_paths(nested, found)?;
            }
        }
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {}
    }
    Ok(())
}
