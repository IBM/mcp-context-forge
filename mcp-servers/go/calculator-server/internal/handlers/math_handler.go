package handlers

import (
    "encoding/json"
    "fmt"

    "calculator-server/internal/calculator"
    "calculator-server/internal/types"
)

type MathHandler struct {
    basicCalc     *calculator.BasicCalculator
    advancedCalc  *calculator.AdvancedCalculator
    exprCalc      *calculator.ExpressionCalculator
    unitConverter *calculator.UnitConverter
}

func NewMathHandler() *MathHandler {
    return &MathHandler{
        basicCalc:     calculator.NewBasicCalculator(),
        advancedCalc:  calculator.NewAdvancedCalculator(),
        exprCalc:      calculator.NewExpressionCalculator(),
        unitConverter: calculator.NewUnitConverter(),
    }
}

func (mh *MathHandler) HandleBasicMath(params map[string]interface{}) (interface{}, error) {
    // Convert params to BasicMathRequest
    paramsJSON, err := json.Marshal(params)
    if err != nil {
        return nil, fmt.Errorf("failed to marshal parameters: %v", err)
    }

    var req types.BasicMathRequest
    if err := json.Unmarshal(paramsJSON, &req); err != nil {
        return nil, fmt.Errorf("invalid parameters for basic math: %v", err)
    }

    // Validate input
    if err := mh.basicCalc.ValidateOperation(req.Operation); err != nil {
        return nil, err
    }
    if err := mh.basicCalc.ValidateOperands(req.Operands); err != nil {
        return nil, err
    }

    // Perform calculation
    result, err := mh.basicCalc.Calculate(req)
    if err != nil {
        return nil, err
    }

    return result, nil
}

func (mh *MathHandler) HandleAdvancedMath(params map[string]interface{}) (interface{}, error) {
    // Convert params to AdvancedMathRequest
    paramsJSON, err := json.Marshal(params)
    if err != nil {
        return nil, fmt.Errorf("failed to marshal parameters: %v", err)
    }

    var req types.AdvancedMathRequest
    if err := json.Unmarshal(paramsJSON, &req); err != nil {
        return nil, fmt.Errorf("invalid parameters for advanced math: %v", err)
    }

    // Validate input
    if err := mh.advancedCalc.ValidateFunction(req.Function); err != nil {
        return nil, err
    }
    if err := mh.advancedCalc.ValidateValue(req.Value); err != nil {
        return nil, err
    }
    if err := mh.advancedCalc.ValidateUnit(req.Unit); err != nil {
        return nil, err
    }

    // Special validation for pow function
    if req.Function == "pow" && req.Exponent == 0 {
        // Note: we allow exponent=0 as a valid mathematical operation (result=1 for non-zero base)
        // But provide helpful info about the function
        _ = req.Exponent // Just acknowledge the parameter exists
    }

    // Perform calculation
    result, err := mh.advancedCalc.Calculate(req)
    if err != nil {
        return nil, err
    }

    return result, nil
}

func (mh *MathHandler) HandleExpressionEval(params map[string]interface{}) (interface{}, error) {
    // Convert params to ExpressionRequest
    paramsJSON, err := json.Marshal(params)
    if err != nil {
        return nil, fmt.Errorf("failed to marshal parameters: %v", err)
    }

    var req types.ExpressionRequest
    if err := json.Unmarshal(paramsJSON, &req); err != nil {
        return nil, fmt.Errorf("invalid parameters for expression evaluation: %v", err)
    }

    // Validate expression
    if err := mh.exprCalc.ValidateExpression(req.Expression); err != nil {
        return nil, err
    }

    // Evaluate expression
    result, err := mh.exprCalc.Evaluate(req)
    if err != nil {
        return nil, err
    }

    // Add additional information
    response := map[string]interface{}{
        "result":              result.Result,
        "expression":          req.Expression,
        "variables":           req.Variables,
        "supported_functions": mh.exprCalc.GetSupportedFunctions(),
        "supported_operators": mh.exprCalc.GetSupportedOperators(),
    }

    return response, nil
}

// Additional helper methods

func (mh *MathHandler) GetBasicMathOperations() []string {
    return []string{"add", "subtract", "multiply", "divide"}
}

func (mh *MathHandler) GetAdvancedMathFunctions() []string {
    return []string{
        "sin", "cos", "tan", "asin", "acos", "atan",
        "log", "log10", "ln", "sqrt", "abs", "factorial", "exp", "pow",
    }
}

func (mh *MathHandler) GetSupportedUnits() []string {
    return []string{"radians", "degrees"}
}

func (mh *MathHandler) GetSupportedUnitCategories() []string {
    return mh.unitConverter.GetSupportedCategories()
}

// Batch operation handlers

func (mh *MathHandler) HandleBasicMathBatch(operations []map[string]interface{}) ([]interface{}, error) {
    results := make([]interface{}, len(operations))

    for i, operation := range operations {
        result, err := mh.HandleBasicMath(operation)
        if err != nil {
            results[i] = map[string]interface{}{
                "error":           err.Error(),
                "operation_index": i,
            }
        } else {
            results[i] = result
        }
    }

    return results, nil
}

func (mh *MathHandler) HandleAdvancedMathBatch(operations []map[string]interface{}) ([]interface{}, error) {
    results := make([]interface{}, len(operations))

    for i, operation := range operations {
        result, err := mh.HandleAdvancedMath(operation)
        if err != nil {
            results[i] = map[string]interface{}{
                "error":           err.Error(),
                "operation_index": i,
            }
        } else {
            results[i] = result
        }
    }

    return results, nil
}

func (mh *MathHandler) HandleUnitConversion(params map[string]interface{}) (interface{}, error) {
    // Convert params to UnitConversionRequest
    paramsJSON, err := json.Marshal(params)
    if err != nil {
        return nil, fmt.Errorf("failed to marshal parameters: %v", err)
    }

    var req types.UnitConversionRequest
    if err := json.Unmarshal(paramsJSON, &req); err != nil {
        return nil, fmt.Errorf("invalid parameters for unit conversion: %v", err)
    }

    // Validate category
    supportedCategories := mh.unitConverter.GetSupportedCategories()
    isCategorySupported := false
    for _, cat := range supportedCategories {
        if req.Category == cat {
            isCategorySupported = true
            break
        }
    }
    if !isCategorySupported {
        return nil, fmt.Errorf("unsupported category: %s. Supported categories: %v", req.Category, supportedCategories)
    }

    // Validate units for the category
    supportedUnits, err := mh.unitConverter.GetSupportedUnits(req.Category)
    if err != nil {
        return nil, err
    }

    isFromUnitSupported := false
    isToUnitSupported := false
    for _, unit := range supportedUnits {
        if req.FromUnit == unit {
            isFromUnitSupported = true
        }
        if req.ToUnit == unit {
            isToUnitSupported = true
        }
    }

    if !isFromUnitSupported {
        return nil, fmt.Errorf("unsupported from unit: %s. Supported units for %s: %v", req.FromUnit, req.Category, supportedUnits)
    }
    if !isToUnitSupported {
        return nil, fmt.Errorf("unsupported to unit: %s. Supported units for %s: %v", req.ToUnit, req.Category, supportedUnits)
    }

    // Perform conversion
    result, err := mh.unitConverter.Convert(req)
    if err != nil {
        return nil, err
    }

    // Add additional information
    response := map[string]interface{}{
        "original_value":       req.Value,
        "original_unit":        req.FromUnit,
        "converted_value":      result.Result,
        "converted_unit":       result.Unit,
        "category":             req.Category,
        "supported_units":      supportedUnits,
        "supported_categories": supportedCategories,
    }

    // Add conversion factor if possible
    if req.Category != "temperature" { // Temperature conversions are not linear
        factor, err := mh.unitConverter.GetConversionFactor(req.FromUnit, req.ToUnit, req.Category)
        if err == nil {
            response["conversion_factor"] = factor
        }
    }

    return response, nil
}
