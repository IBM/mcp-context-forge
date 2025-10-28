package metrics

import (
    "context"
    "testing"
    "time"

    "github.com/IBM/mcp-context-forge/mcp-servers/go/system-monitor-server/pkg/types"
    "github.com/shirou/gopsutil/v3/cpu"
)

func TestSystemCollector_GetSystemMetrics(t *testing.T) {
    collector := NewSystemCollector()
    ctx := context.Background()

    metrics, err := collector.GetSystemMetrics(ctx)
    if err != nil {
        t.Fatalf("Failed to get system metrics: %v", err)
    }

    // Check that metrics are populated
    if metrics.Timestamp.IsZero() {
        t.Error("Timestamp should not be zero")
    }

    // Check CPU metrics
    if metrics.CPU.NumCores <= 0 {
        t.Error("CPU cores should be greater than 0")
    }

    // Check memory metrics
    if metrics.Memory.Total == 0 {
        t.Error("Total memory should be greater than 0")
    }

    // Check that we have at least one disk
    if len(metrics.Disk) == 0 {
        t.Error("Should have at least one disk")
    }

    // Check that we have at least one network interface
    if len(metrics.Network.Interfaces) == 0 {
        t.Error("Should have at least one network interface")
    }
}

func TestSystemCollector_CPUMetrics(t *testing.T) {
    collector := NewSystemCollector()
    ctx := context.Background()

    // Test multiple calls to ensure CPU calculation works
    _, err := collector.GetSystemMetrics(ctx)
    if err != nil {
        t.Fatalf("First call failed: %v", err)
    }

    // Wait a bit for CPU usage to change
    time.Sleep(100 * time.Millisecond)

    metrics, err := collector.GetSystemMetrics(ctx)
    if err != nil {
        t.Fatalf("Second call failed: %v", err)
    }

    // CPU usage should be a valid percentage
    if metrics.CPU.UsagePercent < 0 || metrics.CPU.UsagePercent > 100 {
        t.Errorf("CPU usage should be between 0 and 100, got %f", metrics.CPU.UsagePercent)
    }
}

func TestCalculateCPUUsage(t *testing.T) {
    // Test with identical times (should return 0)
    t1 := cpu.TimesStat{
        User: 100, System: 50, Nice: 10, Iowait: 20,
        Irq: 5, Softirq: 10, Steal: 0, Guest: 0, GuestNice: 0, Idle: 1000,
    }
    t2 := t1

    usage := calculateCPUUsage(t1, t2)
    if usage != 0.0 {
        t.Errorf("Expected 0.0 for identical times, got %f", usage)
    }

    // Test with different times
    t2.Idle = 900 // 100 less idle time
    t2.User = 150 // More user time
    usage = calculateCPUUsage(t1, t2)
    if usage < 0 || usage > 100 {
        t.Errorf("Expected usage between 0 and 100, got %f", usage)
    }
}

func TestContains(t *testing.T) {
    slice := []string{"up", "running", "active"}

    if !contains(slice, "up") {
        t.Error("Should contain 'up'")
    }

    if contains(slice, "down") {
        t.Error("Should not contain 'down'")
    }

    if contains(slice, "UP") {
        t.Error("Should be case sensitive")
    }
}

func TestSystemCollector_CollectCPUMetrics(t *testing.T) {
    collector := NewSystemCollector()
    ctx := context.Background()

    metrics := &types.SystemMetrics{}
    err := collector.collectCPUMetrics(ctx, metrics)
    if err != nil {
        t.Fatalf("Failed to collect CPU metrics: %v", err)
    }

    // Check that CPU metrics are populated
    if metrics.CPU.NumCores <= 0 {
        t.Error("CPU cores should be greater than 0")
    }

    // CPU usage should be a valid percentage
    if metrics.CPU.UsagePercent < 0 || metrics.CPU.UsagePercent > 100 {
        t.Errorf("CPU usage should be between 0 and 100, got %f", metrics.CPU.UsagePercent)
    }

    // Load averages should be non-negative
    if metrics.CPU.LoadAvg1 < 0 {
        t.Error("LoadAvg1 should be non-negative")
    }
    if metrics.CPU.LoadAvg5 < 0 {
        t.Error("LoadAvg5 should be non-negative")
    }
    if metrics.CPU.LoadAvg15 < 0 {
        t.Error("LoadAvg15 should be non-negative")
    }
}

func TestSystemCollector_CollectMemoryMetrics(t *testing.T) {
    collector := NewSystemCollector()
    ctx := context.Background()

    metrics := &types.SystemMetrics{}
    err := collector.collectMemoryMetrics(ctx, metrics)
    if err != nil {
        t.Fatalf("Failed to collect memory metrics: %v", err)
    }

    // Check that memory metrics are populated
    if metrics.Memory.Total == 0 {
        t.Error("Total memory should be greater than 0")
    }

    if metrics.Memory.Available == 0 {
        t.Error("Available memory should be greater than 0")
    }

    if metrics.Memory.Used == 0 {
        t.Error("Used memory should be greater than 0")
    }

    if metrics.Memory.Free == 0 {
        t.Error("Free memory should be greater than 0")
    }

    // Usage percentage should be valid
    if metrics.Memory.UsagePercent < 0 || metrics.Memory.UsagePercent > 100 {
        t.Errorf("Memory usage should be between 0 and 100, got %f", metrics.Memory.UsagePercent)
    }

    // Swap metrics should be non-negative
    if metrics.Memory.SwapTotal < 0 {
        t.Error("SwapTotal should be non-negative")
    }
    if metrics.Memory.SwapUsed < 0 {
        t.Error("SwapUsed should be non-negative")
    }
    if metrics.Memory.SwapFree < 0 {
        t.Error("SwapFree should be non-negative")
    }
}

func TestSystemCollector_CollectDiskMetrics(t *testing.T) {
    collector := NewSystemCollector()
    ctx := context.Background()

    metrics := &types.SystemMetrics{}
    err := collector.collectDiskMetrics(ctx, metrics)
    if err != nil {
        t.Fatalf("Failed to collect disk metrics: %v", err)
    }

    // Should have at least one disk
    if len(metrics.Disk) == 0 {
        t.Error("Should have at least one disk")
    }

    // Check each disk metric
    for i, disk := range metrics.Disk {
        if disk.Device == "" {
            t.Errorf("Disk %d should have a device name", i)
        }
        if disk.Mountpoint == "" {
            t.Errorf("Disk %d should have a mountpoint", i)
        }
        if disk.Fstype == "" {
            t.Errorf("Disk %d should have a filesystem type", i)
        }
        // Some disks might have 0 total size (e.g., special filesystems)
        if disk.Total < 0 {
            t.Errorf("Disk %d should have non-negative total size", i)
        }
        if disk.Free < 0 {
            t.Errorf("Disk %d should have non-negative free space", i)
        }
        if disk.Used < 0 {
            t.Errorf("Disk %d should have non-negative used space", i)
        }
        if disk.UsagePercent < 0 || disk.UsagePercent > 100 {
            t.Errorf("Disk %d usage should be between 0 and 100, got %f", i, disk.UsagePercent)
        }
    }
}

func TestSystemCollector_CollectNetworkMetrics(t *testing.T) {
    collector := NewSystemCollector()
    ctx := context.Background()

    metrics := &types.SystemMetrics{}
    err := collector.collectNetworkMetrics(ctx, metrics)
    if err != nil {
        t.Fatalf("Failed to collect network metrics: %v", err)
    }

    // Should have at least one network interface
    if len(metrics.Network.Interfaces) == 0 {
        t.Error("Should have at least one network interface")
    }

    // Check each network interface
    for i, iface := range metrics.Network.Interfaces {
        if iface.Name == "" {
            t.Errorf("Interface %d should have a name", i)
        }
        if iface.BytesSent < 0 {
            t.Errorf("Interface %d should have non-negative bytes sent", i)
        }
        if iface.BytesRecv < 0 {
            t.Errorf("Interface %d should have non-negative bytes received", i)
        }
        if iface.PacketsSent < 0 {
            t.Errorf("Interface %d should have non-negative packets sent", i)
        }
        if iface.PacketsRecv < 0 {
            t.Errorf("Interface %d should have non-negative packets received", i)
        }
        if iface.ErrIn < 0 {
            t.Errorf("Interface %d should have non-negative input errors", i)
        }
        if iface.ErrOut < 0 {
            t.Errorf("Interface %d should have non-negative output errors", i)
        }
        if iface.DropIn < 0 {
            t.Errorf("Interface %d should have non-negative input drops", i)
        }
        if iface.DropOut < 0 {
            t.Errorf("Interface %d should have non-negative output drops", i)
        }
    }
}

func TestCalculateCPUUsageEdgeCases(t *testing.T) {
    // Test with zero times
    t1 := cpu.TimesStat{}
    t2 := cpu.TimesStat{}

    usage := calculateCPUUsage(t1, t2)
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

    usage = calculateCPUUsage(t1, t2)
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

    usage = calculateCPUUsage(t1, t2)
    if usage != 0.0 {
        t.Errorf("Expected 0.0 for equal times, got %f", usage)
    }
}

func TestSystemCollector_MultipleCalls(t *testing.T) {
    collector := NewSystemCollector()
    ctx := context.Background()

    // First call
    metrics1, err := collector.GetSystemMetrics(ctx)
    if err != nil {
        t.Fatalf("First call failed: %v", err)
    }

    // Wait a bit
    time.Sleep(100 * time.Millisecond)

    // Second call
    metrics2, err := collector.GetSystemMetrics(ctx)
    if err != nil {
        t.Fatalf("Second call failed: %v", err)
    }

    // Timestamps should be different
    if metrics1.Timestamp.Equal(metrics2.Timestamp) {
        t.Error("Timestamps should be different between calls")
    }

    // CPU usage might be different
    if metrics1.CPU.UsagePercent == metrics2.CPU.UsagePercent {
        // This is possible if CPU usage is stable, so we just log it
        t.Logf("CPU usage is the same between calls: %f", metrics1.CPU.UsagePercent)
    }
}

func TestSystemCollector_ContextCancellation(t *testing.T) {
    collector := NewSystemCollector()
    ctx, cancel := context.WithCancel(context.Background())

    // Cancel the context immediately
    cancel()

    // This might fail due to context cancellation, which is expected
    metrics, err := collector.GetSystemMetrics(ctx)
    if err != nil {
        // Context cancellation is expected, so we just log it
        t.Logf("GetSystemMetrics with cancelled context failed as expected: %v", err)
        return
    }

    if metrics == nil {
        t.Fatal("Expected non-nil metrics")
    }
}
