package tests

import (
	"math"
	"testing"

	"calculator-server/internal/calculator"
	"calculator-server/internal/types"
)

func TestBasicCalculator_Add(t *testing.T) {
	calc := calculator.NewBasicCalculator()

	testCases := []struct {
		name      string
		request   types.BasicMathRequest
		expected  float64
		shouldErr bool
	}{
		{
			name: "Add two positive numbers",
			request: types.BasicMathRequest{
				Operation: "add",
				Operands:  []float64{5, 3},
				Precision: 2,
			},
			expected:  8,
			shouldErr: false,
		},
		{
			name: "Add multiple numbers",
			request: types.BasicMathRequest{
				Operation: "add",
				Operands:  []float64{1, 2, 3, 4, 5},
				Precision: 2,
			},
			expected:  15,
			shouldErr: false,
		},
		{
			name: "Add with decimals",
			request: types.BasicMathRequest{
				Operation: "add",
				Operands:  []float64{1.5, 2.7},
				Precision: 2,
			},
			expected:  4.2,
			shouldErr: false,
		},
		{
			name: "Add with negative numbers",
			request: types.BasicMathRequest{
				Operation: "add",
				Operands:  []float64{-5, 3},
				Precision: 2,
			},
			expected:  -2,
			shouldErr: false,
		},
		{
			name: "Add with insufficient operands",
			request: types.BasicMathRequest{
				Operation: "add",
				Operands:  []float64{5},
				Precision: 2,
			},
			expected:  0,
			shouldErr: true,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result, err := calc.Calculate(tc.request)

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

			if math.Abs(result.Result-tc.expected) > 0.01 {
				t.Errorf("Expected %f, got %f", tc.expected, result.Result)
			}
		})
	}
}

func TestBasicCalculator_Subtract(t *testing.T) {
	calc := calculator.NewBasicCalculator()

	testCases := []struct {
		name      string
		request   types.BasicMathRequest
		expected  float64
		shouldErr bool
	}{
		{
			name: "Subtract two positive numbers",
			request: types.BasicMathRequest{
				Operation: "subtract",
				Operands:  []float64{10, 3},
				Precision: 2,
			},
			expected:  7,
			shouldErr: false,
		},
		{
			name: "Subtract with negative result",
			request: types.BasicMathRequest{
				Operation: "subtract",
				Operands:  []float64{3, 10},
				Precision: 2,
			},
			expected:  -7,
			shouldErr: false,
		},
		{
			name: "Subtract multiple numbers",
			request: types.BasicMathRequest{
				Operation: "subtract",
				Operands:  []float64{20, 5, 3, 2},
				Precision: 2,
			},
			expected:  10,
			shouldErr: false,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result, err := calc.Calculate(tc.request)

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

			if math.Abs(result.Result-tc.expected) > 0.01 {
				t.Errorf("Expected %f, got %f", tc.expected, result.Result)
			}
		})
	}
}

func TestBasicCalculator_Multiply(t *testing.T) {
	calc := calculator.NewBasicCalculator()

	testCases := []struct {
		name      string
		request   types.BasicMathRequest
		expected  float64
		shouldErr bool
	}{
		{
			name: "Multiply two positive numbers",
			request: types.BasicMathRequest{
				Operation: "multiply",
				Operands:  []float64{5, 3},
				Precision: 2,
			},
			expected:  15,
			shouldErr: false,
		},
		{
			name: "Multiply by zero",
			request: types.BasicMathRequest{
				Operation: "multiply",
				Operands:  []float64{5, 0},
				Precision: 2,
			},
			expected:  0,
			shouldErr: false,
		},
		{
			name: "Multiply multiple numbers",
			request: types.BasicMathRequest{
				Operation: "multiply",
				Operands:  []float64{2, 3, 4},
				Precision: 2,
			},
			expected:  24,
			shouldErr: false,
		},
		{
			name: "Multiply with decimals",
			request: types.BasicMathRequest{
				Operation: "multiply",
				Operands:  []float64{2.5, 4},
				Precision: 2,
			},
			expected:  10,
			shouldErr: false,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result, err := calc.Calculate(tc.request)

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

			if math.Abs(result.Result-tc.expected) > 0.01 {
				t.Errorf("Expected %f, got %f", tc.expected, result.Result)
			}
		})
	}
}

func TestBasicCalculator_Divide(t *testing.T) {
	calc := calculator.NewBasicCalculator()

	testCases := []struct {
		name      string
		request   types.BasicMathRequest
		expected  float64
		shouldErr bool
	}{
		{
			name: "Divide two positive numbers",
			request: types.BasicMathRequest{
				Operation: "divide",
				Operands:  []float64{15, 3},
				Precision: 2,
			},
			expected:  5,
			shouldErr: false,
		},
		{
			name: "Divide with decimal result",
			request: types.BasicMathRequest{
				Operation: "divide",
				Operands:  []float64{10, 3},
				Precision: 2,
			},
			expected:  3.33,
			shouldErr: false,
		},
		{
			name: "Divide by zero",
			request: types.BasicMathRequest{
				Operation: "divide",
				Operands:  []float64{10, 0},
				Precision: 2,
			},
			expected:  0,
			shouldErr: true,
		},
		{
			name: "Divide multiple numbers",
			request: types.BasicMathRequest{
				Operation: "divide",
				Operands:  []float64{100, 5, 2},
				Precision: 2,
			},
			expected:  10,
			shouldErr: false,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result, err := calc.Calculate(tc.request)

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

			if math.Abs(result.Result-tc.expected) > 0.01 {
				t.Errorf("Expected %f, got %f", tc.expected, result.Result)
			}
		})
	}
}

func TestBasicCalculator_ValidateOperands(t *testing.T) {
	calc := calculator.NewBasicCalculator()

	testCases := []struct {
		name      string
		operands  []float64
		shouldErr bool
	}{
		{
			name:      "Valid operands",
			operands:  []float64{1, 2, 3},
			shouldErr: false,
		},
		{
			name:      "Empty operands",
			operands:  []float64{},
			shouldErr: true,
		},
		{
			name:      "Single operand",
			operands:  []float64{5},
			shouldErr: true,
		},
		{
			name:      "NaN operand",
			operands:  []float64{1, math.NaN(), 3},
			shouldErr: true,
		},
		{
			name:      "Infinite operand",
			operands:  []float64{1, math.Inf(1), 3},
			shouldErr: true,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			err := calc.ValidateOperands(tc.operands)

			if tc.shouldErr && err == nil {
				t.Errorf("Expected error, but got none")
			} else if !tc.shouldErr && err != nil {
				t.Errorf("Unexpected error: %v", err)
			}
		})
	}
}

func TestBasicCalculator_ValidateOperation(t *testing.T) {
	calc := calculator.NewBasicCalculator()

	testCases := []struct {
		name      string
		operation string
		shouldErr bool
	}{
		{
			name:      "Valid operation - add",
			operation: "add",
			shouldErr: false,
		},
		{
			name:      "Valid operation - subtract",
			operation: "subtract",
			shouldErr: false,
		},
		{
			name:      "Valid operation - multiply",
			operation: "multiply",
			shouldErr: false,
		},
		{
			name:      "Valid operation - divide",
			operation: "divide",
			shouldErr: false,
		},
		{
			name:      "Invalid operation",
			operation: "power",
			shouldErr: true,
		},
		{
			name:      "Empty operation",
			operation: "",
			shouldErr: true,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			err := calc.ValidateOperation(tc.operation)

			if tc.shouldErr && err == nil {
				t.Errorf("Expected error, but got none")
			} else if !tc.shouldErr && err != nil {
				t.Errorf("Unexpected error: %v", err)
			}
		})
	}
}

func TestBasicCalculator_Precision(t *testing.T) {
	calc := calculator.NewBasicCalculator()

	testCases := []struct {
		name     string
		request  types.BasicMathRequest
		expected float64
	}{
		{
			name: "Precision 0",
			request: types.BasicMathRequest{
				Operation: "divide",
				Operands:  []float64{10, 3},
				Precision: 0,
			},
			expected: 3,
		},
		{
			name: "Precision 1",
			request: types.BasicMathRequest{
				Operation: "divide",
				Operands:  []float64{10, 3},
				Precision: 1,
			},
			expected: 3.3,
		},
		{
			name: "Precision 3",
			request: types.BasicMathRequest{
				Operation: "divide",
				Operands:  []float64{10, 3},
				Precision: 3,
			},
			expected: 3.333,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result, err := calc.Calculate(tc.request)

			if err != nil {
				t.Errorf("Unexpected error: %v", err)
				return
			}

			if math.Abs(result.Result-tc.expected) > 0.0001 {
				t.Errorf("Expected %f, got %f", tc.expected, result.Result)
			}
		})
	}
}
