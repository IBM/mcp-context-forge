// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! ContextForge MCP Dataplane
//!
//! High-performance MCP protocol dataplane built on Praxis proxy framework.
//! Provides stateless, horizontally scalable MCP request handling with
//! CPEX-based authorization and gRPC control plane integration.
//!
//! ## Architecture
//!
//! 7-filter pipeline:
//! 1. McpFilter (Praxis built-in) - MCP protocol validation
//! 2. cf_control_plane_data - Fetch session + VS config from control plane
//! 3. CPEX Policy #1 - Pre-routing authorization (virtual server access)
//! 4. cf_tools_router - Routing decision (gateway vs upstream)
//! 5. CPEX Policy #2 - Post-routing authorization (gateway/upstream access)
//! 6. cf_mcp_broker - Gateway execution (conditional on route=gateway)
//! 7. cf_upstream_proxy - Upstream forwarding (conditional on route=upstream)
//!
//! ## Configuration
//!
//! All configuration is via YAML file (praxis_cf_dataplane.yaml).
//! See docs/configuration.md for details.

pub mod filters;
mod validation;

use std::sync::Arc;

use praxis_filter::{FilterError, FilterFactory, FilterRegistry, HttpFilter, SecurityClass};

pub use validation::{GenerationValidationError, validate_generation};

type HttpFactory = fn(&serde_yaml::Value) -> Result<Box<dyn HttpFilter>, FilterError>;

fn register_http(
    registry: &mut FilterRegistry,
    name: &str,
    factory: HttpFactory,
    security_class: SecurityClass,
) {
    registry
        .register_with_class(name, FilterFactory::Http(Arc::new(factory)), security_class)
        .unwrap_or_else(|_| panic!("duplicate filter name: '{name}'"));
}

/// Registers the ContextForge filters discovered by the Praxis build.
///
/// The CPEX dispatcher is security-classified so Praxis rejects pipelines that
/// can bypass it; protocol classification and routing filters remain standard.
pub fn register_filters(registry: &mut FilterRegistry) {
    register_http(
        registry,
        "mcp",
        filters::McpClassifierFilter::from_config,
        SecurityClass::Standard,
    );
    register_http(
        registry,
        "cpex",
        filters::CpexDispatcherFilter::from_config,
        SecurityClass::Security,
    );
    register_http(
        registry,
        "cf_control_plane_data",
        filters::ControlPlaneDataFilter::from_config,
        SecurityClass::Standard,
    );
    register_http(
        registry,
        "cf_tools_router",
        filters::ToolsRouterFilter::from_config,
        SecurityClass::Standard,
    );
    register_http(
        registry,
        "cf_mcp_broker",
        filters::McpBrokerFilter::from_config,
        SecurityClass::Standard,
    );
    register_http(
        registry,
        "cf_upstream_proxy",
        filters::UpstreamProxyFilter::from_config,
        SecurityClass::Standard,
    );
}

#[cfg(test)]
mod tests {
    use super::register_filters;
    use praxis_filter::FilterRegistry;

    #[test]
    fn cpex_dispatcher_is_the_only_security_filter() {
        let mut registry = FilterRegistry::with_builtins();
        register_filters(&mut registry);

        assert!(registry.is_security_filter("cpex"));
        assert!(!registry.is_security_filter("mcp"));
        assert!(!registry.is_security_filter("cf_control_plane_data"));
        assert!(!registry.is_security_filter("cf_tools_router"));
        assert!(!registry.is_security_filter("cf_mcp_broker"));
        assert!(!registry.is_security_filter("cf_upstream_proxy"));
    }
}
