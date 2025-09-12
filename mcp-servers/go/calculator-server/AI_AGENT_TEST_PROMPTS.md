# AI Agent Test Prompts for Calculator Server Tools

This document provides ready-to-use prompts for testing the calculator server tools with AI agents. Each prompt is designed to thoroughly test a specific calculator tool.

---

## 🧮 **Basic Math Tool Tests**

### Prompt 1: Basic Math Operations
```
Test the basic_math tool with these calculations:
1. Add these numbers: 15, 25, 10
2. Subtract 45 from 100
3. Multiply 12 by 8
4. Divide 144 by 12
5. Calculate 22 divided by 7 with 4 decimal places precision
6. Add -15 and 8
7. Try to divide 10 by 0 (test error handling)

For each calculation, use the basic_math tool and report both the input and result.
```

### Prompt 2: Basic Math Edge Cases
```
Test edge cases with the basic_math tool:
1. Multiply very large numbers: 999999999 × 999999999
2. Add many small decimals: 0.1 + 0.2 + 0.3 + 0.4 + 0.5
3. Divide with high precision: 1 ÷ 3 with 10 decimal places
4. Subtract resulting in negative: 5 - 12
5. Multiply by zero: 500 × 0

Report any interesting behaviors or limitations you observe.
```

---

## 📐 **Advanced Math Tool Tests**

### Prompt 3: Trigonometric Functions
```
Use the advanced_math tool to calculate:
1. sin(90) in degrees
2. cos(0) in radians
3. tan(45) in degrees
4. sin(π/2) in radians (use 1.5708 as approximation)
5. cos(π) in radians (use 3.1416 as approximation)

Test both degree and radian modes where applicable.
```

### Prompt 4: Logarithmic and Other Functions
```
Test these advanced mathematical functions:
1. Natural logarithm: ln(2.718)
2. Base-10 logarithm: log10(1000)
3. Square root: sqrt(64)
4. Absolute value: abs(-25)
5. Factorial: factorial(6)
6. Exponential: exp(2)
7. Power function: test pow with value 3

For each function, use the advanced_math tool and explain what the result represents.
```

---

## 📊 **Statistics Tool Tests**

### Prompt 5: Basic Statistical Analysis
```
Use the statistics tool to analyze this dataset: [12, 15, 18, 12, 20, 25, 18, 12, 30, 22]

Calculate:
1. Mean (average)
2. Median (middle value)
3. Mode (most frequent value)
4. Standard deviation
5. Variance

Interpret what each statistic tells us about the dataset.
```

### Prompt 6: Advanced Statistics
```
Test the stats_summary tool with this dataset: [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]

Then use the percentile tool to find:
1. 25th percentile
2. 75th percentile
3. 90th percentile

Explain what these percentiles mean in practical terms.
```

---

## 🔄 **Unit Conversion Tool Tests**

### Prompt 7: Length and Weight Conversions
```
Use the unit_conversion tool for these conversions:
1. Convert 100 meters to feet
2. Convert 50 kilograms to pounds
3. Convert 24 inches to centimeters
4. Convert 5 miles to kilometers (use "mi" and "km")

For each conversion, explain the practical application of the result.
```

### Prompt 8: Temperature and Volume Conversions
```
Test temperature and volume conversions:
1. Convert 32°F to Celsius (use "F" and "C")
2. Convert 100°C to Fahrenheit
3. Convert 273.15 Kelvin to Celsius (use "K" and "C")
4. Convert 5 liters to gallons (use "l" and "gal")
5. Convert 1 gallon to liters

Explain when these conversions might be needed in real-world scenarios.
```

### Prompt 9: Batch Conversions
```
Use the batch_conversion tool to convert multiple values at once:
1. Convert [1, 2, 3, 4, 5] meters to feet
2. Convert [10, 20, 30, 40, 50] pounds to kilograms (use "lb" and "kg")

Compare the efficiency of batch vs individual conversions.
```

---

## 💰 **Financial Tool Tests**

### Prompt 10: Basic Financial Calculations
```
Test these financial scenarios with the financial tool:
1. Simple interest: $5000 principal, 4% rate, 3 years
2. Compound interest: $5000 principal, 4% rate, 3 years, monthly compounding (12 periods)
3. Loan payment: $250000 loan, 3.5% rate, 30 years
4. ROI calculation: initial investment $10000, final value $15000

Explain what each calculation tells an investor or borrower.
```

### Prompt 11: Advanced Financial Analysis
```
Test advanced financial tools:
1. Use the npv tool with these cash flows: [-50000, 15000, 20000, 25000, 30000] at 8% discount rate
2. Use the irr tool with the same cash flows
3. Use loan_comparison tool to compare:
   - Loan A: $200000, 4.5% rate, 30 years
   - Loan B: $200000, 3.8% rate, 15 years

Interpret the results for investment decision-making.
```

---

## 🧮 **Expression Evaluation Tests**

### Prompt 12: Simple Expressions
```
Test the expression_eval tool with:
1. Simple arithmetic: "10 + 5 * 2"
2. With parentheses: "(10 + 5) * 2"
3. Using pi constant: "pi * 4"
4. Using e constant: "e * 2"
5. With variables: "x * 2 + y" where x=10, y=5

Note which expressions work and which encounter errors.
```

### Prompt 13: Complex Expressions (Test Limitations)
```
Test these more complex expressions to identify limitations:
1. "sqrt(16) + 4"
2. "sin(pi/2) + cos(0)"
3. "pow(2, 3) + 1"
4. "2^3 + sqrt(9)"
5. "abs(-5) + ln(e)"

Document which functions work within expressions vs. as individual function calls.
```

---

## 🎯 **Comprehensive Integration Tests**

### Prompt 14: Multi-Tool Workflow
```
Create a comprehensive analysis using multiple tools:

Scenario: Analyzing a small business investment
1. Use basic_math to calculate total startup costs: $25000 + $15000 + $8000
2. Use financial tool to calculate loan payment for the total at 5.5% for 7 years
3. Use statistics to analyze projected monthly revenues: [3500, 4200, 3800, 4500, 4100, 3900, 4300]
4. Use unit_conversion to convert 500 square meters to square feet for office space
5. Use expression_eval to calculate monthly profit: "revenue - expenses" where revenue=4100, expenses=2800

Present this as a business analysis report.
```

### Prompt 15: Scientific Calculation Workflow
```
Perform a scientific calculation sequence:
1. Use advanced_math to calculate sin(30°), cos(30°), and tan(30°)
2. Use expression_eval to verify the trigonometric identity: "sin_val^2 + cos_val^2" where sin_val and cos_val are your results from step 1
3. Use basic_math to calculate the area of a circle with radius 5: π × r²
4. Use unit_conversion to convert this area from m² to ft²
5. Use statistics to analyze measurement errors: [4.98, 5.02, 4.97, 5.01, 4.99, 5.03, 4.96]

Present as a scientific measurement report.
```

---

## 🔍 **Error Testing and Edge Cases**

### Prompt 16: Systematic Error Testing
```
Test error handling across different tools:
1. basic_math: Try division by zero
2. advanced_math: Try factorial of negative number
3. statistics: Try operations on empty dataset []
4. unit_conversion: Try invalid units "xyz" to "abc"
5. expression_eval: Try malformed expression "2 + + 3"
6. financial: Try negative time period

Document how each tool handles invalid inputs.
```

### Prompt 17: Boundary Testing
```
Test boundary conditions:
1. Very large numbers: 999999999999 × 999999999999
2. Very small numbers: 0.000000001 × 0.000000001
3. Maximum precision: Calculate 1/7 with maximum decimal places
4. Large datasets: Generate and analyze statistics for 100 random numbers
5. Extreme temperatures: Convert -273°C to Kelvin and Fahrenheit

Report any limitations or unexpected behaviors.
```

---

## 📝 **Usage Instructions for AI Agents**

### How to Use These Prompts:
1. **Copy and paste** any prompt directly to an AI agent with calculator server access
2. **Sequential testing**: Use prompts in order for systematic coverage
3. **Custom modifications**: Adjust numbers and scenarios for specific use cases
4. **Error documentation**: Note any failures or limitations discovered
5. **Performance observation**: Monitor response times and accuracy

### Expected Outcomes:
- **Functional verification**: Confirm all tools work as expected
- **Limitation discovery**: Identify areas needing improvement
- **Integration testing**: Verify tools work well together
- **Error handling**: Confirm robust error responses
- **Performance assessment**: Evaluate speed and accuracy

### Reporting Template:
```
## Test Results for [Tool Name]
- **Prompt Used**: [Prompt number and description]
- **Tests Passed**: X/Y
- **Failures**: [List any failures with error messages]
- **Performance**: [Response time observations]
- **Notes**: [Any interesting observations]
```

---

## 🎯 **Quick Test Commands**

For rapid testing, use these single-line prompts:

```bash
# Quick basic math test
"Calculate: 15+25, 100-45, 12*8, 144/12 using basic_math tool"

# Quick advanced math test
"Calculate: sin(90°), cos(0), sqrt(64), factorial(5) using advanced_math tool"

# Quick statistics test
"Find mean, median, mode of [10,20,30,20,40] using statistics tool"

# Quick unit conversion test
"Convert: 10m→ft, 5kg→lb, 25°C→°F using unit_conversion tool"

# Quick financial test
"Calculate simple interest: $1000, 5%, 2 years using financial tool"
```

These prompts provide comprehensive testing coverage and can be used with any AI agent that has access to the calculator server tools.
