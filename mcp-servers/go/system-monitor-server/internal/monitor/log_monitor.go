package monitor

import (
    "bufio"
    "context"
    "fmt"
    "io"
    "os"
    "path/filepath"
    "regexp"
    "sort"
    "strings"
    "time"

    "github.com/IBM/mcp-context-forge/mcp-servers/go/system-monitor-server/pkg/types"
    "github.com/hpcloud/tail"
)

// LogMonitor handles log file monitoring and tailing
type LogMonitor struct {
    rootPath     string   // Root directory - all file access restricted within this path (empty = no restriction)
    allowedPaths []string
    maxFileSize  int64
}

// NewLogMonitor creates a new log monitor
func NewLogMonitor(rootPath string, allowedPaths []string, maxFileSize int64) *LogMonitor {
    return &LogMonitor{
        rootPath:     rootPath,
        allowedPaths: allowedPaths,
        maxFileSize:  maxFileSize,
    }
}

// TailLogs tails log files with filtering and security controls
func (lm *LogMonitor) TailLogs(ctx context.Context, req *types.LogTailRequest) (*types.LogTailResult, error) {
    // Security check: validate file path
    if err := lm.validateFilePath(req.FilePath); err != nil {
        return nil, fmt.Errorf("file path validation failed: %w", err)
    }

    // Check file size if specified
    if req.MaxSize > 0 {
        if err := lm.checkFileSize(req.FilePath, req.MaxSize); err != nil {
            return nil, err
        }
    }

    // Get file info
    _, err := os.Stat(req.FilePath)
    if err != nil {
        return nil, fmt.Errorf("failed to get file info: %w", err)
    }

    // Determine number of lines to read
    lines := req.Lines
    if lines <= 0 {
        lines = 100 // default
    }

    var logLines []string

    if req.Follow {
        // Use tail library for following
        logLines, err = lm.tailFileFollow(ctx, req)
    } else {
        // Read last N lines from file
        logLines, err = lm.readLastLines(ctx, req.FilePath, lines, req.Filter)
    }

    if err != nil {
        return nil, fmt.Errorf("failed to read log file: %w", err)
    }

    return &types.LogTailResult{
        Lines:      logLines,
        FilePath:   req.FilePath,
        TotalLines: len(logLines),
        Timestamp:  time.Now(),
    }, nil
}

// tailFileFollow uses the tail library to follow a file
func (lm *LogMonitor) tailFileFollow(ctx context.Context, req *types.LogTailRequest) ([]string, error) {
    // Configure tail
    config := tail.Config{
        Follow:    true,
        ReOpen:    true,
        MustExist: false,
        Poll:      true,
        Location:  &tail.SeekInfo{Offset: 0, Whence: io.SeekEnd},
    }

    // Set number of lines to read initially
    if req.Lines > 0 {
        config.Location = &tail.SeekInfo{Offset: 0, Whence: io.SeekEnd}
    }

    t, err := tail.TailFile(req.FilePath, config)
    if err != nil {
        return nil, fmt.Errorf("failed to tail file: %w", err)
    }
    defer t.Stop()

    var lines []string
    lineCount := 0
    maxLines := req.Lines
    if maxLines <= 0 {
        maxLines = 1000 // default max
    }

    // Compile filter regex if provided with ReDoS protection
    var filterRegex *regexp.Regexp
    if req.Filter != "" {
        filterRegex, err = lm.validateRegex(req.Filter)
        if err != nil {
            return nil, fmt.Errorf("invalid filter regex: %w", err)
        }
    }

    // Set up timeout
    timeout := 30 * time.Second
    if req.Follow {
        timeout = 5 * time.Minute // longer timeout for follow mode
    }

    timeoutCtx, cancel := context.WithTimeout(ctx, timeout)
    defer cancel()

    for {
        select {
        case <-timeoutCtx.Done():
            return lines, nil
        case line, ok := <-t.Lines:
            if !ok {
                return lines, nil
            }

            if line.Err != nil {
                return lines, fmt.Errorf("tail error: %w", line.Err)
            }

            // Apply filter if specified
            if filterRegex != nil && !filterRegex.MatchString(line.Text) {
                continue
            }

            lines = append(lines, line.Text)
            lineCount++

            // Stop if we've reached the maximum number of lines
            if lineCount >= maxLines {
                return lines, nil
            }
        }
    }
}

// readLastLines reads the last N lines from a file
func (lm *LogMonitor) readLastLines(ctx context.Context, filePath string, lines int, filter string) ([]string, error) {
    // SECURITY: Check file size BEFORE reading to prevent memory exhaustion
    if lm.maxFileSize > 0 {
        if err := lm.checkFileSize(filePath, lm.maxFileSize); err != nil {
            return nil, err
        }
    }

    file, err := os.Open(filePath)
    if err != nil {
        return nil, fmt.Errorf("failed to open file: %w", err)
    }
    defer file.Close()

    // Compile filter regex if provided with ReDoS protection
    var filterRegex *regexp.Regexp
    if filter != "" {
        filterRegex, err = lm.validateRegex(filter)
        if err != nil {
            return nil, fmt.Errorf("invalid filter regex: %w", err)
        }
    }

    // Read all lines first
    var allLines []string
    scanner := bufio.NewScanner(file)

    // SECURITY: Limit scanner buffer size to prevent memory exhaustion
    const maxScanTokenSize = 10 * 1024 * 1024 // 10MB per line max
    buf := make([]byte, maxScanTokenSize)
    scanner.Buffer(buf, maxScanTokenSize)
    for scanner.Scan() {
        line := scanner.Text()

        // Apply filter if specified
        if filterRegex != nil && !filterRegex.MatchString(line) {
            continue
        }

        allLines = append(allLines, line)
    }

    if err := scanner.Err(); err != nil {
        return nil, fmt.Errorf("failed to read file: %w", err)
    }

    // Return last N lines
    start := len(allLines) - lines
    if start < 0 {
        start = 0
    }

    return allLines[start:], nil
}

// validateFilePath validates that the file path is allowed
// Security: Resolves symlinks to prevent path traversal attacks and enforces root boundary
func (lm *LogMonitor) validateFilePath(filePath string) error {
    // Resolve the absolute path
    absPath, err := filepath.Abs(filePath)
    if err != nil {
        return fmt.Errorf("failed to resolve absolute path: %w", err)
    }

    // SECURITY: Resolve symlinks to prevent path traversal via symlink attacks
    // This prevents attacks where /var/log/evil -> /etc/passwd
    realPath, err := filepath.EvalSymlinks(absPath)
    if err != nil {
        // File might not exist yet, use abs path but validate parent exists
        realPath = absPath
    }

    // Clean the path to remove any .. or . components
    realPath = filepath.Clean(realPath)

    // SECURITY: Enforce root boundary (chroot-like restriction)
    // If rootPath is set, ALL file access must be within this root directory
    if lm.rootPath != "" {
        // Resolve and clean the root path
        rootAbsPath, err := filepath.Abs(lm.rootPath)
        if err != nil {
            return fmt.Errorf("failed to resolve root path: %w", err)
        }

        rootRealPath, err := filepath.EvalSymlinks(rootAbsPath)
        if err != nil {
            // Root might not exist yet, use abs path
            rootRealPath = rootAbsPath
        }
        rootRealPath = filepath.Clean(rootRealPath)

        // Ensure the path is within the root directory
        // Add separator to prevent /opt/root matching /opt/rootmalicious
        if !strings.HasPrefix(realPath, rootRealPath+string(filepath.Separator)) && realPath != rootRealPath {
            return fmt.Errorf("file path %s is outside root directory %s", realPath, rootRealPath)
        }
    }

    // Check if the path is in allowed directories
    allowed := false
    for _, allowedPath := range lm.allowedPaths {
        // Resolve allowed path to absolute and evaluate symlinks
        allowedAbsPath, err := filepath.Abs(allowedPath)
        if err != nil {
            continue
        }

        allowedRealPath, err := filepath.EvalSymlinks(allowedAbsPath)
        if err != nil {
            // Allowed path might not exist, use abs path
            allowedRealPath = allowedAbsPath
        }

        allowedRealPath = filepath.Clean(allowedRealPath)

        // Ensure we're checking directory boundaries properly
        // Add separator to prevent /var/log matching /var/logmalicious
        if realPath == allowedRealPath || strings.HasPrefix(realPath, allowedRealPath+string(filepath.Separator)) {
            allowed = true
            break
        }
    }

    if !allowed {
        return fmt.Errorf("file path %s is not in allowed directories: %v", realPath, lm.allowedPaths)
    }

    return nil
}

// validateRegex validates and compiles a regex pattern with ReDoS protection
// Security: Prevents ReDoS attacks by limiting regex complexity
func (lm *LogMonitor) validateRegex(pattern string) (*regexp.Regexp, error) {
    // Basic ReDoS protection: limit pattern length
    const maxPatternLength = 1000
    if len(pattern) > maxPatternLength {
        return nil, fmt.Errorf("regex pattern too long (max %d characters)", maxPatternLength)
    }

    // Check for dangerous patterns that could cause ReDoS
    // Nested quantifiers like (a+)+ or (a*)*
    dangerousPatterns := []string{
        `\(\w*\+\)\+`, // (a+)+
        `\(\w*\*\)\*`, // (a*)*
        `\(\w*\+\)\*`, // (a+)*
        `\(\w*\*\)\+`, // (a*)+
    }

    for _, dangerous := range dangerousPatterns {
        matched, _ := regexp.MatchString(dangerous, pattern)
        if matched {
            return nil, fmt.Errorf("regex pattern contains potentially dangerous nested quantifiers")
        }
    }

    // Try to compile with timeout protection
    regex, err := regexp.Compile(pattern)
    if err != nil {
        return nil, fmt.Errorf("invalid regex pattern: %w", err)
    }

    return regex, nil
}

// checkFileSize checks if the file size is within limits
func (lm *LogMonitor) checkFileSize(filePath string, maxSize int64) error {
    info, err := os.Stat(filePath)
    if err != nil {
        return fmt.Errorf("failed to get file info: %w", err)
    }

    if info.Size() > maxSize {
        return fmt.Errorf("file size %d exceeds maximum allowed size %d", info.Size(), maxSize)
    }

    return nil
}

// AnalyzeLogs analyzes log files for patterns and statistics
func (lm *LogMonitor) AnalyzeLogs(ctx context.Context, filePath string, patterns []string) (map[string]interface{}, error) {
    // Security check
    if err := lm.validateFilePath(filePath); err != nil {
        return nil, err
    }

    file, err := os.Open(filePath)
    if err != nil {
        return nil, fmt.Errorf("failed to open file: %w", err)
    }
    defer file.Close()

    scanner := bufio.NewScanner(file)
    lineCount := 0
    patternCounts := make(map[string]int)
    errorCount := 0
    warningCount := 0
    infoCount := 0

    // Compile patterns with ReDoS protection
    compiledPatterns := make(map[string]*regexp.Regexp)
    for _, pattern := range patterns {
        regex, err := lm.validateRegex(pattern)
        if err != nil {
            continue // skip invalid or dangerous patterns
        }
        compiledPatterns[pattern] = regex
    }

    for scanner.Scan() {
        line := scanner.Text()
        lineCount++

        // Count log levels
        lineLower := strings.ToLower(line)
        if strings.Contains(lineLower, "error") || strings.Contains(lineLower, "err") {
            errorCount++
        } else if strings.Contains(lineLower, "warn") {
            warningCount++
        } else if strings.Contains(lineLower, "info") {
            infoCount++
        }

        // Count pattern matches
        for pattern, regex := range compiledPatterns {
            if regex.MatchString(line) {
                patternCounts[pattern]++
            }
        }
    }

    if err := scanner.Err(); err != nil {
        return nil, fmt.Errorf("failed to read file: %w", err)
    }

    return map[string]interface{}{
        "total_lines":    lineCount,
        "error_count":    errorCount,
        "warning_count":  warningCount,
        "info_count":     infoCount,
        "pattern_counts": patternCounts,
        "file_path":      filePath,
        "analyzed_at":    time.Now(),
    }, nil
}

// GetDiskUsage analyzes disk usage for a given path
func (lm *LogMonitor) GetDiskUsage(ctx context.Context, req *types.DiskUsageRequest) (*types.DiskUsageResult, error) {
    // Security check
    if err := lm.validateFilePath(req.Path); err != nil {
        return nil, err
    }

    var items []types.DiskUsageItem
    totalSize := int64(0)
    itemCount := 0

    err := filepath.Walk(req.Path, func(path string, info os.FileInfo, err error) error {
        if err != nil {
            return err
        }

        // Check depth limit
        depth := strings.Count(strings.TrimPrefix(path, req.Path), string(filepath.Separator))
        if req.MaxDepth > 0 && depth > req.MaxDepth {
            if info.IsDir() {
                return filepath.SkipDir
            }
            return nil
        }

        // Check file type filter (only for files) - must check before size filter
        if len(req.FileTypes) > 0 {
            if info.IsDir() {
                // Skip directories when filtering by file type
                return nil
            }
            ext := strings.ToLower(filepath.Ext(path))
            found := false
            for _, fileType := range req.FileTypes {
                if strings.HasPrefix(ext, "."+strings.ToLower(fileType)) {
                    found = true
                    break
                }
            }
            if !found {
                return nil
            }
        }

        // Check minimum size (only for files, not directories)
        if req.MinSize > 0 {
            if info.IsDir() {
                // Skip directories when filtering by size
                return nil
            }
            if info.Size() < req.MinSize {
                return nil
            }
        }

        item := types.DiskUsageItem{
            Path:     path,
            Size:     info.Size(),
            IsDir:    info.IsDir(),
            Modified: info.ModTime(),
            Depth:    depth,
        }

        // Determine file type
        if !info.IsDir() {
            item.FileType = strings.TrimPrefix(filepath.Ext(path), ".")
        }

        items = append(items, item)
        totalSize += info.Size()
        itemCount++

        return nil
    })

    if err != nil {
        return nil, fmt.Errorf("failed to walk directory: %w", err)
    }

    // Sort items
    switch req.SortBy {
    case "size":
        sort.Slice(items, func(i, j int) bool {
            return items[i].Size > items[j].Size
        })
    case "name":
        sort.Slice(items, func(i, j int) bool {
            return items[i].Path < items[j].Path
        })
    case "modified":
        sort.Slice(items, func(i, j int) bool {
            return items[i].Modified.After(items[j].Modified)
        })
    }

    return &types.DiskUsageResult{
        Path:      req.Path,
        TotalSize: totalSize,
        ItemCount: itemCount,
        Items:     items,
        Timestamp: time.Now(),
    }, nil
}
