package metrics

import (
    "context"
    "testing"
    "time"

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
