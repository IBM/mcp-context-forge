use crate::tools::{info, read, search};
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

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct ReadFileParameters {
    #[schemars(description = "Filepath for reading a file")]
    path: String,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct ReadMultipleFileParameters {
    #[schemars(description = "Arrays of filenames to be read")]
    paths: Vec<String>,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct GetFileInfoParameters {
    #[schemars(description = "Filepath for get file info of")]
    path: String,
}

#[tool_router]
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
            McpError::internal_error(format!("Error listing directory '{}': {}", path, e), None)
        })?;

        let content = Content::json(&dir_entries).map_err(|e| {
            McpError::internal_error(
                format!("Error converting directory listing to JSON: {}", e),
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
                    format!("Error searching files in '{}': {}", path, e),
                    None,
                )
            })?;

        let content = Content::json(&files_found).map_err(|e| {
            McpError::internal_error(
                format!("Error converting search results to JSON: {}", e),
                None,
            )
        })?;

        Ok(CallToolResult::success(vec![content]))
    }

    #[tool(description = "Read a file from a given filepath")]
    async fn read_file(
        &self,
        Parameters(ReadFileParameters { path }): Parameters<ReadFileParameters>,
    ) -> Result<CallToolResult, McpError> {
        let file_content = read::read_file(&path).await.map_err(|e| {
            McpError::internal_error(format!("Error reading file '{}': {}", path, e), None)
        })?;

        let content = Content::json(&file_content).map_err(|e| {
            McpError::internal_error(
                format!("Error converting file content to JSON: {}", e),
                None,
            )
        })?;

        Ok(CallToolResult::success(vec![content]))
    }

    #[tool(description = "Read several files from a list of filepaths")]
    async fn read_multiple_files(
        &self,
        Parameters(ReadMultipleFileParameters { paths }): Parameters<ReadMultipleFileParameters>,
    ) -> Result<CallToolResult, McpError> {
        let files_content = read::read_multiple_files(paths).await.map_err(|e| {
            McpError::internal_error(format!("Error reading multiple files: {}", e), None)
        })?;

        let content = Content::json(&files_content).map_err(|e| {
            McpError::internal_error(
                format!("Error converting multiple file contents to JSON: {}", e),
                None,
            )
        })?;

        Ok(CallToolResult::success(vec![content]))
    }

    #[tool(
        description = "Return metadata for a given file path, including size, permissions, creation time, and last modified time"
    )]
    async fn get_file_info(
        &self,
        Parameters(GetFileInfoParameters { path }): Parameters<GetFileInfoParameters>,
    ) -> Result<CallToolResult, McpError> {
        let file_info = info::get_file_info(&path).await.map_err(|e| {
            McpError::internal_error(
                format!("Error retrieving file info for '{}': {}", path, e),
                None,
            )
        })?;

        let content = Content::json(&file_info).map_err(|e| {
            McpError::internal_error(
                format!("Error converting file metadata to JSON: {}", e),
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
        - read_file: Read a file from a given filepath
        - read_multiple_files: Read several files from a list of filepaths
        - get_file_info: Return metadata for a given file path, including size, permissions, creation time, and last modified time
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
