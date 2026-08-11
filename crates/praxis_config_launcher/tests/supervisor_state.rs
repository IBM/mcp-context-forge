use chrono::{Duration, TimeZone as _, Utc};
use praxis_config_launcher::models::{DesiredResponse, DirectiveAction};
use praxis_config_launcher::state::{DirectiveDecision, SupervisorState};

fn desired(action: DirectiveAction, generation: Option<&str>, eligible: bool) -> DesiredResponse {
    serde_json::from_value(serde_json::json!({
        "directive_id": "11".repeat(32),
        "response_etag": "22".repeat(32),
        "action": action,
        "rollout_id": "rollout-a",
        "generation_id": generation,
        "policy_epoch": 1,
        "status": "desired",
        "eligible": eligible,
        "eligibility_reason": if eligible { "additive" } else { "removal" },
        "eligibility_deadline": "2099-08-11T02:00:00Z",
        "freshness_deadline": "2026-08-11T03:00:00Z",
        "cohort_replica_ids": ["replica-a"],
        "last_report_sequence": 0,
        "next_report_sequence": 1
    }))
    .expect("valid desired")
}

#[test]
fn supervisor_reports_ordered_activation_and_readiness() {
    let mut state = SupervisorState::new();
    let candidate = "aa".repeat(32);
    let directive = desired(DirectiveAction::Activate, Some(&candidate), true);

    assert_eq!(
        state.observe(&directive),
        DirectiveDecision::Activate(candidate.clone())
    );
    state.mark_prepared(&directive).expect("prepared");
    assert!(!state.is_ready());
    state.mark_canary_passed(&directive).expect("canary");
    assert!(!state.is_ready());
    state.mark_active(&directive).expect("active");

    assert!(state.is_ready());
    assert_eq!(
        state.report_states(),
        &["prepared", "canary_passed", "active"]
    );
}

#[test]
fn supervisor_never_selects_rollback_and_requires_verified_eligible_generation() {
    let mut state = SupervisorState::new();
    let generation = "bb".repeat(32);
    let rollback = desired(DirectiveAction::Rollback, Some(&generation), true);

    assert_eq!(state.observe(&rollback), DirectiveDecision::Reject);
    state.remember_verified(&generation);
    assert_eq!(
        state.observe(&rollback),
        DirectiveDecision::Activate(generation.clone())
    );
    assert_eq!(
        state.observe(&desired(
            DirectiveAction::Rollback,
            Some(&generation),
            false
        )),
        DirectiveDecision::Stop
    );
}

#[test]
fn supervisor_expires_lkg_at_exact_3600_second_deadline() {
    let mut state = SupervisorState::new();
    let generation = "cc".repeat(32);
    let directive = desired(DirectiveAction::Activate, Some(&generation), true);
    state.mark_prepared(&directive).expect("prepared");
    state.mark_canary_passed(&directive).expect("canary");
    state.mark_active(&directive).expect("active");
    let observed = Utc
        .with_ymd_and_hms(2026, 8, 11, 2, 0, 0)
        .single()
        .expect("time");
    state.observe_authenticated(observed);

    assert!(!state.expire_if_stale(observed + Duration::seconds(3_599)));
    assert!(state.is_ready());
    assert!(state.expire_if_stale(observed + Duration::seconds(3_600)));
    assert!(!state.is_ready());
}

#[test]
fn supervisor_failure_is_unready_until_fresh_server_directive() {
    let mut state = SupervisorState::new();
    let generation = "dd".repeat(32);
    let directive = desired(DirectiveAction::Retry, Some(&generation), true);
    state.mark_prepared(&directive).expect("prepared");
    state.mark_failed();

    assert!(!state.is_ready());
    assert_eq!(state.observe(&directive), DirectiveDecision::Wait);
    let mut fresh = desired(DirectiveAction::Stop, None, true);
    fresh.directive_id = praxis_config_launcher::models::Sha256Hex::try_from("99".repeat(32))
        .expect("fresh directive");
    assert_eq!(state.observe(&fresh), DirectiveDecision::Stop);
}
