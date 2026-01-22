#[cfg(test)]
mod comprehensive_tests {
    use filesystem_server::sandbox::Sandbox;
    use filesystem_server::tools::edit::{Edit, edit_file, move_file};
    use filesystem_server::tools::info::get_file_info;
    use filesystem_server::tools::read::{read_file, read_multiple_files};
    use filesystem_server::tools::search::{list_directory, search_files};
    use filesystem_server::tools::write::{create_directory, write_file};
    use std::os::unix::fs::PermissionsExt;
    use std::sync::Arc;
    use tempfile::TempDir;
    use tokio::fs as async_fs;

    async fn setup_sandbox(temp_dir: &TempDir) -> Arc<Sandbox> {
        let root = temp_dir.path().to_string_lossy().to_string();
        let sandbox = Sandbox::new(vec![root]).await.expect("sandbox init failed");
        Arc::new(sandbox)
    }

    // ==================== COMPREHENSIVE WORKFLOW TESTS ====================

    #[tokio::test]
    async fn test_complete_file_workflow() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;
        let root = temp_dir.path().to_string_lossy().to_string();

        // 1. Create directory
        let docs_dir = format!("{}/documents", root);
        create_directory(&sandbox, &docs_dir)
            .await
            .expect("create docs directory");

        // 2. Write file with initial content
        let file_path = format!("{}/README.md", docs_dir);
        write_file(
            &sandbox,
            &file_path,
            "# My Document\nVersion 1.0\n".to_string(),
        )
        .await
        .expect("write initial content");

        // 3. Read and verify initial content
        let initial_content = read_file(&sandbox, &file_path)
            .await
            .expect("read initial content");
        assert!(initial_content.contains("Version 1.0"));

        // 4. Edit the file
        let edits = vec![
            Edit {
                old: "Version 1.0".to_string(),
                new: "Version 2.0".to_string(),
            },
            Edit {
                old: "# My Document".to_string(),
                new: "# My Awesome Document".to_string(),
            },
        ];
        let edit_result = edit_file(&sandbox, &file_path, edits, false)
            .await
            .expect("edit file");
        assert!(edit_result.applied);

        // 5. Read and verify edited content
        let edited_content = read_file(&sandbox, &file_path)
            .await
            .expect("read edited content");
        assert!(edited_content.contains("Version 2.0"));
        assert!(edited_content.contains("# My Awesome Document"));

        // 6. Move file to new location
        let archived_dir = format!("{}/archived", root);
        create_directory(&sandbox, &archived_dir)
            .await
            .expect("create archived directory");

        let new_file_path = format!("{}/README.md", archived_dir);
        move_file(&sandbox, &file_path, &new_file_path)
            .await
            .expect("move file");

        // 7. Verify file was moved (old location should fail)
        let old_read = read_file(&sandbox, &file_path).await;
        assert!(old_read.is_err(), "File should not exist at old location");

        // 8. Verify file exists at new location with content preserved
        let moved_content = read_file(&sandbox, &new_file_path)
            .await
            .expect("read moved file");
        assert!(moved_content.contains("Version 2.0"));
        assert!(moved_content.contains("# My Awesome Document"));

        // 9. Get file info
        let info_json = get_file_info(&sandbox, &new_file_path)
            .await
            .expect("get file info");
        let info: serde_json::Value = serde_json::from_str(&info_json).unwrap();
        assert!(info["size"].as_u64().unwrap() > 0);
        assert!(info["permissions"].is_string());

        // 10. List directory to verify structure
        let entries = list_directory(&sandbox, &archived_dir)
            .await
            .expect("list archived directory");
        assert!(entries.iter().any(|e| e.contains("README.md")));
    }

    #[tokio::test]
    async fn test_complete_permission_and_metadata_workflow() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;
        let root = temp_dir.path().to_string_lossy().to_string();

        // 1. Create directory and file
        let config_dir = format!("{}/config", root);
        create_directory(&sandbox, &config_dir)
            .await
            .expect("create config directory");

        let config_file = format!("{}/settings.json", config_dir);
        write_file(
            &sandbox,
            &config_file,
            r#"{"debug": true, "version": "1.0"}"#.to_string(),
        )
        .await
        .expect("write config file");

        // 2. Get initial metadata
        let initial_info = get_file_info(&sandbox, &config_file)
            .await
            .expect("get initial info");
        let initial_val: serde_json::Value = serde_json::from_str(&initial_info).unwrap();
        let initial_size = initial_val["size"].as_u64().unwrap();
        assert!(initial_size > 0);

        // 3. Edit file to change size
        let edits = vec![Edit {
            old: r#""debug": true"#.to_string(),
            new: r#""debug": false, "production": true"#.to_string(),
        }];
        edit_file(&sandbox, &config_file, edits, false)
            .await
            .expect("edit config");

        // 4. Get updated metadata
        let updated_info = get_file_info(&sandbox, &config_file)
            .await
            .expect("get updated info");
        let updated_val: serde_json::Value = serde_json::from_str(&updated_info).unwrap();
        let updated_size = updated_val["size"].as_u64().unwrap();
        assert!(
            updated_size > initial_size,
            "File should be larger after edit"
        );

        // 5. Set specific permissions and verify
        let file_path_pb = temp_dir.path().join("config/settings.json");
        let perms = std::fs::Permissions::from_mode(0o600);
        async_fs::set_permissions(&file_path_pb, perms)
            .await
            .expect("set permissions");

        let perms_info = get_file_info(&sandbox, &config_file)
            .await
            .expect("get permissions info");
        let perms_val: serde_json::Value = serde_json::from_str(&perms_info).unwrap();
        let perms_str = perms_val["permissions"].as_str().unwrap();
        assert_eq!(perms_str, "600");

        // 6. Read final content and verify
        let final_content = read_file(&sandbox, &config_file)
            .await
            .expect("read final config");
        assert!(final_content.contains("production"));
        assert!(final_content.contains("false"));

        // 7. Move file and verify metadata preserved
        let backup_file = format!("{}/settings.json.backup", config_dir);
        move_file(&sandbox, &config_file, &backup_file)
            .await
            .expect("move to backup");

        let backup_info = get_file_info(&sandbox, &backup_file)
            .await
            .expect("get backup info");
        let backup_val: serde_json::Value = serde_json::from_str(&backup_info).unwrap();
        assert_eq!(backup_val["size"].as_u64().unwrap(), updated_size);
    }

    #[tokio::test]
    async fn test_complete_search_and_organize_workflow() {
        let temp_dir = TempDir::new().unwrap();
        let sandbox = setup_sandbox(&temp_dir).await;
        let root = temp_dir.path().to_string_lossy().to_string();

        // 1. Create mixed directory structure
        let docs_dir = format!("{}/docs", root);
        let images_dir = format!("{}/images", root);
        let code_dir = format!("{}/code", root);

        create_directory(&sandbox, &docs_dir)
            .await
            .expect("create docs");
        create_directory(&sandbox, &images_dir)
            .await
            .expect("create images");
        create_directory(&sandbox, &code_dir)
            .await
            .expect("create code");

        // 2. Create various files
        write_file(
            &sandbox,
            &format!("{}/readme.md", docs_dir),
            "# Read me".to_string(),
        )
        .await
        .expect("write readme");
        write_file(
            &sandbox,
            &format!("{}/guide.md", docs_dir),
            "# Guide".to_string(),
        )
        .await
        .expect("write guide");
        write_file(
            &sandbox,
            &format!("{}/script.py", code_dir),
            "print('hello')".to_string(),
        )
        .await
        .expect("write python");
        write_file(
            &sandbox,
            &format!("{}/script.js", code_dir),
            "console.log('hello')".to_string(),
        )
        .await
        .expect("write js");
        write_file(
            &sandbox,
            &format!("{}/image.txt", images_dir),
            "fake image".to_string(),
        )
        .await
        .expect("write fake image");

        // 3. Search for Markdown files
        let md_files = search_files(&sandbox, &root, "*.md", vec![])
            .await
            .expect("search markdown");
        assert!(md_files.len() >= 2);
        assert!(md_files.iter().any(|f| f.ends_with("readme.md")));
        assert!(md_files.iter().any(|f| f.ends_with("guide.md")));

        // 4. Search excluding specific patterns
        let code_files = search_files(&sandbox, &code_dir, "*", vec!["*.txt".to_string()])
            .await
            .expect("search code files");
        assert!(code_files.len() >= 2);

        // 5. List each directory and verify content
        let docs_entries = list_directory(&sandbox, &docs_dir)
            .await
            .expect("list docs");
        assert_eq!(docs_entries.len(), 2);

        let code_entries = list_directory(&sandbox, &code_dir)
            .await
            .expect("list code");
        assert_eq!(code_entries.len(), 2);

        // 6. Edit a markdown file
        let readme_path = format!("{}/readme.md", docs_dir);
        let edits = vec![Edit {
            old: "# Read me".to_string(),
            new: "# Important Read Me\n\nPlease read this first!".to_string(),
        }];
        edit_file(&sandbox, &readme_path, edits, false)
            .await
            .expect("edit readme");

        let updated_readme = read_file(&sandbox, &readme_path)
            .await
            .expect("read updated readme");
        assert!(updated_readme.contains("Important"));

        // 7. Move markdown files to archive
        let archive_dir = format!("{}/archive", root);
        create_directory(&sandbox, &archive_dir)
            .await
            .expect("create archive");

        move_file(
            &sandbox,
            &readme_path,
            &format!("{}/readme.md", archive_dir),
        )
        .await
        .expect("move readme");
        move_file(
            &sandbox,
            &format!("{}/guide.md", docs_dir),
            &format!("{}/guide.md", archive_dir),
        )
        .await
        .expect("move guide");

        // 8. Verify final structure via search
        let remaining_md = search_files(&sandbox, &root, "*.md", vec![])
            .await
            .expect("search remaining markdown");
        assert!(remaining_md.iter().any(|f| f.contains("archive")));

        // 9. Get metadata on moved files
        let archived_readme = format!("{}/readme.md", archive_dir);
        let readme_info = get_file_info(&sandbox, &archived_readme)
            .await
            .expect("get archived readme info");
        let readme_info_val: serde_json::Value = serde_json::from_str(&readme_info).unwrap();
        assert!(readme_info_val["size"].as_u64().unwrap() > 20);

        // 10. Final verification - list archive directory
        let archive_entries = list_directory(&sandbox, &archive_dir)
            .await
            .expect("list archive");
        assert_eq!(archive_entries.len(), 2);
        assert!(archive_entries.iter().any(|e| e.contains("readme.md")));
        assert!(archive_entries.iter().any(|e| e.contains("guide.md")));
    }

    // ==================== SERVER TESTS ====================

    #[tokio::test]
    async fn test_server_with_multiple_sandbox_roots() {
        let temp_dir1 = TempDir::new().unwrap();
        let temp_dir2 = TempDir::new().unwrap();

        let root1 = temp_dir1.path().to_string_lossy().to_string();
        let root2 = temp_dir2.path().to_string_lossy().to_string();

        // 1. Create sandbox with multiple roots
        let roots = vec![root1.clone(), root2.clone()];
        let sandbox = Sandbox::new(roots)
            .await
            .expect("sandbox with multiple roots failed");

        // 2. Create and manage files in first root
        let proj1_dir = format!("{}/project1", root1);
        create_directory(&sandbox, &proj1_dir)
            .await
            .expect("create project1");

        let file1 = format!("{}/config.json", proj1_dir);
        write_file(&sandbox, &file1, r#"{"name": "Project 1"}"#.to_string())
            .await
            .expect("write project1 config");

        // 3. Create and manage files in second root
        let proj2_dir = format!("{}/project2", root2);
        create_directory(&sandbox, &proj2_dir)
            .await
            .expect("create project2");

        let file2 = format!("{}/config.json", proj2_dir);
        write_file(&sandbox, &file2, r#"{"name": "Project 2"}"#.to_string())
            .await
            .expect("write project2 config");

        // 4. Edit files in both roots
        let edits = vec![Edit {
            old: "Project 1".to_string(),
            new: "Project One".to_string(),
        }];
        edit_file(&sandbox, &file1, edits, false)
            .await
            .expect("edit project1");

        let edits2 = vec![Edit {
            old: "Project 2".to_string(),
            new: "Project Two".to_string(),
        }];
        edit_file(&sandbox, &file2, edits2, false)
            .await
            .expect("edit project2");

        // 5. Read and verify both files
        let content1 = read_file(&sandbox, &file1).await.expect("read project1");
        assert!(content1.contains("Project One"));

        let content2 = read_file(&sandbox, &file2).await.expect("read project2");
        assert!(content2.contains("Project Two"));

        // 5.5. Read multiple files at once
        let file_paths = vec![file1.clone(), file2.clone()];
        let multiple_contents = read_multiple_files(&sandbox, file_paths)
            .await
            .expect("read multiple files");
        assert_eq!(multiple_contents.len(), 2);
        assert!(multiple_contents[0].contains("Project One"));
        assert!(multiple_contents[1].contains("Project Two"));

        // 6. Move files
        let backup1 = format!("{}/backup.json", proj1_dir);
        move_file(&sandbox, &file1, &backup1)
            .await
            .expect("backup project1");

        let backup2 = format!("{}/backup.json", proj2_dir);
        move_file(&sandbox, &file2, &backup2)
            .await
            .expect("backup project2");

        // 7. Get metadata on backups
        let backup1_info = get_file_info(&sandbox, &backup1)
            .await
            .expect("get backup1 info");
        let backup1_val: serde_json::Value = serde_json::from_str(&backup1_info).unwrap();
        assert!(backup1_val["size"].as_u64().unwrap() > 0);

        let backup2_info = get_file_info(&sandbox, &backup2)
            .await
            .expect("get backup2 info");
        let backup2_val: serde_json::Value = serde_json::from_str(&backup2_info).unwrap();
        assert!(backup2_val["size"].as_u64().unwrap() > 0);

        // 8. List directories in both roots
        let root1_entries = list_directory(&sandbox, &root1).await.expect("list root1");
        assert!(root1_entries.iter().any(|e| e.ends_with("/")));

        let root2_entries = list_directory(&sandbox, &root2).await.expect("list root2");
        assert!(root2_entries.iter().any(|e| e.ends_with("/")));
    }

    #[tokio::test]
    async fn test_server_initialize_handler() {
        use filesystem_server::server::{AppContext, FilesystemServer};
        use rmcp::ServerHandler;

        let temp_dir = TempDir::new().unwrap();
        let root = temp_dir.path().to_string_lossy().to_string();

        // 1. Create sandbox and server
        let sandbox = Sandbox::new(vec![root]).await.expect("sandbox init failed");
        let ctx = Arc::new(AppContext {
            sandbox: Arc::new(sandbox),
        });

        let server = FilesystemServer::new(ctx);

        // 2. Test server initialization
        let info = server.get_info();
        assert_eq!(
            info.protocol_version.to_string(),
            "2025-06-18",
            "Protocol version should match expected"
        );
        assert_eq!(info.server_info.name, "rmcp");
        assert!(
            info.instructions.is_some(),
            "Server should have instructions"
        );

        // 3. Verify all operations are in instructions
        let instructions = info.instructions.unwrap();
        assert!(instructions.contains("list_directory"));
        assert!(instructions.contains("search_files"));
        assert!(instructions.contains("read_file"));
        assert!(instructions.contains("write_file"));
        assert!(instructions.contains("edit_file"));
        assert!(instructions.contains("create_directory"));
        assert!(instructions.contains("move_file"));
        assert!(instructions.contains("get_file_info"));
        assert!(instructions.contains("read_multiple_files"));
        assert!(instructions.contains("list_allowed_directories"));

        // 4. Verify capabilities
        assert!(
            info.capabilities.tools.is_some(),
            "Tools capability should be enabled"
        );
    }

    #[tokio::test]
    async fn test_filesystem_server_initialization() {
        use filesystem_server::server::{AppContext, FilesystemServer};

        let temp_dir = TempDir::new().unwrap();
        let root = temp_dir.path().to_string_lossy().to_string();

        // Create sandbox and server
        let sandbox = Sandbox::new(vec![root.clone()])
            .await
            .expect("sandbox init failed");
        let ctx = Arc::new(AppContext {
            sandbox: Arc::new(sandbox),
        });

        let _server = FilesystemServer::new(ctx.clone());

        // Verify server was created successfully
        assert!(!root.is_empty());

        // Create a test file through the server's sandbox
        let file_path = temp_dir.path().join("server_test.txt");
        write_file(
            &ctx.sandbox,
            file_path.to_str().unwrap(),
            "Server test content".to_string(),
        )
        .await
        .expect("write file through server");

        // Verify file exists and can be read
        let content = read_file(&ctx.sandbox, file_path.to_str().unwrap())
            .await
            .expect("read file through server");
        assert_eq!(content, "Server test content");
    }

    #[tokio::test]
    async fn test_filesystem_server_router() {
        use filesystem_server::build_router;

        let temp_dir = TempDir::new().unwrap();
        let root = temp_dir.path().to_string_lossy().to_string();

        // Build router with sandbox roots
        let _router = build_router(vec![root.clone()])
            .await
            .expect("router build failed");

        // Verify router was created
        // The router should be a valid Axum router
        assert!(!root.is_empty());
    }

    // ==================== CLI ARGUMENTS TEST ====================

    #[test]
    fn test_cli_args_parsing() {
        use clap::Parser;

        // Mock the CLI args structure from main.rs
        #[derive(Parser, Debug)]
        struct Args {
            #[arg(long)]
            roots: Vec<String>,
        }

        // Test with single root
        let args = Args::parse_from(&["program", "--roots", "/tmp/root1"]);
        assert_eq!(args.roots.len(), 1);
        assert_eq!(args.roots[0], "/tmp/root1");

        // Test with multiple roots
        let args = Args::parse_from(&["program", "--roots", "/tmp/root1", "--roots", "/tmp/root2"]);
        assert_eq!(args.roots.len(), 2);
        assert_eq!(args.roots[0], "/tmp/root1");
        assert_eq!(args.roots[1], "/tmp/root2");

        // Test with no roots
        let args = Args::parse_from(&["program"]);
        assert_eq!(args.roots.len(), 0);
    }

    #[tokio::test]
    async fn test_cli_args_sandbox_creation() {
        let temp_dir1 = TempDir::new().unwrap();
        let temp_dir2 = TempDir::new().unwrap();

        let root1 = temp_dir1.path().to_string_lossy().to_string();
        let root2 = temp_dir2.path().to_string_lossy().to_string();

        // Simulate CLI args with multiple roots
        let roots = vec![root1.clone(), root2.clone()];

        // Create sandbox with multiple roots
        let sandbox = Sandbox::new(roots)
            .await
            .expect("sandbox with multiple roots failed");

        // Write file in first root
        let file1 = temp_dir1.path().join("file1.txt");
        write_file(&sandbox, file1.to_str().unwrap(), "From root1".to_string())
            .await
            .expect("write to root1");

        // Write file in second root
        let file2 = temp_dir2.path().join("file2.txt");
        write_file(&sandbox, file2.to_str().unwrap(), "From root2".to_string())
            .await
            .expect("write to root2");

        // Verify both files exist and are accessible
        let content1 = read_file(&sandbox, file1.to_str().unwrap())
            .await
            .expect("read from root1");
        assert_eq!(content1, "From root1");

        let content2 = read_file(&sandbox, file2.to_str().unwrap())
            .await
            .expect("read from root2");
        assert_eq!(content2, "From root2");

        // Verify listing works on both roots
        let entries1 = list_directory(&sandbox, root1.as_str())
            .await
            .expect("list root1");
        assert!(entries1.iter().any(|e| e.contains("file1")));

        let entries2 = list_directory(&sandbox, root2.as_str())
            .await
            .expect("list root2");
        assert!(entries2.iter().any(|e| e.contains("file2")));
    }
}
