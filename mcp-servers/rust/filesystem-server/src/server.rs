use crate::APP_NAME;
use crate::sandbox::Sandbox;
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
        let result = search::list_directory(&self.ctx.sandbox, &path)
            .await
            .map_err(|e| {
                McpError::internal_error(format!("Error listing directory '{}': {}", path, e), None)
            })?;

        let content = Content::json(&result).map_err(|e| {
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
        let result = search::search_files(&self.ctx.sandbox, &path, &pattern, exclude_pattern)
            .await
            .map_err(|e| {
                McpError::internal_error(
                    format!("Error searching files in '{}': {}", path, e),
                    None,
                )
            })?;

        let content = Content::json(&result).map_err(|e| {
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
        let result = read::read_file(&self.ctx.sandbox, &path)
            .await
            .map_err(|e| {
                McpError::internal_error(format!("Error reading file '{}': {}", path, e), None)
            })?;

        let content = Content::json(&result).map_err(|e| {
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
                    format!(
                        "Error moving file from '{}' to '{}': {}",
                        source, destination, e
                    ),
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
                McpError::internal_error(
                    format!("Error creating directory '{}': {}", path, e),
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

    #[tool(description = "Read several files from a list of filepaths")]
    async fn read_multiple_files(
        &self,
        Parameters(ReadMultipleFileParameters { paths }): Parameters<ReadMultipleFileParameters>,
    ) -> Result<CallToolResult, McpError> {
        let result = read::read_multiple_files(&self.ctx.sandbox, paths)
            .await
            .map_err(|e| {
                McpError::internal_error(format!("Error reading multiple files: {}", e), None)
            })?;

        let content = Content::json(&result).map_err(|e| {
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
        let result = info::get_file_info(&self.ctx.sandbox, &path)
            .await
            .map_err(|e| {
                McpError::internal_error(
                    format!("Error retrieving file info for '{}': {}", path, e),
                    None,
                )
            })?;

        let content = Content::json(&result).map_err(|e| {
            McpError::internal_error(
                format!("Error converting file metadata to JSON: {}", e),
                None,
            )
        })?;

        Ok(CallToolResult::success(vec![content]))
    }

    #[tool(description = "Reveal sandbox roots")]
    async fn list_allowed_directories(&self) -> Result<CallToolResult, McpError> {
        tracing::info!("List allowed directories");
        let roots = self.ctx.sandbox.get_roots();
        let content = Content::json(&roots).map_err(|e| {
            McpError::internal_error(format!("Error converting roots to JSON: {}", e), None)
        })?;
        tracing::info!("Success: Allowed directories {:?}", roots);
        Ok(CallToolResult::success(vec![content]))
    }
}

#[tool_handler]
impl ServerHandler for FilesystemServer {
    fn get_info(&self) -> ServerInfo {
        ServerInfo {
            protocol_version: ProtocolVersion::V_2025_06_18,
            capabilities: ServerCapabilities::builder().enable_tools().build(),
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
        tracing::info!("Client connected to {}", APP_NAME);
        Ok(self.get_info())
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use tempfile::TempDir;

    async fn setup_sandbox(temp_dir: &TempDir) -> Arc<Sandbox> {
        Arc::new(
            Sandbox::new(vec![temp_dir.path().to_string_lossy().to_string()])
                .await
                .expect("sandbox init failed"),
        )
    }

    fn create_app_context(sandbox: Arc<Sandbox>) -> Arc<AppContext> {
        Arc::new(AppContext { sandbox })
    }

    async fn create_test_server(temp_dir: &TempDir) -> FilesystemServer {
        let sandbox = setup_sandbox(temp_dir).await;
        let ctx = create_app_context(sandbox);
        FilesystemServer::new(ctx)
    }

    #[tokio::test]
    async fn test_server_info() {
        let temp_dir = tempfile::tempdir().unwrap();
        let server = create_test_server(&temp_dir).await;

        let info = server.get_info();
        assert!(info.instructions.is_some());
        let instr = info.instructions.unwrap();
        assert!(instr.contains("list_directory"));
        assert!(instr.contains("read_file"));
        assert!(instr.contains("write_file"));
    }

    #[tokio::test]
    async fn test_list_directory_and_allowed_dirs() {
        let temp_dir = tempfile::tempdir().unwrap();
        let server = create_test_server(&temp_dir).await;

        // Create file & subdir
        let file = temp_dir.path().join("file.txt");
        let subdir = temp_dir.path().join("subdir");
        std::fs::write(&file, "content").unwrap();
        std::fs::create_dir(&subdir).unwrap();

        // List directory
        let result = server
            .list_directory(Parameters(ReadFolderParameters {
                path: temp_dir.path().to_string_lossy().to_string(),
            }))
            .await;
        assert!(result.is_ok());

        // List sandbox roots
        let roots = server.list_allowed_directories().await;
        assert!(roots.is_ok());
    }

    #[tokio::test]
    async fn test_write_read_and_edit_file() {
        let temp_dir = tempfile::tempdir().unwrap();
        let server = create_test_server(&temp_dir).await;

        let file_path = temp_dir.path().join("file.txt");
        let path_str = file_path.to_string_lossy().to_string();

        // Write file
        server
            .write_file(Parameters(CreateFileParameters {
                path: path_str.clone(),
                content: "line1\nline2".to_string(),
            }))
            .await
            .unwrap();

        // Read file
        let read_result = server
            .read_file(Parameters(ReadFileParameters {
                path: path_str.clone(),
            }))
            .await;
        assert!(read_result.is_ok());

        // Apply edit
        let edits = vec![Edit {
            old: "line2".to_string(),
            new: "modified_line2".to_string(),
        }];
        server
            .edit_file(Parameters(EditFileParameters {
                path: path_str.clone(),
                edits: edits.clone(),
                dry_run: false,
            }))
            .await
            .unwrap();

        let content = std::fs::read_to_string(&file_path).unwrap();
        assert!(content.contains("modified_line2"));

        // Dry-run edit
        server
            .edit_file(Parameters(EditFileParameters {
                path: path_str.clone(),
                edits,
                dry_run: true,
            }))
            .await
            .unwrap();
    }

    #[tokio::test]
    async fn test_create_move_directory_and_file() {
        let temp_dir = tempfile::tempdir().unwrap();
        let server = create_test_server(&temp_dir).await;

        let nested_dir = temp_dir.path().join("a/b/c");
        server
            .create_directory(Parameters(CreateDirectoryParameter {
                path: nested_dir.to_string_lossy().to_string(),
            }))
            .await
            .unwrap();
        assert!(nested_dir.exists());

        let source = nested_dir.join("source.txt");
        let dest = temp_dir.path().join("dest.txt");
        std::fs::write(&source, "content").unwrap();

        server
            .move_file(Parameters(MoveFileParameters {
                source: source.to_string_lossy().to_string(),
                destination: dest.to_string_lossy().to_string(),
            }))
            .await
            .unwrap();

        assert!(!source.exists());
        assert!(dest.exists());
    }

    #[tokio::test]
    async fn test_get_file_info_and_search() {
        let temp_dir = tempfile::tempdir().unwrap();
        let server = create_test_server(&temp_dir).await;

        // File for info
        let file_path = temp_dir.path().join("file.txt");
        std::fs::write(&file_path, "content").unwrap();

        let info_res = server
            .get_file_info(Parameters(GetFileInfoParameters {
                path: file_path.to_string_lossy().to_string(),
            }))
            .await;
        assert!(info_res.is_ok());

        // Search files
        let nested = temp_dir.path().join("nested");
        std::fs::create_dir(&nested).unwrap();
        std::fs::write(nested.join("b.txt"), "2").unwrap();

        let search_res = server
            .search_files(Parameters(SearchFolderParameters {
                path: temp_dir.path().to_string_lossy().to_string(),
                pattern: "*.txt".to_string(),
                exclude_pattern: vec![],
            }))
            .await;
        assert!(search_res.is_ok());
    }

    #[tokio::test]
    async fn test_read_multiple_files() {
        let temp_dir = tempfile::tempdir().unwrap();
        let server = create_test_server(&temp_dir).await;

        let file1 = temp_dir.path().join("file1.txt");
        let file2 = temp_dir.path().join("file2.txt");
        std::fs::write(&file1, "1").unwrap();
        std::fs::write(&file2, "2").unwrap();

        let paths = vec![
            file1.to_string_lossy().to_string(),
            file2.to_string_lossy().to_string(),
        ];
        let res = server
            .read_multiple_files(Parameters(ReadMultipleFileParameters { paths }))
            .await;
        assert!(res.is_ok());
    }

    // ----------------------------
    // ERROR PATH TESTS
    // ----------------------------

    #[tokio::test]
    async fn test_invalid_paths() {
        let temp_dir = tempfile::tempdir().unwrap();
        let server = create_test_server(&temp_dir).await;

        // Read non-existent
        let r = server
            .read_file(Parameters(ReadFileParameters {
                path: "/nonexistent/file.txt".to_string(),
            }))
            .await;
        assert!(r.is_err());

        // Move non-existent
        let m = server
            .move_file(Parameters(MoveFileParameters {
                source: "/nonexistent/source.txt".to_string(),
                destination: "/nonexistent/dest.txt".to_string(),
            }))
            .await;
        assert!(m.is_err());

        // Edit non-existent
        let e = server
            .edit_file(Parameters(EditFileParameters {
                path: "/nonexistent.txt".to_string(),
                edits: vec![Edit {
                    old: "a".to_string(),
                    new: "b".to_string(),
                }],
                dry_run: false,
            }))
            .await;
        assert!(e.is_err());

        // Search invalid
        let s = server
            .search_files(Parameters(SearchFolderParameters {
                path: "/invalid/path".to_string(),
                pattern: "*.txt".to_string(),
                exclude_pattern: vec![],
            }))
            .await;
        assert!(s.is_err());
    }
}
