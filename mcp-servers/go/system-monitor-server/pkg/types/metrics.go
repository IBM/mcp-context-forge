package types

import (
    "time"
)

// SystemMetrics represents comprehensive system resource usage
type SystemMetrics struct {
    CPU       CPUMetrics     `json:"cpu"`
    Memory    MemoryMetrics  `json:"memory"`
    Disk      []DiskMetrics  `json:"disk"`
    Network   NetworkMetrics `json:"network"`
    Timestamp time.Time      `json:"timestamp"`
}

// CPUMetrics represents CPU usage information
type CPUMetrics struct {
    UsagePercent float64 `json:"usage_percent"`
    LoadAvg1     float64 `json:"load_avg_1"`
    LoadAvg5     float64 `json:"load_avg_5"`
    LoadAvg15    float64 `json:"load_avg_15"`
    NumCores     int     `json:"num_cores"`
}

// MemoryMetrics represents memory usage information
type MemoryMetrics struct {
    Total        uint64  `json:"total"`
    Available    uint64  `json:"available"`
    Used         uint64  `json:"used"`
    Free         uint64  `json:"free"`
    UsagePercent float64 `json:"usage_percent"`
    SwapTotal    uint64  `json:"swap_total"`
    SwapUsed     uint64  `json:"swap_used"`
    SwapFree     uint64  `json:"swap_free"`
}

// DiskMetrics represents disk usage information for a single disk
type DiskMetrics struct {
    Device       string  `json:"device"`
    Mountpoint   string  `json:"mountpoint"`
    Fstype       string  `json:"fstype"`
    Total        uint64  `json:"total"`
    Free         uint64  `json:"free"`
    Used         uint64  `json:"used"`
    UsagePercent float64 `json:"usage_percent"`
}

// NetworkMetrics represents network interface information
type NetworkMetrics struct {
    Interfaces []NetworkInterface `json:"interfaces"`
}

// NetworkInterface represents a single network interface
type NetworkInterface struct {
    Name        string `json:"name"`
    BytesSent   uint64 `json:"bytes_sent"`
    BytesRecv   uint64 `json:"bytes_recv"`
    PacketsSent uint64 `json:"packets_sent"`
    PacketsRecv uint64 `json:"packets_recv"`
    ErrIn       uint64 `json:"err_in"`
    ErrOut      uint64 `json:"err_out"`
    DropIn      uint64 `json:"drop_in"`
    DropOut     uint64 `json:"drop_out"`
    IsUp        bool   `json:"is_up"`
}

// ProcessListRequest represents parameters for listing processes
type ProcessListRequest struct {
    FilterBy       string `json:"filter_by,omitempty"` // name, user, pid
    FilterValue    string `json:"filter_value,omitempty"`
    SortBy         string `json:"sort_by,omitempty"` // cpu, memory, name
    Limit          int    `json:"limit,omitempty"`
    IncludeThreads bool   `json:"include_threads,omitempty"`
}

// ProcessInfo represents information about a single process
type ProcessInfo struct {
    PID           int32   `json:"pid"`
    Name          string  `json:"name"`
    CPUPercent    float64 `json:"cpu_percent"`
    MemoryPercent float32 `json:"memory_percent"`
    MemoryRSS     uint64  `json:"memory_rss"`
    MemoryVMS     uint64  `json:"memory_vms"`
    Status        string  `json:"status"`
    CreateTime    int64   `json:"create_time"`
    Username      string  `json:"username"`
    Command       string  `json:"command"`
    Threads       int32   `json:"threads,omitempty"`
}

// ProcessMonitorRequest represents parameters for monitoring a specific process
type ProcessMonitorRequest struct {
    PID             int32      `json:"pid,omitempty"`
    ProcessName     string     `json:"process_name,omitempty"`
    Duration        int        `json:"duration"` // seconds
    Interval        int        `json:"interval"` // seconds
    AlertThresholds Thresholds `json:"alert_thresholds,omitempty"`
}

// Thresholds represents alert thresholds for monitoring
type Thresholds struct {
    CPUPercent    float64 `json:"cpu_percent,omitempty"`
    MemoryPercent float64 `json:"memory_percent,omitempty"`
    MemoryRSS     uint64  `json:"memory_rss,omitempty"`
}

// ProcessMonitorResult represents the result of process monitoring
type ProcessMonitorResult struct {
    ProcessInfo ProcessInfo `json:"process_info"`
    Alerts      []Alert     `json:"alerts,omitempty"`
    Timestamp   time.Time   `json:"timestamp"`
}

// Alert represents a monitoring alert
type Alert struct {
    Type      string    `json:"type"` // cpu, memory, etc.
    Message   string    `json:"message"`
    Threshold float64   `json:"threshold"`
    Value     float64   `json:"value"`
    Timestamp time.Time `json:"timestamp"`
}

// HealthCheckRequest represents parameters for health checking
type HealthCheckRequest struct {
    Services []ServiceCheck `json:"services"`
    Timeout  int            `json:"timeout,omitempty"` // seconds
}

// ServiceCheck represents a single service to check
type ServiceCheck struct {
    Name     string            `json:"name"`
    Type     string            `json:"type"` // port, http, file (command disabled for security)
    Target   string            `json:"target"`
    Expected map[string]string `json:"expected,omitempty"`
}

// HealthCheckResult represents the result of a health check
type HealthCheckResult struct {
    ServiceName  string    `json:"service_name"`
    Status       string    `json:"status"` // healthy, unhealthy, unknown
    Message      string    `json:"message"`
    ResponseTime int64     `json:"response_time_ms"`
    Timestamp    time.Time `json:"timestamp"`
}

// LogTailRequest represents parameters for tailing log files
type LogTailRequest struct {
    FilePath string `json:"file_path"`
    Lines    int    `json:"lines,omitempty"`    // number of lines to tail
    Follow   bool   `json:"follow,omitempty"`   // continuous monitoring
    Filter   string `json:"filter,omitempty"`   // regex filter
    MaxSize  int64  `json:"max_size,omitempty"` // max file size to process
}

// LogTailResult represents the result of log tailing
type LogTailResult struct {
    Lines      []string  `json:"lines"`
    FilePath   string    `json:"file_path"`
    TotalLines int       `json:"total_lines"`
    Timestamp  time.Time `json:"timestamp"`
}

// DiskUsageRequest represents parameters for disk usage analysis
type DiskUsageRequest struct {
    Path      string   `json:"path"`
    MaxDepth  int      `json:"max_depth,omitempty"`
    MinSize   int64    `json:"min_size,omitempty"`
    SortBy    string   `json:"sort_by,omitempty"` // size, name, modified
    FileTypes []string `json:"file_types,omitempty"`
}

// DiskUsageItem represents a single file or directory in disk usage analysis
type DiskUsageItem struct {
    Path     string    `json:"path"`
    Size     int64     `json:"size"`
    IsDir    bool      `json:"is_dir"`
    Modified time.Time `json:"modified"`
    FileType string    `json:"file_type,omitempty"`
    Depth    int       `json:"depth"`
}

// DiskUsageResult represents the result of disk usage analysis
type DiskUsageResult struct {
    Path      string          `json:"path"`
    TotalSize int64           `json:"total_size"`
    ItemCount int             `json:"item_count"`
    Items     []DiskUsageItem `json:"items"`
    Timestamp time.Time       `json:"timestamp"`
}
