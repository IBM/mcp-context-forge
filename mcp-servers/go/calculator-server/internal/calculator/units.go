package calculator

import (
	"fmt"
	"math"

	"calculator-server/internal/types"
)

type UnitConverter struct {
	conversions map[string]map[string]map[string]float64
}

func NewUnitConverter() *UnitConverter {
	uc := &UnitConverter{}
	uc.initializeConversions()
	return uc
}

func (uc *UnitConverter) Convert(req types.UnitConversionRequest) (types.CalculationResult, error) {
	if err := uc.validateRequest(req); err != nil {
		return types.CalculationResult{}, err
	}

	var result float64
	var err error

	switch req.Category {
	case "length":
		result, err = uc.convertLength(req.Value, req.FromUnit, req.ToUnit)
	case "weight":
		result, err = uc.convertWeight(req.Value, req.FromUnit, req.ToUnit)
	case "temperature":
		result, err = uc.convertTemperature(req.Value, req.FromUnit, req.ToUnit)
	case "volume":
		result, err = uc.convertVolume(req.Value, req.FromUnit, req.ToUnit)
	case "area":
		result, err = uc.convertArea(req.Value, req.FromUnit, req.ToUnit)
	default:
		return types.CalculationResult{}, fmt.Errorf("unsupported category: %s", req.Category)
	}

	if err != nil {
		return types.CalculationResult{}, err
	}

	return types.CalculationResult{
		Result: result,
		Unit:   req.ToUnit,
	}, nil
}

func (uc *UnitConverter) initializeConversions() {
	uc.conversions = make(map[string]map[string]map[string]float64)

	// Length conversions (to meters)
	uc.conversions["length"] = map[string]map[string]float64{
		"to_base": {
			"mm":  0.001,
			"cm":  0.01,
			"m":   1.0,
			"km":  1000.0,
			"in":  0.0254,
			"ft":  0.3048,
			"yd":  0.9144,
			"mi":  1609.344,
			"mil": 0.0000254,
			"μm":  0.000001,
			"nm":  0.000000001,
		},
	}

	// Weight conversions (to grams)
	uc.conversions["weight"] = map[string]map[string]float64{
		"to_base": {
			"mg":  0.001,
			"g":   1.0,
			"kg":  1000.0,
			"t":   1000000.0,
			"oz":  28.3495,
			"lb":  453.592,
			"st":  6350.29, // stone
			"ton": 907185,  // US ton
		},
	}

	// Volume conversions (to liters)
	uc.conversions["volume"] = map[string]map[string]float64{
		"to_base": {
			"ml":    0.001,
			"cl":    0.01,
			"dl":    0.1,
			"l":     1.0,
			"kl":    1000.0,
			"fl_oz": 0.0295735,  // US fluid ounce
			"cup":   0.236588,   // US cup
			"pt":    0.473176,   // US pint
			"qt":    0.946353,   // US quart
			"gal":   3.78541,    // US gallon
			"tsp":   0.00492892, // US teaspoon
			"tbsp":  0.0147868,  // US tablespoon
			"bbl":   158.987,    // barrel
		},
	}

	// Area conversions (to square meters)
	uc.conversions["area"] = map[string]map[string]float64{
		"to_base": {
			"mm2":  0.000001,
			"cm2":  0.0001,
			"m2":   1.0,
			"km2":  1000000.0,
			"in2":  0.00064516,
			"ft2":  0.092903,
			"yd2":  0.836127,
			"mi2":  2589988.11,
			"acre": 4046.86,
			"ha":   10000.0, // hectare
		},
	}
}

func (uc *UnitConverter) convertLength(value float64, fromUnit, toUnit string) (float64, error) {
	return uc.convertGeneric(value, fromUnit, toUnit, "length")
}

func (uc *UnitConverter) convertWeight(value float64, fromUnit, toUnit string) (float64, error) {
	return uc.convertGeneric(value, fromUnit, toUnit, "weight")
}

func (uc *UnitConverter) convertVolume(value float64, fromUnit, toUnit string) (float64, error) {
	return uc.convertGeneric(value, fromUnit, toUnit, "volume")
}

func (uc *UnitConverter) convertArea(value float64, fromUnit, toUnit string) (float64, error) {
	return uc.convertGeneric(value, fromUnit, toUnit, "area")
}

func (uc *UnitConverter) convertGeneric(value float64, fromUnit, toUnit string, category string) (float64, error) {
	if fromUnit == toUnit {
		return value, nil
	}

	conversions, exists := uc.conversions[category]
	if !exists {
		return 0, fmt.Errorf("category not supported: %s", category)
	}

	toBase := conversions["to_base"]

	fromFactor, fromExists := toBase[fromUnit]
	toFactor, toExists := toBase[toUnit]

	if !fromExists {
		return 0, fmt.Errorf("unsupported unit: %s", fromUnit)
	}
	if !toExists {
		return 0, fmt.Errorf("unsupported unit: %s", toUnit)
	}

	// Convert to base unit, then to target unit
	baseValue := value * fromFactor
	result := baseValue / toFactor

	return result, nil
}

func (uc *UnitConverter) convertTemperature(value float64, fromUnit, toUnit string) (float64, error) {
	if fromUnit == toUnit {
		return value, nil
	}

	// Convert to Celsius first
	var celsius float64
	switch fromUnit {
	case "C":
		celsius = value
	case "F":
		celsius = (value - 32) * 5 / 9
	case "K":
		celsius = value - 273.15
	case "R": // Rankine
		celsius = (value - 491.67) * 5 / 9
	default:
		return 0, fmt.Errorf("unsupported temperature unit: %s", fromUnit)
	}

	// Convert from Celsius to target unit
	var result float64
	switch toUnit {
	case "C":
		result = celsius
	case "F":
		result = celsius*9/5 + 32
	case "K":
		if celsius < -273.15 {
			return 0, fmt.Errorf("temperature below absolute zero")
		}
		result = celsius + 273.15
	case "R": // Rankine
		if celsius < -273.15 {
			return 0, fmt.Errorf("temperature below absolute zero")
		}
		result = (celsius + 273.15) * 9 / 5
	default:
		return 0, fmt.Errorf("unsupported temperature unit: %s", toUnit)
	}

	return result, nil
}

func (uc *UnitConverter) validateRequest(req types.UnitConversionRequest) error {
	if math.IsNaN(req.Value) {
		return fmt.Errorf("value cannot be NaN")
	}
	if math.IsInf(req.Value, 0) {
		return fmt.Errorf("value cannot be infinite")
	}

	if req.FromUnit == "" {
		return fmt.Errorf("fromUnit cannot be empty")
	}
	if req.ToUnit == "" {
		return fmt.Errorf("toUnit cannot be empty")
	}
	if req.Category == "" {
		return fmt.Errorf("category cannot be empty")
	}

	// Validate category
	supportedCategories := []string{"length", "weight", "temperature", "volume", "area"}
	categoryValid := false
	for _, cat := range supportedCategories {
		if req.Category == cat {
			categoryValid = true
			break
		}
	}
	if !categoryValid {
		return fmt.Errorf("unsupported category: %s", req.Category)
	}

	return nil
}

// GetSupportedUnits returns supported units for a given category
func (uc *UnitConverter) GetSupportedUnits(category string) ([]string, error) {
	switch category {
	case "length":
		return []string{"mm", "cm", "m", "km", "in", "ft", "yd", "mi", "mil", "μm", "nm"}, nil
	case "weight":
		return []string{"mg", "g", "kg", "t", "oz", "lb", "st", "ton"}, nil
	case "temperature":
		return []string{"C", "F", "K", "R"}, nil
	case "volume":
		return []string{"ml", "cl", "dl", "l", "kl", "fl_oz", "cup", "pt", "qt", "gal", "tsp", "tbsp", "bbl"}, nil
	case "area":
		return []string{"mm2", "cm2", "m2", "km2", "in2", "ft2", "yd2", "mi2", "acre", "ha"}, nil
	default:
		return nil, fmt.Errorf("unsupported category: %s", category)
	}
}

// GetSupportedCategories returns all supported conversion categories
func (uc *UnitConverter) GetSupportedCategories() []string {
	return []string{"length", "weight", "temperature", "volume", "area"}
}

// ConvertMultiple converts multiple values at once
func (uc *UnitConverter) ConvertMultiple(values []float64, fromUnit, toUnit, category string) ([]float64, error) {
	results := make([]float64, len(values))

	for i, value := range values {
		req := types.UnitConversionRequest{
			Value:    value,
			FromUnit: fromUnit,
			ToUnit:   toUnit,
			Category: category,
		}

		result, err := uc.Convert(req)
		if err != nil {
			return nil, fmt.Errorf("error converting value at index %d: %v", i, err)
		}

		results[i] = result.Result
	}

	return results, nil
}

// GetConversionFactor returns the conversion factor between two units
func (uc *UnitConverter) GetConversionFactor(fromUnit, toUnit, category string) (float64, error) {
	result, err := uc.convertGeneric(1.0, fromUnit, toUnit, category)
	if err != nil {
		// Try temperature conversion if generic conversion fails
		if category == "temperature" {
			// Temperature conversion is not linear, so we can't provide a simple factor
			return 0, fmt.Errorf("temperature conversions don't have linear conversion factors")
		}
		return 0, err
	}
	return result, nil
}
