//! Startup-loaded per-server CPEX policy dispatcher.

use std::collections::BTreeMap;

use async_trait::async_trait;
use bytes::Bytes;
use praxis_filter::{
    BodyAccess, BodyMode, FilterAction, FilterError, HttpFilter, HttpFilterContext, PolicyFilter,
    Rejection,
};
use serde::Deserialize;

use super::cpex_models::{PolicyMapping, PolicyProfile, ServerId, parse_server_path};

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct DispatcherConfig {
    policies: Vec<PolicyMapping>,
}

struct LoadedPolicy {
    filter: Box<dyn HttpFilter>,
    profile: PolicyProfile,
}

/// Unconditional security filter that dispatches to immutable CPEX policies.
pub struct CpexDispatcherFilter {
    policies: BTreeMap<ServerId, LoadedPolicy>,
}

fn rejection(status: u16) -> FilterAction {
    FilterAction::Reject(
        Rejection::status(status)
            .with_header("content-type", "application/json")
            .with_body(
                r#"{"jsonrpc":"2.0","id":null,"error":{"code":-32001,"message":"request denied"}}"#,
            ),
    )
}

const fn should_evaluate_request_body(end_of_stream: bool) -> bool {
    end_of_stream
}

impl CpexDispatcherFilter {
    /// Load and initialize every configured CPEX policy during pipeline construction.
    pub fn from_config(config: &serde_yaml::Value) -> Result<Box<dyn HttpFilter>, FilterError> {
        let config: DispatcherConfig = serde_yaml::from_value(config.clone())?;
        if config.policies.is_empty() {
            return Err("cpex: at least one policy mapping is required".into());
        }
        let mut validated = Vec::with_capacity(config.policies.len());
        let mut server_ids = std::collections::BTreeSet::new();
        for mapping in &config.policies {
            let (server_id, path) = mapping.validated()?;
            if !server_ids.insert(server_id.clone()) {
                return Err("cpex: duplicate server id".into());
            }
            validated.push((server_id, path.to_owned()));
        }
        let mut policies = BTreeMap::new();
        for (server_id, path) in validated {
            let typed = cpex::cpex_core::config::load_config(&path)?;
            let profile = PolicyProfile::try_from(typed)?;
            let policy_config = serde_yaml::to_value(serde_json::json!({
                "body_access": "read_only",
                "config_path": path,
                "require_protocol_metadata": true,
            }))?;
            let filter = PolicyFilter::from_config(&policy_config)?;
            policies.insert(server_id, LoadedPolicy { filter, profile });
        }
        Ok(Box::new(Self { policies }))
    }

    fn policy_for_path(
        &self,
        path: &str,
        query: Option<&str>,
    ) -> Result<&LoadedPolicy, FilterAction> {
        let server_id = parse_server_path(path, query).map_err(|_| rejection(404))?;
        self.policies.get(&server_id).ok_or_else(|| rejection(404))
    }

    fn policy<'a>(&'a self, ctx: &HttpFilterContext<'_>) -> Result<&'a LoadedPolicy, FilterAction> {
        self.policy_for_path(ctx.request.uri.path(), ctx.request.uri.query())
    }

    fn entity_allowed(
        policy: &LoadedPolicy,
        ctx: &HttpFilterContext<'_>,
    ) -> Result<bool, FilterAction> {
        let method = ctx
            .get_metadata("mcp.method")
            .ok_or_else(|| rejection(500))?;
        match method {
            "tools/call" | "resources/read" | "prompts/get" => {
                let name = ctx.get_metadata("mcp.name").ok_or_else(|| rejection(400))?;
                Ok(policy.profile.allows(method, name))
            }
            _ => Ok(true),
        }
    }
}

#[async_trait]
impl HttpFilter for CpexDispatcherFilter {
    fn name(&self) -> &'static str {
        "cpex"
    }

    fn request_body_access(&self) -> BodyAccess {
        BodyAccess::ReadOnly
    }

    fn request_body_mode(&self) -> BodyMode {
        BodyMode::Stream
    }

    fn response_body_access(&self) -> BodyAccess {
        BodyAccess::ReadOnly
    }

    fn needs_request_context(&self) -> bool {
        true
    }

    async fn on_request(
        &self,
        ctx: &mut HttpFilterContext<'_>,
    ) -> Result<FilterAction, FilterError> {
        match self.policy(ctx) {
            Ok(_) => Ok(FilterAction::Continue),
            Err(action) => return Ok(action),
        }
    }

    async fn on_request_body(
        &self,
        ctx: &mut HttpFilterContext<'_>,
        body: &mut Option<Bytes>,
        end_of_stream: bool,
    ) -> Result<FilterAction, FilterError> {
        if !should_evaluate_request_body(end_of_stream) {
            return Ok(FilterAction::Continue);
        }
        let policy = match self.policy(ctx) {
            Ok(policy) => policy,
            Err(action) => return Ok(action),
        };
        match Self::entity_allowed(policy, ctx) {
            Ok(true) => {}
            Ok(false) => return Ok(rejection(403)),
            Err(action) => return Ok(action),
        }
        match policy
            .filter
            .on_request(ctx)
            .await
            .unwrap_or_else(|_| rejection(500))
        {
            FilterAction::Continue | FilterAction::Release | FilterAction::BodyDone => {}
            FilterAction::Reject(rejection) => return Ok(FilterAction::Reject(rejection)),
            FilterAction::TerminalResponse(response) => {
                return Ok(FilterAction::TerminalResponse(response));
            }
        }
        policy
            .filter
            .on_request_body(ctx, body, end_of_stream)
            .await
            .or_else(|_| Ok(rejection(500)))
    }

    async fn on_response(
        &self,
        ctx: &mut HttpFilterContext<'_>,
    ) -> Result<FilterAction, FilterError> {
        let policy = match self.policy(ctx) {
            Ok(policy) => policy,
            Err(action) => return Ok(action),
        };
        policy
            .filter
            .on_response(ctx)
            .await
            .or_else(|_| Ok(rejection(500)))
    }

    fn on_response_body(
        &self,
        ctx: &mut HttpFilterContext<'_>,
        body: &mut Option<Bytes>,
        end_of_stream: bool,
    ) -> Result<FilterAction, FilterError> {
        let policy = match self.policy(ctx) {
            Ok(policy) => policy,
            Err(action) => return Ok(action),
        };
        policy
            .filter
            .on_response_body(ctx, body, end_of_stream)
            .or_else(|_| Ok(rejection(500)))
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use super::{CpexDispatcherFilter, should_evaluate_request_body};
    use praxis_filter::{FilterAction, PolicyFilter};

    #[test]
    fn cpex_waits_for_complete_stream_buffer_before_authorizing() {
        assert!(!should_evaluate_request_body(false));
        assert!(should_evaluate_request_body(true));
    }

    #[test]
    fn factory_rejects_duplicate_server_ids() {
        let config: serde_yaml::Value = serde_yaml::from_str(
            "policies:\n  - {server_id: server-a, config_path: cpex/a--server-a.yaml}\n  - {server_id: server-a, config_path: cpex/b--server-a.yaml}\n",
        )
        .expect("test yaml");

        assert!(CpexDispatcherFilter::from_config(&config).is_err());
    }

    #[test]
    fn factory_rejects_missing_policy_file() {
        let config: serde_yaml::Value = serde_yaml::from_str(
            "policies:\n  - {server_id: server-a, config_path: cpex/missing--server-a.yaml}\n",
        )
        .expect("test yaml");

        assert!(CpexDispatcherFilter::from_config(&config).is_err());
    }

    #[test]
    fn linked_audit_plugin_initializes_via_policy_filter() {
        let directory = tempfile::tempdir().expect("temporary policy directory");
        let path = directory.path().join("policy.yaml");
        std::fs::write(
            &path,
            r#"
plugin_settings:
  routing_enabled: true
  fail_on_plugin_error: true
plugins:
  - name: native-audit
    kind: audit/logger
    hooks: [cmf.tool_pre_invoke]
    mode: sequential
    priority: 10
    on_error: fail
    config: {destination: tracing, source: task5-rust}
routes:
  - tool: search
    plugins: [native-audit]
  - tool: "*"
  - resource: "*"
  - prompt: "*"
"#,
        )
        .expect("write policy");
        let config = serde_yaml::to_value(serde_json::json!({
            "body_access": "read_only",
            "config_path": path,
            "require_protocol_metadata": true,
        }))
        .expect("policy filter config");

        let filter = PolicyFilter::from_config(&config).expect("linked audit plugin");

        assert_eq!(filter.name(), "policy");
    }

    #[test]
    fn task5_native_compat_unknown_server_id_is_rejected() {
        let dispatcher = CpexDispatcherFilter {
            policies: BTreeMap::new(),
        };

        let result = dispatcher.policy_for_path("/servers/unknown/mcp", None);

        assert!(matches!(result, Err(FilterAction::Reject(rejection)) if rejection.status == 404));
    }
}
