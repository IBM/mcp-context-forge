use std::time::Duration;

use reqwest::header::{AUTHORIZATION, HeaderName};
use reqwest::{Method, Response, StatusCode};

use crate::config::LauncherConfig;
use crate::error::LauncherError;

const REQUEST_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Clone, Debug)]
pub(crate) struct AuthenticatedTransport {
    config: LauncherConfig,
    http: reqwest::Client,
}

impl AuthenticatedTransport {
    pub(crate) async fn new(config: LauncherConfig) -> Result<Self, LauncherError> {
        let ca_bytes =
            tokio::fs::read(config.ca_path())
                .await
                .map_err(|source| LauncherError::CaRead {
                    path: config.ca_path().to_path_buf(),
                    source,
                })?;
        let ca_text = std::str::from_utf8(&ca_bytes).map_err(|_| LauncherError::InvalidCaFormat)?;
        if !ca_text
            .lines()
            .any(|line| line.trim() == "-----BEGIN CERTIFICATE-----")
            || !ca_text
                .lines()
                .any(|line| line.trim() == "-----END CERTIFICATE-----")
        {
            return Err(LauncherError::InvalidCaFormat);
        }
        let ca = reqwest::Certificate::from_pem(&ca_bytes)
            .map_err(|_| LauncherError::InvalidCaFormat)?;
        let builder = reqwest::Client::builder()
            .https_only(true)
            .tls_built_in_root_certs(false)
            .add_root_certificate(ca);
        let http = builder
            .redirect(reqwest::redirect::Policy::none())
            .timeout(REQUEST_TIMEOUT)
            .user_agent(concat!(
                env!("CARGO_PKG_NAME"),
                "/",
                env!("CARGO_PKG_VERSION")
            ))
            .build()
            .map_err(LauncherError::ClientBuild)?;
        Ok(Self { config, http })
    }

    pub(crate) async fn send(
        &self,
        method: Method,
        leaf: &str,
        conditional: Option<(HeaderName, String)>,
        body: Option<serde_json::Value>,
    ) -> Result<Response, LauncherError> {
        let url = self.config.endpoint(leaf)?;
        let first = self
            .request(&method, url.clone(), conditional.as_ref(), body.as_ref())
            .await?;
        if matches!(
            first.status(),
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN
        ) {
            let second = self
                .request(&method, url, conditional.as_ref(), body.as_ref())
                .await?;
            if matches!(
                second.status(),
                StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN
            ) {
                return Err(LauncherError::AuthenticationRejected);
            }
            return Ok(second);
        }
        Ok(first)
    }

    async fn request(
        &self,
        method: &Method,
        url: url::Url,
        conditional: Option<&(HeaderName, String)>,
        body: Option<&serde_json::Value>,
    ) -> Result<Response, LauncherError> {
        let token = tokio::fs::read_to_string(self.config.token_path())
            .await
            .map_err(|source| LauncherError::CredentialRead {
                path: self.config.token_path().to_path_buf(),
                source,
            })?;
        let token = token.trim();
        if token.is_empty() {
            return Err(LauncherError::EmptyCredential);
        }
        let mut request = self
            .http
            .request(method.clone(), url)
            .header(AUTHORIZATION, format!("Bearer {token}"));
        if let Some((name, value)) = conditional {
            request = request.header(name, value);
        }
        if let Some(value) = body {
            request = request.json(value);
        }
        request.send().await.map_err(LauncherError::Transport)
    }
}
