package metrics

import (
    "context"
    "strings"
    "testing"

    "github.com/IBM/mcp-context-forge/mcp-servers/go/system-monitor-server/pkg/types"
    "github.com/shirou/gopsutil/v3/cpu"
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
