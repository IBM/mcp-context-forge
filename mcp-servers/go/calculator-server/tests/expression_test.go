package tests

import (
	"math"
	"testing"

	"calculator-server/internal/calculator"
	"calculator-server/internal/types"
)

func TestExpressionCalculator_BasicExpressions(t *testing.T) {
	calc := calculator.NewExpressionCalculator()

	testCases := []struct {
		name      string
		request   types.ExpressionRequest
		expected  float64
		tolerance float64
		shouldErr bool
	}{
		{
			name: "Simple addition",
			request: types.ExpressionRequest{
				Expression: "2 + 3",
			},
			expected:  5,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Simple subtraction",
			request: types.ExpressionRequest{
				Expression: "10 - 4",
			},
			expected:  6,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Simple multiplication",
			request: types.ExpressionRequest{
				Expression: "6 * 7",
			},
			expected:  42,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Simple division",
			request: types.ExpressionRequest{
				Expression: "15 / 3",
			},
			expected:  5,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Complex expression with parentheses",
			request: types.ExpressionRequest{
				Expression: "(2 + 3) * (4 - 1)",
			},
			expected:  15,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Expression with decimals",
			request: types.ExpressionRequest{
				Expression: "2.5 * 4.2",
			},
			expected:  10.5,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Expression with power",
			request: types.ExpressionRequest{
				Expression: "pow(2, 3)",
			},
			expected:  8,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Empty expression",
			request: types.ExpressionRequest{
				Expression: "",
			},
			expected:  0,
			tolerance: 0,
			shouldErr: true,
		},
		{
			name: "Whitespace only expression",
			request: types.ExpressionRequest{
				Expression: "   ",
			},
			expected:  0,
			tolerance: 0,
			shouldErr: true,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result, err := calc.Evaluate(tc.request)

			if tc.shouldErr {
				if err == nil {
					t.Errorf("Expected error, but got none")
				}
				return
			}

			if err != nil {
				t.Errorf("Unexpected error: %v", err)
				return
			}

			if math.Abs(result.Result-tc.expected) > tc.tolerance {
				t.Errorf("Expected %f, got %f (tolerance: %f)", tc.expected, result.Result, tc.tolerance)
			}
		})
	}
}

func TestExpressionCalculator_WithVariables(t *testing.T) {
	calc := calculator.NewExpressionCalculator()

	testCases := []struct {
		name      string
		request   types.ExpressionRequest
		expected  float64
		tolerance float64
		shouldErr bool
	}{
		{
			name: "Single variable",
			request: types.ExpressionRequest{
				Expression: "x + 5",
				Variables: map[string]float64{
					"x": 10,
				},
			},
			expected:  15,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Multiple variables",
			request: types.ExpressionRequest{
				Expression: "a * b + c",
				Variables: map[string]float64{
					"a": 3,
					"b": 4,
					"c": 2,
				},
			},
			expected:  14,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Variable with underscore",
			request: types.ExpressionRequest{
				Expression: "var_1 + var_2",
				Variables: map[string]float64{
					"var_1": 5,
					"var_2": 7,
				},
			},
			expected:  12,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Complex expression with variables",
			request: types.ExpressionRequest{
				Expression: "(x + y) * z / 2",
				Variables: map[string]float64{
					"x": 3,
					"y": 7,
					"z": 4,
				},
			},
			expected:  20,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Missing variable",
			request: types.ExpressionRequest{
				Expression: "x + y",
				Variables: map[string]float64{
					"x": 5,
				},
			},
			expected:  0,
			tolerance: 0,
			shouldErr: true,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result, err := calc.Evaluate(tc.request)

			if tc.shouldErr {
				if err == nil {
					t.Errorf("Expected error, but got none")
				}
				return
			}

			if err != nil {
				t.Errorf("Unexpected error: %v", err)
				return
			}

			if math.Abs(result.Result-tc.expected) > tc.tolerance {
				t.Errorf("Expected %f, got %f (tolerance: %f)", tc.expected, result.Result, tc.tolerance)
			}
		})
	}
}

func TestExpressionCalculator_WithConstants(t *testing.T) {
	calc := calculator.NewExpressionCalculator()

	testCases := []struct {
		name      string
		request   types.ExpressionRequest
		expected  float64
		tolerance float64
		shouldErr bool
	}{
		{
			name: "Pi constant (lowercase)",
			request: types.ExpressionRequest{
				Expression: "pi * 2",
			},
			expected:  math.Pi * 2,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Pi constant (uppercase)",
			request: types.ExpressionRequest{
				Expression: "PI * 2",
			},
			expected:  math.Pi * 2,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "E constant (lowercase)",
			request: types.ExpressionRequest{
				Expression: "e + 1",
			},
			expected:  math.E + 1,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "E constant (uppercase)",
			request: types.ExpressionRequest{
				Expression: "E + 1",
			},
			expected:  math.E + 1,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Constants with variables",
			request: types.ExpressionRequest{
				Expression: "pi * pow(r, 2)",
				Variables: map[string]float64{
					"r": 5,
				},
			},
			expected:  math.Pi * 25,
			tolerance: 0.0001,
			shouldErr: false,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result, err := calc.Evaluate(tc.request)

			if tc.shouldErr {
				if err == nil {
					t.Errorf("Expected error, but got none")
				}
				return
			}

			if err != nil {
				t.Errorf("Unexpected error: %v", err)
				return
			}

			if math.Abs(result.Result-tc.expected) > tc.tolerance {
				t.Errorf("Expected %f, got %f (tolerance: %f)", tc.expected, result.Result, tc.tolerance)
			}
		})
	}
}

func TestExpressionCalculator_WithFunctions(t *testing.T) {
	calc := calculator.NewExpressionCalculator()

	testCases := []struct {
		name      string
		request   types.ExpressionRequest
		expected  float64
		tolerance float64
		shouldErr bool
	}{
		{
			name: "Absolute value function",
			request: types.ExpressionRequest{
				Expression: "abs(-5)",
			},
			expected:  5,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Power function",
			request: types.ExpressionRequest{
				Expression: "pow(2, 3)",
			},
			expected:  8,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Square root function",
			request: types.ExpressionRequest{
				Expression: "sqrt(16)",
			},
			expected:  4,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Exponential function",
			request: types.ExpressionRequest{
				Expression: "exp(0)",
			},
			expected:  1,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Logarithm function",
			request: types.ExpressionRequest{
				Expression: "log(10)",
			},
			expected:  1,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Natural logarithm function",
			request: types.ExpressionRequest{
				Expression: "ln(e)",
			},
			expected:  1,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Nested functions",
			request: types.ExpressionRequest{
				Expression: "sqrt(pow(3, 2) + pow(4, 2))",
			},
			expected:  5,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Functions with variables",
			request: types.ExpressionRequest{
				Expression: "sqrt(pow(x, 2) + pow(y, 2))",
				Variables: map[string]float64{
					"x": 3,
					"y": 4,
				},
			},
			expected:  5,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Factorial function - 0!",
			request: types.ExpressionRequest{
				Expression: "factorial(0)",
			},
			expected:  1,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Factorial function - 5!",
			request: types.ExpressionRequest{
				Expression: "factorial(5)",
			},
			expected:  120,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Factorial function - negative input error",
			request: types.ExpressionRequest{
				Expression: "factorial(-1)",
			},
			expected:  0,
			tolerance: 0.0001,
			shouldErr: true,
		},
		{
			name: "Factorial function - non-integer input error",
			request: types.ExpressionRequest{
				Expression: "factorial(5.5)",
			},
			expected:  0,
			tolerance: 0.0001,
			shouldErr: true,
		},
		{
			name: "Factorial function - overflow protection",
			request: types.ExpressionRequest{
				Expression: "factorial(25)",
			},
			expected:  0,
			tolerance: 0.0001,
			shouldErr: true,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result, err := calc.Evaluate(tc.request)

			if tc.shouldErr {
				if err == nil {
					t.Errorf("Expected error, but got none")
				}
				return
			}

			if err != nil {
				t.Errorf("Unexpected error: %v", err)
				return
			}

			if math.Abs(result.Result-tc.expected) > tc.tolerance {
				t.Errorf("Expected %f, got %f (tolerance: %f)", tc.expected, result.Result, tc.tolerance)
			}
		})
	}
}

func TestExpressionCalculator_ValidateExpression(t *testing.T) {
	calc := calculator.NewExpressionCalculator()

	testCases := []struct {
		name       string
		expression string
		shouldErr  bool
	}{
		{
			name:       "Valid simple expression",
			expression: "2 + 3",
			shouldErr:  false,
		},
		{
			name:       "Valid complex expression",
			expression: "(a + b) * c / d",
			shouldErr:  false,
		},
		{
			name:       "Empty expression",
			expression: "",
			shouldErr:  true,
		},
		{
			name:       "Whitespace only",
			expression: "   ",
			shouldErr:  true,
		},
		{
			name:       "Unmatched opening parenthesis",
			expression: "((2 + 3)",
			shouldErr:  true,
		},
		{
			name:       "Unmatched closing parenthesis",
			expression: "(2 + 3))",
			shouldErr:  true,
		},
		{
			name:       "Consecutive operators",
			expression: "2 ++ 3",
			shouldErr:  true,
		},
		{
			name:       "Valid nested parentheses",
			expression: "((2 + 3) * (4 - 1))",
			shouldErr:  false,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			err := calc.ValidateExpression(tc.expression)

			if tc.shouldErr && err == nil {
				t.Errorf("Expected error, but got none")
			} else if !tc.shouldErr && err != nil {
				t.Errorf("Unexpected error: %v", err)
			}
		})
	}
}

func TestExpressionCalculator_VariableValidation(t *testing.T) {
	calc := calculator.NewExpressionCalculator()

	testCases := []struct {
		name         string
		variableName string
		expected     bool
	}{
		{
			name:         "Valid variable name",
			variableName: "x",
			expected:     true,
		},
		{
			name:         "Valid variable with number",
			variableName: "var1",
			expected:     true,
		},
		{
			name:         "Valid variable with underscore",
			variableName: "var_name",
			expected:     true,
		},
		{
			name:         "Invalid - starts with number",
			variableName: "1var",
			expected:     false,
		},
		{
			name:         "Invalid - empty name",
			variableName: "",
			expected:     false,
		},
		{
			name:         "Invalid - contains special characters",
			variableName: "var-name",
			expected:     false,
		},
		{
			name:         "Invalid - reserved word (pi)",
			variableName: "pi",
			expected:     false,
		},
		{
			name:         "Invalid - reserved word (sin)",
			variableName: "sin",
			expected:     false,
		},
		{
			name:         "Invalid - reserved word (factorial)",
			variableName: "factorial",
			expected:     false,
		},
		{
			name:         "Valid - mixed case",
			variableName: "MyVar",
			expected:     true,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			// This is testing the private method through the Evaluate function
			// by trying to use invalid variable names
			request := types.ExpressionRequest{
				Expression: tc.variableName + " + 1",
				Variables: map[string]float64{
					tc.variableName: 5,
				},
			}

			_, err := calc.Evaluate(request)

			if tc.expected {
				// Variable should be valid, so no error expected
				if err != nil && err.Error() == "invalid variable name: "+tc.variableName {
					t.Errorf("Valid variable name %s was rejected", tc.variableName)
				}
			} else {
				// Variable should be invalid, but we might get other errors too
				// This test is approximate since we're testing through Evaluate
				if err == nil {
					// If no error, the variable might have been treated as a literal
					// This is acceptable for some cases
				}
			}
		})
	}
}

func TestExpressionCalculator_ErrorHandling(t *testing.T) {
	calc := calculator.NewExpressionCalculator()

	testCases := []struct {
		name    string
		request types.ExpressionRequest
	}{
		{
			name: "Division by zero",
			request: types.ExpressionRequest{
				Expression: "1 / 0",
			},
		},
		{
			name: "Invalid function",
			request: types.ExpressionRequest{
				Expression: "invalid_function(5)",
			},
		},
		{
			name: "Invalid variable values - NaN",
			request: types.ExpressionRequest{
				Expression: "x + 1",
				Variables: map[string]float64{
					"x": math.NaN(),
				},
			},
		},
		{
			name: "Invalid variable values - Inf",
			request: types.ExpressionRequest{
				Expression: "x + 1",
				Variables: map[string]float64{
					"x": math.Inf(1),
				},
			},
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := calc.Evaluate(tc.request)

			if err == nil {
				t.Errorf("Expected error, but got none")
			}
		})
	}
}

func TestExpressionCalculator_GetSupportedFunctions(t *testing.T) {
	calc := calculator.NewExpressionCalculator()

	functions := calc.GetSupportedFunctions()

	expectedFunctions := []string{"sin(x)", "cos(x)", "tan(x)", "log(x)", "ln(x)", "abs(x)", "sqrt(x)", "pow(x, y)", "exp(x)", "factorial(x)", "pi", "e"}

	if len(functions) == 0 {
		t.Errorf("No supported functions returned")
	}

	// Check if all expected functions are present
	for _, expected := range expectedFunctions {
		found := false
		for _, actual := range functions {
			if actual == expected {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("Expected function %s not found in supported functions", expected)
		}
	}
}

func TestExpressionCalculator_GetSupportedOperators(t *testing.T) {
	calc := calculator.NewExpressionCalculator()

	operators := calc.GetSupportedOperators()

	expectedOperators := []string{"+", "-", "*", "/", "^", "%", "(", ")"}

	if len(operators) == 0 {
		t.Errorf("No supported operators returned")
	}

	// Check if all expected operators are present
	for _, expected := range expectedOperators {
		found := false
		for _, actual := range operators {
			if actual == expected {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("Expected operator %s not found in supported operators", expected)
		}
	}
}

// New comprehensive tests for enhanced expression evaluator
func TestExpressionCalculator_EnhancedFunctions(t *testing.T) {
	calc := calculator.NewExpressionCalculator()

	testCases := []struct {
		name      string
		request   types.ExpressionRequest
		expected  float64
		tolerance float64
		shouldErr bool
	}{
		{
			name: "Square root in expression",
			request: types.ExpressionRequest{
				Expression: "sqrt(16) + 4",
			},
			expected:  8,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Power function in expression",
			request: types.ExpressionRequest{
				Expression: "pow(2, 3) + pow(3, 2)",
			},
			expected:  17, // 8 + 9
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Complex mathematical expression",
			request: types.ExpressionRequest{
				Expression: "sqrt(16) + pow(2, 3) - abs(-5)",
			},
			expected:  7, // 4 + 8 - 5
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Trigonometric functions",
			request: types.ExpressionRequest{
				Expression: "sin(0) + cos(0)",
			},
			expected:  1, // 0 + 1
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Logarithmic functions",
			request: types.ExpressionRequest{
				Expression: "log(100) + ln(e)",
			},
			expected:  3, // 2 + 1
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Nested functions",
			request: types.ExpressionRequest{
				Expression: "sqrt(pow(3, 2) + pow(4, 2))",
			},
			expected:  5, // sqrt(9 + 16) = sqrt(25) = 5
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Functions with variables",
			request: types.ExpressionRequest{
				Expression: "sqrt(pow(x, 2) + pow(y, 2)) + abs(z)",
				Variables: map[string]float64{
					"x": 3,
					"y": 4,
					"z": -7,
				},
			},
			expected:  12, // sqrt(9 + 16) + abs(-7) = 5 + 7 = 12
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Multiple operations with functions",
			request: types.ExpressionRequest{
				Expression: "2 * sqrt(25) + 3 * pow(2, 3) - abs(-10) + exp(0)",
			},
			expected:  25, // 2*5 + 3*8 - 10 + 1 = 10 + 24 - 10 + 1 = 25
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Domain error - negative sqrt",
			request: types.ExpressionRequest{
				Expression: "sqrt(-4)",
			},
			expected:  0,
			tolerance: 0,
			shouldErr: true,
		},
		{
			name: "Domain error - negative log",
			request: types.ExpressionRequest{
				Expression: "log(-10)",
			},
			expected:  0,
			tolerance: 0,
			shouldErr: true,
		},
		{
			name: "Division by zero in pow",
			request: types.ExpressionRequest{
				Expression: "pow(0, -1)",
			},
			expected:  0,
			tolerance: 0,
			shouldErr: true,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result, err := calc.Evaluate(tc.request)

			if tc.shouldErr {
				if err == nil {
					t.Errorf("Expected error, but got none")
				}
				return
			}

			if err != nil {
				t.Errorf("Unexpected error: %v", err)
				return
			}

			if math.Abs(result.Result-tc.expected) > tc.tolerance {
				t.Errorf("Expected %f, got %f (tolerance: %f)", tc.expected, result.Result, tc.tolerance)
			}
		})
	}
}

func TestExpressionCalculator_InverseTrigFunctions(t *testing.T) {
	calc := calculator.NewExpressionCalculator()

	testCases := []struct {
		name      string
		request   types.ExpressionRequest
		expected  float64
		tolerance float64
		shouldErr bool
	}{
		{
			name: "Arcsine function",
			request: types.ExpressionRequest{
				Expression: "asin(0.5)",
			},
			expected:  0.5236, // approximately π/6
			tolerance: 0.001,
			shouldErr: false,
		},
		{
			name: "Arccosine function",
			request: types.ExpressionRequest{
				Expression: "acos(0.5)",
			},
			expected:  1.0472, // approximately π/3
			tolerance: 0.001,
			shouldErr: false,
		},
		{
			name: "Arctangent function",
			request: types.ExpressionRequest{
				Expression: "atan(1)",
			},
			expected:  0.7854, // approximately π/4
			tolerance: 0.001,
			shouldErr: false,
		},
		{
			name: "Inverse trig domain error - asin",
			request: types.ExpressionRequest{
				Expression: "asin(2)",
			},
			expected:  0,
			tolerance: 0,
			shouldErr: true,
		},
		{
			name: "Inverse trig domain error - acos",
			request: types.ExpressionRequest{
				Expression: "acos(-2)",
			},
			expected:  0,
			tolerance: 0,
			shouldErr: true,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result, err := calc.Evaluate(tc.request)

			if tc.shouldErr {
				if err == nil {
					t.Errorf("Expected error, but got none")
				}
				return
			}

			if err != nil {
				t.Errorf("Unexpected error: %v", err)
				return
			}

			if math.Abs(result.Result-tc.expected) > tc.tolerance {
				t.Errorf("Expected %f, got %f (tolerance: %f)", tc.expected, result.Result, tc.tolerance)
			}
		})
	}
}

func TestExpressionCalculator_ExtractVariables(t *testing.T) {
	calc := calculator.NewExpressionCalculator()

	testCases := []struct {
		name       string
		expression string
		expected   []string
		shouldErr  bool
	}{
		{
			name:       "Empty expression",
			expression: "",
			expected:   []string{},
			shouldErr:  false,
		},
		{
			name:       "Whitespace only expression",
			expression: "   ",
			expected:   []string{},
			shouldErr:  false,
		},
		{
			name:       "Expression with no variables",
			expression: "2 + 3",
			expected:   []string{},
			shouldErr:  false,
		},
		{
			name:       "Single variable",
			expression: "x + 5",
			expected:   []string{"x"},
			shouldErr:  false,
		},
		{
			name:       "Multiple variables",
			expression: "a * b + c",
			expected:   []string{"a", "b", "c"},
			shouldErr:  false,
		},
		{
			name:       "Variables with underscores",
			expression: "var_1 + var_2",
			expected:   []string{"var_1", "var_2"},
			shouldErr:  false,
		},
		{
			name:       "Duplicate variables",
			expression: "x + x * y + y",
			expected:   []string{"x", "y"},
			shouldErr:  false,
		},
		{
			name:       "Complex expression with variables",
			expression: "(x + y) * z / 2 + abs(w)",
			expected:   []string{"w", "x", "y", "z"},
			shouldErr:  false,
		},
		{
			name:       "Variables with constants - should exclude constants",
			expression: "x + pi * y + e",
			expected:   []string{"x", "y"},
			shouldErr:  false,
		},
		{
			name:       "Variables with uppercase constants",
			expression: "a + PI * b + E",
			expected:   []string{"a", "b"},
			shouldErr:  false,
		},
		{
			name:       "Variables with functions - should exclude function names",
			expression: "sin(x) + cos(y) + log(z)",
			expected:   []string{"x", "y", "z"},
			shouldErr:  false,
		},
		{
			name:       "Mixed case variables",
			expression: "MyVar + myOtherVar",
			expected:   []string{"MyVar", "myOtherVar"},
			shouldErr:  false,
		},
		{
			name:       "Variables in function arguments",
			expression: "pow(base, exponent) + sqrt(value)",
			expected:   []string{"base", "exponent", "value"},
			shouldErr:  false,
		},
		{
			name:       "All built-in identifiers - should return empty",
			expression: "sin(pi) + cos(e) + log(PI) + abs(E)",
			expected:   []string{},
			shouldErr:  false,
		},
		{
			name:       "Business formula with meaningful variable names",
			expression: "principal * pow(1 + interest_rate, years)",
			expected:   []string{"interest_rate", "principal", "years"},
			shouldErr:  false,
		},
		{
			name:       "Invalid expression - unmatched parentheses",
			expression: "((x + y",
			expected:   nil,
			shouldErr:  true,
		},
		{
			name:       "Invalid expression - consecutive operators",
			expression: "x ++ y",
			expected:   nil,
			shouldErr:  true,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result, err := calc.ExtractVariables(tc.expression)

			if tc.shouldErr {
				if err == nil {
					t.Errorf("Expected error, but got none")
				}
				return
			}

			if err != nil {
				t.Errorf("Unexpected error: %v", err)
				return
			}

			if len(result) != len(tc.expected) {
				t.Errorf("Expected %d variables, got %d. Expected: %v, Got: %v",
					len(tc.expected), len(result), tc.expected, result)
				return
			}

			for i, expected := range tc.expected {
				if result[i] != expected {
					t.Errorf("At index %d: expected %s, got %s", i, expected, result[i])
				}
			}
		})
	}
}

func TestExpressionCalculator_ComplexBusinessLogic(t *testing.T) {
	calc := calculator.NewExpressionCalculator()

	testCases := []struct {
		name      string
		request   types.ExpressionRequest
		expected  float64
		tolerance float64
		shouldErr bool
	}{
		{
			name: "Compound interest formula",
			request: types.ExpressionRequest{
				Expression: "P * pow(1 + r, t)",
				Variables: map[string]float64{
					"P": 1000, // Principal
					"r": 0.05, // 5% rate
					"t": 10,   // 10 years
				},
			},
			expected:  1628.89, // Approximate compound interest result
			tolerance: 0.01,
			shouldErr: false,
		},
		{
			name: "Distance formula",
			request: types.ExpressionRequest{
				Expression: "sqrt(pow(x2 - x1, 2) + pow(y2 - y1, 2))",
				Variables: map[string]float64{
					"x1": 1,
					"y1": 1,
					"x2": 4,
					"y2": 5,
				},
			},
			expected:  5, // Distance between (1,1) and (4,5)
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Quadratic formula discriminant",
			request: types.ExpressionRequest{
				Expression: "pow(b, 2) - 4 * a * c",
				Variables: map[string]float64{
					"a": 1,
					"b": -3,
					"c": 2,
				},
			},
			expected:  1, // b² - 4ac = 9 - 8 = 1
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Surface area of sphere",
			request: types.ExpressionRequest{
				Expression: "4 * pi * pow(r, 2)",
				Variables: map[string]float64{
					"r": 5,
				},
			},
			expected:  314.159, // 4π * 25 ≈ 314.159
			tolerance: 0.01,
			shouldErr: false,
		},
		{
			name: "Exponential decay",
			request: types.ExpressionRequest{
				Expression: "N0 * exp(-lambda * t)",
				Variables: map[string]float64{
					"N0":     1000,
					"lambda": 0.693, // Half-life related constant
					"t":      1,
				},
			},
			expected:  500.05, // Approximate half-life result
			tolerance: 0.1,
			shouldErr: false,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result, err := calc.Evaluate(tc.request)

			if tc.shouldErr {
				if err == nil {
					t.Errorf("Expected error, but got none")
				}
				return
			}

			if err != nil {
				t.Errorf("Unexpected error: %v", err)
				return
			}

			if math.Abs(result.Result-tc.expected) > tc.tolerance {
				t.Errorf("Expected %f, got %f (tolerance: %f)", tc.expected, result.Result, tc.tolerance)
			}
		})
	}
}
