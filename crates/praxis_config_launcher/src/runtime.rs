use std::env;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::time::Duration;

use chrono::Utc;

use crate::client::{ArtifactFetch, DesiredPoll};
use crate::health::{HealthState, validate_listen_address};
use crate::local_store::{LocalGeneration, LocalStore};
use crate::models::DesiredResponse;
use crate::persistence::StateStore;
use crate::probes::ProbeTimings;
use crate::process::ProcessSpec;
use crate::state::DirectiveDecision;
use crate::supervisor::Supervisor;
use crate::{ArtifactClient, LauncherConfig, LauncherError};

mod reporter;
use reporter::ClientReporter;

pub struct RuntimeConfig {
    pub client: LauncherConfig,
    pub generation_root: PathBuf,
    pub state_path: PathBuf,
    pub praxis_binary: PathBuf,
    pub health_address: SocketAddr,
    pub probe_timings: ProbeTimings,
    pub e2e_stale_age_path: Option<PathBuf>,
}

impl RuntimeConfig {
    pub fn from_env() -> Result<Self, LauncherError> {
        let url = required("PRAXIS_CONTROL_PLANE_URL")?;
        let ca = PathBuf::from(required("PRAXIS_CA_PATH")?);
        let token = PathBuf::from(required("PRAXIS_TOKEN_PATH")?);
        let generation_root = PathBuf::from(required("PRAXIS_GENERATION_ROOT")?);
        let state_path = PathBuf::from(required("PRAXIS_STATE_PATH")?);
        let praxis_binary = PathBuf::from(required("PRAXIS_BINARY")?);
        let health_address = required("PRAXIS_HEALTH_LISTEN")?
            .parse()
            .map_err(|_| LauncherError::Config("health listen address is invalid"))?;
        let health_address = validate_listen_address(health_address)?;
        let activation_seconds = env::var("PRAXIS_ACTIVATION_CANARY_SECONDS")
            .unwrap_or_else(|_| "30".to_owned())
            .parse::<u64>()
            .map_err(|_| LauncherError::Config("activation canary duration is invalid"))?;
        if activation_seconds == 0 {
            return Err(LauncherError::Config(
                "activation canary duration must be positive",
            ));
        }
        let e2e_stale_age_path = match env::var("PRAXIS_E2E_STALE_AGE_PATH") {
            Ok(path) if env::var("PRAXIS_E2E_CONTROLS_ENABLED").as_deref() == Ok("true") => {
                Some(PathBuf::from(path))
            }
            Ok(_) => {
                return Err(LauncherError::Config(
                    "Praxis E2E stale-age control requires explicit enablement",
                ));
            }
            Err(_) => None,
        };
        Ok(Self {
            client: LauncherConfig::new(&url, &ca, &token)?,
            generation_root,
            state_path,
            praxis_binary,
            health_address,
            probe_timings: ProbeTimings {
                activation_timeout: Duration::from_secs(activation_seconds),
                ..ProbeTimings::default()
            },
            e2e_stale_age_path,
        })
    }
}

pub async fn run(config: RuntimeConfig) -> Result<(), LauncherError> {
    let health_address = validate_listen_address(config.health_address)?;
    let client = ArtifactClient::new(config.client.clone()).await?;
    let store = LocalStore::open(&config.generation_root)?;
    let state_store = StateStore::new(&config.state_path);
    let state = state_store.load()?;
    let mut supervisor = Supervisor::new(
        state,
        ProcessSpec::praxis(&config.praxis_binary),
        config.probe_timings,
    )
    .with_checkpoint(state_store.clone());
    let health = HealthState::default();
    let health_listener = tokio::net::TcpListener::bind(health_address)
        .await
        .map_err(|_| LauncherError::Process("failed to bind launcher health listener"))?;
    let mut health_task = tokio::spawn(crate::health::serve(health_listener, health.clone()));
    let result = tokio::select! {
        result = reconcile_loop(
            &client,
            &store,
            &state_store,
            &mut supervisor,
            &health,
            config.client.desired_poll_interval(),
            config.e2e_stale_age_path.as_deref(),
        ) => result,
        result = &mut health_task => match result {
            Ok(Ok(())) => Err(LauncherError::Process("launcher health server stopped")),
            Ok(Err(_)) | Err(_) => Err(LauncherError::Process("launcher health server failed")),
        }
    };
    supervisor.stop().await?;
    health.unready().await;
    health_task.abort();
    result
}

async fn reconcile_loop(
    client: &ArtifactClient,
    store: &LocalStore,
    state_store: &StateStore,
    supervisor: &mut Supervisor,
    health: &HealthState,
    poll_interval: Duration,
    e2e_stale_age_path: Option<&std::path::Path>,
) -> Result<(), LauncherError> {
    let mut response_etag: Option<String> = None;
    let terminate = termination_signal();
    tokio::pin!(terminate);
    let mut process_check = tokio::time::interval(Duration::from_secs(1));
    loop {
        tokio::select! {
            biased;
            result = &mut terminate => return result,
            _ = process_check.tick() => {
                if expire_if_stale(supervisor.state_mut(), e2e_stale_age_path)? {
                    health.unready().await;
                    supervisor.stop().await?;
                    state_store.save(supervisor.state())?;
                } else if supervisor.stop_if_exited().await? {
                    health.unready().await;
                    state_store.save(supervisor.state())?;
                }
                continue;
            }
            result = client.poll_desired(response_etag.as_deref()) => {
                match result {
                    Ok(DesiredPoll::NotModified { freshness_deadline }) => {
                        supervisor
                            .state_mut()
                            .observe_authenticated(freshness_deadline - chrono::Duration::seconds(3_600));
                    }
                    Ok(DesiredPoll::Modified(desired)) => {
                        response_etag = Some(desired.response_etag.as_str().to_owned());
                        apply_desired(client, store, supervisor, health, *desired).await?;
                    }
                    Err(error) => {
                        eprintln!("desired reconciliation failed: {error:?}");
                        if expire_if_stale(supervisor.state_mut(), e2e_stale_age_path)? {
                            health.unready().await;
                            supervisor.stop().await?;
                        }
                    }
                }
                state_store.save(supervisor.state())?;
            }
        }
        tokio::select! {
            biased;
            result = &mut terminate => return result,
            () = tokio::time::sleep(poll_interval) => {}
        }
    }
}

fn expire_if_stale(
    state: &mut crate::state::SupervisorState,
    e2e_stale_age_path: Option<&std::path::Path>,
) -> Result<bool, LauncherError> {
    let Some(path) = e2e_stale_age_path else {
        return Ok(state.expire_if_stale(Utc::now()));
    };
    let raw = std::fs::read_to_string(path)
        .map_err(|_| LauncherError::Config("failed to read Praxis E2E stale age"))?;
    let seconds = raw
        .trim()
        .parse::<i64>()
        .map_err(|_| LauncherError::Config("Praxis E2E stale age is invalid"))?;
    if !(0..=3_600).contains(&seconds) {
        return Err(LauncherError::Config(
            "Praxis E2E stale age is out of range",
        ));
    }
    Ok(state.expire_if_stale_after(chrono::Duration::seconds(seconds)))
}

async fn apply_desired(
    client: &ArtifactClient,
    store: &LocalStore,
    supervisor: &mut Supervisor,
    health: &HealthState,
    desired: DesiredResponse,
) -> Result<(), LauncherError> {
    match supervisor.state_mut().observe(&desired) {
        DirectiveDecision::Stop => {
            health.unready().await;
            supervisor.stop().await
        }
        DirectiveDecision::Reject => {
            health.unready().await;
            Ok(())
        }
        DirectiveDecision::Wait => Ok(()),
        DirectiveDecision::Activate(generation_id) => {
            let Some(generation) =
                obtain_generation(client, store, &desired, &generation_id).await?
            else {
                return Ok(());
            };
            health.unready().await;
            let mut reporter = ClientReporter::new(client, desired.clone());
            match supervisor
                .activate(&desired, generation.path(), &mut reporter)
                .await
            {
                Ok(()) => health.ready(&generation_id).await,
                Err(category) => eprintln!("activation failed: {category:?}"),
            }
            Ok(())
        }
    }
}

async fn obtain_generation(
    client: &ArtifactClient,
    store: &LocalStore,
    desired: &DesiredResponse,
    generation_id: &str,
) -> Result<Option<LocalGeneration>, LauncherError> {
    match store.generation(generation_id) {
        Ok(Some(generation)) => return Ok(Some(generation)),
        Ok(None) => {}
        Err(LauncherError::LocalStore(_) | LauncherError::Incompatible(_)) => {
            store.discard_corrupt_generation(generation_id)?;
        }
        Err(error) => return Err(error),
    }
    match client.fetch_artifact(desired).await? {
        ArtifactFetch::Verified(artifact) => store.stage(&artifact).map(Some),
        ArtifactFetch::DesiredChanged => Ok(None),
    }
}

fn required(name: &'static str) -> Result<String, LauncherError> {
    env::var(name).map_err(|_| LauncherError::Config(name))
}

async fn termination_signal() -> Result<(), LauncherError> {
    let mut terminate =
        tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .map_err(|_| LauncherError::Process("failed to install termination signal handler"))?;
    let mut interrupt =
        tokio::signal::unix::signal(tokio::signal::unix::SignalKind::interrupt())
            .map_err(|_| LauncherError::Process("failed to install interrupt signal handler"))?;
    tokio::select! {
        _ = terminate.recv() => Ok(()),
        _ = interrupt.recv() => Ok(()),
    }
}
