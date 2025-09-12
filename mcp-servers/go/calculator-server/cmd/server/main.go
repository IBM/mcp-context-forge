/*
Copyright 2025
SPDX-License-Identifier: Apache-2.0
*/
package main

import (
	"calculator-server/internal/config"
	"calculator-server/internal/handlers"
	"calculator-server/pkg/mcp"
	"context"
	"flag"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func main() {
	// Parse command line flags
	transport := flag.String("transport", "", "Transport method (stdio, http)")
	port := flag.Int("port", 0, "Port for HTTP transport")
	host := flag.String("host", "", "Host for HTTP transport")
	configPath := flag.String("config", "", "Path to configuration file")
	flag.Parse()

	// Load configuration
	loader := config.NewLoader()
	cfg, err := loader.Load(*configPath)
	if err != nil {
		log.Fatalf("Failed to load configuration: %v", err)
	}

	// Override configuration with command line flags
	if *transport != "" {
		cfg.Server.Transport = *transport
	}
	if *host != "" {
		cfg.Server.HTTP.Host = *host
	}
	if *port != 0 {
		cfg.Server.HTTP.Port = *port
	}

	// Validate final configuration
	if err := cfg.Validate(); err != nil {
		log.Fatalf("Configuration validation failed: %v", err)
	}

	// Create MCP server
	server := mcp.NewServer()

	// Create handlers
	mathHandler := handlers.NewMathHandler()
	statsHandler := handlers.NewStatsHandler()
	financeHandler := handlers.NewFinanceHandler()

	// Register tools
	registerTools(server, mathHandler, statsHandler, financeHandler)

	// Start server based on transport
	switch cfg.Server.Transport {
	case "stdio":
		log.Println("Starting calculator server with stdio transport...")
		if err := server.Run(); err != nil {
			log.Fatalf("Server error: %v", err)
		}
	case "http":
		startHTTPServerWithConfig(server, cfg)
	default:
		log.Fatalf("Unknown transport: %s", cfg.Server.Transport)
	}
}

func startHTTPServerWithConfig(server *mcp.Server, cfg *config.Config) {
	// Configure MCP-compliant streamable HTTP transport from config
	httpConfig := &mcp.StreamableHTTPConfig{
		Host:           cfg.Server.HTTP.Host,
		Port:           cfg.Server.HTTP.Port,
		SessionTimeout: cfg.Server.HTTP.SessionTimeout,
		MaxConnections: cfg.Server.HTTP.MaxConnections,
		CORSEnabled:    cfg.Server.HTTP.CORS.Enabled,
		CORSOrigins:    cfg.Server.HTTP.CORS.Origins,
	}

	// Create MCP-compliant streamable HTTP transport
	httpTransport := mcp.NewStreamableHTTPTransport(server, httpConfig)

	// Setup graceful shutdown
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Channel to listen for interrupt signals
	c := make(chan os.Signal, 1)
	signal.Notify(c, os.Interrupt, syscall.SIGTERM)

	// Start server in a goroutine
	go func() {
		log.Printf("Starting calculator server with MCP streamable HTTP transport on %s:%d...",
			cfg.Server.HTTP.Host, cfg.Server.HTTP.Port)

		if err := httpTransport.Start(); err != nil {
			log.Printf("HTTP server error: %v", err)
			cancel()
		}
	}()

	// Wait for shutdown signal
	select {
	case <-c:
		log.Println("Received shutdown signal...")
	case <-ctx.Done():
		log.Println("Server context cancelled...")
	}

	// Create a timeout context for shutdown
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer shutdownCancel()

	// Graceful shutdown
	if err := httpTransport.Stop(shutdownCtx); err != nil {
		log.Printf("Error during shutdown: %v", err)
	} else {
		log.Println("Server shut down gracefully")
	}
}

func registerTools(server *mcp.Server, mathHandler *handlers.MathHandler, statsHandler *handlers.StatsHandler, financeHandler *handlers.FinanceHandler) {
	// Basic Math Operations
	server.RegisterTool(
		"basic_math",
		"Perform basic mathematical operations (add, subtract, multiply, divide)",
		getBasicMathSchema(),
		mathHandler.HandleBasicMath,
	)

	// Advanced Math Functions
	server.RegisterTool(
		"advanced_math",
		"Perform advanced mathematical functions (trigonometry, logarithms, etc.)",
		getAdvancedMathSchema(),
		mathHandler.HandleAdvancedMath,
	)

	// Expression Evaluation
	server.RegisterTool(
		"expression_eval",
		"Evaluate mathematical expressions with variable substitution",
		getExpressionEvalSchema(),
		mathHandler.HandleExpressionEval,
	)

	// Statistics
	server.RegisterTool(
		"statistics",
		"Perform statistical analysis on data sets",
		getStatisticsSchema(),
		statsHandler.HandleStatistics,
	)

	// Unit Conversion
	server.RegisterTool(
		"unit_conversion",
		"Convert between different units of measurement",
		getUnitConversionSchema(),
		mathHandler.HandleUnitConversion,
	)

	// Financial Calculations
	server.RegisterTool(
		"financial",
		"Perform financial calculations (interest, loans, ROI)",
		getFinancialSchema(),
		financeHandler.HandleFinancialCalculation,
	)

	// Additional specialized tools
	registerAdditionalTools(server, statsHandler, financeHandler)
}

func registerAdditionalTools(server *mcp.Server, statsHandler *handlers.StatsHandler, financeHandler *handlers.FinanceHandler) {
	// Statistics Summary
	server.RegisterTool(
		"stats_summary",
		"Get comprehensive statistical summary of a dataset",
		getStatsSummarySchema(),
		statsHandler.HandleStatsSummary,
	)

	// Percentile Calculation
	server.RegisterTool(
		"percentile",
		"Calculate specific percentile of a dataset",
		getPercentileSchema(),
		statsHandler.HandlePercentileCalculation,
	)

	// Multiple Unit Conversions
	server.RegisterTool(
		"batch_conversion",
		"Convert multiple values between units",
		getBatchConversionSchema(),
		statsHandler.HandleMultipleConversions,
	)

	// NPV Calculation
	server.RegisterTool(
		"npv",
		"Calculate Net Present Value of cash flows",
		getNPVSchema(),
		financeHandler.HandleNPV,
	)

	// IRR Calculation
	server.RegisterTool(
		"irr",
		"Calculate Internal Rate of Return of cash flows",
		getIRRSchema(),
		financeHandler.HandleIRR,
	)

	// Loan Comparison
	server.RegisterTool(
		"loan_comparison",
		"Compare multiple loan options",
		getLoanComparisonSchema(),
		financeHandler.HandleLoanComparison,
	)

	// Investment Scenarios
	server.RegisterTool(
		"investment_scenarios",
		"Compare multiple investment scenarios",
		getInvestmentScenariosSchema(),
		financeHandler.HandleInvestmentScenarios,
	)
}

// Schema definitions for tool parameters
func getBasicMathSchema() map[string]interface{} {
	return map[string]interface{}{
		"type": "object",
		"properties": map[string]interface{}{
			"operation": map[string]interface{}{
				"type":        "string",
				"enum":        []string{"add", "subtract", "multiply", "divide"},
				"description": "The mathematical operation to perform",
			},
			"operands": map[string]interface{}{
				"type": "array",
				"items": map[string]interface{}{
					"type": "number",
				},
				"minItems":    2,
				"description": "Array of numbers to operate on",
			},
			"precision": map[string]interface{}{
				"type":        "integer",
				"minimum":     0,
				"maximum":     15,
				"default":     2,
				"description": "Number of decimal places in result",
			},
		},
		"required": []string{"operation", "operands"},
	}
}

func getAdvancedMathSchema() map[string]interface{} {
	return map[string]interface{}{
		"type": "object",
		"properties": map[string]interface{}{
			"function": map[string]interface{}{
				"type":        "string",
				"enum":        []string{"sin", "cos", "tan", "asin", "acos", "atan", "log", "log10", "ln", "sqrt", "abs", "factorial", "pow", "exp"},
				"description": "The mathematical function to apply",
			},
			"value": map[string]interface{}{
				"type":        "number",
				"description": "The input value for the function (base for pow function)",
			},
			"exponent": map[string]interface{}{
				"type":        "number",
				"description": "The exponent for pow function (required for pow, ignored for other functions)",
			},
			"unit": map[string]interface{}{
				"type":        "string",
				"enum":        []string{"radians", "degrees"},
				"default":     "radians",
				"description": "Unit for trigonometric functions",
			},
		},
		"required": []string{"function", "value"},
	}
}

func getExpressionEvalSchema() map[string]interface{} {
	return map[string]interface{}{
		"type": "object",
		"properties": map[string]interface{}{
			"expression": map[string]interface{}{
				"type":        "string",
				"description": "Mathematical expression to evaluate",
			},
			"variables": map[string]interface{}{
				"type":        "object",
				"description": "Variables to substitute in the expression",
				"patternProperties": map[string]interface{}{
					"^[a-zA-Z][a-zA-Z0-9_]*$": map[string]interface{}{
						"type": "number",
					},
				},
			},
		},
		"required": []string{"expression"},
	}
}

func getStatisticsSchema() map[string]interface{} {
	return map[string]interface{}{
		"type": "object",
		"properties": map[string]interface{}{
			"data": map[string]interface{}{
				"type": "array",
				"items": map[string]interface{}{
					"type": "number",
				},
				"minItems":    1,
				"description": "Array of numerical data",
			},
			"operation": map[string]interface{}{
				"type":        "string",
				"enum":        []string{"mean", "median", "mode", "std_dev", "variance", "percentile"},
				"description": "Statistical operation to perform",
			},
		},
		"required": []string{"data", "operation"},
	}
}

func getUnitConversionSchema() map[string]interface{} {
	return map[string]interface{}{
		"type": "object",
		"properties": map[string]interface{}{
			"value": map[string]interface{}{
				"type":        "number",
				"description": "Value to convert",
			},
			"fromUnit": map[string]interface{}{
				"type":        "string",
				"description": "Source unit",
			},
			"toUnit": map[string]interface{}{
				"type":        "string",
				"description": "Target unit",
			},
			"category": map[string]interface{}{
				"type":        "string",
				"enum":        []string{"length", "weight", "temperature", "volume", "area"},
				"description": "Category of measurement",
			},
		},
		"required": []string{"value", "fromUnit", "toUnit", "category"},
	}
}

func getFinancialSchema() map[string]interface{} {
	return map[string]interface{}{
		"type": "object",
		"properties": map[string]interface{}{
			"operation": map[string]interface{}{
				"type":        "string",
				"enum":        []string{"compound_interest", "simple_interest", "loan_payment", "roi", "present_value", "future_value"},
				"description": "Financial operation to perform",
			},
			"principal": map[string]interface{}{
				"type":        "number",
				"minimum":     0,
				"description": "Principal amount or initial investment",
			},
			"rate": map[string]interface{}{
				"type":        "number",
				"minimum":     0,
				"description": "Interest rate (as percentage)",
			},
			"time": map[string]interface{}{
				"type":        "number",
				"minimum":     0,
				"description": "Time period in years",
			},
			"periods": map[string]interface{}{
				"type":        "integer",
				"minimum":     1,
				"description": "Number of compounding periods per year",
			},
			"futureValue": map[string]interface{}{
				"type":        "number",
				"minimum":     0,
				"description": "Future value (for ROI and present value calculations)",
			},
		},
		"required": []string{"operation"},
	}
}

// Additional schema definitions
func getStatsSummarySchema() map[string]interface{} {
	return map[string]interface{}{
		"type": "object",
		"properties": map[string]interface{}{
			"data": map[string]interface{}{
				"type": "array",
				"items": map[string]interface{}{
					"type": "number",
				},
				"minItems":    1,
				"description": "Array of numerical data for summary statistics",
			},
		},
		"required": []string{"data"},
	}
}

func getPercentileSchema() map[string]interface{} {
	return map[string]interface{}{
		"type": "object",
		"properties": map[string]interface{}{
			"data": map[string]interface{}{
				"type": "array",
				"items": map[string]interface{}{
					"type": "number",
				},
				"minItems":    1,
				"description": "Array of numerical data",
			},
			"percentile": map[string]interface{}{
				"type":        "number",
				"minimum":     0,
				"maximum":     100,
				"description": "Percentile to calculate (0-100)",
			},
		},
		"required": []string{"data", "percentile"},
	}
}

func getBatchConversionSchema() map[string]interface{} {
	return map[string]interface{}{
		"type": "object",
		"properties": map[string]interface{}{
			"values": map[string]interface{}{
				"type": "array",
				"items": map[string]interface{}{
					"type": "number",
				},
				"minItems":    1,
				"description": "Array of values to convert",
			},
			"fromUnit": map[string]interface{}{
				"type":        "string",
				"description": "Source unit",
			},
			"toUnit": map[string]interface{}{
				"type":        "string",
				"description": "Target unit",
			},
			"category": map[string]interface{}{
				"type":        "string",
				"enum":        []string{"length", "weight", "temperature", "volume", "area"},
				"description": "Category of measurement",
			},
		},
		"required": []string{"values", "fromUnit", "toUnit", "category"},
	}
}

func getNPVSchema() map[string]interface{} {
	return map[string]interface{}{
		"type": "object",
		"properties": map[string]interface{}{
			"cashFlows": map[string]interface{}{
				"type": "array",
				"items": map[string]interface{}{
					"type": "number",
				},
				"minItems":    1,
				"description": "Array of cash flows (negative for outflows, positive for inflows)",
			},
			"discountRate": map[string]interface{}{
				"type":        "number",
				"minimum":     0,
				"description": "Discount rate as percentage",
			},
		},
		"required": []string{"cashFlows", "discountRate"},
	}
}

func getIRRSchema() map[string]interface{} {
	return map[string]interface{}{
		"type": "object",
		"properties": map[string]interface{}{
			"cashFlows": map[string]interface{}{
				"type": "array",
				"items": map[string]interface{}{
					"type": "number",
				},
				"minItems":    2,
				"description": "Array of cash flows (negative for outflows, positive for inflows)",
			},
		},
		"required": []string{"cashFlows"},
	}
}

func getLoanComparisonSchema() map[string]interface{} {
	return map[string]interface{}{
		"type": "object",
		"properties": map[string]interface{}{
			"loans": map[string]interface{}{
				"type": "array",
				"items": map[string]interface{}{
					"type": "object",
					"properties": map[string]interface{}{
						"principal": map[string]interface{}{
							"type":    "number",
							"minimum": 0,
						},
						"rate": map[string]interface{}{
							"type":    "number",
							"minimum": 0,
						},
						"time": map[string]interface{}{
							"type":    "number",
							"minimum": 0,
						},
					},
					"required": []string{"principal", "rate", "time"},
				},
				"minItems":    1,
				"description": "Array of loan scenarios to compare",
			},
		},
		"required": []string{"loans"},
	}
}

func getInvestmentScenariosSchema() map[string]interface{} {
	return map[string]interface{}{
		"type": "object",
		"properties": map[string]interface{}{
			"scenarios": map[string]interface{}{
				"type": "array",
				"items": map[string]interface{}{
					"type": "object",
					"properties": map[string]interface{}{
						"principal": map[string]interface{}{
							"type":    "number",
							"minimum": 0,
						},
						"rate": map[string]interface{}{
							"type":    "number",
							"minimum": 0,
						},
						"time": map[string]interface{}{
							"type":    "number",
							"minimum": 0,
						},
					},
					"required": []string{"principal", "rate", "time"},
				},
				"minItems":    1,
				"description": "Array of investment scenarios to compare",
			},
		},
		"required": []string{"scenarios"},
	}
}
