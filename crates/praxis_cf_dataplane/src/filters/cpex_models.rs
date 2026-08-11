//! Canonical server and policy mapping types for the CPEX dispatcher.

use std::{borrow::Borrow, collections::BTreeSet, path::Path};

use cpex::cpex_core::{
    config::{CpexConfig, RouteEntry, StringOrList},
    plugin::OnError,
};
use serde::Deserialize;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub(super) struct ServerId(String);

impl ServerId {
    pub(super) fn new(value: &str) -> Result<Self, MappingError> {
        let valid = !value.is_empty()
            && value.len() <= 128
            && value.bytes().enumerate().all(|(index, byte)| {
                byte.is_ascii_alphanumeric() || (index > 0 && b"._:-".contains(&byte))
            });
        if !valid {
            return Err(MappingError::ServerId);
        }
        Ok(Self(value.to_owned()))
    }
}

impl Borrow<str> for ServerId {
    fn borrow(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct PolicyMapping {
    server_id: String,
    config_path: String,
}

impl PolicyMapping {
    #[cfg(test)]
    pub(super) fn new(server_id: &str, config_path: &str) -> Result<Self, MappingError> {
        let mapping = Self {
            server_id: server_id.to_owned(),
            config_path: config_path.to_owned(),
        };
        mapping.validated()?;
        Ok(mapping)
    }

    pub(super) fn validated(&self) -> Result<(ServerId, &Path), MappingError> {
        let server_id = ServerId::new(&self.server_id)?;
        let path = Path::new(&self.config_path);
        let components: Vec<_> = path.components().collect();
        let valid_shape = !path.is_absolute()
            && components.len() == 2
            && components
                .first()
                .is_some_and(|part| part.as_os_str() == "cpex");
        let suffix = format!("--{}.yaml", self.server_id);
        let file_name = path.file_name().and_then(|name| name.to_str());
        let scope = file_name.and_then(|name| name.strip_suffix(&suffix));
        if !valid_shape || scope.is_none_or(|value| ServerId::new(value).is_err()) {
            return Err(MappingError::PolicyPath);
        }
        Ok((server_id, path))
    }
}

#[derive(Debug, thiserror::Error, Eq, PartialEq)]
pub(super) enum MappingError {
    #[error("invalid server id")]
    ServerId,
    #[error("invalid policy path")]
    PolicyPath,
    #[error("invalid CPEX policy profile")]
    PolicyProfile,
}

pub(super) fn parse_server_path(path: &str, query: Option<&str>) -> Result<ServerId, MappingError> {
    if query.is_some() || path.contains('%') {
        return Err(MappingError::ServerId);
    }
    let parts: Vec<_> = path.split('/').collect();
    match parts.as_slice() {
        ["", "servers", server_id, "mcp"] => ServerId::new(server_id),
        _ => Err(MappingError::ServerId),
    }
}

#[derive(Debug)]
pub(super) struct PolicyProfile {
    tools: BTreeSet<String>,
    resources: BTreeSet<String>,
    prompts: BTreeSet<String>,
}

impl PolicyProfile {
    pub(super) fn allows(&self, method: &str, name: &str) -> bool {
        match method {
            "tools/call" => self.tools.contains(name),
            "resources/read" => self.resources.contains(name),
            "prompts/get" => self.prompts.contains(name),
            _ => false,
        }
    }
}

fn exact_matcher(route: &RouteEntry) -> Result<(&'static str, &str), MappingError> {
    let entries = [
        ("tool", route.tool.as_ref()),
        ("resource", route.resource.as_ref()),
        ("prompt", route.prompt.as_ref()),
    ];
    let mut present = entries
        .into_iter()
        .filter_map(|(kind, matcher)| matcher.map(|item| (kind, item)));
    let Some((kind, matcher)) = present.next() else {
        return Err(MappingError::PolicyProfile);
    };
    if present.next().is_some() || route.llm.is_some() {
        return Err(MappingError::PolicyProfile);
    }
    match matcher {
        StringOrList::Single(pattern) => Ok((kind, pattern.as_str())),
        StringOrList::List(_) => Err(MappingError::PolicyProfile),
    }
}

impl TryFrom<CpexConfig> for PolicyProfile {
    type Error = MappingError;

    fn try_from(config: CpexConfig) -> Result<Self, Self::Error> {
        if !config.plugin_settings.routing_enabled || !config.plugin_settings.fail_on_plugin_error {
            return Err(MappingError::PolicyProfile);
        }
        if config.plugins.iter().any(|plugin| {
            let mandatory = plugin.tags.iter().any(|tag| {
                matches!(
                    tag.to_ascii_lowercase().as_str(),
                    "security"
                        | "auth"
                        | "authorization"
                        | "access-control"
                        | "rbac"
                        | "abac"
                        | "pdp"
                        | "mac"
                )
            }) || plugin
                .hooks
                .iter()
                .any(|hook| hook.starts_with("http_auth_"));
            mandatory && !matches!(plugin.on_error, OnError::Fail)
        }) {
            return Err(MappingError::PolicyProfile);
        }
        let terminal_start = config
            .routes
            .len()
            .checked_sub(3)
            .ok_or(MappingError::PolicyProfile)?;
        let (routes, terminal_routes) = config.routes.split_at(terminal_start);
        let terminal: Result<Vec<_>, _> = terminal_routes
            .iter()
            .map(|route| {
                let (kind, name) = exact_matcher(route)?;
                if name != "*" || !route.plugins.is_empty() || route.identity.is_some() {
                    return Err(MappingError::PolicyProfile);
                }
                Ok(kind)
            })
            .collect();
        if terminal? != ["tool", "resource", "prompt"] {
            return Err(MappingError::PolicyProfile);
        }
        let mut tools = BTreeSet::new();
        let mut resources = BTreeSet::new();
        let mut prompts = BTreeSet::new();
        for route in routes {
            let (kind, name) = exact_matcher(route)?;
            if name.contains(['*', '?']) || name.is_empty() {
                return Err(MappingError::PolicyProfile);
            }
            match kind {
                "tool" => tools.insert(name.to_owned()),
                "resource" => resources.insert(name.to_owned()),
                "prompt" => prompts.insert(name.to_owned()),
                _ => false,
            };
        }
        Ok(Self {
            tools,
            resources,
            prompts,
        })
    }
}

#[cfg(test)]
mod tests {
    include!("cpex_models_test.rs");
}
