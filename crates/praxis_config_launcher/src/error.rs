use std::path::PathBuf;

/// Sanitized launcher client failures.
#[derive(Debug, thiserror::Error)]
#[non_exhaustive]
pub enum LauncherError {
    #[error("invalid launcher configuration: {0}")]
    Config(&'static str),
    #[error("failed to read launcher credential file {path}")]
    CredentialRead {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("launcher credential file is empty")]
    EmptyCredential,
    #[error("failed to read CA certificate {path}")]
    CaRead {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("CA certificate is invalid")]
    InvalidCa(#[source] reqwest::Error),
    #[error("CA certificate PEM is invalid")]
    InvalidCaFormat,
    #[error("HTTPS client construction failed")]
    ClientBuild(#[source] reqwest::Error),
    #[error("machine API transport failed")]
    Transport(#[source] reqwest::Error),
    #[error("machine API returned HTTP {0}")]
    Http(reqwest::StatusCode),
    #[error("machine authentication was rejected")]
    AuthenticationRejected,
    #[error("desired state changed during the operation")]
    DesiredChanged,
    #[error("machine API response violated its contract: {0}")]
    Contract(&'static str),
    #[error("artifact exceeds the 16 MiB limit")]
    ArtifactTooLarge,
    #[error("artifact body ended before Content-Length")]
    ArtifactTruncated,
    #[error("artifact hash does not match its ETag")]
    ArtifactHashMismatch,
    #[error("artifact is incompatible: {0}")]
    Incompatible(&'static str),
    #[error("local generation store contract failed: {0}")]
    LocalStore(&'static str),
    #[error("local generation store I/O failed during {operation} at {path}")]
    LocalStoreIo {
        operation: &'static str,
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("local generation staging fault injected at {0:?}")]
    StagingFault(crate::local_store::FaultPoint),
    #[error("launcher state contract failed: {0}")]
    State(&'static str),
    #[error("launcher state I/O failed during {operation} at {path}")]
    StateIo {
        operation: &'static str,
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("Praxis process supervision failed: {0}")]
    Process(&'static str),
    #[error("launcher build provenance could not be read")]
    BuildInfo,
}
