package calculator

import (
	"fmt"
	"math"
	"sort"

	"calculator-server/internal/types"
	"gonum.org/v1/gonum/stat"
)

type StatisticsCalculator struct{}

func NewStatisticsCalculator() *StatisticsCalculator {
	return &StatisticsCalculator{}
}

func (sc *StatisticsCalculator) Calculate(req types.StatisticsRequest) (types.StatisticsResult, error) {
	if len(req.Data) == 0 {
		return types.StatisticsResult{}, fmt.Errorf("data set cannot be empty")
	}

	// Validate data
	if err := sc.validateData(req.Data); err != nil {
		return types.StatisticsResult{}, err
	}

	var result interface{}
	var err error

	switch req.Operation {
	case "mean":
		result = sc.mean(req.Data)
	case "median":
		result = sc.median(req.Data)
	case "mode":
		result, err = sc.mode(req.Data)
		if err != nil {
			return types.StatisticsResult{}, err
		}
	case "std_dev":
		result = sc.standardDeviation(req.Data)
	case "variance":
		result = sc.variance(req.Data)
	case "percentile":
		// For percentile, we need an additional parameter
		// For now, we'll calculate common percentiles
		percentiles := sc.percentiles(req.Data, []float64{25, 50, 75, 90, 95, 99})
		result = percentiles
	default:
		return types.StatisticsResult{}, fmt.Errorf("unsupported operation: %s", req.Operation)
	}

	return types.StatisticsResult{
		Result: result,
		Count:  len(req.Data),
	}, nil
}

// CalculatePercentile calculates a specific percentile
func (sc *StatisticsCalculator) CalculatePercentile(data []float64, percentile float64) (float64, error) {
	if len(data) == 0 {
		return 0, fmt.Errorf("data set cannot be empty")
	}
	if percentile < 0 || percentile > 100 {
		return 0, fmt.Errorf("percentile must be between 0 and 100")
	}

	if err := sc.validateData(data); err != nil {
		return 0, err
	}

	// Create a copy and sort it
	sortedData := make([]float64, len(data))
	copy(sortedData, data)
	sort.Float64s(sortedData)

	return stat.Quantile(percentile/100.0, stat.Empirical, sortedData, nil), nil
}

func (sc *StatisticsCalculator) mean(data []float64) float64 {
	return stat.Mean(data, nil)
}

func (sc *StatisticsCalculator) median(data []float64) float64 {
	// Create a copy and sort it
	sortedData := make([]float64, len(data))
	copy(sortedData, data)
	sort.Float64s(sortedData)

	return stat.Quantile(0.5, stat.Empirical, sortedData, nil)
}

func (sc *StatisticsCalculator) mode(data []float64) (interface{}, error) {
	if len(data) == 0 {
		return nil, fmt.Errorf("cannot calculate mode of empty data set")
	}

	// Count frequency of each value
	frequency := make(map[float64]int)
	for _, value := range data {
		frequency[value]++
	}

	// Find maximum frequency
	maxFreq := 0
	for _, freq := range frequency {
		if freq > maxFreq {
			maxFreq = freq
		}
	}

	// If all values appear only once, there's no mode
	if maxFreq == 1 {
		return "No mode (all values appear once)", nil
	}

	// Collect all values with maximum frequency
	var modes []float64
	for value, freq := range frequency {
		if freq == maxFreq {
			modes = append(modes, value)
		}
	}

	// Sort modes for consistent output
	sort.Float64s(modes)

	// Return single mode or multiple modes
	if len(modes) == 1 {
		return modes[0], nil
	}

	return map[string]interface{}{
		"modes":     modes,
		"frequency": maxFreq,
		"type":      "multimodal",
	}, nil
}

func (sc *StatisticsCalculator) standardDeviation(data []float64) float64 {
	return stat.StdDev(data, nil)
}

func (sc *StatisticsCalculator) variance(data []float64) float64 {
	return stat.Variance(data, nil)
}

func (sc *StatisticsCalculator) percentiles(data []float64, percentiles []float64) map[string]float64 {
	result := make(map[string]float64)

	// Create a copy and sort it
	sortedData := make([]float64, len(data))
	copy(sortedData, data)
	sort.Float64s(sortedData)

	for _, p := range percentiles {
		result[fmt.Sprintf("P%.0f", p)] = stat.Quantile(p/100.0, stat.Empirical, sortedData, nil)
	}

	return result
}

// Additional statistical functions

func (sc *StatisticsCalculator) Range(data []float64) (float64, error) {
	if len(data) == 0 {
		return 0, fmt.Errorf("data set cannot be empty")
	}

	if err := sc.validateData(data); err != nil {
		return 0, err
	}

	min := data[0]
	max := data[0]

	for _, value := range data {
		if value < min {
			min = value
		}
		if value > max {
			max = value
		}
	}

	return max - min, nil
}

func (sc *StatisticsCalculator) Skewness(data []float64) (float64, error) {
	if len(data) < 3 {
		return 0, fmt.Errorf("skewness requires at least 3 data points")
	}

	if err := sc.validateData(data); err != nil {
		return 0, err
	}

	n := float64(len(data))
	mean := sc.mean(data)
	stdDev := sc.standardDeviation(data)

	if stdDev == 0 {
		return 0, fmt.Errorf("cannot calculate skewness: standard deviation is zero")
	}

	var sum float64
	for _, value := range data {
		sum += math.Pow((value-mean)/stdDev, 3)
	}

	return (n / ((n - 1) * (n - 2))) * sum, nil
}

func (sc *StatisticsCalculator) Kurtosis(data []float64) (float64, error) {
	if len(data) < 4 {
		return 0, fmt.Errorf("kurtosis requires at least 4 data points")
	}

	if err := sc.validateData(data); err != nil {
		return 0, err
	}

	n := float64(len(data))
	mean := sc.mean(data)
	stdDev := sc.standardDeviation(data)

	if stdDev == 0 {
		return 0, fmt.Errorf("cannot calculate kurtosis: standard deviation is zero")
	}

	var sum float64
	for _, value := range data {
		sum += math.Pow((value-mean)/stdDev, 4)
	}

	// Excess kurtosis (subtract 3 for normal distribution baseline)
	kurtosis := (n*(n+1))/((n-1)*(n-2)*(n-3))*sum - 3*(n-1)*(n-1)/((n-2)*(n-3))
	return kurtosis, nil
}

func (sc *StatisticsCalculator) Summary(data []float64) (map[string]interface{}, error) {
	if err := sc.validateData(data); err != nil {
		return nil, err
	}

	summary := make(map[string]interface{})

	summary["count"] = len(data)
	summary["mean"] = sc.mean(data)
	summary["median"] = sc.median(data)
	summary["std_dev"] = sc.standardDeviation(data)
	summary["variance"] = sc.variance(data)

	dataRange, _ := sc.Range(data)
	summary["range"] = dataRange

	// Min and Max
	sortedData := make([]float64, len(data))
	copy(sortedData, data)
	sort.Float64s(sortedData)
	summary["min"] = sortedData[0]
	summary["max"] = sortedData[len(sortedData)-1]

	// Common percentiles
	summary["percentiles"] = sc.percentiles(data, []float64{25, 50, 75})

	return summary, nil
}

func (sc *StatisticsCalculator) validateData(data []float64) error {
	for i, value := range data {
		if math.IsNaN(value) {
			return fmt.Errorf("data point %d is NaN", i)
		}
		if math.IsInf(value, 0) {
			return fmt.Errorf("data point %d is infinite", i)
		}
	}
	return nil
}

// GetSupportedOperations returns a list of supported statistical operations
func (sc *StatisticsCalculator) GetSupportedOperations() []string {
	return []string{
		"mean", "median", "mode", "std_dev", "variance",
		"percentile", "range", "skewness", "kurtosis", "summary",
	}
}
