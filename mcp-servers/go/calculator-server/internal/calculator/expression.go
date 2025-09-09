package calculator

import (
	"fmt"
	"math"
	"strings"
	
	"calculator-server/internal/types"
	"github.com/Knetic/govaluate"
)

type ExpressionCalculator struct{}

func NewExpressionCalculator() *ExpressionCalculator {
	return &ExpressionCalculator{}
}

func (ec *ExpressionCalculator) Evaluate(req types.ExpressionRequest) (types.CalculationResult, error) {
	// Validate expression
	if strings.TrimSpace(req.Expression) == "" {
		return types.CalculationResult{}, fmt.Errorf("expression cannot be empty")
	}

	// Prepare the expression with mathematical constants
	expression := ec.preprocessExpression(req.Expression)

	// Create evaluable expression with custom functions
	expr, err := govaluate.NewEvaluableExpressionWithFunctions(expression, ec.getMathFunctions())
	if err != nil {
		return types.CalculationResult{}, fmt.Errorf("invalid expression: %v", err)
	}

	// Prepare parameters (variables + constants)
	parameters := make(map[string]interface{})
	
	// Add mathematical constants
	parameters["pi"] = math.Pi
	parameters["e"] = math.E
	parameters["PI"] = math.Pi
	parameters["E"] = math.E
	
	// Add user-provided variables
	if req.Variables != nil {
		for key, value := range req.Variables {
			// Validate variable names
			if !ec.isValidVariableName(key) {
				return types.CalculationResult{}, fmt.Errorf("invalid variable name: %s", key)
			}
			// Validate variable values
			if math.IsNaN(value) || math.IsInf(value, 0) {
				return types.CalculationResult{}, fmt.Errorf("invalid variable value for %s: %f", key, value)
			}
			parameters[key] = value
		}
	}

	// Evaluate the expression
	result, err := expr.Evaluate(parameters)
	if err != nil {
		return types.CalculationResult{}, fmt.Errorf("evaluation error: %v", err)
	}

	// Convert result to float64
	var floatResult float64
	switch v := result.(type) {
	case float64:
		floatResult = v
	case int:
		floatResult = float64(v)
	case int64:
		floatResult = float64(v)
	default:
		return types.CalculationResult{}, fmt.Errorf("unexpected result type: %T", result)
	}

	// Validate result
	if math.IsNaN(floatResult) {
		return types.CalculationResult{}, fmt.Errorf("expression evaluation resulted in NaN")
	}
	if math.IsInf(floatResult, 0) {
		return types.CalculationResult{}, fmt.Errorf("expression evaluation resulted in infinity")
	}

	return types.CalculationResult{
		Result: floatResult,
	}, nil
}

// getMathFunctions returns a map of custom mathematical functions for govaluate
func (ec *ExpressionCalculator) getMathFunctions() map[string]govaluate.ExpressionFunction {
	functions := make(map[string]govaluate.ExpressionFunction)

	// Trigonometric functions
	functions["sin"] = func(args ...interface{}) (interface{}, error) {
		if len(args) != 1 {
			return nil, fmt.Errorf("sin function expects 1 argument")
		}
		val, ok := args[0].(float64)
		if !ok {
			return nil, fmt.Errorf("sin function expects numeric argument")
		}
		return math.Sin(val), nil
	}

	functions["cos"] = func(args ...interface{}) (interface{}, error) {
		if len(args) != 1 {
			return nil, fmt.Errorf("cos function expects 1 argument")
		}
		val, ok := args[0].(float64)
		if !ok {
			return nil, fmt.Errorf("cos function expects numeric argument")
		}
		return math.Cos(val), nil
	}

	functions["tan"] = func(args ...interface{}) (interface{}, error) {
		if len(args) != 1 {
			return nil, fmt.Errorf("tan function expects 1 argument")
		}
		val, ok := args[0].(float64)
		if !ok {
			return nil, fmt.Errorf("tan function expects numeric argument")
		}
		return math.Tan(val), nil
	}

	// Logarithmic functions
	functions["log"] = func(args ...interface{}) (interface{}, error) {
		if len(args) != 1 {
			return nil, fmt.Errorf("log function expects 1 argument")
		}
		val, ok := args[0].(float64)
		if !ok {
			return nil, fmt.Errorf("log function expects numeric argument")
		}
		if val <= 0 {
			return nil, fmt.Errorf("log function domain error: argument must be positive")
		}
		return math.Log10(val), nil
	}

	functions["ln"] = func(args ...interface{}) (interface{}, error) {
		if len(args) != 1 {
			return nil, fmt.Errorf("ln function expects 1 argument")
		}
		val, ok := args[0].(float64)
		if !ok {
			return nil, fmt.Errorf("ln function expects numeric argument")
		}
		if val <= 0 {
			return nil, fmt.Errorf("ln function domain error: argument must be positive")
		}
		return math.Log(val), nil
	}

	// Square root function
	functions["sqrt"] = func(args ...interface{}) (interface{}, error) {
		if len(args) != 1 {
			return nil, fmt.Errorf("sqrt function expects 1 argument")
		}
		val, ok := args[0].(float64)
		if !ok {
			return nil, fmt.Errorf("sqrt function expects numeric argument")
		}
		if val < 0 {
			return nil, fmt.Errorf("sqrt function domain error: argument must be non-negative")
		}
		return math.Sqrt(val), nil
	}

	// Power function
	functions["pow"] = func(args ...interface{}) (interface{}, error) {
		if len(args) != 2 {
			return nil, fmt.Errorf("pow function expects 2 arguments")
		}
		base, ok1 := args[0].(float64)
		exponent, ok2 := args[1].(float64)
		if !ok1 || !ok2 {
			return nil, fmt.Errorf("pow function expects numeric arguments")
		}
		if base == 0 && exponent < 0 {
			return nil, fmt.Errorf("pow function domain error: 0 raised to negative power")
		}
		result := math.Pow(base, exponent)
		if math.IsNaN(result) || math.IsInf(result, 0) {
			return nil, fmt.Errorf("pow function resulted in invalid value")
		}
		return result, nil
	}

	// Absolute value function
	functions["abs"] = func(args ...interface{}) (interface{}, error) {
		if len(args) != 1 {
			return nil, fmt.Errorf("abs function expects 1 argument")
		}
		val, ok := args[0].(float64)
		if !ok {
			return nil, fmt.Errorf("abs function expects numeric argument")
		}
		return math.Abs(val), nil
	}

	// Exponential function
	functions["exp"] = func(args ...interface{}) (interface{}, error) {
		if len(args) != 1 {
			return nil, fmt.Errorf("exp function expects 1 argument")
		}
		val, ok := args[0].(float64)
		if !ok {
			return nil, fmt.Errorf("exp function expects numeric argument")
		}
		if val > 700 {
			return nil, fmt.Errorf("exp function overflow: value too large")
		}
		return math.Exp(val), nil
	}

	// Additional inverse trigonometric functions
	functions["asin"] = func(args ...interface{}) (interface{}, error) {
		if len(args) != 1 {
			return nil, fmt.Errorf("asin function expects 1 argument")
		}
		val, ok := args[0].(float64)
		if !ok {
			return nil, fmt.Errorf("asin function expects numeric argument")
		}
		if val < -1 || val > 1 {
			return nil, fmt.Errorf("asin function domain error: argument must be between -1 and 1")
		}
		return math.Asin(val), nil
	}

	functions["acos"] = func(args ...interface{}) (interface{}, error) {
		if len(args) != 1 {
			return nil, fmt.Errorf("acos function expects 1 argument")
		}
		val, ok := args[0].(float64)
		if !ok {
			return nil, fmt.Errorf("acos function expects numeric argument")
		}
		if val < -1 || val > 1 {
			return nil, fmt.Errorf("acos function domain error: argument must be between -1 and 1")
		}
		return math.Acos(val), nil
	}

	functions["atan"] = func(args ...interface{}) (interface{}, error) {
		if len(args) != 1 {
			return nil, fmt.Errorf("atan function expects 1 argument")
		}
		val, ok := args[0].(float64)
		if !ok {
			return nil, fmt.Errorf("atan function expects numeric argument")
		}
		return math.Atan(val), nil
	}

	return functions
}

// preprocessExpression handles basic expression preprocessing
func (ec *ExpressionCalculator) preprocessExpression(expr string) string {
	// No longer need complex preprocessing since we're using custom functions
	// Just return the expression as-is
	return expr
}


// isValidVariableName checks if a variable name is valid
func (ec *ExpressionCalculator) isValidVariableName(name string) bool {
	if len(name) == 0 {
		return false
	}
	
	// First character must be a letter
	if !((name[0] >= 'a' && name[0] <= 'z') || (name[0] >= 'A' && name[0] <= 'Z')) {
		return false
	}
	
	// Remaining characters can be letters, digits, or underscore
	for i := 1; i < len(name); i++ {
		char := name[i]
		if !((char >= 'a' && char <= 'z') || (char >= 'A' && char <= 'Z') || 
			 (char >= '0' && char <= '9') || char == '_') {
			return false
		}
	}
	
	// Check against reserved words
	reserved := []string{"pi", "e", "PI", "E", "sin", "cos", "tan", "asin", "acos", "atan", "log", "ln", "abs", "pow", "exp", "sqrt"}
	for _, res := range reserved {
		if strings.ToLower(name) == strings.ToLower(res) {
			return false
		}
	}
	
	return true
}

// GetSupportedFunctions returns a list of supported mathematical functions
func (ec *ExpressionCalculator) GetSupportedFunctions() []string {
	return []string{
		"sin(x)", "cos(x)", "tan(x)",
		"asin(x)", "acos(x)", "atan(x)",
		"log(x)", "ln(x)", "abs(x)",
		"sqrt(x)", "pow(x, y)", "exp(x)",
		"pi", "e", // constants
	}
}

// GetSupportedOperators returns a list of supported operators
func (ec *ExpressionCalculator) GetSupportedOperators() []string {
	return []string{
		"+", "-", "*", "/", "^", "%",
		"(", ")", // grouping
		"<", ">", "<=", ">=", "==", "!=", // comparison
		"&&", "||", "!", // logical
	}
}

// ValidateExpression performs basic validation of the expression
func (ec *ExpressionCalculator) ValidateExpression(expression string) error {
	if strings.TrimSpace(expression) == "" {
		return fmt.Errorf("expression cannot be empty")
	}
	
	// Check for balanced parentheses
	openCount := 0
	for _, char := range expression {
		if char == '(' {
			openCount++
		} else if char == ')' {
			openCount--
			if openCount < 0 {
				return fmt.Errorf("unmatched closing parenthesis")
			}
		}
	}
	if openCount != 0 {
		return fmt.Errorf("unmatched opening parenthesis")
	}
	
	// Check for consecutive operators (basic check)
	operators := []string{"++", "--", "**", "//", "^^"}
	for _, op := range operators {
		if strings.Contains(expression, op) {
			return fmt.Errorf("invalid consecutive operators: %s", op)
		}
	}
	
	return nil
}

// ExtractVariables extracts variable names from an expression
func (ec *ExpressionCalculator) ExtractVariables(expression string) ([]string, error) {
	// This is a simplified variable extraction
	// In a production system, you'd want more sophisticated parsing
	
	expr, err := govaluate.NewEvaluableExpression(expression)
	if err != nil {
		return nil, fmt.Errorf("invalid expression: %v", err)
	}
	
	// Try to evaluate with empty parameters to find missing variables
	_, err = expr.Evaluate(map[string]interface{}{
		"pi": math.Pi,
		"e":  math.E,
		"PI": math.Pi,
		"E":  math.E,
	})
	
	if err != nil {
		// Parse the error message to extract variable names
		// This is a simplified approach
		errStr := err.Error()
		if strings.Contains(errStr, "No parameter") {
			// Extract variable name from error message
			// This would need more robust implementation
			return []string{}, fmt.Errorf("cannot extract variables automatically: %v", err)
		}
	}
	
	return []string{}, nil
}