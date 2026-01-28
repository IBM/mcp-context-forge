package monitor

import (
    "context"
    "os"
    "path/filepath"
    "strings"
    "testing"
    "time"

    "github.com/IBM/mcp-context-forge/mcp-servers/go/system-monitor-server/pkg/types"
)

func TestNewLogMonitor(t *testing.T) {
    rootPath := ""
    allowedPaths := []string{"/var/log", "/tmp"}
    maxFileSize := int64(1024 * 1024) // 1MB

    lm := NewLogMonitor(rootPath, allowedPaths, maxFileSize)

    if lm == nil {
        t.Fatal("NewLogMonitor should not return nil")
    }

    if len(lm.allowedPaths) != 2 {
        t.Errorf("Expected 2 allowed paths, got %d", len(lm.allowedPaths))
    }

    if lm.allowedPaths[0] != "/var/log" {
        t.Errorf("Expected first allowed path /var/log, got %s", lm.allowedPaths[0])
    }

    if lm.allowedPaths[1] != "/tmp" {
        t.Errorf("Expected second allowed path /tmp, got %s", lm.allowedPaths[1])
    }

    if lm.maxFileSize != maxFileSize {
        t.Errorf("Expected maxFileSize %d, got %d", maxFileSize, lm.maxFileSize)
    }
}

func TestLogMonitorValidateFilePath(t *testing.T) {
    // Create a temporary directory for testing
    tmpDir, err := os.MkdirTemp("", "log-monitor-test-*")
    if err != nil {
        t.Fatalf("Failed to create temp dir: %v", err)
    }
    defer os.RemoveAll(tmpDir)

    // Create a subdirectory
    subDir := filepath.Join(tmpDir, "subdir")
    err = os.Mkdir(subDir, 0755)
    if err != nil {
        t.Fatalf("Failed to create subdir: %v", err)
    }

    // Create a test file
    testFile := filepath.Join(subDir, "test.log")
    err = os.WriteFile(testFile, []byte("test content"), 0644)
    if err != nil {
        t.Fatalf("Failed to create test file: %v", err)
    }

    lm := NewLogMonitor("", []string{tmpDir}, 1024*1024)

    // Test valid file path
    err = lm.validateFilePath(testFile)
    if err != nil {
        t.Errorf("Expected valid file path, got error: %v", err)
    }

    // Test file path outside allowed directory
    outsideFile := "/etc/passwd"
    err = lm.validateFilePath(outsideFile)
    if err == nil {
        t.Error("Expected error for file outside allowed directory")
    }

    // Test relative path
    relFile := filepath.Join("subdir", "test.log")
    err = lm.validateFilePath(relFile)
    if err == nil {
        t.Error("Expected error for relative path")
    }

    // Test non-existent file (should still validate path)
    nonExistentFile := filepath.Join(tmpDir, "nonexistent.log")
    err = lm.validateFilePath(nonExistentFile)
    if err != nil {
        t.Errorf("Expected valid path for non-existent file, got error: %v", err)
    }
}

func TestLogMonitorRootPathRestriction(t *testing.T) {
    // Create a root directory for testing
    rootDir, err := os.MkdirTemp("", "root-dir-test-*")
    if err != nil {
        t.Fatalf("Failed to create root dir: %v", err)
    }
    defer os.RemoveAll(rootDir)

    // Create a directory inside the root
    insideDir := filepath.Join(rootDir, "logs")
    err = os.Mkdir(insideDir, 0755)
    if err != nil {
        t.Fatalf("Failed to create inside dir: %v", err)
    }

    // Create a test file inside the root
    insideFile := filepath.Join(insideDir, "test.log")
    err = os.WriteFile(insideFile, []byte("test content"), 0644)
    if err != nil {
        t.Fatalf("Failed to create test file: %v", err)
    }

    // Create log monitor with root restriction
    lm := NewLogMonitor(rootDir, []string{insideDir}, 1024*1024)

    // Test file inside root - should be allowed
    err = lm.validateFilePath(insideFile)
    if err != nil {
        t.Errorf("Expected file inside root to be allowed, got error: %v", err)
    }

    // Test file outside root - should be denied
    outsideFile := "/etc/passwd"
    err = lm.validateFilePath(outsideFile)
    if err == nil {
        t.Error("Expected error for file outside root directory")
    }
    if err != nil && !strings.Contains(err.Error(), "outside root directory") {
        t.Errorf("Expected 'outside root directory' error, got: %v", err)
    }

    // Test file in /tmp (outside root) - should be denied even if in allowed paths
    tmpFile, err := os.CreateTemp("", "outside-root-test-*.txt")
    if err != nil {
        t.Fatalf("Failed to create temp file: %v", err)
    }
    defer os.Remove(tmpFile.Name())
    tmpFile.Close()

    lm2 := NewLogMonitor(rootDir, []string{"/tmp"}, 1024*1024)
    err = lm2.validateFilePath(tmpFile.Name())
    if err == nil {
        t.Error("Expected error for file outside root even with allowed path")
    }
    if err != nil && !strings.Contains(err.Error(), "outside root directory") {
        t.Errorf("Expected 'outside root directory' error, got: %v", err)
    }

    // Test with empty root path (no restriction) - should allow /tmp
    lm3 := NewLogMonitor("", []string{"/tmp"}, 1024*1024)
    err = lm3.validateFilePath(tmpFile.Name())
    if err != nil {
        t.Errorf("Expected file in /tmp to be allowed with empty root, got error: %v", err)
    }
}

func TestLogMonitorCheckFileSize(t *testing.T) {
    // Create a temporary file
    tmpFile, err := os.CreateTemp("", "size-test-*.txt")
    if err != nil {
        t.Fatalf("Failed to create temp file: %v", err)
    }
    defer os.Remove(tmpFile.Name())
    defer tmpFile.Close()

    // Write some content
    content := strings.Repeat("a", 1000) // 1000 bytes
    _, err = tmpFile.WriteString(content)
    if err != nil {
        t.Fatalf("Failed to write content: %v", err)
    }
    tmpFile.Close()

    lm := NewLogMonitor("", []string{"/tmp"}, 1024*1024)

    // Test file within size limit
    err = lm.checkFileSize(tmpFile.Name(), 2000)
    if err != nil {
        t.Errorf("Expected no error for file within size limit, got: %v", err)
    }

    // Test file exceeding size limit
    err = lm.checkFileSize(tmpFile.Name(), 500)
    if err == nil {
        t.Error("Expected error for file exceeding size limit")
    }

    // Test non-existent file
    err = lm.checkFileSize("/nonexistent/file.txt", 1000)
    if err == nil {
        t.Error("Expected error for non-existent file")
    }
}

func TestLogMonitorReadLastLines(t *testing.T) {
    // Create a temporary file with multiple lines
    tmpFile, err := os.CreateTemp("", "lines-test-*.txt")
    if err != nil {
        t.Fatalf("Failed to create temp file: %v", err)
    }
    defer os.Remove(tmpFile.Name())
    defer tmpFile.Close()

    // Write multiple lines
    lines := []string{
        "line 1",
        "line 2",
        "line 3",
        "line 4",
        "line 5",
    }
    for _, line := range lines {
        tmpFile.WriteString(line + "\n")
    }
    tmpFile.Close()

    lm := NewLogMonitor("", []string{"/tmp"}, 1024*1024)

    ctx := context.Background()

    // Test reading last 3 lines
    result, err := lm.readLastLines(ctx, tmpFile.Name(), 3, "")
    if err != nil {
        t.Fatalf("Failed to read last lines: %v", err)
    }

    if len(result) != 3 {
        t.Errorf("Expected 3 lines, got %d", len(result))
    }

    expected := []string{"line 3", "line 4", "line 5"}
    for i, line := range result {
        if line != expected[i] {
            t.Errorf("Expected line %d to be %s, got %s", i, expected[i], line)
        }
    }

    // Test reading more lines than available
    result, err = lm.readLastLines(ctx, tmpFile.Name(), 10, "")
    if err != nil {
        t.Fatalf("Failed to read lines: %v", err)
    }

    if len(result) != 5 {
        t.Errorf("Expected 5 lines, got %d", len(result))
    }

    // Test with filter
    result, err = lm.readLastLines(ctx, tmpFile.Name(), 10, "line [3-5]")
    if err != nil {
        t.Fatalf("Failed to read filtered lines: %v", err)
    }

    if len(result) != 3 {
        t.Errorf("Expected 3 filtered lines, got %d", len(result))
    }

    // Test with invalid regex
    _, err = lm.readLastLines(ctx, tmpFile.Name(), 10, "[invalid")
    if err == nil {
        t.Error("Expected error for invalid regex")
    }
}

func TestLogMonitorTailLogs(t *testing.T) {
    // Create a temporary file in /tmp
    tmpFile, err := os.CreateTemp("/tmp", "tail-test-*.txt")
    if err != nil {
        t.Fatalf("Failed to create temp file: %v", err)
    }
    defer os.Remove(tmpFile.Name())
    defer tmpFile.Close()

    // Write some content
    content := "test log line 1\ntest log line 2\ntest log line 3\n"
    _, err = tmpFile.WriteString(content)
    if err != nil {
        t.Fatalf("Failed to write content: %v", err)
    }
    tmpFile.Close()

    lm := NewLogMonitor("", []string{"/tmp"}, 1024*1024)

    ctx := context.Background()

    // Test basic tail request
    req := &types.LogTailRequest{
        FilePath: tmpFile.Name(),
        Lines:    2,
        Follow:   false,
    }

    result, err := lm.TailLogs(ctx, req)
    if err != nil {
        t.Fatalf("Failed to tail logs: %v", err)
    }

    if result == nil {
        t.Fatal("Expected non-nil result")
    }

    if result.FilePath != tmpFile.Name() {
        t.Errorf("Expected file path %s, got %s", tmpFile.Name(), result.FilePath)
    }

    if len(result.Lines) != 2 {
        t.Errorf("Expected 2 lines, got %d", len(result.Lines))
    }

    if result.TotalLines != 2 {
        t.Errorf("Expected total lines 2, got %d", result.TotalLines)
    }

    // Test with invalid file path (outside allowed directory)
    req.FilePath = "/etc/passwd"
    _, err = lm.TailLogs(ctx, req)
    if err == nil {
        t.Error("Expected error for file outside allowed directory")
    }

    // Test with file size check
    req.FilePath = tmpFile.Name()
    req.MaxSize = 10 // Very small size
    _, err = lm.TailLogs(ctx, req)
    if err == nil {
        t.Error("Expected error for file exceeding size limit")
    }

    // Test with missing file
    req.FilePath = "/nonexistent/file.txt"
    req.MaxSize = 0
    _, err = lm.TailLogs(ctx, req)
    if err == nil {
        t.Error("Expected error for missing file")
    }
}

func TestLogMonitorAnalyzeLogs(t *testing.T) {
    // Create a temporary file with various log levels in /tmp
    tmpFile, err := os.CreateTemp("/tmp", "analyze-test-*.txt")
    if err != nil {
        t.Fatalf("Failed to create temp file: %v", err)
    }
    defer os.Remove(tmpFile.Name())
    defer tmpFile.Close()

    // Write log lines with different levels
    logLines := []string{
        "2023-01-01 INFO: Application started",
        "2023-01-01 WARN: Low memory warning",
        "2023-01-01 ERROR: Database connection failed",
        "2023-01-01 INFO: User logged in",
        "2023-01-01 ERROR: File not found",
        "2023-01-01 WARN: Disk space low",
    }
    for _, line := range logLines {
        tmpFile.WriteString(line + "\n")
    }
    tmpFile.Close()

    lm := NewLogMonitor("", []string{"/tmp"}, 1024*1024)

    ctx := context.Background()

    // Test analysis with patterns
    patterns := []string{
        "ERROR",
        "WARN",
        "INFO",
        "Database",
    }

    result, err := lm.AnalyzeLogs(ctx, tmpFile.Name(), patterns)
    if err != nil {
        t.Fatalf("Failed to analyze logs: %v", err)
    }

    if result == nil {
        t.Fatal("Expected non-nil result")
    }

    // Check total lines
    if result["total_lines"] != 6 {
        t.Errorf("Expected 6 total lines, got %v", result["total_lines"])
    }

    // Check error count
    if result["error_count"] != 2 {
        t.Errorf("Expected 2 errors, got %v", result["error_count"])
    }

    // Check warning count
    if result["warning_count"] != 2 {
        t.Errorf("Expected 2 warnings, got %v", result["warning_count"])
    }

    // Check info count
    if result["info_count"] != 2 {
        t.Errorf("Expected 2 info messages, got %v", result["info_count"])
    }

    // Check pattern counts
    patternCounts, ok := result["pattern_counts"].(map[string]int)
    if !ok {
        t.Fatal("Expected pattern_counts to be map[string]int")
    }

    if patternCounts["ERROR"] != 2 {
        t.Errorf("Expected 2 ERROR matches, got %d", patternCounts["ERROR"])
    }

    if patternCounts["WARN"] != 2 {
        t.Errorf("Expected 2 WARN matches, got %d", patternCounts["WARN"])
    }

    if patternCounts["INFO"] != 2 {
        t.Errorf("Expected 2 INFO matches, got %d", patternCounts["INFO"])
    }

    if patternCounts["Database"] != 1 {
        t.Errorf("Expected 1 Database match, got %d", patternCounts["Database"])
    }

    // Test with file outside allowed directory
    _, err = lm.AnalyzeLogs(ctx, "/etc/passwd", patterns)
    if err == nil {
        t.Error("Expected error for file outside allowed directory")
    }
}

func TestLogMonitorGetDiskUsage(t *testing.T) {
    // Create a temporary directory structure
    tmpDir, err := os.MkdirTemp("", "disk-usage-test-*")
    if err != nil {
        t.Fatalf("Failed to create temp dir: %v", err)
    }
    defer os.RemoveAll(tmpDir)

    // Create subdirectories and files
    subDir1 := filepath.Join(tmpDir, "subdir1")
    subDir2 := filepath.Join(tmpDir, "subdir2")
    err = os.Mkdir(subDir1, 0755)
    if err != nil {
        t.Fatalf("Failed to create subdir1: %v", err)
    }
    err = os.Mkdir(subDir2, 0755)
    if err != nil {
        t.Fatalf("Failed to create subdir2: %v", err)
    }

    // Create files with different sizes
    file1 := filepath.Join(subDir1, "file1.txt")
    file2 := filepath.Join(subDir2, "file2.log")
    file3 := filepath.Join(tmpDir, "file3.txt")

    err = os.WriteFile(file1, []byte("content1"), 0644)
    if err != nil {
        t.Fatalf("Failed to create file1: %v", err)
    }

    err = os.WriteFile(file2, []byte("content2"), 0644)
    if err != nil {
        t.Fatalf("Failed to create file2: %v", err)
    }

    err = os.WriteFile(file3, []byte("content3"), 0644)
    if err != nil {
        t.Fatalf("Failed to create file3: %v", err)
    }

    lm := NewLogMonitor("", []string{tmpDir}, 1024*1024)

    ctx := context.Background()

    // Test basic disk usage
    req := &types.DiskUsageRequest{
        Path:     tmpDir,
        MaxDepth: 2,
        MinSize:  0,
        SortBy:   "size",
    }

    result, err := lm.GetDiskUsage(ctx, req)
    if err != nil {
        t.Fatalf("Failed to get disk usage: %v", err)
    }

    if result == nil {
        t.Fatal("Expected non-nil result")
    }

    if result.Path != tmpDir {
        t.Errorf("Expected path %s, got %s", tmpDir, result.Path)
    }

    if result.ItemCount < 5 { // At least 2 dirs + 3 files
        t.Errorf("Expected at least 5 items, got %d", result.ItemCount)
    }

    if result.TotalSize <= 0 {
        t.Errorf("Expected positive total size, got %d", result.TotalSize)
    }

    // Test with file type filter
    req.FileTypes = []string{"txt"}
    result, err = lm.GetDiskUsage(ctx, req)
    if err != nil {
        t.Fatalf("Failed to get disk usage with filter: %v", err)
    }

    // Should have fewer items (only .txt files)
    if result.ItemCount >= 5 {
        t.Errorf("Expected fewer items with file type filter, got %d", result.ItemCount)
    }

    // Test with minimum size filter
    req.FileTypes = []string{}
    req.MinSize = 1000 // Much larger than our file sizes
    result, err = lm.GetDiskUsage(ctx, req)
    if err != nil {
        t.Fatalf("Failed to get disk usage with size filter: %v", err)
    }

    // Should have no items (all files are smaller than 100 bytes)
    if result.ItemCount != 0 {
        t.Errorf("Expected 0 items with size filter, got %d", result.ItemCount)
    }

    // Test with depth limit
    req.MinSize = 0
    req.MaxDepth = 1
    result, err = lm.GetDiskUsage(ctx, req)
    if err != nil {
        t.Fatalf("Failed to get disk usage with depth limit: %v", err)
    }

    // Should have fewer items (only top level)
    if result.ItemCount >= 5 {
        t.Errorf("Expected fewer items with depth limit, got %d", result.ItemCount)
    }

    // Test with path outside allowed directory
    req.Path = "/etc"
    _, err = lm.GetDiskUsage(ctx, req)
    if err == nil {
        t.Error("Expected error for path outside allowed directory")
    }
}

func TestLogMonitorTailLogsFollow(t *testing.T) {
    // Create a temporary file in /tmp
    tmpFile, err := os.CreateTemp("/tmp", "follow-test-*.txt")
    if err != nil {
        t.Fatalf("Failed to create temp file: %v", err)
    }
    defer os.Remove(tmpFile.Name())
    defer tmpFile.Close()

    lm := NewLogMonitor("", []string{"/tmp"}, 1024*1024)

    ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
    defer cancel()

    // Test follow mode with timeout
    req := &types.LogTailRequest{
        FilePath: tmpFile.Name(),
        Lines:    10,
        Follow:   true,
    }

    result, err := lm.TailLogs(ctx, req)
    if err != nil {
        t.Fatalf("Failed to tail logs in follow mode: %v", err)
    }

    if result == nil {
        t.Fatal("Expected non-nil result")
    }

    // In follow mode with timeout, we should get an empty result
    if len(result.Lines) != 0 {
        t.Errorf("Expected empty lines in follow mode with timeout, got %d", len(result.Lines))
    }
}

func TestLogMonitorInvalidRegex(t *testing.T) {
    // Create a temporary file
    tmpFile, err := os.CreateTemp("", "regex-test-*.txt")
    if err != nil {
        t.Fatalf("Failed to create temp file: %v", err)
    }
    defer os.Remove(tmpFile.Name())
    defer tmpFile.Close()

    // Write some content
    tmpFile.WriteString("test line\n")
    tmpFile.Close()

    lm := NewLogMonitor("", []string{"/tmp"}, 1024*1024)

    ctx := context.Background()

    // Test with invalid regex in readLastLines
    _, err = lm.readLastLines(ctx, tmpFile.Name(), 10, "[invalid")
    if err == nil {
        t.Error("Expected error for invalid regex in readLastLines")
    }

    // Test with invalid regex in TailLogs
    req := &types.LogTailRequest{
        FilePath: tmpFile.Name(),
        Lines:    10,
        Follow:   false,
        Filter:   "[invalid",
    }

    _, err = lm.TailLogs(ctx, req)
    if err == nil {
        t.Error("Expected error for invalid regex in TailLogs")
    }
}
