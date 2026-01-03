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
    #[schemars(description = "Path to get the folder and files inside")]
    path: String,
}

#[tool_router] // Macro that generates the tool router
impl FilesystemServer {
    pub fn new() -> Self {
        Self {
            tool_router: Self::tool_router(),
        }
    }
    #[tool(description = "Read a folder and get results")]
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
        - list_directory: List files and folders from a path
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
