package handlers

import (
	"encoding/json"
	"fmt"
	
	"calculator-server/internal/calculator"
	"calculator-server/internal/types"
)

type StatsHandler struct {
	statsCalc    *calculator.StatisticsCalculator
	unitConverter *calculator.UnitConverter
}

func NewStatsHandler() *StatsHandler {
	return &StatsHandler{
		statsCalc:     calculator.NewStatisticsCalculator(),
		unitConverter: calculator.NewUnitConverter(),
	}
}

func (sh *StatsHandler) HandleStatistics(params map[string]interface{}) (interface{}, error) {
	// Convert params to StatisticsRequest
	paramsJSON, err := json.Marshal(params)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal parameters: %v", err)
	}

	var req types.StatisticsRequest
	if err := json.Unmarshal(paramsJSON, &req); err != nil {
		return nil, fmt.Errorf("invalid parameters for statistics: %v", err)
	}

	// Validate input
	if len(req.Data) == 0 {
		return nil, fmt.Errorf("data cannot be empty")
	}

	// Check if operation is supported
	supportedOps := sh.statsCalc.GetSupportedOperations()
	isSupported := false
	for _, op := range supportedOps {
		if req.Operation == op {
			isSupported = true
			break
		}
	}
	if !isSupported {
		return nil, fmt.Errorf("unsupported operation: %s. Supported operations: %v", req.Operation, supportedOps)
	}

	// Perform calculation
	result, err := sh.statsCalc.Calculate(req)
	if err != nil {
		return nil, err
	}

	// Add additional information
	response := map[string]interface{}{
		"operation":            req.Operation,
		"result":               result.Result,
		"count":                result.Count,
		"data_preview":         sh.getDataPreview(req.Data),
		"supported_operations": supportedOps,
	}

	return response, nil
}

func (sh *StatsHandler) HandleUnitConversion(params map[string]interface{}) (interface{}, error) {
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
	supportedCategories := sh.unitConverter.GetSupportedCategories()
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
	supportedUnits, err := sh.unitConverter.GetSupportedUnits(req.Category)
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
	result, err := sh.unitConverter.Convert(req)
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
		factor, err := sh.unitConverter.GetConversionFactor(req.FromUnit, req.ToUnit, req.Category)
		if err == nil {
			response["conversion_factor"] = factor
		}
	}

	return response, nil
}

// Additional specialized statistics operations

func (sh *StatsHandler) HandleStatsSummary(params map[string]interface{}) (interface{}, error) {
	// Extract data from parameters
	dataInterface, exists := params["data"]
	if !exists {
		return nil, fmt.Errorf("data parameter is required")
	}

	// Convert to float64 slice
	data, err := sh.convertToFloatSlice(dataInterface)
	if err != nil {
		return nil, fmt.Errorf("invalid data format: %v", err)
	}

	if len(data) == 0 {
		return nil, fmt.Errorf("data cannot be empty")
	}

	// Get comprehensive summary
	summary, err := sh.statsCalc.Summary(data)
	if err != nil {
		return nil, err
	}

	// Add additional information
	response := map[string]interface{}{
		"summary":              summary,
		"data_preview":         sh.getDataPreview(data),
		"supported_operations": sh.statsCalc.GetSupportedOperations(),
	}

	return response, nil
}

func (sh *StatsHandler) HandlePercentileCalculation(params map[string]interface{}) (interface{}, error) {
	// Extract parameters
	dataInterface, exists := params["data"]
	if !exists {
		return nil, fmt.Errorf("data parameter is required")
	}

	percentileInterface, exists := params["percentile"]
	if !exists {
		return nil, fmt.Errorf("percentile parameter is required")
	}

	// Convert data
	data, err := sh.convertToFloatSlice(dataInterface)
	if err != nil {
		return nil, fmt.Errorf("invalid data format: %v", err)
	}

	// Convert percentile
	percentile, ok := percentileInterface.(float64)
	if !ok {
		return nil, fmt.Errorf("percentile must be a number")
	}

	// Calculate percentile
	result, err := sh.statsCalc.CalculatePercentile(data, percentile)
	if err != nil {
		return nil, err
	}

	response := map[string]interface{}{
		"percentile":       percentile,
		"value":            result,
		"data_count":       len(data),
		"data_preview":     sh.getDataPreview(data),
	}

	return response, nil
}

// Batch operations

func (sh *StatsHandler) HandleMultipleConversions(params map[string]interface{}) (interface{}, error) {
	// Extract parameters
	valuesInterface, exists := params["values"]
	if !exists {
		return nil, fmt.Errorf("values parameter is required")
	}

	fromUnit, exists := params["fromUnit"]
	if !exists {
		return nil, fmt.Errorf("fromUnit parameter is required")
	}

	toUnit, exists := params["toUnit"]
	if !exists {
		return nil, fmt.Errorf("toUnit parameter is required")
	}

	category, exists := params["category"]
	if !exists {
		return nil, fmt.Errorf("category parameter is required")
	}

	// Convert values
	values, err := sh.convertToFloatSlice(valuesInterface)
	if err != nil {
		return nil, fmt.Errorf("invalid values format: %v", err)
	}

	// Perform conversions
	results, err := sh.unitConverter.ConvertMultiple(values, fromUnit.(string), toUnit.(string), category.(string))
	if err != nil {
		return nil, err
	}

	response := map[string]interface{}{
		"original_values": values,
		"converted_values": results,
		"fromUnit": fromUnit,
		"toUnit": toUnit,
		"category": category,
		"count": len(values),
	}

	return response, nil
}

// Helper methods

func (sh *StatsHandler) convertToFloatSlice(data interface{}) ([]float64, error) {
	switch v := data.(type) {
	case []interface{}:
		result := make([]float64, len(v))
		for i, item := range v {
			if num, ok := item.(float64); ok {
				result[i] = num
			} else {
				return nil, fmt.Errorf("item at index %d is not a number", i)
			}
		}
		return result, nil
	case []float64:
		return v, nil
	default:
		return nil, fmt.Errorf("data must be an array of numbers")
	}
}

func (sh *StatsHandler) getDataPreview(data []float64) map[string]interface{} {
	preview := make(map[string]interface{})
	
	count := len(data)
	preview["count"] = count
	
	if count == 0 {
		return preview
	}

	// Show first few and last few elements
	previewSize := 3
	if count <= previewSize*2 {
		preview["values"] = data
	} else {
		preview["first"] = data[:previewSize]
		preview["last"] = data[count-previewSize:]
		preview["truncated"] = true
	}

	return preview
}

func (sh *StatsHandler) GetSupportedStatOperations() []string {
	return sh.statsCalc.GetSupportedOperations()
}

func (sh *StatsHandler) GetSupportedUnitCategories() []string {
	return sh.unitConverter.GetSupportedCategories()
}

func (sh *StatsHandler) GetSupportedUnitsForCategory(category string) ([]string, error) {
	return sh.unitConverter.GetSupportedUnits(category)
}