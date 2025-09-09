package types

import (
	"encoding/json"
	"time"
)

// MCP Protocol Types
type MCPRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      interface{}     `json:"id"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type MCPResponse struct {
	JSONRPC string      `json:"jsonrpc"`
	ID      interface{} `json:"id"`
	Result  interface{} `json:"result,omitempty"`
	Error   *MCPError   `json:"error,omitempty"`
}

type MCPError struct {
	Code    int         `json:"code"`
	Message string      `json:"message"`
	Data    interface{} `json:"data,omitempty"`
}

// Tool Types
type Tool struct {
	Name        string                 `json:"name"`
	Description string                 `json:"description"`
	InputSchema map[string]interface{} `json:"inputSchema"`
}

type ListToolsResult struct {
	Tools []Tool `json:"tools"`
}

type CallToolParams struct {
	Name      string                 `json:"name"`
	Arguments map[string]interface{} `json:"arguments,omitempty"`
}

type CallToolResult struct {
	Content []ContentBlock `json:"content"`
}

type ContentBlock struct {
	Type string `json:"type"`
	Text string `json:"text"`
}

// Calculator Request Types
type BasicMathRequest struct {
	Operation string    `json:"operation"`
	Operands  []float64 `json:"operands"`
	Precision int       `json:"precision,omitempty"`
}

type AdvancedMathRequest struct {
	Function string  `json:"function"`
	Value    float64 `json:"value"`
	Unit     string  `json:"unit,omitempty"`
}

type ExpressionRequest struct {
	Expression string             `json:"expression"`
	Variables  map[string]float64 `json:"variables,omitempty"`
}

type StatisticsRequest struct {
	Data      []float64 `json:"data"`
	Operation string    `json:"operation"`
}

type UnitConversionRequest struct {
	Value    float64 `json:"value"`
	FromUnit string  `json:"fromUnit"`
	ToUnit   string  `json:"toUnit"`
	Category string  `json:"category"`
}

type FinancialRequest struct {
	Operation   string  `json:"operation"`
	Principal   float64 `json:"principal,omitempty"`
	Rate        float64 `json:"rate,omitempty"`
	Time        float64 `json:"time,omitempty"`
	Periods     int     `json:"periods,omitempty"`
	FutureValue float64 `json:"futureValue,omitempty"`
}

// Response Types
type CalculationResult struct {
	Result float64 `json:"result"`
	Unit   string  `json:"unit,omitempty"`
}

type StatisticsResult struct {
	Result interface{} `json:"result"`
	Count  int         `json:"count"`
}

type FinancialResult struct {
	Result      float64                `json:"result"`
	Breakdown   map[string]interface{} `json:"breakdown,omitempty"`
	Description string                 `json:"description,omitempty"`
}

// MCP Session Management Types
type Session struct {
	ID        string    `json:"id"`
	CreatedAt time.Time `json:"created_at"`
	LastSeen  time.Time `json:"last_seen"`
	Active    bool      `json:"active"`
}

type SessionError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}