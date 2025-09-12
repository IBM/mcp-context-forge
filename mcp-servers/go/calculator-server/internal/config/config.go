package config

import (
    "time"
)

// Config represents the complete server configuration
type Config struct {
    Server   ServerConfig   `yaml:"server" json:"server"`
    Logging  LoggingConfig  `yaml:"logging" json:"logging"`
    Tools    ToolsConfig    `yaml:"tools" json:"tools"`
    Security SecurityConfig `yaml:"security" json:"security"`
}

// ServerConfig contains server-specific configuration
type ServerConfig struct {
    Transport string     `yaml:"transport" json:"transport"`
    HTTP      HTTPConfig `yaml:"http" json:"http"`
}

// HTTPConfig contains MCP-compliant HTTP transport configuration
type HTTPConfig struct {
    Host           string        `yaml:"host" json:"host"`
    Port           int           `yaml:"port" json:"port"`
    SessionTimeout time.Duration `yaml:"session_timeout" json:"session_timeout"`
    MaxConnections int           `yaml:"max_connections" json:"max_connections"`
    CORS           CORSConfig    `yaml:"cors" json:"cors"`
}

// CORSConfig contains CORS configuration
type CORSConfig struct {
    Enabled bool     `yaml:"enabled" json:"enabled"`
    Origins []string `yaml:"origins" json:"origins"`
}

// LoggingConfig contains logging configuration
type LoggingConfig struct {
    Level  string `yaml:"level" json:"level"`
    Format string `yaml:"format" json:"format"`
    Output string `yaml:"output" json:"output"`
}

// ToolsConfig contains tools-specific configuration
type ToolsConfig struct {
    Precision      PrecisionConfig      `yaml:"precision" json:"precision"`
    ExpressionEval ExpressionEvalConfig `yaml:"expression_eval" json:"expression_eval"`
    Statistics     StatisticsConfig     `yaml:"statistics" json:"statistics"`
    Financial      FinancialConfig      `yaml:"financial" json:"financial"`
}

// PrecisionConfig contains precision configuration
type PrecisionConfig struct {
    MaxDecimalPlaces     int `yaml:"max_decimal_places" json:"max_decimal_places"`
    DefaultDecimalPlaces int `yaml:"default_decimal_places" json:"default_decimal_places"`
}

// ExpressionEvalConfig contains expression evaluation configuration
type ExpressionEvalConfig struct {
    Timeout      time.Duration `yaml:"timeout" json:"timeout"`
    MaxVariables int           `yaml:"max_variables" json:"max_variables"`
}

// StatisticsConfig contains statistics configuration
type StatisticsConfig struct {
    MaxDataPoints int `yaml:"max_data_points" json:"max_data_points"`
}

// FinancialConfig contains financial calculations configuration
type FinancialConfig struct {
    CurrencyDefault string `yaml:"currency_default" json:"currency_default"`
}

// SecurityConfig contains security configuration
type SecurityConfig struct {
    RateLimiting     RateLimitingConfig `yaml:"rate_limiting" json:"rate_limiting"`
    RequestSizeLimit string             `yaml:"request_size_limit" json:"request_size_limit"`
}

// RateLimitingConfig contains rate limiting configuration
type RateLimitingConfig struct {
    Enabled           bool `yaml:"enabled" json:"enabled"`
    RequestsPerMinute int  `yaml:"requests_per_minute" json:"requests_per_minute"`
}

// Default returns a configuration with default values
func Default() *Config {
    return &Config{
        Server: ServerConfig{
            Transport: "stdio",
            HTTP: HTTPConfig{
                Host:           "127.0.0.1", // Default to localhost for security
                Port:           8080,
                SessionTimeout: 5 * time.Minute,
                MaxConnections: 100,
                CORS: CORSConfig{
                    Enabled: true,
                    Origins: []string{"http://localhost:3000", "http://127.0.0.1:3000"},
                },
            },
        },
        Logging: LoggingConfig{
            Level:  "info",
            Format: "json",
            Output: "stdout",
        },
        Tools: ToolsConfig{
            Precision: PrecisionConfig{
                MaxDecimalPlaces:     15,
                DefaultDecimalPlaces: 2,
            },
            ExpressionEval: ExpressionEvalConfig{
                Timeout:      10 * time.Second,
                MaxVariables: 100,
            },
            Statistics: StatisticsConfig{
                MaxDataPoints: 10000,
            },
            Financial: FinancialConfig{
                CurrencyDefault: "USD",
            },
        },
        Security: SecurityConfig{
            RateLimiting: RateLimitingConfig{
                Enabled:           true,
                RequestsPerMinute: 100,
            },
            RequestSizeLimit: "1MB",
        },
    }
}

// Validate validates the configuration
func (c *Config) Validate() error {
    if c.Server.Transport != "stdio" && c.Server.Transport != "http" {
        return ErrInvalidTransport
    }

    if c.Server.HTTP.Port < 1 || c.Server.HTTP.Port > 65535 {
        return ErrInvalidPort
    }

    if c.Tools.Precision.MaxDecimalPlaces < 0 || c.Tools.Precision.MaxDecimalPlaces > 15 {
        return ErrInvalidPrecision
    }

    if c.Tools.Precision.DefaultDecimalPlaces < 0 || c.Tools.Precision.DefaultDecimalPlaces > c.Tools.Precision.MaxDecimalPlaces {
        return ErrInvalidDefaultPrecision
    }

    if c.Tools.ExpressionEval.MaxVariables < 1 {
        return ErrInvalidMaxVariables
    }

    if c.Tools.Statistics.MaxDataPoints < 1 {
        return ErrInvalidMaxDataPoints
    }

    if c.Security.RateLimiting.RequestsPerMinute < 1 {
        return ErrInvalidRateLimit
    }

    return nil
}
