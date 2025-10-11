package config

import (
    "time"
)

// Config represents the application configuration
type Config struct {
    Monitoring    MonitoringConfig    `yaml:"monitoring"`
    Alerts        AlertsConfig        `yaml:"alerts"`
    HealthChecks  []HealthCheckConfig `yaml:"health_checks"`
    LogMonitoring LogMonitoringConfig `yaml:"log_monitoring"`
    Security      SecurityConfig      `yaml:"security"`
}

// MonitoringConfig represents monitoring configuration
type MonitoringConfig struct {
    UpdateInterval    time.Duration `yaml:"update_interval"`
    HistoryRetention  time.Duration `yaml:"history_retention"`
    MaxProcesses      int           `yaml:"max_processes"`
    ProcessUpdateFreq time.Duration `yaml:"process_update_freq"`
}

// AlertsConfig represents alert configuration
type AlertsConfig struct {
    CPUThreshold    float64 `yaml:"cpu_threshold"`
    MemoryThreshold float64 `yaml:"memory_threshold"`
    DiskThreshold   float64 `yaml:"disk_threshold"`
    Enabled         bool    `yaml:"enabled"`
}

// HealthCheckConfig represents a single health check configuration
type HealthCheckConfig struct {
    Name     string            `yaml:"name"`
    Type     string            `yaml:"type"` // port, http, file (command disabled for security)
    Target   string            `yaml:"target"`
    Interval time.Duration     `yaml:"interval"`
    Timeout  time.Duration     `yaml:"timeout"`
    Expected map[string]string `yaml:"expected,omitempty"`
}

// LogMonitoringConfig represents log monitoring configuration
type LogMonitoringConfig struct {
    MaxFileSize   string        `yaml:"max_file_size"`
    MaxTailLines  int           `yaml:"max_tail_lines"`
    AllowedPaths  []string      `yaml:"allowed_paths"`
    FollowTimeout time.Duration `yaml:"follow_timeout"`
}

// SecurityConfig represents security configuration
type SecurityConfig struct {
    RootPath       string   `yaml:"root_path"`        // Root directory - all file access restricted within this path (empty = no restriction)
    AllowedPaths   []string `yaml:"allowed_paths"`
    MaxFileSize    int64    `yaml:"max_file_size"`
    RateLimitRPS   int      `yaml:"rate_limit_rps"`
    EnableAuditLog bool     `yaml:"enable_audit_log"`
}

// DefaultConfig returns a default configuration
func DefaultConfig() *Config {
    return &Config{
        Monitoring: MonitoringConfig{
            UpdateInterval:    5 * time.Second,
            HistoryRetention:  24 * time.Hour,
            MaxProcesses:      1000,
            ProcessUpdateFreq: 1 * time.Second,
        },
        Alerts: AlertsConfig{
            CPUThreshold:    80.0,
            MemoryThreshold: 85.0,
            DiskThreshold:   90.0,
            Enabled:         true,
        },
        HealthChecks: []HealthCheckConfig{
            {
                Name:     "web_server",
                Type:     "http",
                Target:   "http://localhost:8080/health",
                Interval: 30 * time.Second,
                Timeout:  5 * time.Second,
            },
            {
                Name:     "database",
                Type:     "port",
                Target:   "localhost:5432",
                Interval: 60 * time.Second,
                Timeout:  5 * time.Second,
            },
        },
        LogMonitoring: LogMonitoringConfig{
            MaxFileSize:  "100MB",
            MaxTailLines: 1000,
            // SECURITY: Removed /tmp (too permissive), using absolute paths only
            AllowedPaths:  []string{"/var/log"},
            FollowTimeout: 30 * time.Second,
        },
        Security: SecurityConfig{
            // SECURITY: RootPath restricts all file access within this directory (chroot-like)
            // Empty string means no root restriction (not recommended for production)
            RootPath: "", // Set to a path like "/opt/monitoring-root" to enable root restriction
            // SECURITY: Removed /tmp (too permissive), using absolute paths only
            // Users should configure specific directories in config.yaml as needed
            AllowedPaths:   []string{"/var/log"},
            MaxFileSize:    100 * 1024 * 1024, // 100MB
            RateLimitRPS:   10,
            EnableAuditLog: true,
        },
    }
}
