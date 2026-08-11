use std::collections::BTreeSet;

use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};

use crate::models::{DesiredResponse, DirectiveAction};

mod recovery;

const LKG_MAX_AGE: Duration = Duration::seconds(3_600);

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DirectiveDecision {
    Activate(String),
    Stop,
    Wait,
    Reject,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SupervisorState {
    schema: String,
    active_generation: Option<String>,
    active_directive: Option<String>,
    pending_directive: Option<String>,
    failed_directive: Option<String>,
    reported_rank: u8,
    verified_generations: BTreeSet<String>,
    last_authenticated_observation: Option<DateTime<Utc>>,
    #[serde(skip)]
    report_states: Vec<&'static str>,
    #[serde(skip)]
    phase: Phase,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
enum Phase {
    #[default]
    Unready,
    Prepared,
    CanaryPassed,
    Active,
    Failed,
}

impl Default for SupervisorState {
    fn default() -> Self {
        Self::new()
    }
}

impl SupervisorState {
    #[must_use]
    pub fn new() -> Self {
        Self {
            schema: "praxis-launcher-state/v1".to_owned(),
            active_generation: None,
            active_directive: None,
            pending_directive: None,
            failed_directive: None,
            reported_rank: 0,
            verified_generations: BTreeSet::new(),
            last_authenticated_observation: None,
            report_states: Vec::new(),
            phase: Phase::Unready,
        }
    }

    #[must_use]
    pub fn observe(&mut self, desired: &DesiredResponse) -> DirectiveDecision {
        self.observe_at(desired, Utc::now())
    }

    #[must_use]
    pub fn observe_at(
        &mut self,
        desired: &DesiredResponse,
        now: DateTime<Utc>,
    ) -> DirectiveDecision {
        self.last_authenticated_observation = Some(desired.freshness_deadline - LKG_MAX_AGE);
        if !desired.eligible || now >= desired.eligibility_deadline {
            self.clear_active();
            return DirectiveDecision::Stop;
        }
        if self.failed_directive.as_deref() == Some(desired.directive_id.as_str()) {
            return DirectiveDecision::Wait;
        }
        match desired.action {
            DirectiveAction::Stop => {
                self.clear_active();
                DirectiveDecision::Stop
            }
            DirectiveAction::Rollback => self.content_decision(desired, true),
            DirectiveAction::Activate | DirectiveAction::Retry => {
                self.content_decision(desired, false)
            }
        }
    }

    fn content_decision(
        &self,
        desired: &DesiredResponse,
        require_local: bool,
    ) -> DirectiveDecision {
        let Some(generation) = desired.generation_id.as_ref() else {
            return DirectiveDecision::Reject;
        };
        if self.active_generation.as_deref() == Some(generation.as_str())
            && self.active_directive.as_deref() == Some(desired.directive_id.as_str())
            && self.phase == Phase::Active
        {
            return DirectiveDecision::Wait;
        }
        if require_local && !self.verified_generations.contains(generation.as_str()) {
            return DirectiveDecision::Reject;
        }
        DirectiveDecision::Activate(generation.as_str().to_owned())
    }

    pub fn mark_prepared(&mut self, desired: &DesiredResponse) -> Result<(), &'static str> {
        let generation = desired.generation_id.as_ref().ok_or("generation missing")?;
        if self.active_directive.as_deref() == Some(desired.directive_id.as_str()) {
            self.reported_rank = 3;
        } else if self.pending_directive.as_deref() != Some(desired.directive_id.as_str()) {
            self.reported_rank = 0;
            self.failed_directive = None;
        }
        self.verified_generations
            .insert(generation.as_str().to_owned());
        self.pending_directive = Some(desired.directive_id.as_str().to_owned());
        self.active_generation = None;
        self.active_directive = None;
        self.phase = Phase::Prepared;
        self.report_states.push("prepared");
        Ok(())
    }

    pub fn mark_canary_passed(&mut self, desired: &DesiredResponse) -> Result<(), &'static str> {
        self.require_pending(desired, Phase::Prepared)?;
        self.phase = Phase::CanaryPassed;
        self.report_states.push("canary_passed");
        Ok(())
    }

    pub fn mark_active(&mut self, desired: &DesiredResponse) -> Result<(), &'static str> {
        self.require_pending(desired, Phase::CanaryPassed)?;
        let generation = desired.generation_id.as_ref().ok_or("generation missing")?;
        self.active_generation = Some(generation.as_str().to_owned());
        self.active_directive = Some(desired.directive_id.as_str().to_owned());
        self.pending_directive = None;
        self.phase = Phase::Active;
        self.report_states.push("active");
        Ok(())
    }

    fn require_pending(&self, desired: &DesiredResponse, phase: Phase) -> Result<(), &'static str> {
        if self.pending_directive.as_deref() == Some(desired.directive_id.as_str())
            && self.phase == phase
        {
            Ok(())
        } else {
            Err("invalid activation transition")
        }
    }

    pub fn mark_failed(&mut self) {
        self.active_generation = None;
        self.active_directive = None;
        self.failed_directive = self.pending_directive.clone();
        self.phase = Phase::Failed;
    }

    pub(crate) fn mark_reported(
        &mut self,
        desired: &DesiredResponse,
        rank: u8,
    ) -> Result<(), &'static str> {
        if self.pending_directive.as_deref() != Some(desired.directive_id.as_str())
            || rank != self.reported_rank.saturating_add(1)
            || rank > 3
        {
            return Err("local report sequence is invalid");
        }
        self.reported_rank = rank;
        Ok(())
    }

    #[must_use]
    pub(crate) fn reported_rank(&self, desired: &DesiredResponse) -> u8 {
        if self.pending_directive.as_deref() == Some(desired.directive_id.as_str()) {
            self.reported_rank
        } else if self.active_directive.as_deref() == Some(desired.directive_id.as_str()) {
            3
        } else {
            0
        }
    }

    pub fn remember_verified(&mut self, generation: &str) {
        self.verified_generations.insert(generation.to_owned());
    }

    pub fn observe_authenticated(&mut self, observed_at: DateTime<Utc>) {
        self.last_authenticated_observation = Some(observed_at);
    }

    #[must_use]
    pub fn expire_if_stale(&mut self, now: DateTime<Utc>) -> bool {
        let age = self
            .last_authenticated_observation
            .map_or(LKG_MAX_AGE, |observed| now - observed);
        self.expire_if_stale_after(age)
    }

    #[must_use]
    pub fn expire_if_stale_after(&mut self, age: Duration) -> bool {
        let expired = age >= LKG_MAX_AGE;
        if expired && self.active_generation.is_some() {
            self.clear_active();
            true
        } else {
            false
        }
    }

    pub fn make_unready(&mut self) {
        self.phase = Phase::Unready;
    }

    pub fn clear_active(&mut self) {
        self.active_generation = None;
        self.active_directive = None;
        self.phase = Phase::Unready;
    }

    #[must_use]
    pub const fn is_ready(&self) -> bool {
        matches!(self.phase, Phase::Active)
    }

    #[must_use]
    pub fn active_generation(&self) -> Option<&str> {
        self.active_generation.as_deref()
    }

    #[must_use]
    pub fn report_states(&self) -> &[&'static str] {
        &self.report_states
    }
}
