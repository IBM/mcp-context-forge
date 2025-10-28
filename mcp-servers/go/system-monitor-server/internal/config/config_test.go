package config

import (
    "testing"
    "time"
)

func TestDefaultConfig(t *testing.T) {
    config := DefaultConfig()

    // Test Monitoring config
    if config.Monitoring.UpdateInterval != 5*time.Second {
        t.Errorf("Expected UpdateInterval 5s, got %v", config.Monitoring.UpdateInterval)
    }
    if config.Monitoring.HistoryRetention != 24*time.Hour {
        t.Errorf("Expected HistoryRetention 24h, got %v", config.Monitoring.HistoryRetention)
    }
    if config.Monitoring.MaxProcesses != 1000 {
        t.Errorf("Expected MaxProcesses 1000, got %d", config.Monitoring.MaxProcesses)
    }
    if config.Monitoring.ProcessUpdateFreq != 1*time.Second {
        t.Errorf("Expected ProcessUpdateFreq 1s, got %v", config.Monitoring.ProcessUpdateFreq)
    }

    // Test Alerts config
    if config.Alerts.CPUThreshold != 80.0 {
        t.Errorf("Expected CPUThreshold 80.0, got %f", config.Alerts.CPUThreshold)
    }
    if config.Alerts.MemoryThreshold != 85.0 {
        t.Errorf("Expected MemoryThreshold 85.0, got %f", config.Alerts.MemoryThreshold)
    }
    if config.Alerts.DiskThreshold != 90.0 {
        t.Errorf("Expected DiskThreshold 90.0, got %f", config.Alerts.DiskThreshold)
    }
    if !config.Alerts.Enabled {
        t.Error("Expected Alerts.Enabled to be true")
    }

    // Test HealthChecks config
    if len(config.HealthChecks) != 2 {
        t.Errorf("Expected 2 health checks, got %d", len(config.HealthChecks))
    }

    webServerCheck := config.HealthChecks[0]
    if webServerCheck.Name != "web_server" {
        t.Errorf("Expected web_server name, got %s", webServerCheck.Name)
    }
    if webServerCheck.Type != "http" {
        t.Errorf("Expected http type, got %s", webServerCheck.Type)
    }
    if webServerCheck.Target != "http://localhost:8080/health" {
        t.Errorf("Expected web server target, got %s", webServerCheck.Target)
    }

    databaseCheck := config.HealthChecks[1]
    if databaseCheck.Name != "database" {
        t.Errorf("Expected database name, got %s", databaseCheck.Name)
    }
    if databaseCheck.Type != "port" {
        t.Errorf("Expected port type, got %s", databaseCheck.Type)
    }
    if databaseCheck.Target != "localhost:5432" {
        t.Errorf("Expected database target, got %s", databaseCheck.Target)
    }

    // Test LogMonitoring config
    if config.LogMonitoring.MaxFileSize != "100MB" {
        t.Errorf("Expected MaxFileSize 100MB, got %s", config.LogMonitoring.MaxFileSize)
    }
    if config.LogMonitoring.MaxTailLines != 1000 {
        t.Errorf("Expected MaxTailLines 1000, got %d", config.LogMonitoring.MaxTailLines)
    }
    // SECURITY: Only /var/log should be allowed by default (removed /tmp and ./logs)
    if len(config.LogMonitoring.AllowedPaths) != 1 {
        t.Errorf("Expected 1 allowed path, got %d", len(config.LogMonitoring.AllowedPaths))
    }
    if config.LogMonitoring.AllowedPaths[0] != "/var/log" {
        t.Errorf("Expected allowed path /var/log, got %s", config.LogMonitoring.AllowedPaths[0])
    }
    if config.LogMonitoring.FollowTimeout != 30*time.Second {
        t.Errorf("Expected FollowTimeout 30s, got %v", config.LogMonitoring.FollowTimeout)
    }

    // Test Security config
    // SECURITY: Only /var/log should be allowed by default (removed /tmp and ./logs)
    if len(config.Security.AllowedPaths) != 1 {
        t.Errorf("Expected 1 security allowed path, got %d", len(config.Security.AllowedPaths))
    }
    if config.Security.AllowedPaths[0] != "/var/log" {
        t.Errorf("Expected security allowed path /var/log, got %s", config.Security.AllowedPaths[0])
    }
    if config.Security.MaxFileSize != 100*1024*1024 {
        t.Errorf("Expected MaxFileSize 100MB, got %d", config.Security.MaxFileSize)
    }
    if config.Security.RateLimitRPS != 10 {
        t.Errorf("Expected RateLimitRPS 10, got %d", config.Security.RateLimitRPS)
    }
    if !config.Security.EnableAuditLog {
        t.Error("Expected EnableAuditLog to be true")
    }
}

func TestConfigStructs(t *testing.T) {
    // Test that all struct fields are properly defined
    config := DefaultConfig()

    // Test MonitoringConfig
    if config.Monitoring.UpdateInterval == 0 {
        t.Error("UpdateInterval should not be zero")
    }
    if config.Monitoring.HistoryRetention == 0 {
        t.Error("HistoryRetention should not be zero")
    }
    if config.Monitoring.MaxProcesses == 0 {
        t.Error("MaxProcesses should not be zero")
    }
    if config.Monitoring.ProcessUpdateFreq == 0 {
        t.Error("ProcessUpdateFreq should not be zero")
    }

    // Test AlertsConfig
    if config.Alerts.CPUThreshold <= 0 {
        t.Error("CPUThreshold should be positive")
    }
    if config.Alerts.MemoryThreshold <= 0 {
        t.Error("MemoryThreshold should be positive")
    }
    if config.Alerts.DiskThreshold <= 0 {
        t.Error("DiskThreshold should be positive")
    }

    // Test HealthCheckConfig
    for i, check := range config.HealthChecks {
        if check.Name == "" {
            t.Errorf("HealthCheck %d should have a name", i)
        }
        if check.Type == "" {
            t.Errorf("HealthCheck %d should have a type", i)
        }
        if check.Target == "" {
            t.Errorf("HealthCheck %d should have a target", i)
        }
        if check.Interval == 0 {
            t.Errorf("HealthCheck %d should have an interval", i)
        }
        if check.Timeout == 0 {
            t.Errorf("HealthCheck %d should have a timeout", i)
        }
    }

    // Test LogMonitoringConfig
    if config.LogMonitoring.MaxFileSize == "" {
        t.Error("MaxFileSize should not be empty")
    }
    if config.LogMonitoring.MaxTailLines <= 0 {
        t.Error("MaxTailLines should be positive")
    }
    if len(config.LogMonitoring.AllowedPaths) == 0 {
        t.Error("AllowedPaths should not be empty")
    }
    if config.LogMonitoring.FollowTimeout == 0 {
        t.Error("FollowTimeout should not be zero")
    }

    // Test SecurityConfig
    if len(config.Security.AllowedPaths) == 0 {
        t.Error("Security AllowedPaths should not be empty")
    }
    if config.Security.MaxFileSize <= 0 {
        t.Error("MaxFileSize should be positive")
    }
    if config.Security.RateLimitRPS <= 0 {
        t.Error("RateLimitRPS should be positive")
    }
}

func TestConfigImmutable(t *testing.T) {
    // Test that DefaultConfig returns a new instance each time
    config1 := DefaultConfig()
    config2 := DefaultConfig()

    if config1 == config2 {
        t.Error("DefaultConfig should return different instances")
    }

    // Modify one config and ensure the other is not affected
    config1.Monitoring.MaxProcesses = 9999
    if config2.Monitoring.MaxProcesses == 9999 {
        t.Error("Modifying one config should not affect another")
    }
}

func TestConfigFieldTypes(t *testing.T) {
    config := DefaultConfig()

    // Test that numeric fields have correct types
    if config.Monitoring.MaxProcesses < 0 {
        t.Error("MaxProcesses should be non-negative")
    }
    if config.Alerts.CPUThreshold < 0 || config.Alerts.CPUThreshold > 100 {
        t.Error("CPUThreshold should be between 0 and 100")
    }
    if config.Alerts.MemoryThreshold < 0 || config.Alerts.MemoryThreshold > 100 {
        t.Error("MemoryThreshold should be between 0 and 100")
    }
    if config.Alerts.DiskThreshold < 0 || config.Alerts.DiskThreshold > 100 {
        t.Error("DiskThreshold should be between 0 and 100")
    }
    if config.LogMonitoring.MaxTailLines < 0 {
        t.Error("MaxTailLines should be non-negative")
    }
    if config.Security.MaxFileSize < 0 {
        t.Error("MaxFileSize should be non-negative")
    }
    if config.Security.RateLimitRPS < 0 {
        t.Error("RateLimitRPS should be non-negative")
    }

    // Test that duration fields are positive
    if config.Monitoring.UpdateInterval <= 0 {
        t.Error("UpdateInterval should be positive")
    }
    if config.Monitoring.HistoryRetention <= 0 {
        t.Error("HistoryRetention should be positive")
    }
    if config.Monitoring.ProcessUpdateFreq <= 0 {
        t.Error("ProcessUpdateFreq should be positive")
    }
    if config.LogMonitoring.FollowTimeout <= 0 {
        t.Error("FollowTimeout should be positive")
    }

    // Test health check durations
    for i, check := range config.HealthChecks {
        if check.Interval <= 0 {
            t.Errorf("HealthCheck %d interval should be positive", i)
        }
        if check.Timeout <= 0 {
            t.Errorf("HealthCheck %d timeout should be positive", i)
        }
    }
}
