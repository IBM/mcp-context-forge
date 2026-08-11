use std::fs;
use std::path::Path;

const GOLDEN: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../praxis_config_launcher/fixtures/golden"
);

#[test]
fn validates_real_registered_filters_from_exact_generation_cwd() {
    // Given / When
    let result = praxis_cf_dataplane::validate_generation(Path::new(GOLDEN));

    // Then
    result.expect("golden generation must validate");
}

#[test]
fn rejects_missing_relative_cpex_file_without_mutating_bundle() {
    // Given
    let temporary = tempfile::tempdir().expect("temporary generation");
    copy_tree(Path::new(GOLDEN), temporary.path());
    fs::remove_file(temporary.path().join("cpex/team-red--server-team.yaml"))
        .expect("remove policy fixture");
    let before = fs::read(temporary.path().join("praxis.yaml")).expect("read root before");

    // When
    let result = praxis_cf_dataplane::validate_generation(temporary.path());

    // Then
    assert!(result.is_err());
    assert_eq!(
        fs::read(temporary.path().join("praxis.yaml")).expect("read root after"),
        before
    );
    assert!(
        !temporary
            .path()
            .join("cpex/team-red--server-team.yaml")
            .exists()
    );
}

#[test]
fn ignores_non_file_entries_in_policy_directory() {
    // Given
    let temporary = tempfile::tempdir().expect("temporary generation");
    copy_tree(Path::new(GOLDEN), temporary.path());
    fs::create_dir(temporary.path().join("cpex/cache")).expect("create incidental directory");

    // When
    let result = praxis_cf_dataplane::validate_generation(temporary.path());

    // Then
    result.expect("non-file entries are not generated policies");
}

fn copy_tree(source: &Path, destination: &Path) {
    fs::create_dir_all(destination.join("cpex")).expect("create policy directory");
    fs::copy(source.join("praxis.yaml"), destination.join("praxis.yaml")).expect("copy root");
    for name in ["platform--server-public.yaml", "team-red--server-team.yaml"] {
        fs::copy(
            source.join("cpex").join(name),
            destination.join("cpex").join(name),
        )
        .expect("copy policy");
    }
}
