package calculator

import (
    "fmt"
    "math"

    "calculator-server/internal/types"
)

type AdvancedCalculator struct{}

func NewAdvancedCalculator() *AdvancedCalculator {
    return &AdvancedCalculator{}
}

func (ac *AdvancedCalculator) Calculate(req types.AdvancedMathRequest) (types.CalculationResult, error) {
    var result float64
    var err error

    // Convert degrees to radians for trigonometric functions if needed
    value := req.Value
    if ac.isTrigFunction(req.Function) && req.Unit == "degrees" {
        value = ac.degreesToRadians(value)
    }

    switch req.Function {
    case "sin":
        result = math.Sin(value)
    case "cos":
        result = math.Cos(value)
    case "tan":
        result = math.Tan(value)
    case "asin":
        if value < -1 || value > 1 {
            return types.CalculationResult{}, fmt.Errorf("asin domain error: value must be between -1 and 1")
        }
        result = math.Asin(value)
        if req.Unit == "degrees" {
            result = ac.radiansToDegrees(result)
        }
    case "acos":
        if value < -1 || value > 1 {
            return types.CalculationResult{}, fmt.Errorf("acos domain error: value must be between -1 and 1")
        }
        result = math.Acos(value)
        if req.Unit == "degrees" {
            result = ac.radiansToDegrees(result)
        }
    case "atan":
        result = math.Atan(value)
        if req.Unit == "degrees" {
            result = ac.radiansToDegrees(result)
        }
    case "log":
        if value <= 0 {
            return types.CalculationResult{}, fmt.Errorf("logarithm domain error: value must be positive")
        }
        result = math.Log10(value)
    case "log10":
        if value <= 0 {
            return types.CalculationResult{}, fmt.Errorf("log10 domain error: value must be positive")
        }
        result = math.Log10(value)
    case "ln":
        if value <= 0 {
            return types.CalculationResult{}, fmt.Errorf("natural logarithm domain error: value must be positive")
        }
        result = math.Log(value)
    case "sqrt":
        if value < 0 {
            return types.CalculationResult{}, fmt.Errorf("square root domain error: value must be non-negative")
        }
        result = math.Sqrt(value)
    case "abs":
        result = math.Abs(value)
    case "factorial":
        if value < 0 {
            return types.CalculationResult{}, fmt.Errorf("factorial domain error: value must be non-negative")
        }
        if value != math.Floor(value) {
            return types.CalculationResult{}, fmt.Errorf("factorial domain error: value must be an integer")
        }
        if value > 170 {
            return types.CalculationResult{}, fmt.Errorf("factorial overflow: value too large (max 170)")
        }
        result, err = ac.factorial(int(value))
        if err != nil {
            return types.CalculationResult{}, err
        }
    case "exp":
        if value > 700 {
            return types.CalculationResult{}, fmt.Errorf("exponential overflow: value too large")
        }
        result = math.Exp(value)
    case "pow":
        // For power function, we use the existing Power method
        exponent := req.Exponent
        var err error
        result, err = ac.Power(value, exponent)
        if err != nil {
            return types.CalculationResult{}, err
        }
    default:
        return types.CalculationResult{}, fmt.Errorf("unsupported function: %s", req.Function)
    }

    // Check for NaN or Inf results
    if math.IsNaN(result) {
        return types.CalculationResult{}, fmt.Errorf("calculation resulted in NaN")
    }
    if math.IsInf(result, 0) {
        return types.CalculationResult{}, fmt.Errorf("calculation resulted in infinity")
    }

    return types.CalculationResult{
        Result: result,
    }, nil
}

// Power function with two parameters
func (ac *AdvancedCalculator) Power(base, exponent float64) (float64, error) {
    if base == 0 && exponent < 0 {
        return 0, fmt.Errorf("division by zero: 0 raised to negative power")
    }
    if base < 0 && exponent != math.Floor(exponent) {
        return 0, fmt.Errorf("complex result: negative base with non-integer exponent")
    }

    result := math.Pow(base, exponent)
    if math.IsNaN(result) {
        return 0, fmt.Errorf("calculation resulted in NaN")
    }
    if math.IsInf(result, 0) {
        return 0, fmt.Errorf("calculation resulted in infinity")
    }

    return result, nil
}

func (ac *AdvancedCalculator) factorial(n int) (float64, error) {
    if n < 0 {
        return 0, fmt.Errorf("factorial of negative number")
    }
    if n == 0 || n == 1 {
        return 1, nil
    }

    result := 1.0
    for i := 2; i <= n; i++ {
        result *= float64(i)
    }

    return result, nil
}

func (ac *AdvancedCalculator) degreesToRadians(degrees float64) float64 {
    return degrees * (math.Pi / 180)
}

func (ac *AdvancedCalculator) radiansToDegrees(radians float64) float64 {
    return radians * (180 / math.Pi)
}

func (ac *AdvancedCalculator) isTrigFunction(function string) bool {
    trigFunctions := []string{"sin", "cos", "tan"}
    for _, trigFunc := range trigFunctions {
        if function == trigFunc {
            return true
        }
    }
    return false
}

// Validation functions
func (ac *AdvancedCalculator) ValidateFunction(function string) error {
    validFunctions := []string{
        "sin", "cos", "tan", "asin", "acos", "atan",
        "log", "log10", "ln", "sqrt", "abs", "factorial", "exp", "pow",
    }

    for _, validFunc := range validFunctions {
        if function == validFunc {
            return nil
        }
    }

    return fmt.Errorf("invalid function: %s. Valid functions are: %v", function, validFunctions)
}

func (ac *AdvancedCalculator) ValidateValue(value float64) error {
    if math.IsNaN(value) {
        return fmt.Errorf("value is NaN")
    }
    if math.IsInf(value, 0) {
        return fmt.Errorf("value is infinite")
    }
    return nil
}

func (ac *AdvancedCalculator) ValidateUnit(unit string) error {
    if unit == "" {
        return nil // Empty unit is valid (defaults to radians)
    }

    validUnits := []string{"radians", "degrees"}
    for _, validUnit := range validUnits {
        if unit == validUnit {
            return nil
        }
    }

    return fmt.Errorf("invalid unit: %s. Valid units are: %v", unit, validUnits)
}
