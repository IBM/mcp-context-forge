package calculator

import (
	"fmt"
	"math"

	"calculator-server/internal/types"
	"github.com/shopspring/decimal"
)

type BasicCalculator struct{}

func NewBasicCalculator() *BasicCalculator {
	return &BasicCalculator{}
}

func (bc *BasicCalculator) Calculate(req types.BasicMathRequest) (types.CalculationResult, error) {
	if len(req.Operands) < 2 {
		return types.CalculationResult{}, fmt.Errorf("at least 2 operands required")
	}

	precision := req.Precision
	// Note: precision 0 means no decimal places, don't default to 2

	var result float64
	var err error

	switch req.Operation {
	case "add":
		result = bc.add(req.Operands)
	case "subtract":
		result = bc.subtract(req.Operands)
	case "multiply":
		result = bc.multiply(req.Operands)
	case "divide":
		result, err = bc.divide(req.Operands)
		if err != nil {
			return types.CalculationResult{}, err
		}
	default:
		return types.CalculationResult{}, fmt.Errorf("unsupported operation: %s", req.Operation)
	}

	// Round to specified precision
	result = bc.roundToPrecision(result, precision)

	return types.CalculationResult{
		Result: result,
	}, nil
}

func (bc *BasicCalculator) add(operands []float64) float64 {
	// Use decimal for precise addition
	result := decimal.NewFromFloat(operands[0])
	for i := 1; i < len(operands); i++ {
		result = result.Add(decimal.NewFromFloat(operands[i]))
	}

	floatResult, _ := result.Float64()
	return floatResult
}

func (bc *BasicCalculator) subtract(operands []float64) float64 {
	// Use decimal for precise subtraction
	result := decimal.NewFromFloat(operands[0])
	for i := 1; i < len(operands); i++ {
		result = result.Sub(decimal.NewFromFloat(operands[i]))
	}

	floatResult, _ := result.Float64()
	return floatResult
}

func (bc *BasicCalculator) multiply(operands []float64) float64 {
	// Use decimal for precise multiplication
	result := decimal.NewFromFloat(operands[0])
	for i := 1; i < len(operands); i++ {
		result = result.Mul(decimal.NewFromFloat(operands[i]))
	}

	floatResult, _ := result.Float64()
	return floatResult
}

func (bc *BasicCalculator) divide(operands []float64) (float64, error) {
	// Check for division by zero
	for i := 1; i < len(operands); i++ {
		if operands[i] == 0 {
			return 0, fmt.Errorf("division by zero")
		}
	}

	// Use decimal for precise division
	result := decimal.NewFromFloat(operands[0])
	for i := 1; i < len(operands); i++ {
		result = result.Div(decimal.NewFromFloat(operands[i]))
	}

	floatResult, _ := result.Float64()
	return floatResult, nil
}

func (bc *BasicCalculator) roundToPrecision(value float64, precision int) float64 {
	multiplier := math.Pow(10, float64(precision))
	return math.Round(value*multiplier) / multiplier
}

// Additional utility functions for validation
func (bc *BasicCalculator) ValidateOperands(operands []float64) error {
	if len(operands) == 0 {
		return fmt.Errorf("no operands provided")
	}
	if len(operands) < 2 {
		return fmt.Errorf("at least 2 operands required")
	}

	// Check for invalid numbers (NaN, Inf)
	for i, operand := range operands {
		if math.IsNaN(operand) {
			return fmt.Errorf("operand %d is NaN", i)
		}
		if math.IsInf(operand, 0) {
			return fmt.Errorf("operand %d is infinite", i)
		}
	}

	return nil
}

func (bc *BasicCalculator) ValidateOperation(operation string) error {
	validOperations := []string{"add", "subtract", "multiply", "divide"}
	for _, validOp := range validOperations {
		if operation == validOp {
			return nil
		}
	}
	return fmt.Errorf("invalid operation: %s. Valid operations are: %v", operation, validOperations)
}
