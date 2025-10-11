package metrics

import (
    "context"
    "os"
    "strings"
    "testing"

    "github.com/IBM/mcp-context-forge/mcp-servers/go/system-monitor-server/pkg/types"
    "github.com/shirou/gopsutil/v3/cpu"
    "github.com/shirou/gopsutil/v3/process"
)

func TestProcessCollector_ListProcesses(t *testing.T) {
    collector := NewProcessCollector()
    ctx := context.Background()

    // Test basic process listing
    req := &types.ProcessListRequest{
        SortBy: "cpu",
        Limit:  10,
    }

    processes, err := collector.ListProcesses(ctx, req)
    if err != nil {
        t.Fatalf("Failed to list processes: %v", err)
    }

    // Should have at least one process (the test process itself)
    if len(processes) == 0 {
        t.Error("Should have at least one process")
    }

    // Test filtering by name
    req = &types.ProcessListRequest{
        FilterBy:    "name",
        FilterValue: "go",
        Limit:       5,
    }

    processes, err = collector.ListProcesses(ctx, req)
    if err != nil {
        t.Fatalf("Failed to list filtered processes: %v", err)
    }

    // All returned processes should contain "go" in their name (case insensitive)
    for _, proc := range processes {
        name := strings.ToLower(proc.Name)
        if !strings.Contains(name, "go") {
            t.Errorf("Process %s should contain 'go' in name", proc.Name)
        }
    }
}

func TestProcessCollector_MatchesFilter(t *testing.T) {
    collector := NewProcessCollector()

    info := &types.ProcessInfo{
        PID:      1234,
        Name:     "test-process",
        Username: "testuser",
    }

    // Test name filter
    if !collector.matchesFilter(info, "name", "test") {
        t.Error("Should match name filter")
    }

    if collector.matchesFilter(info, "name", "other") {
        t.Error("Should not match different name")
    }

    // Test user filter
    if !collector.matchesFilter(info, "user", "test") {
        t.Error("Should match user filter")
    }

    if collector.matchesFilter(info, "user", "other") {
        t.Error("Should not match different user")
    }

    // Test PID filter
    if !collector.matchesFilter(info, "pid", "1234") {
        t.Error("Should match PID filter")
    }

    if collector.matchesFilter(info, "pid", "5678") {
        t.Error("Should not match different PID")
    }

    // Test empty filter (should match)
    if !collector.matchesFilter(info, "", "") {
        t.Error("Empty filter should match")
    }
}

func TestProcessCollector_SortProcesses(t *testing.T) {
    collector := NewProcessCollector()

    processes := []types.ProcessInfo{
        {Name: "z-process", CPUPercent: 10.0, MemoryPercent: 5.0, PID: 3},
        {Name: "a-process", CPUPercent: 30.0, MemoryPercent: 15.0, PID: 1},
        {Name: "m-process", CPUPercent: 20.0, MemoryPercent: 10.0, PID: 2},
    }

    // Test CPU sorting
    collector.sortProcesses(processes, "cpu")
    if processes[0].CPUPercent != 30.0 {
        t.Error("Processes should be sorted by CPU usage (descending)")
    }

    // Test memory sorting
    collector.sortProcesses(processes, "memory")
    if processes[0].MemoryPercent != 15.0 {
        t.Error("Processes should be sorted by memory usage (descending)")
    }

    // Test name sorting
    collector.sortProcesses(processes, "name")
    if processes[0].Name != "a-process" {
        t.Error("Processes should be sorted by name (ascending)")
    }

    // Test PID sorting
    collector.sortProcesses(processes, "pid")
    if processes[0].PID != 1 {
        t.Error("Processes should be sorted by PID (ascending)")
    }
}

func TestProcessCollector_CheckAlerts(t *testing.T) {
    collector := NewProcessCollector()

    info := types.ProcessInfo{
        CPUPercent:    85.0,
        MemoryPercent: 90.0,
        MemoryRSS:     1000000,
    }

    thresholds := types.Thresholds{
        CPUPercent:    80.0,
        MemoryPercent: 85.0,
        MemoryRSS:     500000,
    }

    alerts := collector.checkAlerts(info, thresholds)

    // Should have 3 alerts (CPU, memory, memory RSS)
    if len(alerts) != 3 {
        t.Errorf("Expected 3 alerts, got %d", len(alerts))
    }

    // Check alert types
    alertTypes := make(map[string]bool)
    for _, alert := range alerts {
        alertTypes[alert.Type] = true
    }

    if !alertTypes["cpu"] {
        t.Error("Should have CPU alert")
    }
    if !alertTypes["memory"] {
        t.Error("Should have memory alert")
    }
    if !alertTypes["memory_rss"] {
        t.Error("Should have memory RSS alert")
    }
}

func TestCalculateProcessCPUUsage(t *testing.T) {
    collector := NewProcessCollector()

    // Test with identical times (should return 0)
    t1 := cpu.TimesStat{
        User: 100, System: 50, Nice: 10, Iowait: 20,
        Irq: 5, Softirq: 10, Steal: 0, Guest: 0, GuestNice: 0, Idle: 1000,
    }
    t2 := t1

    usage := collector.calculateProcessCPUUsage(t1, t2)
    if usage != 0.0 {
        t.Errorf("Expected 0.0 for identical times, got %f", usage)
    }

    // Test with different times
    t2.Idle = 900 // 100 less idle time
    t2.User = 150 // More user time
    usage = collector.calculateProcessCPUUsage(t1, t2)
    if usage < 0 || usage > 100 {
        t.Errorf("Expected usage between 0 and 100, got %f", usage)
    }
}

func TestProcessCollector_GetProcessInfo(t *testing.T) {
    collector := NewProcessCollector()
    ctx := context.Background()

    // Get current process
    currentPID := int32(os.Getpid())
    p, err := process.NewProcessWithContext(ctx, currentPID)
    if err != nil {
        t.Fatalf("Failed to get current process: %v", err)
    }

    // Test without threads
    info, err := collector.getProcessInfo(ctx, p, false)
    if err != nil {
        t.Fatalf("Failed to get process info: %v", err)
    }

    if info == nil {
        t.Fatal("Expected non-nil process info")
    }

    if info.PID != currentPID {
        t.Errorf("Expected PID %d, got %d", currentPID, info.PID)
    }

    if info.Name == "" {
        t.Error("Process name should not be empty")
    }

    if info.CPUPercent < 0 || info.CPUPercent > 100 {
        t.Errorf("CPU percent should be between 0 and 100, got %f", info.CPUPercent)
    }

    if info.MemoryPercent < 0 || info.MemoryPercent > 100 {
        t.Errorf("Memory percent should be between 0 and 100, got %f", info.MemoryPercent)
    }

    if info.MemoryRSS <= 0 {
        t.Error("Memory RSS should be positive")
    }

    if info.MemoryVMS <= 0 {
        t.Error("Memory VMS should be positive")
    }

    if info.Status == "" {
        t.Error("Process status should not be empty")
    }

    if info.CreateTime <= 0 {
        t.Error("Create time should be positive")
    }

    if info.Username == "" {
        t.Error("Username should not be empty")
    }

    if info.Threads != 0 {
        t.Error("Threads should be 0 when not requested")
    }

    // Test with threads
    info, err = collector.getProcessInfo(ctx, p, true)
    if err != nil {
        t.Fatalf("Failed to get process info with threads: %v", err)
    }

    if info.Threads < 0 {
        t.Error("Thread count should be non-negative")
    }
}

func TestProcessCollector_FindProcessByName(t *testing.T) {
    collector := NewProcessCollector()
    ctx := context.Background()

    // Test finding current process by name
    currentProcess, err := process.NewProcessWithContext(ctx, int32(os.Getpid()))
    if err != nil {
        t.Fatalf("Failed to get current process: %v", err)
    }

    name, err := currentProcess.NameWithContext(ctx)
    if err != nil {
        t.Fatalf("Failed to get process name: %v", err)
    }

    foundProcess, err := collector.findProcessByName(ctx, name)
    if err != nil {
        t.Fatalf("Failed to find process by name: %v", err)
    }

    if foundProcess == nil {
        t.Fatal("Expected non-nil process")
    }

    foundName, err := foundProcess.NameWithContext(ctx)
    if err != nil {
        t.Fatalf("Failed to get found process name: %v", err)
    }

    if !strings.EqualFold(foundName, name) {
        t.Errorf("Expected process name %s, got %s", name, foundName)
    }

    // Test finding non-existent process
    _, err = collector.findProcessByName(ctx, "nonexistent-process-12345")
    if err == nil {
        t.Error("Expected error for non-existent process")
    }
}

func TestProcessCollector_MatchesFilterEdgeCases(t *testing.T) {
    collector := NewProcessCollector()

    info := &types.ProcessInfo{
        PID:      1234,
        Name:     "test-process",
        Username: "testuser",
    }

    // Test empty filter (should match)
    if !collector.matchesFilter(info, "", "") {
        t.Error("Empty filter should match")
    }

    // Test empty filter value (should match)
    if !collector.matchesFilter(info, "name", "") {
        t.Error("Empty filter value should match")
    }

    // Test unknown filter type (should match)
    if !collector.matchesFilter(info, "unknown", "value") {
        t.Error("Unknown filter type should match")
    }

    // Test case sensitivity
    if !collector.matchesFilter(info, "name", "TEST") {
        t.Error("Name filter should be case insensitive")
    }

    if !collector.matchesFilter(info, "user", "TEST") {
        t.Error("User filter should be case insensitive")
    }

    // Test partial matches
    if !collector.matchesFilter(info, "name", "test") {
        t.Error("Name filter should match partial strings")
    }

    if !collector.matchesFilter(info, "user", "test") {
        t.Error("User filter should match partial strings")
    }
}

func TestProcessCollector_SortProcessesEdgeCases(t *testing.T) {
    collector := NewProcessCollector()

    processes := []types.ProcessInfo{
        {Name: "z-process", CPUPercent: 10.0, MemoryPercent: 5.0, PID: 3},
        {Name: "a-process", CPUPercent: 30.0, MemoryPercent: 15.0, PID: 1},
        {Name: "m-process", CPUPercent: 20.0, MemoryPercent: 10.0, PID: 2},
    }

    // Test unknown sort criteria (should not change order)
    originalOrder := make([]types.ProcessInfo, len(processes))
    copy(originalOrder, processes)

    collector.sortProcesses(processes, "unknown")
    for i, proc := range processes {
        if proc.Name != originalOrder[i].Name {
            t.Error("Unknown sort criteria should not change order")
        }
    }

    // Test empty sort criteria (should not change order)
    copy(processes, originalOrder)
    collector.sortProcesses(processes, "")
    for i, proc := range processes {
        if proc.Name != originalOrder[i].Name {
            t.Error("Empty sort criteria should not change order")
        }
    }
}

func TestProcessCollector_CheckAlertsEdgeCases(t *testing.T) {
    collector := NewProcessCollector()

    info := types.ProcessInfo{
        CPUPercent:    50.0,
        MemoryPercent: 60.0,
        MemoryRSS:     1000000,
    }

    // Test with zero thresholds (should not alert)
    thresholds := types.Thresholds{
        CPUPercent:    0.0,
        MemoryPercent: 0.0,
        MemoryRSS:     0,
    }

    alerts := collector.checkAlerts(info, thresholds)
    if len(alerts) != 0 {
        t.Errorf("Expected 0 alerts with zero thresholds, got %d", len(alerts))
    }

    // Test with very high thresholds (should not alert)
    thresholds = types.Thresholds{
        CPUPercent:    100.0,
        MemoryPercent: 100.0,
        MemoryRSS:     10000000,
    }

    alerts = collector.checkAlerts(info, thresholds)
    if len(alerts) != 0 {
        t.Errorf("Expected 0 alerts with high thresholds, got %d", len(alerts))
    }

    // Test with exact threshold values (should not alert)
    thresholds = types.Thresholds{
        CPUPercent:    50.0,
        MemoryPercent: 60.0,
        MemoryRSS:     1000000,
    }

    alerts = collector.checkAlerts(info, thresholds)
    if len(alerts) != 0 {
        t.Errorf("Expected 0 alerts with exact thresholds, got %d", len(alerts))
    }
}

func TestProcessCollector_CalculateProcessCPUUsageEdgeCases(t *testing.T) {
    collector := NewProcessCollector()

    // Test with zero times
    t1 := cpu.TimesStat{}
    t2 := cpu.TimesStat{}

    usage := collector.calculateProcessCPUUsage(t1, t2)
    if usage != 0.0 {
        t.Errorf("Expected 0.0 for zero times, got %f", usage)
    }

    // Test with decreasing times (should return 0)
    t1 = cpu.TimesStat{
        User: 100, System: 50, Nice: 10, Iowait: 20,
        Irq: 5, Softirq: 10, Steal: 0, Guest: 0, GuestNice: 0, Idle: 1000,
    }
    t2 = cpu.TimesStat{
        User: 50, System: 25, Nice: 5, Iowait: 10,
        Irq: 2, Softirq: 5, Steal: 0, Guest: 0, GuestNice: 0, Idle: 500,
    }

    usage = collector.calculateProcessCPUUsage(t1, t2)
    if usage != 0.0 {
        t.Errorf("Expected 0.0 for decreasing times, got %f", usage)
    }

    // Test with equal total times (should return 0)
    t1 = cpu.TimesStat{
        User: 100, System: 50, Nice: 10, Iowait: 20,
        Irq: 5, Softirq: 10, Steal: 0, Guest: 0, GuestNice: 0, Idle: 1000,
    }
    t2 = cpu.TimesStat{
        User: 100, System: 50, Nice: 10, Iowait: 20,
        Irq: 5, Softirq: 10, Steal: 0, Guest: 0, GuestNice: 0, Idle: 1000,
    }

    usage = collector.calculateProcessCPUUsage(t1, t2)
    if usage != 0.0 {
        t.Errorf("Expected 0.0 for equal times, got %f", usage)
    }
}

func TestProcessCollector_ListProcessesWithLimit(t *testing.T) {
    collector := NewProcessCollector()
    ctx := context.Background()

    // Test with limit
    req := &types.ProcessListRequest{
        SortBy: "cpu",
        Limit:  5,
    }

    processes, err := collector.ListProcesses(ctx, req)
    if err != nil {
        t.Fatalf("Failed to list processes with limit: %v", err)
    }

    if len(processes) > 5 {
        t.Errorf("Expected at most 5 processes, got %d", len(processes))
    }

    // Test with zero limit (should return all)
    req.Limit = 0
    processes, err = collector.ListProcesses(ctx, req)
    if err != nil {
        t.Fatalf("Failed to list processes with zero limit: %v", err)
    }

    if len(processes) == 0 {
        t.Error("Expected at least one process")
    }
}

func TestProcessCollector_ListProcessesWithThreads(t *testing.T) {
    collector := NewProcessCollector()
    ctx := context.Background()

    // Test without threads
    req := &types.ProcessListRequest{
        SortBy:         "cpu",
        Limit:          10,
        IncludeThreads: false,
    }

    processes, err := collector.ListProcesses(ctx, req)
    if err != nil {
        t.Fatalf("Failed to list processes without threads: %v", err)
    }

    for _, proc := range processes {
        if proc.Threads != 0 {
            t.Errorf("Expected 0 threads when not requested, got %d", proc.Threads)
        }
    }

    // Test with threads
    req.IncludeThreads = true
    processes, err = collector.ListProcesses(ctx, req)
    if err != nil {
        t.Fatalf("Failed to list processes with threads: %v", err)
    }

    for _, proc := range processes {
        if proc.Threads < 0 {
            t.Errorf("Expected non-negative thread count, got %d", proc.Threads)
        }
    }
}
