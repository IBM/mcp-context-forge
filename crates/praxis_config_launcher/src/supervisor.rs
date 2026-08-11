use std::future::Future;
use std::path::Path;
use std::pin::Pin;
use std::time::Duration;

use crate::error::LauncherError;
use crate::models::{DesiredResponse, FailureCategory, ReportState};
use crate::persistence::StateStore;
use crate::probes::{self, ProbeTimings};
use crate::process::{ManagedProcess, ProcessSpec};
use crate::state::SupervisorState;

pub trait Reporter {
    fn submit<'a>(
        &'a mut self,
        state: &'a ReportState,
    ) -> Pin<Box<dyn Future<Output = Result<(), LauncherError>> + Send + 'a>>;
}

pub struct Supervisor {
    state: SupervisorState,
    spec: ProcessSpec,
    process: Option<ManagedProcess>,
    timings: ProbeTimings,
    checkpoint: Option<StateStore>,
}

impl Supervisor {
    #[must_use]
    pub const fn new(state: SupervisorState, spec: ProcessSpec, timings: ProbeTimings) -> Self {
        Self {
            state,
            spec,
            process: None,
            timings,
            checkpoint: None,
        }
    }

    #[must_use]
    pub fn with_checkpoint(mut self, checkpoint: StateStore) -> Self {
        self.checkpoint = Some(checkpoint);
        self
    }

    #[must_use]
    pub const fn state(&self) -> &SupervisorState {
        &self.state
    }

    pub const fn state_mut(&mut self) -> &mut SupervisorState {
        &mut self.state
    }

    pub async fn activate<R: Reporter + Send>(
        &mut self,
        desired: &DesiredResponse,
        generation: &Path,
        reporter: &mut R,
    ) -> Result<(), FailureCategory> {
        self.state
            .mark_prepared(desired)
            .map_err(|_| FailureCategory::ConfigValidation)?;
        if self
            .report_stage(desired, &ReportState::Prepared, 1, reporter)
            .await
            .is_err()
        {
            return self.fail(FailureCategory::Timeout, reporter).await;
        }
        if let Some(old) = self.process.take() {
            if old.stop().await.is_err() {
                return self.fail(FailureCategory::Timeout, reporter).await;
            }
        }
        let address = match probes::listener_address(generation) {
            Ok(address) => address,
            Err(category) => return self.fail(category, reporter).await,
        };
        let canary_path = match probes::policy_canary_path(generation) {
            Ok(path) => path,
            Err(category) => return self.fail(category, reporter).await,
        };
        if let Err(category) = probes::old_listener_closed(address) {
            return self.fail(category, reporter).await;
        }
        if let Err(category) =
            probes::validate_config(&self.spec, generation, self.timings.activation_timeout).await
        {
            return self.fail(category, reporter).await;
        }
        let mut candidate = match ManagedProcess::spawn(&self.spec, generation) {
            Ok(candidate) => candidate,
            Err(_) => return self.fail(FailureCategory::Spawn, reporter).await,
        };
        let result = self
            .finish_activation(desired, address, &canary_path, &mut candidate, reporter)
            .await;
        if let Err(category) = result {
            let _ = candidate.stop().await;
            return self.fail(category, reporter).await;
        }
        self.process = Some(candidate);
        Ok(())
    }

    async fn fail<R: Reporter + Send>(
        &mut self,
        category: FailureCategory,
        reporter: &mut R,
    ) -> Result<(), FailureCategory> {
        self.state.mark_failed();
        let _ = reporter
            .submit(&ReportState::Failed {
                failure_category: category,
            })
            .await;
        Err(category)
    }

    async fn report_stage<R: Reporter + Send>(
        &mut self,
        desired: &DesiredResponse,
        state: &ReportState,
        rank: u8,
        reporter: &mut R,
    ) -> Result<(), LauncherError> {
        if self.state.reported_rank(desired) >= rank {
            return Ok(());
        }
        reporter.submit(state).await?;
        self.state
            .mark_reported(desired, rank)
            .map_err(LauncherError::State)?;
        if let Some(store) = &self.checkpoint {
            store.save(&self.state)?;
        }
        Ok(())
    }

    async fn finish_activation<R: Reporter + Send>(
        &mut self,
        desired: &DesiredResponse,
        address: std::net::SocketAddr,
        canary_path: &str,
        candidate: &mut ManagedProcess,
        reporter: &mut R,
    ) -> Result<(), FailureCategory> {
        probes::wait_for_listener(candidate, address, self.timings).await?;
        probes::policy_canary(address, canary_path, self.timings.activation_timeout).await?;
        self.state
            .mark_canary_passed(desired)
            .map_err(|_| FailureCategory::PolicyCanary)?;
        self.report_stage(desired, &ReportState::CanaryPassed, 2, reporter)
            .await
            .map_err(|_| FailureCategory::Timeout)?;
        self.report_stage(desired, &ReportState::Active, 3, reporter)
            .await
            .map_err(|_| FailureCategory::Timeout)?;
        self.state
            .mark_active(desired)
            .map_err(|_| FailureCategory::PolicyCanary)
    }

    pub async fn stop(&mut self) -> Result<(), LauncherError> {
        self.state.make_unready();
        if let Some(process) = self.process.take() {
            process.stop().await?;
        }
        Ok(())
    }

    pub async fn stop_if_exited(&mut self) -> Result<bool, LauncherError> {
        let exited = match self.process.as_mut() {
            Some(process) => process.try_wait()?.is_some(),
            None => false,
        };
        if exited {
            self.state.clear_active();
            if let Some(process) = self.process.take() {
                process
                    .stop_with_grace(Duration::ZERO, crate::process::KILL_GRACE)
                    .await?;
            }
        }
        Ok(exited)
    }
}
