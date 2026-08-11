#![cfg(unix)]

use std::fs;
use std::future::Future;
use std::net::TcpListener;
use std::os::unix::fs::PermissionsExt as _;
use std::pin::Pin;
use std::time::Duration;

use praxis_config_launcher::LauncherError;
use praxis_config_launcher::models::{DesiredResponse, FailureCategory, ReportState};
use praxis_config_launcher::probes::ProbeTimings;
use praxis_config_launcher::process::ProcessSpec;
use praxis_config_launcher::state::SupervisorState;
use praxis_config_launcher::supervisor::{Reporter, Supervisor};
use tempfile::TempDir;

#[derive(Default)]
struct Reports(Vec<ReportState>);

impl Reporter for Reports {
    fn submit<'a>(
        &'a mut self,
        state: &'a ReportState,
    ) -> Pin<Box<dyn Future<Output = Result<(), LauncherError>> + Send + 'a>> {
        self.0.push(state.clone());
        Box::pin(async { Ok(()) })
    }
}

#[tokio::test]
async fn supervisor_candidate_early_exit_reports_one_sanitized_category_and_stays_unready() {
    let root = TempDir::new().expect("tempdir");
    let program = root.path().join("early-exit");
    fs::write(
        &program,
        "#!/bin/sh\nif [ \"$3\" = \"--validate\" ]; then exit 0; fi\nexit 1\n",
    )
    .expect("program");
    fs::set_permissions(&program, fs::Permissions::from_mode(0o700)).expect("chmod");
    let listener = TcpListener::bind("127.0.0.1:0").expect("reserve port");
    let port = listener.local_addr().expect("address").port();
    drop(listener);
    fs::write(
        root.path().join("praxis.yaml"),
        format!(r#"{{"listeners":[{{"address":"127.0.0.1:{port}"}}],"policies":[{{"server_id":"server-a"}}]}}"#),
    )
    .expect("config");
    let desired: DesiredResponse = serde_json::from_value(serde_json::json!({
        "directive_id": "aa".repeat(32), "response_etag": "bb".repeat(32),
        "action": "activate", "rollout_id": "rollout-a", "generation_id": "cc".repeat(32),
        "policy_epoch": 1, "status": "desired", "eligible": true, "eligibility_reason": "additive",
        "eligibility_deadline": "2099-01-01T00:00:00Z", "freshness_deadline": "2099-01-01T01:00:00Z",
        "cohort_replica_ids": ["replica-a"], "last_report_sequence": 0, "next_report_sequence": 1
    }))
    .expect("desired");
    let mut supervisor = Supervisor::new(
        SupervisorState::new(),
        ProcessSpec::praxis(program),
        ProbeTimings {
            activation_timeout: Duration::from_secs(1),
            interval: Duration::from_millis(5),
        },
    );
    let mut reports = Reports::default();

    assert_eq!(
        supervisor
            .activate(&desired, root.path(), &mut reports)
            .await,
        Err(FailureCategory::EarlyExit)
    );
    assert_eq!(
        reports.0,
        [
            ReportState::Prepared,
            ReportState::Failed {
                failure_category: FailureCategory::EarlyExit
            }
        ]
    );
    assert!(!supervisor.state().is_ready());
}
