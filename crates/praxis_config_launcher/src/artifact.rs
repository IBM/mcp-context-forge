use sha2::{Digest, Sha256};

use crate::error::LauncherError;
use crate::models::{Compatibility, DesiredResponse, SafeIdentifier, Sha256Hex};

pub const MAX_ARTIFACT_BYTES: usize = 16 * 1024 * 1024;
const MANIFEST_PATH: &str = "render-manifest.json";

/// Compatibility metadata verified before an artifact can leave the client.
#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct ArtifactManifest {
    pub manifest_schema: String,
    pub bundle_schema: String,
    pub cpex_contract_version: String,
    pub documents: Vec<DocumentDescriptor>,
    pub generation_id: Sha256Hex,
    pub mcp_protocol_version: String,
    pub minimum_launcher_version: String,
    pub payload_hash: Sha256Hex,
    pub praxis_revision: String,
    pub renderer_version: String,
    pub source_fingerprint: Sha256Hex,
    pub target_id: SafeIdentifier,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct DocumentDescriptor {
    pub path: String,
    pub sha256: Sha256Hex,
}

/// Verified canonical archive bytes for later staging by Task 14.
#[derive(Clone, Debug)]
pub struct VerifiedArtifact {
    bytes: Vec<u8>,
    content_hash: String,
    manifest: ArtifactManifest,
}

impl VerifiedArtifact {
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    #[must_use]
    pub const fn manifest(&self) -> &ArtifactManifest {
        &self.manifest
    }

    #[must_use]
    pub fn content_hash(&self) -> &str {
        &self.content_hash
    }

    pub(crate) fn verify(
        bytes: Vec<u8>,
        content_hash: String,
        desired: &DesiredResponse,
    ) -> Result<Self, LauncherError> {
        let manifest_bytes = manifest_entry(&bytes)?;
        let manifest: ArtifactManifest = serde_json::from_slice(manifest_bytes)
            .map_err(|_| LauncherError::Contract("artifact manifest is invalid"))?;
        validate_manifest(&manifest, desired)?;
        Ok(Self {
            bytes,
            content_hash,
            manifest,
        })
    }

    #[cfg(test)]
    pub(crate) fn forged_for_local_store(
        bytes: Vec<u8>,
        content_hash: String,
        manifest: ArtifactManifest,
    ) -> Self {
        Self {
            bytes,
            content_hash,
            manifest,
        }
    }
}

fn manifest_entry(archive: &[u8]) -> Result<&[u8], LauncherError> {
    if archive.len() % 512 != 0 || archive.len() < 1_024 {
        return Err(LauncherError::Contract(
            "artifact is not a complete ustar archive",
        ));
    }
    let mut offset = 0usize;
    while offset
        .checked_add(512)
        .is_some_and(|end| end <= archive.len())
    {
        let header = &archive[offset..offset + 512];
        if header.iter().all(|byte| *byte == 0) {
            break;
        }
        if &header[257..263] != b"ustar\0" || !matches!(header[156], 0 | b'0') {
            return Err(LauncherError::Contract(
                "artifact contains a non-ustar regular entry",
            ));
        }
        let name = nul_text(&header[..100])?;
        let size = octal_size(&header[124..136])?;
        let data_start = offset
            .checked_add(512)
            .ok_or(LauncherError::Contract("artifact offset overflow"))?;
        let data_end = data_start
            .checked_add(size)
            .ok_or(LauncherError::Contract("artifact size overflow"))?;
        if data_end > archive.len() {
            return Err(LauncherError::ArtifactTruncated);
        }
        if name == MANIFEST_PATH {
            return Ok(&archive[data_start..data_end]);
        }
        let padded = size
            .checked_add(511)
            .ok_or(LauncherError::Contract("artifact size overflow"))?
            / 512
            * 512;
        offset = data_start
            .checked_add(padded)
            .ok_or(LauncherError::Contract("artifact offset overflow"))?;
    }
    Err(LauncherError::Contract("artifact manifest is missing"))
}

fn nul_text(field: &[u8]) -> Result<&str, LauncherError> {
    let end = field
        .iter()
        .position(|byte| *byte == 0)
        .unwrap_or(field.len());
    std::str::from_utf8(&field[..end])
        .map_err(|_| LauncherError::Contract("artifact header is not UTF-8"))
}

fn octal_size(field: &[u8]) -> Result<usize, LauncherError> {
    let text = nul_text(field)?.trim();
    usize::from_str_radix(text, 8)
        .map_err(|_| LauncherError::Contract("artifact entry size is invalid"))
}

fn validate_manifest(
    manifest: &ArtifactManifest,
    desired: &DesiredResponse,
) -> Result<(), LauncherError> {
    if manifest.manifest_schema != "praxis-render-manifest/v1"
        || manifest.bundle_schema != "praxis-bundle/v1"
        || manifest.cpex_contract_version != "cpex/v1"
        || manifest.mcp_protocol_version != "2025-11-25"
        || manifest.praxis_revision != "ed46eb5"
    {
        return Err(LauncherError::Incompatible(
            "artifact contract version is unsupported",
        ));
    }
    if !launcher_version_satisfies(&manifest.minimum_launcher_version) {
        return Err(LauncherError::Incompatible(
            "launcher version is below the artifact minimum",
        ));
    }
    let expected = desired
        .generation_id
        .as_ref()
        .ok_or(LauncherError::Contract("stop directives have no artifact"))?;
    if &manifest.generation_id != expected || recompute_generation_id(manifest)? != *expected {
        return Err(LauncherError::Contract(
            "artifact generation identity is invalid",
        ));
    }
    Ok(())
}

pub(crate) fn recompute_generation_id(
    manifest: &ArtifactManifest,
) -> Result<Sha256Hex, LauncherError> {
    let compatibility = Compatibility {
        bundle_schema: manifest.bundle_schema.clone(),
        renderer_version: manifest.renderer_version.clone(),
        praxis_revision: manifest.praxis_revision.clone(),
        cpex_contract_version: manifest.cpex_contract_version.clone(),
        mcp_protocol_version: manifest.mcp_protocol_version.clone(),
        minimum_launcher_version: manifest.minimum_launcher_version.clone(),
    };
    let fields = [
        manifest.target_id.as_str(),
        manifest.source_fingerprint.as_str(),
        &compatibility.bundle_schema,
        &compatibility.renderer_version,
        &compatibility.praxis_revision,
        &compatibility.cpex_contract_version,
        &compatibility.mcp_protocol_version,
        &compatibility.minimum_launcher_version,
        manifest.payload_hash.as_str(),
    ];
    let mut preimage = Vec::new();
    for field in fields {
        let length = u32::try_from(field.len())
            .map_err(|_| LauncherError::Contract("generation field is too long"))?;
        preimage.extend_from_slice(&length.to_be_bytes());
        preimage.extend_from_slice(field.as_bytes());
    }
    Sha256Hex::try_from(format!("{:x}", Sha256::digest(preimage)))
        .map_err(|_| LauncherError::Contract("computed generation hash is invalid"))
}

pub(crate) fn launcher_version_satisfies(required: &str) -> bool {
    fn parse(value: &str) -> Option<[u64; 3]> {
        let mut parts = value.split('.').map(str::parse::<u64>);
        let parsed = [
            parts.next()?.ok()?,
            parts.next()?.ok()?,
            parts.next()?.ok()?,
        ];
        parts.next().is_none().then_some(parsed)
    }
    matches!((parse(env!("CARGO_PKG_VERSION")), parse(required)), (Some(current), Some(minimum)) if current >= minimum)
}
