#![cfg(unix)]

use std::fs;
use std::future::Future;
use std::net::TcpListener;
use std::os::unix::fs::PermissionsExt as _;
use std::pin::Pin;
use std::time::Duration;

use praxis_config_launcher::LauncherError;
use praxis_config_launcher::models::{DesiredResponse, ReportState};
use praxis_config_launcher::persistence::StateStore;
use praxis_config_launcher::probes::ProbeTimings;
use praxis_config_launcher::process::ProcessSpec;
use praxis_config_launcher::state::SupervisorState;
use praxis_config_launcher::supervisor::{Reporter, Supervisor};
use tempfile::TempDir;

static PROCESS_TEST_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

#[derive(Default)]
struct RecordingReporter {
    states: Vec<String>,
}

impl Reporter for RecordingReporter {
    fn submit<'a>(
        &'a mut self,
        state: &'a ReportState,
    ) -> Pin<Box<dyn Future<Output = Result<(), LauncherError>> + Send + 'a>> {
        self.states.push(match state {
            ReportState::Prepared => "prepared".to_owned(),
            ReportState::CanaryPassed => "canary_passed".to_owned(),
            ReportState::Active => "active".to_owned(),
            ReportState::Failed { failure_category } => format!("failed:{failure_category:?}"),
        });
        Box::pin(async { Ok(()) })
    }
}

fn desired(generation: &str) -> DesiredResponse {
    serde_json::from_value(serde_json::json!({
        "directive_id": generation, "response_etag": "22".repeat(32),
        "action": "activate", "rollout_id": "rollout-a", "generation_id": generation,
        "policy_epoch": 1, "status": "desired", "eligible": true,
        "eligibility_reason": "additive", "eligibility_deadline": "2099-08-11T04:00:00Z",
        "freshness_deadline": "2026-08-11T05:00:00Z", "cohort_replica_ids": ["replica-a"],
        "last_report_sequence": 0, "next_report_sequence": 1
    }))
    .expect("desired")
}

fn fake_praxis(root: &TempDir, port: u16) -> std::path::PathBuf {
    let path = root.path().join("fake-praxis");
    let python_path = root.path().join("fake-praxis.py");
    fs::write(
        &python_path,
        "import socket,subprocess,os\nchild=subprocess.Popen(['sleep','60'])\nopen('grandchild.pid','w').write(str(child.pid))\ns=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',{port}));s.listen()\nwhile True:\n c,_=s.accept();c.recv(4096);c.sendall(b'HTTP/1.1 403 Forbidden\\r\\nContent-Length: 0\\r\\nConnection: close\\r\\n\\r\\n');c.close()\n"
            .replace("{port}", &port.to_string()),
    )
    .expect("write fake Praxis server");
    fs::write(
        &path,
        format!(
            "#!/bin/sh\nif [ \"$3\" = \"--validate\" ]; then exit 0; fi\nexec python3 {:?}\n",
            python_path
        ),
    )
    .expect("write fake Praxis");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o700)).expect("chmod");
    path
}

#[tokio::test]
async fn supervisor_owns_descendants_listener_and_ordered_activation() {
    let _guard = PROCESS_TEST_LOCK.lock().await;
    praxis_config_launcher::process::become_subreaper().expect("subreaper");
    let root = TempDir::new().expect("tempdir");
    let reservation = TcpListener::bind("127.0.0.1:0").expect("reserve port");
    let port = reservation.local_addr().expect("address").port();
    drop(reservation);
    let generation_id = "aa".repeat(32);
    let generation = root.path().join(&generation_id);
    fs::create_dir(&generation).expect("generation");
    fs::write(
        generation.join("praxis.yaml"),
        format!(r#"{{"listeners":[{{"address":"127.0.0.1:{port}"}}],"filter_chains":[{{"filters":[{{"policies":[{{"server_id":"server-a"}}]}}]}}]}}"#),
    )
    .expect("config");
    let mut supervisor = Supervisor::new(
        SupervisorState::new(),
        ProcessSpec::praxis(fake_praxis(&root, port)),
        ProbeTimings {
            activation_timeout: Duration::from_secs(3),
            interval: Duration::from_millis(10),
        },
    );
    let mut reporter = RecordingReporter::default();

    supervisor
        .activate(&desired(&generation_id), &generation, &mut reporter)
        .await
        .expect("activation");
    assert!(supervisor.state().is_ready());
    assert_eq!(reporter.states, ["prepared", "canary_passed", "active"]);
    let first_grandchild = fs::read_to_string(generation.join("grandchild.pid")).expect("pid");
    let successor_id = "bb".repeat(32);
    let successor = root.path().join(&successor_id);
    fs::create_dir(&successor).expect("successor generation");
    fs::write(
        successor.join("praxis.yaml"),
        format!(r#"{{"listeners":[{{"address":"127.0.0.1:{port}"}}],"filter_chains":[{{"filters":[{{"policies":[{{"server_id":"server-a"}}]}}]}}]}}"#),
    )
    .expect("successor config");
    supervisor
        .activate(&desired(&successor_id), &successor, &mut reporter)
        .await
        .expect("successor activation");
    assert_eq!(
        reporter.states,
        [
            "prepared",
            "canary_passed",
            "active",
            "prepared",
            "canary_passed",
            "active"
        ]
    );
    let first_pid = nix::unistd::Pid::from_raw(first_grandchild.parse().expect("numeric pid"));
    assert!(matches!(
        nix::sys::signal::kill(first_pid, None),
        Err(nix::errno::Errno::ESRCH)
    ));
    let grandchild = fs::read_to_string(successor.join("grandchild.pid")).expect("successor pid");
    let persisted = StateStore::new(root.path().join("state.json"));
    persisted
        .save(supervisor.state())
        .expect("persist active state");
    supervisor.stop().await.expect("stop process group");

    assert!(TcpListener::bind(("127.0.0.1", port)).is_ok());
    let pid = nix::unistd::Pid::from_raw(grandchild.parse().expect("numeric pid"));
    assert!(matches!(
        nix::sys::signal::kill(pid, None),
        Err(nix::errno::Errno::ESRCH)
    ));

    let recovered = persisted.load().expect("recover state");
    let mut restarted = Supervisor::new(
        recovered,
        ProcessSpec::praxis(fake_praxis(&root, port)),
        ProbeTimings {
            activation_timeout: Duration::from_secs(3),
            interval: Duration::from_millis(10),
        },
    );
    let mut restart_reports = RecordingReporter::default();
    restarted
        .activate(&desired(&successor_id), &successor, &mut restart_reports)
        .await
        .expect("restart active generation");
    assert!(restart_reports.states.is_empty());
    assert!(restarted.state().is_ready());
    restarted.stop().await.expect("stop restarted group");
}

#[tokio::test]
async fn supervisor_escalates_and_reaps_term_ignoring_process_group() {
    let _guard = PROCESS_TEST_LOCK.lock().await;
    praxis_config_launcher::process::become_subreaper().expect("subreaper");
    let root = TempDir::new().expect("tempdir");
    let spec = ProcessSpec {
        program: "/bin/sh".into(),
        args: vec![
            "-c".into(),
            "trap '' TERM; sleep 60 & echo $! > ignored.pid; wait".into(),
        ],
    };
    let process = praxis_config_launcher::process::ManagedProcess::spawn(&spec, root.path())
        .expect("spawn group");
    for _ in 0..100 {
        if root.path().join("ignored.pid").exists() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
    let descendant = fs::read_to_string(root.path().join("ignored.pid")).expect("descendant pid");

    process
        .stop_with_grace(Duration::from_millis(20), Duration::from_secs(1))
        .await
        .expect("TERM then KILL");

    let pid = nix::unistd::Pid::from_raw(descendant.trim().parse().expect("numeric pid"));
    assert!(matches!(
        nix::sys::signal::kill(pid, None),
        Err(nix::errno::Errno::ESRCH)
    ));
}
