use std::fs;
use std::os::unix::fs::PermissionsExt as _;

use praxis_config_launcher::persistence::StateStore;
use praxis_config_launcher::state::SupervisorState;
use tempfile::TempDir;

fn write_state(path: &std::path::Path, value: serde_json::Value) {
    fs::write(path, serde_json::to_vec(&value).expect("state JSON")).expect("write state");
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).expect("chmod 0600");
}

fn state_value() -> serde_json::Value {
    serde_json::json!({
        "schema": "praxis-launcher-state/v1",
        "active_generation": null,
        "active_directive": null,
        "pending_directive": null,
        "failed_directive": null,
        "reported_rank": 0,
        "verified_generations": [],
        "last_authenticated_observation": null
    })
}

#[test]
fn supervisor_persistence_rejects_corrupt_or_permissive_state() {
    let root = TempDir::new().expect("tempdir");
    let path = root.path().join("state.json");
    fs::write(&path, b"not-json").expect("write");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("chmod");
    assert!(StateStore::new(&path).load().is_err());

    fs::write(&path, b"{}").expect("replace");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).expect("chmod");
    assert!(StateStore::new(&path).load().is_err());
}

#[test]
fn supervisor_persistence_recovers_verified_state_but_never_pid_readiness() {
    let root = TempDir::new().expect("tempdir");
    let path = root.path().join("state.json");
    let store = StateStore::new(&path);
    let mut state = SupervisorState::new();
    state.remember_verified(&"aa".repeat(32));
    store.save(&state).expect("save");

    let recovered = store.load().expect("recover");
    assert!(!recovered.is_ready());
}

#[test]
fn supervisor_persistence_rejects_each_malformed_directive_identity() {
    let root = TempDir::new().expect("tempdir");
    let path = root.path().join("state.json");
    let generation = "aa".repeat(32);
    let pending = "cc".repeat(32);
    for overrides in [
        serde_json::json!({"active_generation": generation, "active_directive": "NOT-A-SHA256", "reported_rank": 3, "verified_generations": [generation]}),
        serde_json::json!({"pending_directive": "NOT-A-SHA256", "reported_rank": 1}),
        serde_json::json!({"pending_directive": pending, "failed_directive": "NOT-A-SHA256", "reported_rank": 1}),
    ] {
        let mut value = state_value();
        for (key, item) in overrides.as_object().expect("object") {
            value[key] = item.clone();
        }
        write_state(&path, value);
        assert!(
            StateStore::new(&path).load().is_err(),
            "accepted {overrides}"
        );
    }
}

#[test]
fn supervisor_persistence_rejects_impossible_identity_and_rank_shapes() {
    let root = TempDir::new().expect("tempdir");
    let path = root.path().join("state.json");
    let generation = "aa".repeat(32);
    let active = "bb".repeat(32);
    let pending = "cc".repeat(32);
    let cases = [
        serde_json::json!({"active_generation": generation}),
        serde_json::json!({"active_directive": active}),
        serde_json::json!({"active_generation": generation, "active_directive": active, "pending_directive": pending, "reported_rank": 3, "verified_generations": [generation]}),
        serde_json::json!({"failed_directive": pending}),
        serde_json::json!({"pending_directive": pending, "failed_directive": active, "reported_rank": 1}),
        serde_json::json!({"reported_rank": 1}),
        serde_json::json!({"active_generation": generation, "active_directive": active, "reported_rank": 2, "verified_generations": [generation]}),
        serde_json::json!({"pending_directive": pending, "reported_rank": 0}),
        serde_json::json!({"active_generation": generation, "active_directive": active, "reported_rank": 3}),
    ];
    for overrides in cases {
        let mut value = state_value();
        for (key, item) in overrides.as_object().expect("object") {
            value[key] = item.clone();
        }
        write_state(&path, value);
        assert!(
            StateStore::new(&path).load().is_err(),
            "accepted {overrides}"
        );
    }
}

#[test]
fn supervisor_persistence_accepts_coherent_shapes_but_recovers_unready() {
    let root = TempDir::new().expect("tempdir");
    let path = root.path().join("state.json");
    let generation = "aa".repeat(32);
    let active = "bb".repeat(32);
    let pending = "cc".repeat(32);
    for overrides in [
        serde_json::json!({}),
        serde_json::json!({"active_generation": generation, "active_directive": active, "reported_rank": 3, "verified_generations": [generation]}),
        serde_json::json!({"pending_directive": pending, "reported_rank": 1, "verified_generations": [generation]}),
        serde_json::json!({"pending_directive": pending, "failed_directive": pending, "reported_rank": 1, "verified_generations": [generation]}),
    ] {
        let mut value = state_value();
        for (key, item) in overrides.as_object().expect("object") {
            value[key] = item.clone();
        }
        write_state(&path, value);
        assert!(
            !StateStore::new(&path)
                .load()
                .expect("valid shape")
                .is_ready()
        );
    }
}
