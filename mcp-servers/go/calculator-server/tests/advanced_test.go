package tests

import (
	"math"
	"testing"
	
	"calculator-server/internal/calculator"
	"calculator-server/internal/types"
)

func TestAdvancedCalculator_TrigonometricFunctions(t *testing.T) {
	calc := calculator.NewAdvancedCalculator()
	
	testCases := []struct {
		name      string
		request   types.AdvancedMathRequest
		expected  float64
		tolerance float64
		shouldErr bool
	}{
		{
			name: "Sin(0) in radians",
			request: types.AdvancedMathRequest{
				Function: "sin",
				Value:    0,
				Unit:     "radians",
			},
			expected:  0,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Sin(π/2) in radians",
			request: types.AdvancedMathRequest{
				Function: "sin",
				Value:    math.Pi / 2,
				Unit:     "radians",
			},
			expected:  1,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Sin(90) in degrees",
			request: types.AdvancedMathRequest{
				Function: "sin",
				Value:    90,
				Unit:     "degrees",
			},
			expected:  1,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Cos(0) in radians",
			request: types.AdvancedMathRequest{
				Function: "cos",
				Value:    0,
				Unit:     "radians",
			},
			expected:  1,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Cos(π) in radians",
			request: types.AdvancedMathRequest{
				Function: "cos",
				Value:    math.Pi,
				Unit:     "radians",
			},
			expected:  -1,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Tan(0) in radians",
			request: types.AdvancedMathRequest{
				Function: "tan",
				Value:    0,
				Unit:     "radians",
			},
			expected:  0,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Tan(π/4) in radians",
			request: types.AdvancedMathRequest{
				Function: "tan",
				Value:    math.Pi / 4,
				Unit:     "radians",
			},
			expected:  1,
			tolerance: 0.0001,
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
			
			if math.Abs(result.Result-tc.expected) > tc.tolerance {
				t.Errorf("Expected %f, got %f (tolerance: %f)", tc.expected, result.Result, tc.tolerance)
			}
		})
	}
}

func TestAdvancedCalculator_InverseTrigonometricFunctions(t *testing.T) {
	calc := calculator.NewAdvancedCalculator()
	
	testCases := []struct {
		name      string
		request   types.AdvancedMathRequest
		expected  float64
		tolerance float64
		shouldErr bool
	}{
		{
			name: "Asin(0) in radians",
			request: types.AdvancedMathRequest{
				Function: "asin",
				Value:    0,
				Unit:     "radians",
			},
			expected:  0,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Asin(1) in radians",
			request: types.AdvancedMathRequest{
				Function: "asin",
				Value:    1,
				Unit:     "radians",
			},
			expected:  math.Pi / 2,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Asin(1) in degrees",
			request: types.AdvancedMathRequest{
				Function: "asin",
				Value:    1,
				Unit:     "degrees",
			},
			expected:  90,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Asin(2) - domain error",
			request: types.AdvancedMathRequest{
				Function: "asin",
				Value:    2,
				Unit:     "radians",
			},
			expected:  0,
			tolerance: 0,
			shouldErr: true,
		},
		{
			name: "Acos(1) in radians",
			request: types.AdvancedMathRequest{
				Function: "acos",
				Value:    1,
				Unit:     "radians",
			},
			expected:  0,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Atan(0) in radians",
			request: types.AdvancedMathRequest{
				Function: "atan",
				Value:    0,
				Unit:     "radians",
			},
			expected:  0,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Atan(1) in radians",
			request: types.AdvancedMathRequest{
				Function: "atan",
				Value:    1,
				Unit:     "radians",
			},
			expected:  math.Pi / 4,
			tolerance: 0.0001,
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
			
			if math.Abs(result.Result-tc.expected) > tc.tolerance {
				t.Errorf("Expected %f, got %f (tolerance: %f)", tc.expected, result.Result, tc.tolerance)
			}
		})
	}
}

func TestAdvancedCalculator_LogarithmicFunctions(t *testing.T) {
	calc := calculator.NewAdvancedCalculator()
	
	testCases := []struct {
		name      string
		request   types.AdvancedMathRequest
		expected  float64
		tolerance float64
		shouldErr bool
	}{
		{
			name: "Log10(10)",
			request: types.AdvancedMathRequest{
				Function: "log10",
				Value:    10,
			},
			expected:  1,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Log10(100)",
			request: types.AdvancedMathRequest{
				Function: "log10",
				Value:    100,
			},
			expected:  2,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Log10(1)",
			request: types.AdvancedMathRequest{
				Function: "log10",
				Value:    1,
			},
			expected:  0,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Log10(0) - domain error",
			request: types.AdvancedMathRequest{
				Function: "log10",
				Value:    0,
			},
			expected:  0,
			tolerance: 0,
			shouldErr: true,
		},
		{
			name: "Ln(e)",
			request: types.AdvancedMathRequest{
				Function: "ln",
				Value:    math.E,
			},
			expected:  1,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Ln(1)",
			request: types.AdvancedMathRequest{
				Function: "ln",
				Value:    1,
			},
			expected:  0,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Ln(-1) - domain error",
			request: types.AdvancedMathRequest{
				Function: "ln",
				Value:    -1,
			},
			expected:  0,
			tolerance: 0,
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
			
			if math.Abs(result.Result-tc.expected) > tc.tolerance {
				t.Errorf("Expected %f, got %f (tolerance: %f)", tc.expected, result.Result, tc.tolerance)
			}
		})
	}
}

func TestAdvancedCalculator_OtherFunctions(t *testing.T) {
	calc := calculator.NewAdvancedCalculator()
	
	testCases := []struct {
		name      string
		request   types.AdvancedMathRequest
		expected  float64
		tolerance float64
		shouldErr bool
	}{
		{
			name: "Sqrt(4)",
			request: types.AdvancedMathRequest{
				Function: "sqrt",
				Value:    4,
			},
			expected:  2,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Sqrt(0)",
			request: types.AdvancedMathRequest{
				Function: "sqrt",
				Value:    0,
			},
			expected:  0,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Sqrt(-1) - domain error",
			request: types.AdvancedMathRequest{
				Function: "sqrt",
				Value:    -1,
			},
			expected:  0,
			tolerance: 0,
			shouldErr: true,
		},
		{
			name: "Abs(5)",
			request: types.AdvancedMathRequest{
				Function: "abs",
				Value:    5,
			},
			expected:  5,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Abs(-5)",
			request: types.AdvancedMathRequest{
				Function: "abs",
				Value:    -5,
			},
			expected:  5,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Abs(0)",
			request: types.AdvancedMathRequest{
				Function: "abs",
				Value:    0,
			},
			expected:  0,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Factorial(5)",
			request: types.AdvancedMathRequest{
				Function: "factorial",
				Value:    5,
			},
			expected:  120,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Factorial(0)",
			request: types.AdvancedMathRequest{
				Function: "factorial",
				Value:    0,
			},
			expected:  1,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Factorial(-1) - domain error",
			request: types.AdvancedMathRequest{
				Function: "factorial",
				Value:    -1,
			},
			expected:  0,
			tolerance: 0,
			shouldErr: true,
		},
		{
			name: "Factorial(3.5) - domain error",
			request: types.AdvancedMathRequest{
				Function: "factorial",
				Value:    3.5,
			},
			expected:  0,
			tolerance: 0,
			shouldErr: true,
		},
		{
			name: "Exp(0)",
			request: types.AdvancedMathRequest{
				Function: "exp",
				Value:    0,
			},
			expected:  1,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name: "Exp(1)",
			request: types.AdvancedMathRequest{
				Function: "exp",
				Value:    1,
			},
			expected:  math.E,
			tolerance: 0.0001,
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
			
			if math.Abs(result.Result-tc.expected) > tc.tolerance {
				t.Errorf("Expected %f, got %f (tolerance: %f)", tc.expected, result.Result, tc.tolerance)
			}
		})
	}
}

func TestAdvancedCalculator_PowerFunction(t *testing.T) {
	calc := calculator.NewAdvancedCalculator()
	
	testCases := []struct {
		name      string
		base      float64
		exponent  float64
		expected  float64
		tolerance float64
		shouldErr bool
	}{
		{
			name:      "Power(2, 3)",
			base:      2,
			exponent:  3,
			expected:  8,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name:      "Power(5, 0)",
			base:      5,
			exponent:  0,
			expected:  1,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name:      "Power(4, 0.5)",
			base:      4,
			exponent:  0.5,
			expected:  2,
			tolerance: 0.0001,
			shouldErr: false,
		},
		{
			name:      "Power(0, -1) - domain error",
			base:      0,
			exponent:  -1,
			expected:  0,
			tolerance: 0,
			shouldErr: true,
		},
		{
			name:      "Power(-2, 0.5) - domain error",
			base:      -2,
			exponent:  0.5,
			expected:  0,
			tolerance: 0,
			shouldErr: true,
		},
	}
	
	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result, err := calc.Power(tc.base, tc.exponent)
			
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
			
			if math.Abs(result-tc.expected) > tc.tolerance {
				t.Errorf("Expected %f, got %f (tolerance: %f)", tc.expected, result, tc.tolerance)
			}
		})
	}
}

func TestAdvancedCalculator_Validation(t *testing.T) {
	calc := calculator.NewAdvancedCalculator()
	
	// Test function validation
	t.Run("ValidateFunction", func(t *testing.T) {
		validFunctions := []string{"sin", "cos", "tan", "asin", "acos", "atan", "log", "log10", "ln", "sqrt", "abs", "factorial", "exp", "pow"}
		
		for _, fn := range validFunctions {
			if err := calc.ValidateFunction(fn); err != nil {
				t.Errorf("Valid function %s rejected: %v", fn, err)
			}
		}
		
		invalidFunctions := []string{"invalid", "", "sine", "cosine"}
		for _, fn := range invalidFunctions {
			if err := calc.ValidateFunction(fn); err == nil {
				t.Errorf("Invalid function %s accepted", fn)
			}
		}
	})
	
	// Test value validation
	t.Run("ValidateValue", func(t *testing.T) {
		validValues := []float64{0, 1, -1, 3.14159, 100, -100}
		
		for _, val := range validValues {
			if err := calc.ValidateValue(val); err != nil {
				t.Errorf("Valid value %f rejected: %v", val, err)
			}
		}
		
		invalidValues := []float64{math.NaN(), math.Inf(1), math.Inf(-1)}
		for _, val := range invalidValues {
			if err := calc.ValidateValue(val); err == nil {
				t.Errorf("Invalid value %f accepted", val)
			}
		}
	})
	
	// Test unit validation
	t.Run("ValidateUnit", func(t *testing.T) {
		validUnits := []string{"", "radians", "degrees"}
		
		for _, unit := range validUnits {
			if err := calc.ValidateUnit(unit); err != nil {
				t.Errorf("Valid unit '%s' rejected: %v", unit, err)
			}
		}
		
		invalidUnits := []string{"invalid", "grads", "turns"}
		for _, unit := range invalidUnits {
			if err := calc.ValidateUnit(unit); err == nil {
				t.Errorf("Invalid unit '%s' accepted", unit)
			}
		}
	})
}