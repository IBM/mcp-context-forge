package calculator

import (
    "fmt"
    "math"

    "calculator-server/internal/types"
    "github.com/shopspring/decimal"
)

type FinancialCalculator struct{}

func NewFinancialCalculator() *FinancialCalculator {
    return &FinancialCalculator{}
}

func (fc *FinancialCalculator) Calculate(req types.FinancialRequest) (types.FinancialResult, error) {
    if err := fc.validateRequest(req); err != nil {
        return types.FinancialResult{}, err
    }

    var result float64
    var breakdown map[string]interface{}
    var description string
    var err error

    switch req.Operation {
    case "compound_interest":
        result, breakdown, err = fc.compoundInterest(req)
        description = "Compound interest calculation"
    case "simple_interest":
        result, breakdown, err = fc.simpleInterest(req)
        description = "Simple interest calculation"
    case "loan_payment":
        result, breakdown, err = fc.loanPayment(req)
        description = "Monthly loan payment calculation"
    case "roi":
        result, breakdown, err = fc.returnOnInvestment(req)
        description = "Return on investment calculation"
    case "present_value":
        result, breakdown, err = fc.presentValue(req)
        description = "Present value calculation"
    case "future_value":
        result, breakdown, err = fc.futureValue(req)
        description = "Future value calculation"
    default:
        return types.FinancialResult{}, fmt.Errorf("unsupported operation: %s", req.Operation)
    }

    if err != nil {
        return types.FinancialResult{}, err
    }

    return types.FinancialResult{
        Result:      result,
        Breakdown:   breakdown,
        Description: description,
    }, nil
}

func (fc *FinancialCalculator) compoundInterest(req types.FinancialRequest) (float64, map[string]interface{}, error) {
    if req.Principal <= 0 {
        return 0, nil, fmt.Errorf("principal must be positive")
    }
    if req.Rate < 0 {
        return 0, nil, fmt.Errorf("rate cannot be negative")
    }
    if req.Time <= 0 {
        return 0, nil, fmt.Errorf("time must be positive")
    }

    periods := req.Periods
    if periods == 0 {
        periods = 1 // Default to annual compounding
    }

    // Use decimal for precise calculation
    principal := decimal.NewFromFloat(req.Principal)
    rate := decimal.NewFromFloat(req.Rate / 100) // Convert percentage to decimal
    time := decimal.NewFromFloat(req.Time)
    n := decimal.NewFromInt(int64(periods))

    // Formula: A = P(1 + r/n)^(nt)
    // Calculate (1 + r/n)
    ratePerPeriod := rate.Div(n)
    onePlusRate := decimal.NewFromInt(1).Add(ratePerPeriod)

    // Calculate exponent (nt)
    exponent := n.Mul(time)
    exponentFloat, _ := exponent.Float64()

    // Calculate (1 + r/n)^(nt)
    onePlusRateFloat, _ := onePlusRate.Float64()
    compoundFactor := math.Pow(onePlusRateFloat, exponentFloat)

    // Calculate final amount
    amount := principal.Mul(decimal.NewFromFloat(compoundFactor))
    finalAmount, _ := amount.Float64()

    // Calculate interest earned
    interestEarned := finalAmount - req.Principal

    breakdown := map[string]interface{}{
        "principal":          req.Principal,
        "rate_percent":       req.Rate,
        "time_years":         req.Time,
        "compounds_per_year": periods,
        "final_amount":       finalAmount,
        "interest_earned":    interestEarned,
        "effective_rate":     (finalAmount/req.Principal - 1) / req.Time * 100,
    }

    return finalAmount, breakdown, nil
}

func (fc *FinancialCalculator) simpleInterest(req types.FinancialRequest) (float64, map[string]interface{}, error) {
    if req.Principal <= 0 {
        return 0, nil, fmt.Errorf("principal must be positive")
    }
    if req.Rate < 0 {
        return 0, nil, fmt.Errorf("rate cannot be negative")
    }
    if req.Time <= 0 {
        return 0, nil, fmt.Errorf("time must be positive")
    }

    // Formula: I = PRT
    interest := req.Principal * (req.Rate / 100) * req.Time
    finalAmount := req.Principal + interest

    breakdown := map[string]interface{}{
        "principal":    req.Principal,
        "rate_percent": req.Rate,
        "time_years":   req.Time,
        "interest":     interest,
        "final_amount": finalAmount,
    }

    return interest, breakdown, nil
}

func (fc *FinancialCalculator) loanPayment(req types.FinancialRequest) (float64, map[string]interface{}, error) {
    if req.Principal <= 0 {
        return 0, nil, fmt.Errorf("principal (loan amount) must be positive")
    }
    if req.Rate <= 0 {
        return 0, nil, fmt.Errorf("rate must be positive")
    }
    if req.Time <= 0 {
        return 0, nil, fmt.Errorf("time must be positive")
    }

    periods := req.Periods
    if periods == 0 {
        periods = 12 // Default to monthly payments
    }

    // Convert annual rate to period rate
    periodRate := (req.Rate / 100) / float64(periods)

    // Total number of payments
    totalPayments := req.Time * float64(periods)

    // Formula: PMT = P * [r(1 + r)^n] / [(1 + r)^n - 1]
    if periodRate == 0 {
        // If no interest, payment is just principal divided by number of payments
        monthlyPayment := req.Principal / totalPayments
        totalPaid := monthlyPayment * totalPayments

        breakdown := map[string]interface{}{
            "loan_amount":       req.Principal,
            "rate_percent":      req.Rate,
            "term_years":        req.Time,
            "payments_per_year": periods,
            "monthly_payment":   monthlyPayment,
            "total_paid":        totalPaid,
            "total_interest":    0.0,
        }

        return monthlyPayment, breakdown, nil
    }

    // Calculate (1 + r)^n
    factor := math.Pow(1+periodRate, totalPayments)

    // Calculate monthly payment
    monthlyPayment := req.Principal * (periodRate * factor) / (factor - 1)

    // Calculate totals
    totalPaid := monthlyPayment * totalPayments
    totalInterest := totalPaid - req.Principal

    breakdown := map[string]interface{}{
        "loan_amount":         req.Principal,
        "rate_percent":        req.Rate,
        "term_years":          req.Time,
        "payments_per_year":   periods,
        "monthly_payment":     monthlyPayment,
        "total_paid":          totalPaid,
        "total_interest":      totalInterest,
        "interest_percentage": (totalInterest / req.Principal) * 100,
    }

    return monthlyPayment, breakdown, nil
}

func (fc *FinancialCalculator) returnOnInvestment(req types.FinancialRequest) (float64, map[string]interface{}, error) {
    if req.Principal <= 0 {
        return 0, nil, fmt.Errorf("initial investment must be positive")
    }
    if req.FutureValue <= 0 {
        return 0, nil, fmt.Errorf("final value must be positive")
    }

    // ROI = (Final Value - Initial Investment) / Initial Investment * 100
    roi := ((req.FutureValue - req.Principal) / req.Principal) * 100

    gain := req.FutureValue - req.Principal

    breakdown := map[string]interface{}{
        "initial_investment": req.Principal,
        "final_value":        req.FutureValue,
        "gain_loss":          gain,
        "roi_percent":        roi,
    }

    // If time is provided, calculate annualized ROI
    if req.Time > 0 {
        annualizedROI := (math.Pow(req.FutureValue/req.Principal, 1/req.Time) - 1) * 100
        breakdown["annualized_roi_percent"] = annualizedROI
        breakdown["time_years"] = req.Time
    }

    return roi, breakdown, nil
}

func (fc *FinancialCalculator) presentValue(req types.FinancialRequest) (float64, map[string]interface{}, error) {
    if req.FutureValue <= 0 {
        return 0, nil, fmt.Errorf("future value must be positive")
    }
    if req.Rate <= 0 {
        return 0, nil, fmt.Errorf("discount rate must be positive")
    }
    if req.Time <= 0 {
        return 0, nil, fmt.Errorf("time must be positive")
    }

    periods := req.Periods
    if periods == 0 {
        periods = 1 // Default to annual compounding
    }

    // Formula: PV = FV / (1 + r/n)^(nt)
    periodRate := (req.Rate / 100) / float64(periods)
    totalPeriods := req.Time * float64(periods)

    discountFactor := math.Pow(1+periodRate, totalPeriods)
    presentValue := req.FutureValue / discountFactor

    discount := req.FutureValue - presentValue

    breakdown := map[string]interface{}{
        "future_value":       req.FutureValue,
        "discount_rate":      req.Rate,
        "time_years":         req.Time,
        "compounds_per_year": periods,
        "present_value":      presentValue,
        "discount_amount":    discount,
        "discount_factor":    discountFactor,
    }

    return presentValue, breakdown, nil
}

func (fc *FinancialCalculator) futureValue(req types.FinancialRequest) (float64, map[string]interface{}, error) {
    if req.Principal <= 0 {
        return 0, nil, fmt.Errorf("principal must be positive")
    }
    if req.Rate < 0 {
        return 0, nil, fmt.Errorf("rate cannot be negative")
    }
    if req.Time <= 0 {
        return 0, nil, fmt.Errorf("time must be positive")
    }

    periods := req.Periods
    if periods == 0 {
        periods = 1 // Default to annual compounding
    }

    // This is essentially the same as compound interest
    result, breakdown, err := fc.compoundInterest(req)
    if err != nil {
        return 0, nil, err
    }

    // Rename some fields for future value context
    breakdown["present_value"] = req.Principal
    delete(breakdown, "principal")
    breakdown["growth"] = result - req.Principal

    return result, breakdown, nil
}

// Additional financial functions

func (fc *FinancialCalculator) NetPresentValue(cashFlows []float64, discountRate float64) (float64, error) {
    if len(cashFlows) == 0 {
        return 0, fmt.Errorf("cash flows cannot be empty")
    }
    if discountRate <= 0 {
        return 0, fmt.Errorf("discount rate must be positive")
    }

    npv := 0.0
    rate := discountRate / 100

    for i, cashFlow := range cashFlows {
        discountFactor := math.Pow(1+rate, float64(i))
        npv += cashFlow / discountFactor
    }

    return npv, nil
}

func (fc *FinancialCalculator) InternalRateOfReturn(cashFlows []float64) (float64, error) {
    if len(cashFlows) < 2 {
        return 0, fmt.Errorf("at least 2 cash flows required")
    }

    // Newton-Raphson method to find IRR
    rate := 0.1 // Initial guess
    tolerance := 0.000001
    maxIterations := 100

    for i := 0; i < maxIterations; i++ {
        npv := 0.0
        npvDerivative := 0.0

        for t, cashFlow := range cashFlows {
            factor := math.Pow(1+rate, float64(t))
            npv += cashFlow / factor
            if t > 0 {
                npvDerivative += -float64(t) * cashFlow / math.Pow(1+rate, float64(t+1))
            }
        }

        if math.Abs(npv) < tolerance {
            return rate * 100, nil // Return as percentage
        }

        if npvDerivative == 0 {
            return 0, fmt.Errorf("cannot converge to IRR")
        }

        rate = rate - npv/npvDerivative
    }

    return 0, fmt.Errorf("IRR calculation did not converge")
}

func (fc *FinancialCalculator) validateRequest(req types.FinancialRequest) error {
    if req.Operation == "" {
        return fmt.Errorf("operation cannot be empty")
    }

    // Validate numeric fields for NaN and Inf
    fields := map[string]float64{
        "principal":   req.Principal,
        "rate":        req.Rate,
        "time":        req.Time,
        "futureValue": req.FutureValue,
    }

    for name, value := range fields {
        if math.IsNaN(value) {
            return fmt.Errorf("%s cannot be NaN", name)
        }
        if math.IsInf(value, 0) {
            return fmt.Errorf("%s cannot be infinite", name)
        }
    }

    // Validate periods
    if req.Periods < 0 {
        return fmt.Errorf("periods cannot be negative")
    }

    return nil
}

// GetSupportedOperations returns a list of supported financial operations
func (fc *FinancialCalculator) GetSupportedOperations() []string {
    return []string{
        "compound_interest", "simple_interest", "loan_payment",
        "roi", "present_value", "future_value",
        "npv", "irr", // Additional operations
    }
}
