package metrics

import (
    "context"
    "fmt"
    "math"
    "sort"
    "strings"
    "time"

    "github.com/IBM/mcp-context-forge/mcp-servers/go/system-monitor-server/pkg/types"
    "github.com/shirou/gopsutil/v3/cpu"
    "github.com/shirou/gopsutil/v3/process"
)

// ProcessCollector handles process monitoring and management
type ProcessCollector struct {
    lastProcessTimes map[int32]cpu.TimesStat
}

// NewProcessCollector creates a new process collector
func NewProcessCollector() *ProcessCollector {
    return &ProcessCollector{
        lastProcessTimes: make(map[int32]cpu.TimesStat),
    }
}

// ListProcesses lists running processes with filtering and sorting options
func (pc *ProcessCollector) ListProcesses(ctx context.Context, req *types.ProcessListRequest) ([]types.ProcessInfo, error) {
    processes, err := process.ProcessesWithContext(ctx)
    if err != nil {
        return nil, fmt.Errorf("failed to get processes: %w", err)
    }

    var processInfos []types.ProcessInfo

    for _, p := range processes {
        info, err := pc.getProcessInfo(ctx, p, req.IncludeThreads)
        if err != nil {
            // Skip processes we can't access
            continue
        }

        // Apply filters
        if !pc.matchesFilter(info, req.FilterBy, req.FilterValue) {
            continue
        }

        processInfos = append(processInfos, *info)
    }

    // Apply sorting
    pc.sortProcesses(processInfos, req.SortBy)

    // Apply limit
    if req.Limit > 0 && len(processInfos) > req.Limit {
        processInfos = processInfos[:req.Limit]
    }

    return processInfos, nil
}

// MonitorProcess monitors a specific process for a given duration
func (pc *ProcessCollector) MonitorProcess(ctx context.Context, req *types.ProcessMonitorRequest) ([]types.ProcessMonitorResult, error) {
    var targetProcess *process.Process
    var err error

    // Find the target process
    if req.PID > 0 {
        targetProcess, err = process.NewProcessWithContext(ctx, req.PID)
        if err != nil {
            return nil, fmt.Errorf("failed to find process with PID %d: %w", req.PID, err)
        }
    } else if req.ProcessName != "" {
        targetProcess, err = pc.findProcessByName(ctx, req.ProcessName)
        if err != nil {
            return nil, fmt.Errorf("failed to find process with name %s: %w", req.ProcessName, err)
        }
    } else {
        return nil, fmt.Errorf("either PID or process name must be specified")
    }

    // Verify the process exists
    exists, err := targetProcess.IsRunningWithContext(ctx)
    if err != nil || !exists {
        return nil, fmt.Errorf("process not found or not running")
    }

    var results []types.ProcessMonitorResult
    duration := time.Duration(req.Duration) * time.Second
    interval := time.Duration(req.Interval) * time.Second
    startTime := time.Now()

    ticker := time.NewTicker(interval)
    defer ticker.Stop()

    for {
        select {
        case <-ctx.Done():
            return results, ctx.Err()
        case <-ticker.C:
            if time.Since(startTime) > duration {
                return results, nil
            }

            info, err := pc.getProcessInfo(ctx, targetProcess, false)
            if err != nil {
                // Process might have exited
                break
            }

            // Check for alerts
            alerts := pc.checkAlerts(*info, req.AlertThresholds)

            result := types.ProcessMonitorResult{
                ProcessInfo: *info,
                Alerts:      alerts,
                Timestamp:   time.Now(),
            }

            results = append(results, result)
        }
    }
}

// getProcessInfo extracts detailed information about a process
func (pc *ProcessCollector) getProcessInfo(ctx context.Context, p *process.Process, includeThreads bool) (*types.ProcessInfo, error) {
    // Get basic process info
    name, err := p.NameWithContext(ctx)
    if err != nil {
        return nil, err
    }

    pid := p.Pid

    // Get CPU and memory usage
    cpuPercent, err := p.CPUPercentWithContext(ctx)
    if err != nil {
        cpuPercent = 0.0
    }

    memInfo, err := p.MemoryInfoWithContext(ctx)
    if err != nil {
        return nil, err
    }

    memPercent, err := p.MemoryPercentWithContext(ctx)
    if err != nil {
        memPercent = 0.0
    }

    // Get process status
    status, err := p.StatusWithContext(ctx)
    if err != nil {
        status = []string{"unknown"}
    }

    // Get create time
    createTime, err := p.CreateTimeWithContext(ctx)
    if err != nil {
        createTime = 0
    }

    // Get username
    username, err := p.UsernameWithContext(ctx)
    if err != nil {
        username = "unknown"
    }

    // Get command line
    cmdline, err := p.CmdlineWithContext(ctx)
    if err != nil {
        cmdline = ""
    }

    // Get thread count if requested
    var threadCount int32
    if includeThreads {
        threads, err := p.ThreadsWithContext(ctx)
        if err == nil {
            threadLen := int64(len(threads))
            if threadLen > math.MaxInt32 {
                threadCount = math.MaxInt32
            } else {
                threadCount = int32(threadLen)
            }
        }
    }

    // Calculate CPU usage from times if available
    cpuTimes, err := p.TimesWithContext(ctx)
    if err == nil {
        if lastTimes, exists := pc.lastProcessTimes[pid]; exists {
            cpuPercent = pc.calculateProcessCPUUsage(lastTimes, *cpuTimes)
        }
        pc.lastProcessTimes[pid] = *cpuTimes
    }

    statusStr := "unknown"
    if len(status) > 0 {
        statusStr = status[0]
    }

    return &types.ProcessInfo{
        PID:           pid,
        Name:          name,
        CPUPercent:    cpuPercent,
        MemoryPercent: memPercent,
        MemoryRSS:     memInfo.RSS,
        MemoryVMS:     memInfo.VMS,
        Status:        statusStr,
        CreateTime:    createTime,
        Username:      username,
        Command:       cmdline,
        Threads:       threadCount,
    }, nil
}

// findProcessByName finds a process by name
func (pc *ProcessCollector) findProcessByName(ctx context.Context, name string) (*process.Process, error) {
    processes, err := process.ProcessesWithContext(ctx)
    if err != nil {
        return nil, err
    }

    for _, p := range processes {
        processName, err := p.NameWithContext(ctx)
        if err != nil {
            continue
        }

        if strings.EqualFold(processName, name) {
            return p, nil
        }
    }

    return nil, fmt.Errorf("process with name %s not found", name)
}

// matchesFilter checks if a process matches the given filter criteria
func (pc *ProcessCollector) matchesFilter(info *types.ProcessInfo, filterBy, filterValue string) bool {
    if filterBy == "" || filterValue == "" {
        return true
    }

    switch filterBy {
    case "name":
        return strings.Contains(strings.ToLower(info.Name), strings.ToLower(filterValue))
    case "user":
        return strings.Contains(strings.ToLower(info.Username), strings.ToLower(filterValue))
    case "pid":
        return fmt.Sprintf("%d", info.PID) == filterValue
    default:
        return true
    }
}

// sortProcesses sorts processes by the specified criteria
func (pc *ProcessCollector) sortProcesses(processes []types.ProcessInfo, sortBy string) {
    switch sortBy {
    case "cpu":
        sort.Slice(processes, func(i, j int) bool {
            return processes[i].CPUPercent > processes[j].CPUPercent
        })
    case "memory":
        sort.Slice(processes, func(i, j int) bool {
            return processes[i].MemoryPercent > processes[j].MemoryPercent
        })
    case "name":
        sort.Slice(processes, func(i, j int) bool {
            return processes[i].Name < processes[j].Name
        })
    case "pid":
        sort.Slice(processes, func(i, j int) bool {
            return processes[i].PID < processes[j].PID
        })
    }
}

// checkAlerts checks if process metrics exceed alert thresholds
func (pc *ProcessCollector) checkAlerts(info types.ProcessInfo, thresholds types.Thresholds) []types.Alert {
    var alerts []types.Alert

    if thresholds.CPUPercent > 0 && info.CPUPercent > thresholds.CPUPercent {
        alerts = append(alerts, types.Alert{
            Type:      "cpu",
            Message:   fmt.Sprintf("CPU usage %.2f%% exceeds threshold %.2f%%", info.CPUPercent, thresholds.CPUPercent),
            Threshold: thresholds.CPUPercent,
            Value:     info.CPUPercent,
            Timestamp: time.Now(),
        })
    }

    if thresholds.MemoryPercent > 0 && float64(info.MemoryPercent) > thresholds.MemoryPercent {
        alerts = append(alerts, types.Alert{
            Type:      "memory",
            Message:   fmt.Sprintf("Memory usage %.2f%% exceeds threshold %.2f%%", info.MemoryPercent, thresholds.MemoryPercent),
            Threshold: thresholds.MemoryPercent,
            Value:     float64(info.MemoryPercent),
            Timestamp: time.Now(),
        })
    }

    if thresholds.MemoryRSS > 0 && info.MemoryRSS > thresholds.MemoryRSS {
        alerts = append(alerts, types.Alert{
            Type:      "memory_rss",
            Message:   fmt.Sprintf("Memory RSS %d bytes exceeds threshold %d bytes", info.MemoryRSS, thresholds.MemoryRSS),
            Threshold: float64(thresholds.MemoryRSS),
            Value:     float64(info.MemoryRSS),
            Timestamp: time.Now(),
        })
    }

    return alerts
}

// calculateProcessCPUUsage calculates CPU usage percentage from process times
func (pc *ProcessCollector) calculateProcessCPUUsage(t1, t2 cpu.TimesStat) float64 {
    total1 := t1.User + t1.System + t1.Nice + t1.Iowait + t1.Irq + t1.Softirq + t1.Steal + t1.Guest + t1.GuestNice + t1.Idle
    total2 := t2.User + t2.System + t2.Nice + t2.Iowait + t2.Irq + t2.Softirq + t2.Steal + t2.Guest + t2.GuestNice + t2.Idle

    if total2 <= total1 {
        return 0.0
    }

    idle := t2.Idle - t1.Idle
    total := total2 - total1

    if total == 0 {
        return 0.0
    }

    return 100.0 * (total - idle) / total
}
