use super::SupervisorState;

impl SupervisorState {
    pub(crate) fn validate_recovered(&self) -> Result<(), &'static str> {
        if self.schema != "praxis-launcher-state/v1"
            || self.reported_rank > 3
            || optional_invalid(&self.active_generation)
            || optional_invalid(&self.active_directive)
            || optional_invalid(&self.pending_directive)
            || optional_invalid(&self.failed_directive)
            || self
                .verified_generations
                .iter()
                .any(|value| !valid_hash(value))
            || !self.has_coherent_recovered_shape()
        {
            Err("persisted launcher state is invalid")
        } else {
            Ok(())
        }
    }

    fn has_coherent_recovered_shape(&self) -> bool {
        match (
            self.active_generation.as_ref(),
            self.active_directive.as_ref(),
            self.pending_directive.as_ref(),
        ) {
            (Some(generation), Some(_), None) => {
                self.failed_directive.is_none()
                    && self.reported_rank == 3
                    && self.verified_generations.contains(generation)
            }
            (None, None, Some(pending)) => {
                let failure_matches = self
                    .failed_directive
                    .as_ref()
                    .is_none_or(|failed| failed == pending && self.reported_rank <= 2);
                failure_matches && (self.reported_rank > 0 || self.failed_directive.is_some())
            }
            (None, None, None) => self.failed_directive.is_none() && self.reported_rank == 0,
            (Some(_), None, _) | (None, Some(_), _) | (Some(_), Some(_), Some(_)) => false,
        }
    }
}

fn optional_invalid(value: &Option<String>) -> bool {
    value.as_ref().is_some_and(|item| !valid_hash(item))
}

fn valid_hash(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}
