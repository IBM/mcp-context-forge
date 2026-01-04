use crate::tools::search;
use rmcp::ErrorData as McpError;
use rmcp::{
    ServerHandler,
    handler::server::{tool::ToolRouter, wrapper::Parameters},
    model::{
        CallToolResult, Content, Implementation, InitializeResult, ProtocolVersion,
        ServerCapabilities, ServerInfo,
    },
    schemars, tool, tool_handler, tool_router,
};
use serde::Deserialize;

#[derive(Clone)]
pub struct FilesystemServer {
    tool_router: ToolRouter<Self>,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct ReadFolderParameters {
    #[schemars(description = "Directory path whose immediate files and subdirectories are listed")]
    path: String,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct SearchFolderParameters {
    #[schemars(description = "Root directory to search recursively")]
    path: String,
    #[schemars(description = "Glob pattern used to include matching files")]
    pattern: String,
    #[schemars(
        description = "List of glob patterns used to exclude files or directories from the search"
    )]
    exclude_pattern: Vec<String>,
}

#[tool_router] // Macro that generates the tool router
impl FilesystemServer {
    pub fn new() -> Self {
        Self {
            tool_router: Self::tool_router(),
        }
    }
    #[tool(description = "List files and subdirectories in a directory")]
    async fn list_directory(
        &self,
        Parameters(ReadFolderParameters { path }): Parameters<ReadFolderParameters>,
    ) -> Result<CallToolResult, McpError> {
        let dir_entries = search::list_directory(&path).await.map_err(|e| {
            McpError::internal_error(format!("Error reading directory '{}': {}", path, e), None)
        })?;

        let content = Content::json(&dir_entries).map_err(|e| {
            McpError::internal_error(
                format!("Error converting directory entries to JSON: {}", e),
                None,
            )
        })?;

        Ok(CallToolResult::success(vec![content]))
    }

    #[tool(description = "Recursively search for files under a directory matching glob patterns")]
    async fn search_files(
        &self,
        Parameters(SearchFolderParameters {
            path,
            pattern,
            exclude_pattern,
        }): Parameters<SearchFolderParameters>,
    ) -> Result<CallToolResult, McpError> {
        let files_found = search::search_files(&path, &pattern, exclude_pattern)
            .await
            .map_err(|e| {
                McpError::internal_error(
                    format!("Error searching directory '{}': {}", path, e),
                    None,
                )
            })?;

        let content = Content::json(&files_found).map_err(|e| {
            McpError::internal_error(
                format!("Error converting directory entries to JSON: {}", e),
                None,
            )
        })?;

        Ok(CallToolResult::success(vec![content]))
    }
}

#[tool_handler] // Macro that will generate a tool handler
impl ServerHandler for FilesystemServer {
    fn get_info(&self) -> rmcp::model::ServerInfo {
        ServerInfo {
            protocol_version: ProtocolVersion::V_2025_06_18,
            capabilities: ServerCapabilities::builder()
                .enable_tools() // Only enable tools
                .build(),
            server_info: Implementation::from_build_env(),
            instructions: Some(
                "I manage a list of TODOs. That are stored behind an API server.

        The available actions are:
        - list_directory: List files and subdirectories in a directory
        - search_files: Recursively search for files under a directory matching glob patterns
        "
                .to_string(),
            ),
        }
    }
    async fn initialize(
        &self,
        _request: rmcp::model::InitializeRequestParam,
        _context: rmcp::service::RequestContext<rmcp::RoleServer>,
    ) -> Result<InitializeResult, McpError> {
        Ok(self.get_info())
    }
}
