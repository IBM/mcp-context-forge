use std::collections::BTreeMap;

use serde_json::json;
use sha2::{Digest as _, Sha256};

use crate::artifact::{
    ArtifactManifest, DocumentDescriptor, VerifiedArtifact, recompute_generation_id,
};
use crate::models::{SafeIdentifier, Sha256Hex};

pub(super) fn artifact(marker: &str) -> VerifiedArtifact {
    let root = serde_json::to_vec(&json!({
        "listeners": [{"filter_chains": [{"filters": [{"config": {"config_path": "cpex/team.yaml"}}]}]}],
        "marker": marker
    }))
    .expect("root JSON");
    let cpex = serde_json::to_vec(&json!({"routes": [], "marker": marker})).expect("cpex JSON");
    artifact_from_documents(BTreeMap::from([
        ("cpex/team.yaml".to_owned(), cpex),
        ("praxis.yaml".to_owned(), root),
    ]))
}

pub(super) fn artifact_from_documents(documents: BTreeMap<String, Vec<u8>>) -> VerifiedArtifact {
    let descriptors = documents
        .iter()
        .map(|(path, content)| DocumentDescriptor {
            path: path.clone(),
            sha256: sha(format!("{:x}", Sha256::digest(content))),
        })
        .collect::<Vec<_>>();
    let mut preimage = Vec::new();
    for (path, content) in &documents {
        for field in [path.as_bytes(), content.as_slice()] {
            preimage.extend_from_slice(
                &u32::try_from(field.len())
                    .expect("test field length")
                    .to_be_bytes(),
            );
            preimage.extend_from_slice(field);
        }
    }
    let mut manifest = ArtifactManifest {
        bundle_schema: "praxis-bundle/v1".to_owned(),
        cpex_contract_version: "cpex/v1".to_owned(),
        documents: descriptors,
        generation_id: sha("0".repeat(64)),
        manifest_schema: "praxis-render-manifest/v1".to_owned(),
        mcp_protocol_version: "2025-11-25".to_owned(),
        minimum_launcher_version: "0.1.0".to_owned(),
        payload_hash: sha(format!("{:x}", Sha256::digest(preimage))),
        praxis_revision: "ed46eb5".to_owned(),
        renderer_version: "1.2.3".to_owned(),
        source_fingerprint: sha("1".repeat(64)),
        target_id: SafeIdentifier::try_from("target-alpha".to_owned()).expect("target id"),
    };
    manifest.generation_id = recompute_generation_id(&manifest).expect("generation id");
    let manifest_bytes =
        serde_json::to_vec(&serde_json::to_value(&manifest).expect("manifest value"))
            .expect("manifest JSON");
    let mut entries = documents;
    entries.insert("render-manifest.json".to_owned(), manifest_bytes);
    let bytes = canonical_archive(&entries);
    let content_hash = format!("{:x}", Sha256::digest(&bytes));
    VerifiedArtifact::forged_for_local_store(bytes, content_hash, manifest)
}

pub(super) fn canonical_archive(entries: &BTreeMap<String, Vec<u8>>) -> Vec<u8> {
    let mut archive = Vec::new();
    for (path, content) in entries {
        let mut header = [0u8; 512];
        let (prefix, name) = split_path(path);
        header[..name.len()].copy_from_slice(name.as_bytes());
        header[100..108].copy_from_slice(b"0000600\0");
        header[108..116].copy_from_slice(b"0000000\0");
        header[116..124].copy_from_slice(b"0000000\0");
        header[124..136].copy_from_slice(format!("{:011o}\0", content.len()).as_bytes());
        header[136..148].copy_from_slice(b"00000000000\0");
        header[148..156].fill(b' ');
        header[156] = b'0';
        header[257..263].copy_from_slice(b"ustar\0");
        header[263..265].copy_from_slice(b"00");
        header[345..345 + prefix.len()].copy_from_slice(prefix.as_bytes());
        let checksum: u32 = header.iter().map(|byte| u32::from(*byte)).sum();
        header[148..156].copy_from_slice(format!("{checksum:06o}\0 ").as_bytes());
        archive.extend_from_slice(&header);
        archive.extend_from_slice(content);
        archive.resize(archive.len().div_ceil(512) * 512, 0);
    }
    archive.extend_from_slice(&[0u8; 1_024]);
    archive
}

fn split_path(path: &str) -> (&str, &str) {
    if path.len() <= 100 {
        return ("", path);
    }
    path.char_indices()
        .rev()
        .find_map(|(index, character)| {
            (character == '/' && index <= 155 && path.len() - index - 1 <= 100)
                .then_some((&path[..index], &path[index + 1..]))
        })
        .expect("representable test path")
}

pub(super) fn sha(value: String) -> Sha256Hex {
    Sha256Hex::try_from(value).expect("SHA-256 fixture")
}
