use crate::config::Config;
use crate::streamer::McpStreamClient;
use arc_swap::ArcSwap;
use reqwest::header::{ACCEPT, AUTHORIZATION, CONTENT_TYPE, HeaderMap, HeaderValue};

const ACCEPT_VALUES: &str = "application/json, application/x-ndjson, text/event-stream";

impl McpStreamClient {
    #[allow(unused)]
    /// Initialize the client with standard MCP headers
    /// # Errors
    /// * invalid auth header
    /// # Panics
    /// * wrong or missing tls certificate
    pub fn try_new(config: Config) -> Result<Self, Box<dyn std::error::Error>> {
        // Build static headers once during initialization
        let mut static_headers = HeaderMap::new();
        static_headers.insert(ACCEPT, HeaderValue::from_static(ACCEPT_VALUES));
        let cont_type = HeaderValue::from_str(&config.mcp_content_type)?;
        static_headers.insert(CONTENT_TYPE, cont_type);

        // Add authorization header if configured
        if let Some(auth) = config.mcp_auth.as_ref() {
            let auth_header = HeaderValue::from_str(auth)?;
            static_headers.insert(AUTHORIZATION, auth_header);
        }

        Ok(Self {
            session_id: ArcSwap::from_pointee(None),
            config,
            static_headers,
        })
    }
}
