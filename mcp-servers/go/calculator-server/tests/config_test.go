package tests

import (
    "io/ioutil"
    "os"
    "path/filepath"
    "testing"
    "time"

    "calculator-server/internal/config"
)

func TestDefaultConfig(t *testing.T) {
    cfg := config.Default()

    // Test default values
    if cfg.Server.Transport != "stdio" {
        t.Errorf("Expected default transport to be 'stdio', got '%s'", cfg.Server.Transport)
    }

    if cfg.Server.HTTP.Port != 8080 {
        t.Errorf("Expected default HTTP port to be 8080, got %d", cfg.Server.HTTP.Port)
    }

    if cfg.Server.HTTP.Host != "127.0.0.1" {
        t.Errorf("Expected default HTTP host to be '127.0.0.1', got '%s'", cfg.Server.HTTP.Host)
    }

    if !cfg.Server.HTTP.CORS.Enabled {
        t.Error("Expected CORS to be enabled by default")
    }

    expectedOrigins := []string{"http://localhost:3000", "http://127.0.0.1:3000"}
    if len(cfg.Server.HTTP.CORS.Origins) != len(expectedOrigins) {
        t.Errorf("Expected default CORS origins length to be %d, got %d", len(expectedOrigins), len(cfg.Server.HTTP.CORS.Origins))
    }
    for i, expected := range expectedOrigins {
        if i >= len(cfg.Server.HTTP.CORS.Origins) || cfg.Server.HTTP.CORS.Origins[i] != expected {
            t.Errorf("Expected default CORS origins to be %v, got %v", expectedOrigins, cfg.Server.HTTP.CORS.Origins)
            break
        }
    }

    if cfg.Tools.Precision.MaxDecimalPlaces != 15 {
        t.Errorf("Expected max decimal places to be 15, got %d", cfg.Tools.Precision.MaxDecimalPlaces)
    }

    if cfg.Tools.Precision.DefaultDecimalPlaces != 2 {
        t.Errorf("Expected default decimal places to be 2, got %d", cfg.Tools.Precision.DefaultDecimalPlaces)
    }
}

func TestConfigValidation(t *testing.T) {
    tests := []struct {
        name    string
        config  func() *config.Config
        wantErr bool
    }{
        {
            name: "Valid default config",
            config: func() *config.Config {
                return config.Default()
            },
            wantErr: false,
        },
        {
            name: "Invalid transport",
            config: func() *config.Config {
                cfg := config.Default()
                cfg.Server.Transport = "invalid"
                return cfg
            },
            wantErr: true,
        },
        {
            name: "Invalid port - too low",
            config: func() *config.Config {
                cfg := config.Default()
                cfg.Server.HTTP.Port = 0
                return cfg
            },
            wantErr: true,
        },
        {
            name: "Invalid port - too high",
            config: func() *config.Config {
                cfg := config.Default()
                cfg.Server.HTTP.Port = 65536
                return cfg
            },
            wantErr: true,
        },
        {
            name: "Invalid max precision",
            config: func() *config.Config {
                cfg := config.Default()
                cfg.Tools.Precision.MaxDecimalPlaces = 16
                return cfg
            },
            wantErr: true,
        },
        {
            name: "Invalid default precision",
            config: func() *config.Config {
                cfg := config.Default()
                cfg.Tools.Precision.DefaultDecimalPlaces = 16
                return cfg
            },
            wantErr: true,
        },
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            cfg := tt.config()
            err := cfg.Validate()

            if (err != nil) != tt.wantErr {
                t.Errorf("Config validation error = %v, wantErr %v", err, tt.wantErr)
            }
        })
    }
}

func TestConfigLoader(t *testing.T) {
    // Create temporary directory for test configs
    tempDir, err := ioutil.TempDir("", "config-test")
    if err != nil {
        t.Fatalf("Failed to create temp dir: %v", err)
    }
    defer os.RemoveAll(tempDir)

    // Test YAML config
    yamlConfig := `
server:
  transport: "http"
  http:
    host: "127.0.0.1"
    port: 9090
    session_timeout: "45s"
    max_connections: 200
    cors:
      enabled: false
      origins: ["https://example.com"]

logging:
  level: "debug"
  format: "text"
  output: "stderr"

tools:
  precision:
    max_decimal_places: 10
    default_decimal_places: 3
  expression_eval:
    timeout: "30s"
    max_variables: 50
`

    yamlFile := filepath.Join(tempDir, "config.yaml")
    err = ioutil.WriteFile(yamlFile, []byte(yamlConfig), 0644)
    if err != nil {
        t.Fatalf("Failed to write YAML config: %v", err)
    }

    loader := config.NewLoader()
    cfg, err := loader.Load(yamlFile)
    if err != nil {
        t.Fatalf("Failed to load YAML config: %v", err)
    }

    // Verify loaded config
    if cfg.Server.Transport != "http" {
        t.Errorf("Expected transport 'http', got '%s'", cfg.Server.Transport)
    }

    if cfg.Server.HTTP.Host != "127.0.0.1" {
        t.Errorf("Expected host '127.0.0.1', got '%s'", cfg.Server.HTTP.Host)
    }

    if cfg.Server.HTTP.Port != 9090 {
        t.Errorf("Expected port 9090, got %d", cfg.Server.HTTP.Port)
    }

    if cfg.Server.HTTP.CORS.Enabled {
        t.Error("Expected CORS to be disabled")
    }

    if cfg.Server.HTTP.SessionTimeout != 45*time.Second {
        t.Errorf("Expected session timeout 45s, got %v", cfg.Server.HTTP.SessionTimeout)
    }

    if cfg.Logging.Level != "debug" {
        t.Errorf("Expected log level 'debug', got '%s'", cfg.Logging.Level)
    }

    if cfg.Tools.Precision.MaxDecimalPlaces != 10 {
        t.Errorf("Expected max decimal places 10, got %d", cfg.Tools.Precision.MaxDecimalPlaces)
    }
}

func TestConfigLoaderJSON(t *testing.T) {
    // Create temporary directory for test configs
    tempDir, err := ioutil.TempDir("", "config-test")
    if err != nil {
        t.Fatalf("Failed to create temp dir: %v", err)
    }
    defer os.RemoveAll(tempDir)

    // Test JSON config
    jsonConfig := `{
        "server": {
            "transport": "http",
            "http": {
                "host": "localhost",
                "port": 8888,
                "cors": {
                    "enabled": true,
                    "origins": ["http://localhost:3000"]
                }
            }
        },
        "logging": {
            "level": "warn",
            "format": "json"
        }
    }`

    jsonFile := filepath.Join(tempDir, "config.json")
    err = ioutil.WriteFile(jsonFile, []byte(jsonConfig), 0644)
    if err != nil {
        t.Fatalf("Failed to write JSON config: %v", err)
    }

    loader := config.NewLoader()
    cfg, err := loader.Load(jsonFile)
    if err != nil {
        t.Fatalf("Failed to load JSON config: %v", err)
    }

    // Verify loaded config
    if cfg.Server.HTTP.Port != 8888 {
        t.Errorf("Expected port 8888, got %d", cfg.Server.HTTP.Port)
    }

    if cfg.Logging.Level != "warn" {
        t.Errorf("Expected log level 'warn', got '%s'", cfg.Logging.Level)
    }

    if len(cfg.Server.HTTP.CORS.Origins) != 1 || cfg.Server.HTTP.CORS.Origins[0] != "http://localhost:3000" {
        t.Errorf("Expected CORS origins ['http://localhost:3000'], got %v", cfg.Server.HTTP.CORS.Origins)
    }
}

func TestConfigLoaderEnvironmentVariables(t *testing.T) {
    // Set environment variables
    envVars := map[string]string{
        "CALCULATOR_TRANSPORT":         "http",
        "CALCULATOR_HTTP_HOST":         "example.com",
        "CALCULATOR_HTTP_PORT":         "9999",
        "CALCULATOR_LOG_LEVEL":         "error",
        "CALCULATOR_MAX_PRECISION":     "12",
        "CALCULATOR_DEFAULT_PRECISION": "4",
    }

    // Set environment variables
    for key, value := range envVars {
        os.Setenv(key, value)
        defer os.Unsetenv(key)
    }

    loader := config.NewLoader()
    cfg, err := loader.Load("") // No config file
    if err != nil {
        t.Fatalf("Failed to load config with env vars: %v", err)
    }

    // Verify environment variables were applied
    if cfg.Server.Transport != "http" {
        t.Errorf("Expected transport 'http', got '%s'", cfg.Server.Transport)
    }

    if cfg.Server.HTTP.Host != "example.com" {
        t.Errorf("Expected host 'example.com', got '%s'", cfg.Server.HTTP.Host)
    }

    if cfg.Server.HTTP.Port != 9999 {
        t.Errorf("Expected port 9999, got %d", cfg.Server.HTTP.Port)
    }

    if cfg.Logging.Level != "error" {
        t.Errorf("Expected log level 'error', got '%s'", cfg.Logging.Level)
    }

    if cfg.Tools.Precision.MaxDecimalPlaces != 12 {
        t.Errorf("Expected max decimal places 12, got %d", cfg.Tools.Precision.MaxDecimalPlaces)
    }

    if cfg.Tools.Precision.DefaultDecimalPlaces != 4 {
        t.Errorf("Expected default decimal places 4, got %d", cfg.Tools.Precision.DefaultDecimalPlaces)
    }
}

func TestConfigLoaderFileNotFound(t *testing.T) {
    loader := config.NewLoader()

    // Should return default config when no config file found
    cfg, err := loader.Load("")
    if err != nil {
        t.Fatalf("Expected no error when config file not found, got: %v", err)
    }

    // Should be default config
    defaultCfg := config.Default()
    if cfg.Server.Transport != defaultCfg.Server.Transport {
        t.Errorf("Expected default transport, got different config")
    }
}

func TestConfigLoaderInvalidFile(t *testing.T) {
    // Create temporary directory
    tempDir, err := ioutil.TempDir("", "config-test")
    if err != nil {
        t.Fatalf("Failed to create temp dir: %v", err)
    }
    defer os.RemoveAll(tempDir)

    // Create invalid config file
    invalidFile := filepath.Join(tempDir, "invalid.yaml")
    err = ioutil.WriteFile(invalidFile, []byte("invalid: yaml: content: ["), 0644)
    if err != nil {
        t.Fatalf("Failed to write invalid config: %v", err)
    }

    loader := config.NewLoader()
    _, err = loader.Load(invalidFile)
    if err == nil {
        t.Error("Expected error when loading invalid config file")
    }
}
