package config

import (
	"encoding/json"
	"fmt"
	"io/ioutil"
	"os"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"
)

// Loader handles configuration loading from various sources
type Loader struct {
	searchPaths []string
}

// NewLoader creates a new configuration loader
func NewLoader() *Loader {
	return &Loader{
		searchPaths: []string{
			".",
			"./config",
			"/etc/calculator-server",
			"$HOME/.calculator-server",
		},
	}
}

// AddSearchPath adds a path to search for configuration files
func (l *Loader) AddSearchPath(path string) {
	l.searchPaths = append(l.searchPaths, path)
}

// Load loads configuration from file with the following priority:
// 1. Default configuration
// 2. Configuration file (if found)
// 3. Environment variables
// 4. Command line flags (handled by caller)
func (l *Loader) Load(configPath string) (*Config, error) {
	// Start with default configuration
	config := Default()

	// Load from file if specified or found
	var configFile string
	var err error

	if configPath != "" {
		configFile = configPath
	} else {
		configFile, err = l.findConfigFile()
		if err != nil && err != ErrConfigFileNotFound {
			return nil, fmt.Errorf("error finding config file: %w", err)
		}
	}

	if configFile != "" {
		fileConfig, err := l.loadFromFile(configFile)
		if err != nil {
			return nil, fmt.Errorf("error loading config file %s: %w", configFile, err)
		}

		// Merge file configuration with defaults
		if err := mergeConfig(config, fileConfig); err != nil {
			return nil, fmt.Errorf("error merging configuration: %w", err)
		}
	}

	// Override with environment variables
	l.loadFromEnvironment(config)

	// Validate final configuration
	if err := config.Validate(); err != nil {
		return nil, fmt.Errorf("configuration validation failed: %w", err)
	}

	return config, nil
}

// findConfigFile searches for configuration files in predefined paths
func (l *Loader) findConfigFile() (string, error) {
	configNames := []string{
		"calculator-server.yaml",
		"calculator-server.yml",
		"calculator-server.json",
		"config.yaml",
		"config.yml",
		"config.json",
	}

	for _, searchPath := range l.searchPaths {
		// Expand environment variables in path
		expandedPath := os.ExpandEnv(searchPath)

		for _, configName := range configNames {
			configPath := filepath.Join(expandedPath, configName)
			if _, err := os.Stat(configPath); err == nil {
				return configPath, nil
			}
		}
	}

	return "", ErrConfigFileNotFound
}

// loadFromFile loads configuration from a file (YAML or JSON)
func (l *Loader) loadFromFile(configPath string) (*Config, error) {
	data, err := ioutil.ReadFile(configPath)
	if err != nil {
		return nil, fmt.Errorf("failed to read config file: %w", err)
	}

	config := &Config{}

	// Determine file format by extension
	ext := strings.ToLower(filepath.Ext(configPath))

	switch ext {
	case ".yaml", ".yml":
		if err := yaml.Unmarshal(data, config); err != nil {
			return nil, fmt.Errorf("failed to parse YAML config: %w", err)
		}
	case ".json":
		if err := json.Unmarshal(data, config); err != nil {
			return nil, fmt.Errorf("failed to parse JSON config: %w", err)
		}
	default:
		// Try YAML first, then JSON
		if err := yaml.Unmarshal(data, config); err != nil {
			if err := json.Unmarshal(data, config); err != nil {
				return nil, ErrInvalidConfigFormat
			}
		}
	}

	return config, nil
}

// loadFromEnvironment overrides configuration with environment variables
func (l *Loader) loadFromEnvironment(config *Config) {
	// Server configuration
	if val := os.Getenv("CALCULATOR_TRANSPORT"); val != "" {
		config.Server.Transport = val
	}
	if val := os.Getenv("CALCULATOR_HTTP_HOST"); val != "" {
		config.Server.HTTP.Host = val
	}
	if val := os.Getenv("CALCULATOR_HTTP_PORT"); val != "" {
		if port := parseInt(val, config.Server.HTTP.Port); port > 0 {
			config.Server.HTTP.Port = port
		}
	}

	// Logging configuration
	if val := os.Getenv("CALCULATOR_LOG_LEVEL"); val != "" {
		config.Logging.Level = val
	}
	if val := os.Getenv("CALCULATOR_LOG_FORMAT"); val != "" {
		config.Logging.Format = val
	}
	if val := os.Getenv("CALCULATOR_LOG_OUTPUT"); val != "" {
		config.Logging.Output = val
	}

	// Tools configuration
	if val := os.Getenv("CALCULATOR_MAX_PRECISION"); val != "" {
		if precision := parseInt(val, config.Tools.Precision.MaxDecimalPlaces); precision >= 0 && precision <= 15 {
			config.Tools.Precision.MaxDecimalPlaces = precision
		}
	}
	if val := os.Getenv("CALCULATOR_DEFAULT_PRECISION"); val != "" {
		if precision := parseInt(val, config.Tools.Precision.DefaultDecimalPlaces); precision >= 0 {
			config.Tools.Precision.DefaultDecimalPlaces = precision
		}
	}

	// Security configuration
	if val := os.Getenv("CALCULATOR_RATE_LIMIT_ENABLED"); val != "" {
		config.Security.RateLimiting.Enabled = parseBool(val, config.Security.RateLimiting.Enabled)
	}
	if val := os.Getenv("CALCULATOR_REQUESTS_PER_MINUTE"); val != "" {
		if rpm := parseInt(val, config.Security.RateLimiting.RequestsPerMinute); rpm > 0 {
			config.Security.RateLimiting.RequestsPerMinute = rpm
		}
	}
}

// mergeConfig merges source configuration into destination
func mergeConfig(dest, src *Config) error {
	// Simple field-by-field merge
	// In a production system, you might want to use reflection or a library like mergo

	if src.Server.Transport != "" {
		dest.Server.Transport = src.Server.Transport
	}
	if src.Server.HTTP.Host != "" {
		dest.Server.HTTP.Host = src.Server.HTTP.Host
	}
	if src.Server.HTTP.Port != 0 {
		dest.Server.HTTP.Port = src.Server.HTTP.Port
	}

	// Merge CORS settings
	// Note: Always merge CORS Enabled since false is a valid override value
	dest.Server.HTTP.CORS.Enabled = src.Server.HTTP.CORS.Enabled
	if len(src.Server.HTTP.CORS.Origins) > 0 {
		dest.Server.HTTP.CORS.Origins = src.Server.HTTP.CORS.Origins
	}

	// Merge session settings
	if src.Server.HTTP.SessionTimeout != 0 {
		dest.Server.HTTP.SessionTimeout = src.Server.HTTP.SessionTimeout
	}
	if src.Server.HTTP.MaxConnections != 0 {
		dest.Server.HTTP.MaxConnections = src.Server.HTTP.MaxConnections
	}

	// Merge logging settings
	if src.Logging.Level != "" {
		dest.Logging.Level = src.Logging.Level
	}
	if src.Logging.Format != "" {
		dest.Logging.Format = src.Logging.Format
	}
	if src.Logging.Output != "" {
		dest.Logging.Output = src.Logging.Output
	}

	// Merge tools settings
	if src.Tools.Precision.MaxDecimalPlaces != 0 {
		dest.Tools.Precision.MaxDecimalPlaces = src.Tools.Precision.MaxDecimalPlaces
	}
	if src.Tools.Precision.DefaultDecimalPlaces != 0 {
		dest.Tools.Precision.DefaultDecimalPlaces = src.Tools.Precision.DefaultDecimalPlaces
	}

	if src.Tools.ExpressionEval.Timeout != 0 {
		dest.Tools.ExpressionEval.Timeout = src.Tools.ExpressionEval.Timeout
	}
	if src.Tools.ExpressionEval.MaxVariables != 0 {
		dest.Tools.ExpressionEval.MaxVariables = src.Tools.ExpressionEval.MaxVariables
	}

	if src.Tools.Statistics.MaxDataPoints != 0 {
		dest.Tools.Statistics.MaxDataPoints = src.Tools.Statistics.MaxDataPoints
	}

	if src.Tools.Financial.CurrencyDefault != "" {
		dest.Tools.Financial.CurrencyDefault = src.Tools.Financial.CurrencyDefault
	}

	// Merge security settings
	if src.Security.RateLimiting.RequestsPerMinute != 0 {
		dest.Security.RateLimiting.RequestsPerMinute = src.Security.RateLimiting.RequestsPerMinute
	}
	if src.Security.RequestSizeLimit != "" {
		dest.Security.RequestSizeLimit = src.Security.RequestSizeLimit
	}

	return nil
}

// Helper functions for parsing environment variables
func parseInt(s string, defaultVal int) int {
	var result int
	if _, err := fmt.Sscanf(s, "%d", &result); err != nil {
		return defaultVal
	}
	return result
}

func parseBool(s string, defaultVal bool) bool {
	switch strings.ToLower(s) {
	case "true", "1", "yes", "on":
		return true
	case "false", "0", "no", "off":
		return false
	default:
		return defaultVal
	}
}
