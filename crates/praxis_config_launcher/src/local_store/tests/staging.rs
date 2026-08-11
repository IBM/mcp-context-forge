use std::fs;
use std::os::unix::fs::PermissionsExt as _;

use crate::local_store::{FaultPoint, LocalStore};

use super::support::artifact;

#[test]
fn local_store_stages_exact_permissions_and_reopens_valid_generation() {
    // Given
    let temporary = tempfile::tempdir().expect("temporary store parent");
    let root = temporary.path().join("generations");
    let store = LocalStore::open(&root).expect("open store");
    let artifact = artifact("happy");

    // When
    let generation = store.stage(&artifact).expect("stage generation");
    let reopened = LocalStore::open(&root)
        .expect("restart store")
        .generation(artifact.manifest().generation_id.as_str())
        .expect("verify generation")
        .expect("generation exists");

    // Then
    assert_eq!(generation, reopened);
    assert_eq!(mode(generation.path()), 0o700);
    assert_eq!(mode(&generation.path().join("cpex")), 0o700);
    assert_eq!(mode(&generation.path().join("cpex/team.yaml")), 0o600);
    assert_eq!(mode(&generation.path().join("praxis.yaml")), 0o600);
    assert_eq!(mode(&generation.path().join("render-manifest.json")), 0o600);
}

#[test]
fn local_store_restart_removes_partial_tmp_and_preserves_completed_generation() {
    // Given
    let temporary = tempfile::tempdir().expect("temporary store parent");
    let root = temporary.path().join("generations");
    let store = LocalStore::open(&root).expect("open store");
    let prior = artifact("prior");
    let prior_path = store
        .stage(&prior)
        .expect("stage prior")
        .path()
        .to_path_buf();
    let candidate = artifact("candidate");
    let result = store.stage_with_fault(&candidate, Some(FaultPoint::ManifestWritten));
    assert!(result.is_err());

    // When
    let restarted = LocalStore::open(&root).expect("restart store");

    // Then
    assert!(prior_path.is_dir());
    assert!(
        restarted
            .generation(prior.manifest().generation_id.as_str())
            .expect("verify prior")
            .is_some()
    );
    assert!(
        !root
            .join(format!(
                "{}.tmp",
                candidate.manifest().generation_id.as_str()
            ))
            .exists()
    );
}

#[test]
fn local_store_faults_before_publication_leave_prior_generation_authoritative() {
    // Given
    let points = [
        FaultPoint::TemporaryDirectoryCreated,
        FaultPoint::BeforeDocumentWrite,
        FaultPoint::DocumentWritten,
        FaultPoint::DocumentDirectoryCreated,
        FaultPoint::DocumentsSynced,
        FaultPoint::ManifestWritten,
        FaultPoint::GenerationSynced,
        FaultPoint::BeforePublish,
    ];
    let temporary = tempfile::tempdir().expect("temporary store parent");
    let root = temporary.path().join("generations");
    let store = LocalStore::open(&root).expect("open store");
    let prior = artifact("prior-faults");
    let prior_path = store
        .stage(&prior)
        .expect("stage prior")
        .path()
        .to_path_buf();

    // When / Then
    for (index, point) in points.into_iter().enumerate() {
        let candidate = artifact(&format!("candidate-{index}"));
        assert!(store.stage_with_fault(&candidate, Some(point)).is_err());
        assert!(prior_path.is_dir());
        assert!(
            !root
                .join(candidate.manifest().generation_id.as_str())
                .exists()
        );
        LocalStore::open(&root).expect("restart cleanup");
    }
}

#[test]
fn local_store_writes_manifest_only_after_documents_are_synced() {
    // Given
    let temporary = tempfile::tempdir().expect("temporary store parent");
    let root = temporary.path().join("generations");
    let store = LocalStore::open(&root).expect("open store");
    let candidate = artifact("manifest-last");
    let temporary_generation = root.join(format!(
        "{}.tmp",
        candidate.manifest().generation_id.as_str()
    ));

    // When
    let result = store.stage_with_fault(&candidate, Some(FaultPoint::DocumentsSynced));

    // Then
    assert!(result.is_err());
    assert!(temporary_generation.join("praxis.yaml").is_file());
    assert!(temporary_generation.join("cpex/team.yaml").is_file());
    assert!(!temporary_generation.join("render-manifest.json").exists());
}

#[test]
fn local_store_never_overwrites_completed_generation() {
    // Given
    let temporary = tempfile::tempdir().expect("temporary store parent");
    let root = temporary.path().join("generations");
    let store = LocalStore::open(&root).expect("open store");
    let candidate = artifact("immutable");
    let generation = store.stage(&candidate).expect("first stage");
    let before = fs::read(generation.path().join("praxis.yaml")).expect("read generation");

    // When
    let result = store.stage(&candidate);

    // Then
    assert!(result.is_err());
    assert_eq!(
        fs::read(generation.path().join("praxis.yaml")).expect("reread generation"),
        before
    );
}

#[test]
fn local_store_discards_corrupt_generation_before_verified_restage() {
    // Given
    let temporary = tempfile::tempdir().expect("temporary store parent");
    let root = temporary.path().join("generations");
    let store = LocalStore::open(&root).expect("open store");
    let candidate = artifact("corrupt-local");
    let generation = store.stage(&candidate).expect("stage generation");
    fs::write(generation.path().join("praxis.yaml"), b"corrupt").expect("corrupt generation");
    let generation_id = candidate.manifest().generation_id.as_str();
    assert!(store.generation(generation_id).is_err());

    // When
    store
        .discard_corrupt_generation(generation_id)
        .expect("discard corrupt generation");
    let recovered = store.stage(&candidate).expect("restage verified artifact");

    // Then
    assert_eq!(recovered.path(), root.join(generation_id));
}

fn mode(path: &std::path::Path) -> u32 {
    fs::symlink_metadata(path)
        .expect("metadata")
        .permissions()
        .mode()
        & 0o777
}
