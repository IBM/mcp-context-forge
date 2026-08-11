use std::collections::BTreeMap;

use sha2::{Digest as _, Sha256};

use crate::artifact::VerifiedArtifact;
use crate::local_store::LocalStore;

use super::support::{artifact, artifact_from_documents};

#[test]
fn local_store_rejects_archive_hash_change_before_creating_tmp_state() {
    // Given
    let temporary = tempfile::tempdir().expect("temporary store parent");
    let root = temporary.path().join("generations");
    let store = LocalStore::open(&root).expect("open store");
    let valid = artifact("hash");
    let mut changed = valid.bytes().to_vec();
    changed[512] ^= 1;
    let forged = VerifiedArtifact::forged_for_local_store(
        changed,
        valid.content_hash().to_owned(),
        valid.manifest().clone(),
    );

    // When
    let result = store.stage(&forged);

    // Then
    assert!(result.is_err());
    assert_eq!(std::fs::read_dir(&root).expect("read root").count(), 0);
}

#[test]
fn local_store_rejects_reordered_complete_members_before_creating_tmp_state() {
    // Given
    let temporary = tempfile::tempdir().expect("temporary store parent");
    let root = temporary.path().join("generations");
    let store = LocalStore::open(&root).expect("open store");
    let valid = artifact("order");
    let reordered = swap_first_two_members(valid.bytes());
    let forged = VerifiedArtifact::forged_for_local_store(
        reordered.clone(),
        format!("{:x}", Sha256::digest(&reordered)),
        valid.manifest().clone(),
    );

    // When
    let result = store.stage(&forged);

    // Then
    assert!(result.is_err());
    assert_eq!(std::fs::read_dir(&root).expect("read root").count(), 0);
}

#[test]
fn local_store_rejects_nonregular_traversal_duplicate_and_noncanonical_members() {
    // Given
    let valid = artifact("headers");
    let cases = [
        mutate_header(valid.bytes(), 156, b'1'),
        mutate_header(valid.bytes(), 156, b'2'),
        mutate_header(valid.bytes(), 156, b'3'),
        mutate_header(valid.bytes(), 156, b'6'),
        mutate_name(valid.bytes(), "../escape"),
        mutate_name(valid.bytes(), "/absolute"),
        duplicate_first_entry(valid.bytes()),
        mutate_header(valid.bytes(), 100, b'7'),
    ];

    // When / Then
    for bytes in cases {
        assert_rejected(bytes, &valid);
    }
}

#[test]
fn local_store_accepts_240_byte_path_and_rejects_241_byte_path() {
    // Given
    let accepted_path = format!("cpex/{}/{}", "a".repeat(134), "b".repeat(100));
    let rejected_path = format!("cpex/{}/{}", "a".repeat(135), "b".repeat(100));
    let accepted = referenced_artifact(&accepted_path);
    let rejected = referenced_artifact(&rejected_path);

    // When
    let temporary = tempfile::tempdir().expect("temporary store parent");
    let store = LocalStore::open(temporary.path().join("store")).expect("open store");
    let result = store.stage(&accepted);

    // Then
    assert!(result.is_ok());
    assert!(store.stage(&rejected).is_err());
}

#[test]
fn local_store_rejects_oversized_and_expansion_claim_archives() {
    // Given
    let valid = artifact("limits");
    let oversized = vec![0u8; crate::artifact::MAX_ARTIFACT_BYTES + 1];
    let mut expansion = valid.bytes().to_vec();
    expansion[124..136].copy_from_slice(b"00400000000\0");
    rewrite_checksum(&mut expansion[..512]);

    // When / Then
    assert_rejected(oversized, &valid);
    assert_rejected(expansion, &valid);
}

fn referenced_artifact(path: &str) -> VerifiedArtifact {
    artifact_from_documents(BTreeMap::from([
        (path.to_owned(), b"{}".to_vec()),
        (
            "praxis.yaml".to_owned(),
            format!(r#"{{"config_path":"{path}"}}"#).into_bytes(),
        ),
    ]))
}

#[test]
fn local_store_rejects_sixty_fifth_file() {
    // Given
    let many = (0..64)
        .map(|index| (format!("cpex/{index:02}.yaml"), b"{}".to_vec()))
        .chain(std::iter::once((
            "praxis.yaml".to_owned(),
            br#"{"config_path":"cpex/00.yaml"}"#.to_vec(),
        )))
        .collect::<BTreeMap<_, _>>();
    let candidate = artifact_from_documents(many);

    // When / Then
    assert_stage_rejected(candidate);
}

fn assert_rejected(bytes: Vec<u8>, valid: &VerifiedArtifact) {
    let hash = format!("{:x}", Sha256::digest(&bytes));
    let forged = VerifiedArtifact::forged_for_local_store(bytes, hash, valid.manifest().clone());
    assert_stage_rejected(forged);
}

fn assert_stage_rejected(artifact: VerifiedArtifact) {
    let temporary = tempfile::tempdir().expect("temporary store parent");
    let store = LocalStore::open(temporary.path().join("store")).expect("open store");
    assert!(store.stage(&artifact).is_err());
}

fn mutate_header(archive: &[u8], offset: usize, value: u8) -> Vec<u8> {
    let mut changed = archive.to_vec();
    changed[offset] = value;
    rewrite_checksum(&mut changed[..512]);
    changed
}

fn mutate_name(archive: &[u8], path: &str) -> Vec<u8> {
    let mut changed = archive.to_vec();
    changed[..100].fill(0);
    changed[..path.len()].copy_from_slice(path.as_bytes());
    rewrite_checksum(&mut changed[..512]);
    changed
}

fn duplicate_first_entry(archive: &[u8]) -> Vec<u8> {
    let size = usize::from_str_radix(
        std::str::from_utf8(&archive[124..135]).expect("size text"),
        8,
    )
    .expect("size");
    let end = 512 + size.div_ceil(512) * 512;
    let mut changed = archive[..end].to_vec();
    changed.extend_from_slice(&archive[..end]);
    changed.extend_from_slice(&archive[end..]);
    changed
}

fn swap_first_two_members(archive: &[u8]) -> Vec<u8> {
    let first_end = member_end(archive, 0);
    let second_end = member_end(archive, first_end);
    let mut reordered = archive[first_end..second_end].to_vec();
    reordered.extend_from_slice(&archive[..first_end]);
    reordered.extend_from_slice(&archive[second_end..]);
    reordered
}

fn member_end(archive: &[u8], offset: usize) -> usize {
    let size = usize::from_str_radix(
        std::str::from_utf8(&archive[offset + 124..offset + 135]).expect("size text"),
        8,
    )
    .expect("size");
    offset + 512 + size.div_ceil(512) * 512
}

fn rewrite_checksum(header: &mut [u8]) {
    header[148..156].fill(b' ');
    let checksum: u32 = header.iter().map(|byte| u32::from(*byte)).sum();
    header[148..156].copy_from_slice(format!("{checksum:06o}\0 ").as_bytes());
}
