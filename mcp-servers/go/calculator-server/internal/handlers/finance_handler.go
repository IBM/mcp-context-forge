package handlers

import (
	"encoding/json"
	"fmt"

	"calculator-server/internal/calculator"
	"calculator-server/internal/types"
)

type FinanceHandler struct {
	financeCalc *calculator.FinancialCalculator
}

func NewFinanceHandler() *FinanceHandler {
	return &FinanceHandler{
		financeCalc: calculator.NewFinancialCalculator(),
	}
}

func (fh *FinanceHandler) HandleFinancialCalculation(params map[string]interface{}) (interface{}, error) {
	// Convert params to FinancialRequest
	paramsJSON, err := json.Marshal(params)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal parameters: %v", err)
	}

	var req types.FinancialRequest
	if err := json.Unmarshal(paramsJSON, &req); err != nil {
		return nil, fmt.Errorf("invalid parameters for financial calculation: %v", err)
	}

	// Validate operation
	supportedOps := fh.financeCalc.GetSupportedOperations()
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
	result, err := fh.financeCalc.Calculate(req)
	if err != nil {
		return nil, err
	}

	// Add additional information
	response := map[string]interface{}{
		"operation":            req.Operation,
		"result":               result.Result,
		"breakdown":            result.Breakdown,
		"description":          result.Description,
		"supported_operations": supportedOps,
	}

	return response, nil
}

// Specialized financial operation handlers

func (fh *FinanceHandler) HandleCompoundInterest(params map[string]interface{}) (interface{}, error) {
	// Set operation to compound_interest
	params["operation"] = "compound_interest"
	return fh.HandleFinancialCalculation(params)
}

func (fh *FinanceHandler) HandleLoanPayment(params map[string]interface{}) (interface{}, error) {
	// Set operation to loan_payment
	params["operation"] = "loan_payment"
	return fh.HandleFinancialCalculation(params)
}

func (fh *FinanceHandler) HandleROI(params map[string]interface{}) (interface{}, error) {
	// Set operation to roi
	params["operation"] = "roi"
	return fh.HandleFinancialCalculation(params)
}

func (fh *FinanceHandler) HandlePresentValue(params map[string]interface{}) (interface{}, error) {
	// Set operation to present_value
	params["operation"] = "present_value"
	return fh.HandleFinancialCalculation(params)
}

func (fh *FinanceHandler) HandleFutureValue(params map[string]interface{}) (interface{}, error) {
	// Set operation to future_value
	params["operation"] = "future_value"
	return fh.HandleFinancialCalculation(params)
}

// Advanced financial calculations

func (fh *FinanceHandler) HandleNPV(params map[string]interface{}) (interface{}, error) {
	// Extract parameters
	cashFlowsInterface, exists := params["cashFlows"]
	if !exists {
		return nil, fmt.Errorf("cashFlows parameter is required")
	}

	discountRateInterface, exists := params["discountRate"]
	if !exists {
		return nil, fmt.Errorf("discountRate parameter is required")
	}

	// Convert cash flows
	cashFlows, err := fh.convertToFloatSlice(cashFlowsInterface)
	if err != nil {
		return nil, fmt.Errorf("invalid cashFlows format: %v", err)
	}

	// Convert discount rate
	discountRate, ok := discountRateInterface.(float64)
	if !ok {
		return nil, fmt.Errorf("discountRate must be a number")
	}

	// Calculate NPV
	npv, err := fh.financeCalc.NetPresentValue(cashFlows, discountRate)
	if err != nil {
		return nil, err
	}

	response := map[string]interface{}{
		"npv":            npv,
		"cashFlows":      cashFlows,
		"discountRate":   discountRate,
		"periods":        len(cashFlows),
		"description":    "Net Present Value calculation",
		"interpretation": fh.interpretNPV(npv),
	}

	return response, nil
}

func (fh *FinanceHandler) HandleIRR(params map[string]interface{}) (interface{}, error) {
	// Extract parameters
	cashFlowsInterface, exists := params["cashFlows"]
	if !exists {
		return nil, fmt.Errorf("cashFlows parameter is required")
	}

	// Convert cash flows
	cashFlows, err := fh.convertToFloatSlice(cashFlowsInterface)
	if err != nil {
		return nil, fmt.Errorf("invalid cashFlows format: %v", err)
	}

	// Calculate IRR
	irr, err := fh.financeCalc.InternalRateOfReturn(cashFlows)
	if err != nil {
		return nil, err
	}

	response := map[string]interface{}{
		"irr":            irr,
		"cashFlows":      cashFlows,
		"periods":        len(cashFlows),
		"description":    "Internal Rate of Return calculation",
		"interpretation": fh.interpretIRR(irr),
	}

	return response, nil
}

// Batch operations and comparisons

func (fh *FinanceHandler) HandleLoanComparison(params map[string]interface{}) (interface{}, error) {
	// Extract loan scenarios
	loansInterface, exists := params["loans"]
	if !exists {
		return nil, fmt.Errorf("loans parameter is required (array of loan objects)")
	}

	loans, ok := loansInterface.([]interface{})
	if !ok {
		return nil, fmt.Errorf("loans must be an array")
	}

	results := make([]map[string]interface{}, len(loans))

	for i, loanInterface := range loans {
		loanMap, ok := loanInterface.(map[string]interface{})
		if !ok {
			return nil, fmt.Errorf("loan at index %d must be an object", i)
		}

		// Add operation type
		loanMap["operation"] = "loan_payment"

		// Calculate loan payment
		result, err := fh.HandleFinancialCalculation(loanMap)
		if err != nil {
			results[i] = map[string]interface{}{
				"error":      err.Error(),
				"loan_index": i,
			}
		} else {
			resultMap := result.(map[string]interface{})
			results[i] = map[string]interface{}{
				"loan_index": i,
				"result":     resultMap["result"],
				"breakdown":  resultMap["breakdown"],
			}
		}
	}

	// Find best loan (lowest monthly payment)
	bestLoanIndex := -1
	lowestPayment := float64(999999999)

	for i, result := range results {
		if payment, ok := result["result"].(float64); ok {
			if payment < lowestPayment {
				lowestPayment = payment
				bestLoanIndex = i
			}
		}
	}

	response := map[string]interface{}{
		"loan_comparisons": results,
		"best_loan_index":  bestLoanIndex,
		"lowest_payment":   lowestPayment,
		"description":      "Loan comparison analysis",
	}

	return response, nil
}

func (fh *FinanceHandler) HandleInvestmentScenarios(params map[string]interface{}) (interface{}, error) {
	// Extract scenarios
	scenariosInterface, exists := params["scenarios"]
	if !exists {
		return nil, fmt.Errorf("scenarios parameter is required (array of investment objects)")
	}

	scenarios, ok := scenariosInterface.([]interface{})
	if !ok {
		return nil, fmt.Errorf("scenarios must be an array")
	}

	results := make([]map[string]interface{}, len(scenarios))

	for i, scenarioInterface := range scenarios {
		scenarioMap, ok := scenarioInterface.(map[string]interface{})
		if !ok {
			return nil, fmt.Errorf("scenario at index %d must be an object", i)
		}

		// Default to compound interest if no operation specified
		if _, exists := scenarioMap["operation"]; !exists {
			scenarioMap["operation"] = "compound_interest"
		}

		// Calculate scenario
		result, err := fh.HandleFinancialCalculation(scenarioMap)
		if err != nil {
			results[i] = map[string]interface{}{
				"error":          err.Error(),
				"scenario_index": i,
			}
		} else {
			resultMap := result.(map[string]interface{})
			results[i] = map[string]interface{}{
				"scenario_index": i,
				"final_amount":   resultMap["result"],
				"breakdown":      resultMap["breakdown"],
			}
		}
	}

	// Find best scenario (highest final amount)
	bestScenarioIndex := -1
	highestAmount := float64(-1)

	for i, result := range results {
		if amount, ok := result["final_amount"].(float64); ok {
			if amount > highestAmount {
				highestAmount = amount
				bestScenarioIndex = i
			}
		}
	}

	response := map[string]interface{}{
		"investment_scenarios": results,
		"best_scenario_index":  bestScenarioIndex,
		"highest_return":       highestAmount,
		"description":          "Investment scenario analysis",
	}

	return response, nil
}

// Helper methods

func (fh *FinanceHandler) convertToFloatSlice(data interface{}) ([]float64, error) {
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

func (fh *FinanceHandler) interpretNPV(npv float64) string {
	if npv > 0 {
		return "Positive NPV indicates the investment is profitable"
	} else if npv < 0 {
		return "Negative NPV indicates the investment is not profitable"
	} else {
		return "Zero NPV indicates the investment breaks even"
	}
}

func (fh *FinanceHandler) interpretIRR(irr float64) string {
	if irr > 15 {
		return "High IRR indicates excellent investment return"
	} else if irr > 10 {
		return "Good IRR indicates strong investment return"
	} else if irr > 5 {
		return "Moderate IRR indicates acceptable investment return"
	} else {
		return "Low IRR indicates poor investment return"
	}
}

func (fh *FinanceHandler) GetSupportedOperations() []string {
	return fh.financeCalc.GetSupportedOperations()
}
