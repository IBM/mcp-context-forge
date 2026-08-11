use crate::client::{DesiredPoll, ReportSubmission};
use crate::models::{DesiredResponse, ReportState};
use crate::supervisor::Reporter;
use crate::{ArtifactClient, LauncherError};

pub(super) struct ClientReporter<'a> {
    client: &'a ArtifactClient,
    desired: DesiredResponse,
}

impl<'a> ClientReporter<'a> {
    pub(super) const fn new(client: &'a ArtifactClient, desired: DesiredResponse) -> Self {
        Self { client, desired }
    }

    async fn send(&mut self, state: &ReportState) -> Result<(), LauncherError> {
        let mut request_failures = 0_u8;
        let mut cursor_recoveries = 0_u8;
        loop {
            let submission = match self.client.submit_report(&self.desired, state).await {
                Ok(submission) => submission,
                Err(_) if request_failures == 0 => {
                    request_failures = 1;
                    continue;
                }
                Err(error) => {
                    if let Ok(DesiredPoll::Modified(current)) = self.client.poll_desired(None).await
                    {
                        if current.directive_id == self.desired.directive_id {
                            self.desired = *current;
                        }
                    }
                    return Err(error);
                }
            };
            match submission {
                ReportSubmission::Accepted(response) => {
                    self.desired.last_report_sequence = response.last_report_sequence;
                    self.desired.next_report_sequence = response.next_report_sequence;
                    self.desired.response_etag = response.response_etag;
                    return Ok(());
                }
                ReportSubmission::CursorRecovered(current)
                    if current.directive_id == self.desired.directive_id =>
                {
                    if cursor_recoveries == 2 {
                        return Err(LauncherError::Contract(
                            "report cursor recovery did not converge",
                        ));
                    }
                    cursor_recoveries += 1;
                    self.desired = current;
                }
                ReportSubmission::CursorRecovered(_) | ReportSubmission::DesiredChanged => {
                    return Err(LauncherError::DesiredChanged);
                }
            }
        }
    }
}

impl Reporter for ClientReporter<'_> {
    fn submit<'a>(
        &'a mut self,
        state: &'a ReportState,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<(), LauncherError>> + Send + 'a>>
    {
        Box::pin(self.send(state))
    }
}
