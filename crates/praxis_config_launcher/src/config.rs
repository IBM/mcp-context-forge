use std::path::{Path, PathBuf};
use std::time::Duration;

use url::Url;

use crate::error::LauncherError;

/// Default interval between desired-state polls.
pub const DEFAULT_DESIRED_POLL_INTERVAL: Duration = Duration::from_secs(15);
/// Default interval between authenticated heartbeat observations.
pub const DEFAULT_HEARTBEAT_INTERVAL: Duration = Duration::from_secs(60);

/// Immutable network configuration for one target-bound launcher.
#[derive(Clone, Debug)]
pub struct LauncherConfig {
    base_url: Url,
    ca_path: PathBuf,
    token_path: PathBuf,
    desired_poll_interval: Duration,
    heartbeat_interval: Duration,
}

impl LauncherConfig {
    /// Parses a fixed `/praxis/v1` endpoint without caller-controlled identity.
    pub fn new(base_url: &str, ca_path: &Path, token_path: &Path) -> Result<Self, LauncherError> {
        let parsed =
            Url::parse(base_url).map_err(|_| LauncherError::Config("base URL is invalid"))?;
        let local_test_http = cfg!(test)
            && parsed.scheme() == "http"
            && matches!(parsed.host_str(), Some("localhost" | "127.0.0.1" | "::1"));
        if parsed.scheme() != "https" && !local_test_http {
            return Err(LauncherError::Config("base URL must use HTTPS"));
        }
        if parsed.username() != ""
            || parsed.password().is_some()
            || parsed.query().is_some()
            || parsed.fragment().is_some()
        {
            return Err(LauncherError::Config(
                "base URL cannot contain identity, query, or fragment",
            ));
        }
        if parsed.path().trim_end_matches('/') != "/praxis/v1" {
            return Err(LauncherError::Config("base URL path must be /praxis/v1"));
        }
        if ca_path.as_os_str().is_empty() {
            return Err(LauncherError::Config("an explicit CA path is required"));
        }
        Ok(Self {
            base_url: parsed,
            ca_path: ca_path.to_path_buf(),
            token_path: token_path.to_path_buf(),
            desired_poll_interval: DEFAULT_DESIRED_POLL_INTERVAL,
            heartbeat_interval: DEFAULT_HEARTBEAT_INTERVAL,
        })
    }

    pub(crate) fn endpoint(&self, leaf: &str) -> Result<Url, LauncherError> {
        self.base_url
            .join(&format!(
                "{}/{}",
                self.base_url.path().trim_end_matches('/'),
                leaf
            ))
            .map_err(|_| LauncherError::Config("machine endpoint is invalid"))
    }

    pub(crate) fn ca_path(&self) -> &Path {
        &self.ca_path
    }

    pub(crate) fn token_path(&self) -> &Path {
        &self.token_path
    }

    /// Returns the configured desired-state polling interval.
    #[must_use]
    pub const fn desired_poll_interval(&self) -> Duration {
        self.desired_poll_interval
    }

    /// Returns the configured authenticated heartbeat interval.
    #[must_use]
    pub const fn heartbeat_interval(&self) -> Duration {
        self.heartbeat_interval
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn config_rejects_identity_and_nonlocal_http() {
        // Given / When / Then
        for url in [
            "http://example.test/praxis/v1",
            "https://user@example.test/praxis/v1",
            "https://example.test/praxis/v1?target=x",
            "https://example.test/praxis/v1/desired",
        ] {
            assert!(LauncherConfig::new(url, Path::new("ca.pem"), Path::new("token")).is_err());
        }
    }

    #[test]
    fn config_defaults_match_launcher_contract() {
        // Given / When
        let config = LauncherConfig::new(
            "http://127.0.0.1/praxis/v1",
            Path::new("ca.pem"),
            Path::new("token"),
        )
        .expect("test HTTP");

        // Then
        assert_eq!(config.desired_poll_interval(), Duration::from_secs(15));
        assert_eq!(config.heartbeat_interval(), Duration::from_secs(60));
    }
}
