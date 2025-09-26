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
    allowedPaths []string
    maxFileSize  int64
}

// NewLogMonitor creates a new log monitor
func NewLogMonitor(allowedPaths []string, maxFileSize int64) *LogMonitor {
    return &LogMonitor{
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

    // Compile filter regex if provided
    var filterRegex *regexp.Regexp
    if req.Filter != "" {
        filterRegex, err = regexp.Compile(req.Filter)
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
    file, err := os.Open(filePath)
    if err != nil {
        return nil, fmt.Errorf("failed to open file: %w", err)
    }
    defer file.Close()

    // Compile filter regex if provided
    var filterRegex *regexp.Regexp
    if filter != "" {
        filterRegex, err = regexp.Compile(filter)
        if err != nil {
            return nil, fmt.Errorf("invalid filter regex: %w", err)
        }
    }

    // Read all lines first
    var allLines []string
    scanner := bufio.NewScanner(file)
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
func (lm *LogMonitor) validateFilePath(filePath string) error {
    // Resolve the absolute path
    absPath, err := filepath.Abs(filePath)
    if err != nil {
        return fmt.Errorf("failed to resolve absolute path: %w", err)
    }

    // Check if the path is in allowed directories
    allowed := false
    for _, allowedPath := range lm.allowedPaths {
        allowedAbsPath, err := filepath.Abs(allowedPath)
        if err != nil {
            continue
        }

        if strings.HasPrefix(absPath, allowedAbsPath) {
            allowed = true
            break
        }
    }

    if !allowed {
        return fmt.Errorf("file path %s is not in allowed directories: %v", filePath, lm.allowedPaths)
    }

    return nil
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

    // Compile patterns
    compiledPatterns := make(map[string]*regexp.Regexp)
    for _, pattern := range patterns {
        regex, err := regexp.Compile(pattern)
        if err != nil {
            continue // skip invalid patterns
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

        // Check minimum size
        if req.MinSize > 0 && info.Size() < req.MinSize {
            return nil
        }

        // Check file type filter
        if len(req.FileTypes) > 0 {
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
