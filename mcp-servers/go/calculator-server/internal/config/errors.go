package config

import "errors"

// Configuration validation errors
var (
	ErrInvalidTransport        = errors.New("transport must be 'stdio' or 'http'")
	ErrInvalidPort             = errors.New("port must be between 1 and 65535")
	ErrInvalidPrecision        = errors.New("max decimal places must be between 0 and 15")
	ErrInvalidDefaultPrecision = errors.New("default decimal places must be between 0 and max decimal places")
	ErrInvalidMaxVariables     = errors.New("max variables must be at least 1")
	ErrInvalidMaxDataPoints    = errors.New("max data points must be at least 1")
	ErrInvalidRateLimit        = errors.New("requests per minute must be at least 1")
	ErrConfigFileNotFound      = errors.New("configuration file not found")
	ErrInvalidConfigFormat     = errors.New("invalid configuration file format")
)