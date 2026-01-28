package calculator

import (
    "fmt"
    "math"
    "regexp"
    "sort"
    "strconv"
    "strings"

    "calculator-server/internal/types"
    "github.com/Knetic/govaluate"
)

const (
    // MaxExpArgument is the maximum argument value for exp function to prevent overflow
    // e^700 ≈ 1.01e+304, approaching float64 max (~1.8e+308)
    MaxExpArgument = 700.0

    // MaxFactorialArgument is the maximum argument for factorial function to prevent overflow
    // 20! = 2.43e+18, which fits in float64, but 21! would exceed practical limits
    MaxFactorialArgument = 20
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
        if val > MaxExpArgument {
            return nil, fmt.Errorf("exp function overflow: value too large")
        }
        return math.Exp(val), nil
    }

    // Factorial function
    functions["factorial"] = func(args ...interface{}) (interface{}, error) {
        if len(args) != 1 {
            return nil, fmt.Errorf("factorial function expects 1 argument")
        }
        val, ok := args[0].(float64)
        if !ok {
            return nil, fmt.Errorf("factorial function expects numeric argument")
        }

        // Check for negative numbers
        if val < 0 {
            return nil, fmt.Errorf("factorial function domain error: argument must be non-negative")
        }

        // Check if input is an integer (within floating point precision)
        intVal := int(val)
        if val != float64(intVal) {
            return nil, fmt.Errorf("factorial function domain error: argument must be an integer")
        }

        // Prevent overflow by limiting to reasonable range
        if intVal > MaxFactorialArgument {
            return nil, fmt.Errorf("factorial function overflow: argument must be ≤ %d", MaxFactorialArgument)
        }

        // Calculate factorial
        result := 1.0
        for i := 2; i <= intVal; i++ {
            result *= float64(i)
        }

        return result, nil
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
    reserved := []string{"pi", "e", "PI", "E", "sin", "cos", "tan", "asin", "acos", "atan", "log", "ln", "abs", "pow", "exp", "sqrt", "factorial"}
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
        "sqrt(x)", "pow(x, y)", "exp(x)", "factorial(x)",
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
    if strings.TrimSpace(expression) == "" {
        return []string{}, nil
    }

    // Validate expression first
    if err := ec.ValidateExpression(expression); err != nil {
        return nil, fmt.Errorf("invalid expression: %v", err)
    }

    // Define built-in constants and function names that should be excluded
    builtInIdentifiers := map[string]bool{
        "pi": true, "PI": true, "e": true, "E": true,
        "sin": true, "cos": true, "tan": true, "asin": true, "acos": true, "atan": true,
        "log": true, "ln": true, "abs": true, "sqrt": true, "pow": true, "exp": true, "factorial": true,
    }

    // Regular expression to match variable names
    // Variables must start with a letter or underscore, followed by letters, numbers, or underscores
    variablePattern := regexp.MustCompile(`\b[a-zA-Z_][a-zA-Z0-9_]*\b`)

    // Find all potential variable matches
    matches := variablePattern.FindAllString(expression, -1)

    // Use a map to ensure uniqueness
    variableMap := make(map[string]bool)

    for _, match := range matches {
        // Skip built-in identifiers
        if builtInIdentifiers[match] {
            continue
        }

        // Skip numeric literals (though regex shouldn't match them)
        if isNumeric(match) {
            continue
        }

        variableMap[match] = true
    }

    // Convert map to sorted slice
    var variables []string
    for variable := range variableMap {
        variables = append(variables, variable)
    }

    // Sort for consistent output
    sort.Strings(variables)

    return variables, nil
}

// isNumeric checks if a string represents a number
func isNumeric(s string) bool {
    _, err := strconv.ParseFloat(s, 64)
    return err == nil
}
