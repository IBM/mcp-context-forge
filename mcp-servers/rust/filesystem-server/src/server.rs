use crate::tools::edit::Edit;
use crate::tools::{edit, info, read, search, write};
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
use std::sync::Arc;
use crate::sandbox::Sandbox;


#[derive(Clone)]
pub struct FilesystemServer {
    tool_router: ToolRouter<Self>,
    ctx: Arc<AppContext>,
}

#[derive(Clone)]
pub struct AppContext {
    pub sandbox: Arc<Sandbox>,
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

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct CreateFileParameters {
    #[schemars(description = "Path for the new file")]
    path: String,
    #[schemars(description = "content for the new file")]
    content: String,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct CreateDirectoryParameter {
    #[schemars(description = "Path of new directory")]
    path: String,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct MoveFileParameters {
    #[schemars(description = "Source file path")]
    source: String,
    #[schemars(description = "Destination file path")]
    destination: String,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct EditFileParameters {
    #[schemars(description = "Source file path")]
    path: String,
    #[schemars(description = "Edits with old and new edits")]
    edits: Vec<Edit>,
    #[schemars(description = "Dry-run edit returns diff")]
    dry_run: bool,
}

// SERVER ROUTER
#[tool_router]
impl FilesystemServer {
    pub fn new(ctx: Arc<AppContext>) -> Self {
        Self {
            tool_router: Self::tool_router(),
            ctx,
        }
    }


    #[tool(description = "List files and subdirectories in a directory")]
    async fn list_directory(
        &self,
        Parameters(ReadFolderParameters { path }): Parameters<ReadFolderParameters>,
    ) -> Result<CallToolResult, McpError> {
        let dir_entries = search::list_directory(&self.ctx.sandbox, &path)
            .await
            .map_err(|e| {
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
        let files_found = search::search_files(&self.ctx.sandbox, &path, &pattern, exclude_pattern)
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
        let file_content = read::read_file(&self.ctx.sandbox, &path)
            .await
            .map_err(|e| {
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

    #[tool(description = "Create or overwrite a file")]
    async fn write_file(
        &self,
        Parameters(CreateFileParameters { path, content }): Parameters<CreateFileParameters>,
    ) -> Result<CallToolResult, McpError> {
        let result = write::write_file(&self.ctx.sandbox, &path, content)
            .await
            .map_err(|e| {
                McpError::internal_error(format!("Error writing file '{}': {}", path, e), None)
            })?;

        let content = Content::json(&result).map_err(|e| {
            McpError::internal_error(
                format!("Error converting file content to JSON: {}", e),
                None,
            )
        })?;

        Ok(CallToolResult::success(vec![content]))
    }

    #[tool(description = "Edit file with dry run")]
    async fn edit_file(
        &self,
        Parameters(EditFileParameters {
            path,
            edits,
            dry_run,
        }): Parameters<EditFileParameters>,
    ) -> Result<CallToolResult, McpError> {
        let result = edit::edit_file(&self.ctx.sandbox, &path, edits, dry_run)
            .await
            .map_err(|e| {
                McpError::internal_error(format!("Error editing file '{}': {}", path, e), None)
            })?;

        let content = Content::json(&result).map_err(|e| {
            McpError::internal_error(
                format!("Error converting file content to JSON: {}", e),
                None,
            )
        })?;

        Ok(CallToolResult::success(vec![content]))
    }

    #[tool(description = "Move a file from a source path to destination path")]
    async fn move_file(
        &self,
        Parameters(MoveFileParameters {
            source,
            destination,
        }): Parameters<MoveFileParameters>,
    ) -> Result<CallToolResult, McpError> {
        let result = edit::move_file(&self.ctx.sandbox, &source, &destination)
            .await
            .map_err(|e| {
                McpError::internal_error(
                    format!("Error moving file from '{}' to '{}': {}", source, destination, e),
                    None,
                )
            })?;

        let content = Content::json(&result).map_err(|e| {
            McpError::internal_error(
                format!("Error converting file content to JSON: {}", e),
                None,
            )
        })?;

        Ok(CallToolResult::success(vec![content]))
    }

    #[tool(description = "Create new directory")]
    async fn create_directory(
        &self,
        Parameters(CreateDirectoryParameter { path }): Parameters<CreateDirectoryParameter>,
    ) -> Result<CallToolResult, McpError> {
        let result = write::create_directory(&self.ctx.sandbox, &path)
            .await
            .map_err(|e| {
                McpError::internal_error(format!("Error creating directory '{}': {}", path, e), None)
            })?;

        let content = Content::json(&result).map_err(|e| {
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

        let files_content = read::read_multiple_files(&self.ctx.sandbox, paths)
            .await
            .map_err(|e| {
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
        let file_info = info::get_file_info(&self.ctx.sandbox, &path)
            .await
            .map_err(|e| {
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

    #[tool(description = "Reveal sandbox roots")]
    async fn list_allowed_directories(&self) -> Result<CallToolResult, McpError> {
        let roots = self.ctx.sandbox.get_roots();
        let content = Content::json(&roots).map_err(|e| {
            McpError::internal_error(
                format!("Error converting roots to JSON: {}", e),
                None,
            )
        })?;

        Ok(CallToolResult::success(vec![content]))
    }
}

#[tool_handler]
impl ServerHandler for FilesystemServer {
    fn get_info(&self) -> ServerInfo {
        ServerInfo {
            protocol_version: ProtocolVersion::V_2025_06_18,
            capabilities: ServerCapabilities::builder()
                .enable_tools()
                .build(),
            server_info: Implementation::from_build_env(),
            instructions: Some(
                "I manage a filesystem sandbox. Available actions:
- list_directory
- search_files
- read_file
- move_file
- read_multiple_files
- get_file_info
- write_file
- edit_file
- create_directory
- list_allowed_directories"
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