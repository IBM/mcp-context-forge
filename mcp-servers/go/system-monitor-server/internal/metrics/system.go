package metrics

import (
    "context"
    "fmt"
    "time"

    "github.com/IBM/mcp-context-forge/mcp-servers/go/system-monitor-server/pkg/types"
    "github.com/shirou/gopsutil/v3/cpu"
    "github.com/shirou/gopsutil/v3/disk"
    "github.com/shirou/gopsutil/v3/load"
    "github.com/shirou/gopsutil/v3/mem"
    "github.com/shirou/gopsutil/v3/net"
)

// SystemCollector handles system metrics collection
type SystemCollector struct {
    lastCPUTimes []cpu.TimesStat
}

// NewSystemCollector creates a new system metrics collector
func NewSystemCollector() *SystemCollector {
    return &SystemCollector{}
}

// GetSystemMetrics collects comprehensive system metrics
func (sc *SystemCollector) GetSystemMetrics(ctx context.Context) (*types.SystemMetrics, error) {
    metrics := &types.SystemMetrics{
        Timestamp: time.Now(),
    }

    // Collect CPU metrics
    if err := sc.collectCPUMetrics(ctx, metrics); err != nil {
        return nil, fmt.Errorf("failed to collect CPU metrics: %w", err)
    }

    // Collect memory metrics
    if err := sc.collectMemoryMetrics(ctx, metrics); err != nil {
        return nil, fmt.Errorf("failed to collect memory metrics: %w", err)
    }

    // Collect disk metrics
    if err := sc.collectDiskMetrics(ctx, metrics); err != nil {
        return nil, fmt.Errorf("failed to collect disk metrics: %w", err)
    }

    // Collect network metrics
    if err := sc.collectNetworkMetrics(ctx, metrics); err != nil {
        return nil, fmt.Errorf("failed to collect network metrics: %w", err)
    }

    return metrics, nil
}

// collectCPUMetrics collects CPU usage and load average information
func (sc *SystemCollector) collectCPUMetrics(ctx context.Context, metrics *types.SystemMetrics) error {
    // Get CPU usage percentage
    cpuPercent, err := cpu.PercentWithContext(ctx, time.Second, false)
    if err != nil {
        return fmt.Errorf("failed to get CPU percent: %w", err)
    }

    // Get load average
    loadAvg, err := load.AvgWithContext(ctx)
    if err != nil {
        return fmt.Errorf("failed to get load average: %w", err)
    }

    // Get number of CPU cores
    cpuCount, err := cpu.Counts(true)
    if err != nil {
        return fmt.Errorf("failed to get CPU count: %w", err)
    }

    // Get CPU times for more detailed analysis
    cpuTimes, err := cpu.TimesWithContext(ctx, false)
    if err != nil {
        return fmt.Errorf("failed to get CPU times: %w", err)
    }

    // Calculate CPU usage from times if we have previous data
    var cpuUsage float64
    if len(sc.lastCPUTimes) > 0 && len(cpuTimes) > 0 {
        cpuUsage = calculateCPUUsage(sc.lastCPUTimes[0], cpuTimes[0])
    } else if len(cpuPercent) > 0 {
        cpuUsage = cpuPercent[0]
    }

    metrics.CPU = types.CPUMetrics{
        UsagePercent: cpuUsage,
        LoadAvg1:     loadAvg.Load1,
        LoadAvg5:     loadAvg.Load5,
        LoadAvg15:    loadAvg.Load15,
        NumCores:     cpuCount,
    }

    // Store current CPU times for next calculation
    sc.lastCPUTimes = cpuTimes

    return nil
}

// collectMemoryMetrics collects memory usage information
func (sc *SystemCollector) collectMemoryMetrics(ctx context.Context, metrics *types.SystemMetrics) error {
    memInfo, err := mem.VirtualMemoryWithContext(ctx)
    if err != nil {
        return fmt.Errorf("failed to get memory info: %w", err)
    }

    swapInfo, err := mem.SwapMemoryWithContext(ctx)
    if err != nil {
        return fmt.Errorf("failed to get swap info: %w", err)
    }

    metrics.Memory = types.MemoryMetrics{
        Total:        memInfo.Total,
        Available:    memInfo.Available,
        Used:         memInfo.Used,
        Free:         memInfo.Free,
        UsagePercent: memInfo.UsedPercent,
        SwapTotal:    swapInfo.Total,
        SwapUsed:     swapInfo.Used,
        SwapFree:     swapInfo.Free,
    }

    return nil
}

// collectDiskMetrics collects disk usage information for all mounted filesystems
func (sc *SystemCollector) collectDiskMetrics(ctx context.Context, metrics *types.SystemMetrics) error {
    partitions, err := disk.PartitionsWithContext(ctx, false)
    if err != nil {
        return fmt.Errorf("failed to get disk partitions: %w", err)
    }

    var diskMetrics []types.DiskMetrics

    for _, partition := range partitions {
        // Skip certain filesystem types that might cause issues
        if partition.Fstype == "squashfs" || partition.Fstype == "tmpfs" {
            continue
        }

        usage, err := disk.UsageWithContext(ctx, partition.Mountpoint)
        if err != nil {
            // Skip partitions we can't access
            continue
        }

        diskMetrics = append(diskMetrics, types.DiskMetrics{
            Device:       partition.Device,
            Mountpoint:   partition.Mountpoint,
            Fstype:       partition.Fstype,
            Total:        usage.Total,
            Free:         usage.Free,
            Used:         usage.Used,
            UsagePercent: usage.UsedPercent,
        })
    }

    metrics.Disk = diskMetrics
    return nil
}

// collectNetworkMetrics collects network interface information
func (sc *SystemCollector) collectNetworkMetrics(ctx context.Context, metrics *types.SystemMetrics) error {
    netStats, err := net.IOCountersWithContext(ctx, true)
    if err != nil {
        return fmt.Errorf("failed to get network stats: %w", err)
    }

    var interfaces []types.NetworkInterface

    for _, stat := range netStats {
        // Get interface status
        netInterfaces, err := net.InterfacesWithContext(ctx)
        if err != nil {
            // If we can't get interface status, assume it's up
            interfaces = append(interfaces, types.NetworkInterface{
                Name:        stat.Name,
                BytesSent:   stat.BytesSent,
                BytesRecv:   stat.BytesRecv,
                PacketsSent: stat.PacketsSent,
                PacketsRecv: stat.PacketsRecv,
                ErrIn:       stat.Errin,
                ErrOut:      stat.Errout,
                DropIn:      stat.Dropin,
                DropOut:     stat.Dropout,
                IsUp:        true,
            })
            continue
        }

        // Find the interface status
        isUp := false
        for _, netInterface := range netInterfaces {
            if netInterface.Name == stat.Name {
                isUp = len(netInterface.Flags) > 0 && contains(netInterface.Flags, "up")
                break
            }
        }

        interfaces = append(interfaces, types.NetworkInterface{
            Name:        stat.Name,
            BytesSent:   stat.BytesSent,
            BytesRecv:   stat.BytesRecv,
            PacketsSent: stat.PacketsSent,
            PacketsRecv: stat.PacketsRecv,
            ErrIn:       stat.Errin,
            ErrOut:      stat.Errout,
            DropIn:      stat.Dropin,
            DropOut:     stat.Dropout,
            IsUp:        isUp,
        })
    }

    metrics.Network = types.NetworkMetrics{
        Interfaces: interfaces,
    }

    return nil
}

// calculateCPUUsage calculates CPU usage percentage from CPU times
func calculateCPUUsage(t1, t2 cpu.TimesStat) float64 {
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

// contains checks if a slice contains a specific string
func contains(slice []string, item string) bool {
    for _, s := range slice {
        if s == item {
            return true
        }
    }
    return false
}
