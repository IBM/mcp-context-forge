#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/go/calculator-server/test_tools.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Avinash Sangle

Comprehensive test suite for calculator server tools
Tests all available calculator tools with various scenarios
"""

import json
import subprocess
import sys
from typing import Dict, Any, List
import time

class CalculatorServerTester:
    def __init__(self, server_path: str = "./dist/calculator-server"):
        self.server_path = server_path
        self.test_results = {}
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0

    def send_request(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send JSON-RPC request to calculator server"""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method
        }
        if params:
            request["params"] = params
        
        try:
            process = subprocess.Popen(
                [self.server_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            stdout, stderr = process.communicate(input=json.dumps(request), timeout=10)
            
            if stderr and "Starting calculator server" not in stderr:
                print(f"Server stderr: {stderr}")
            
            response = json.loads(stdout.strip().split('\n')[0])
            return response
        except Exception as e:
            return {"error": str(e)}

    def test_tool(self, tool_name: str, test_cases: List[Dict[str, Any]]):
        """Test a specific tool with multiple test cases"""
        print(f"\n{'='*50}")
        print(f"Testing {tool_name}")
        print(f"{'='*50}")
        
        tool_results = []
        
        for i, test_case in enumerate(test_cases, 1):
            self.total_tests += 1
            print(f"\nTest {i}: {test_case.get('description', 'No description')}")
            print(f"Input: {test_case['params']}")
            
            response = self.send_request(f"tools/call", {
                "name": tool_name,
                "arguments": test_case["params"]
            })
            
            if "result" in response:
                print(f"✅ Result: {response['result']}")
                self.passed_tests += 1
                tool_results.append({
                    "test": test_case["description"],
                    "status": "PASSED",
                    "result": response["result"]
                })
            else:
                print(f"❌ Error: {response.get('error', 'Unknown error')}")
                self.failed_tests += 1
                tool_results.append({
                    "test": test_case["description"],
                    "status": "FAILED", 
                    "error": response.get("error", "Unknown error")
                })
        
        self.test_results[tool_name] = tool_results

    def test_basic_math(self):
        """Test basic math operations"""
        test_cases = [
            {
                "description": "Simple addition",
                "params": {"operation": "add", "operands": [5, 3]}
            },
            {
                "description": "Multiple number addition",
                "params": {"operation": "add", "operands": [1, 2, 3, 4, 5]}
            },
            {
                "description": "Subtraction",
                "params": {"operation": "subtract", "operands": [10, 3]}
            },
            {
                "description": "Multiplication",
                "params": {"operation": "multiply", "operands": [4, 6]}
            },
            {
                "description": "Division",
                "params": {"operation": "divide", "operands": [15, 3]}
            },
            {
                "description": "Division by zero test",
                "params": {"operation": "divide", "operands": [10, 0]}
            },
            {
                "description": "Decimal precision test",
                "params": {"operation": "divide", "operands": [22, 7], "precision": 4}
            },
            {
                "description": "Negative numbers",
                "params": {"operation": "add", "operands": [-5, 3]}
            }
        ]
        self.test_tool("basic_math", test_cases)

    def test_advanced_math(self):
        """Test advanced mathematical functions"""
        test_cases = [
            {
                "description": "Sine function (radians)",
                "params": {"function": "sin", "value": 1.5708, "unit": "radians"}
            },
            {
                "description": "Sine function (degrees)",
                "params": {"function": "sin", "value": 90, "unit": "degrees"}
            },
            {
                "description": "Cosine function",
                "params": {"function": "cos", "value": 0}
            },
            {
                "description": "Tangent function",
                "params": {"function": "tan", "value": 0.7854}
            },
            {
                "description": "Natural logarithm",
                "params": {"function": "ln", "value": 2.7183}
            },
            {
                "description": "Log base 10",
                "params": {"function": "log10", "value": 100}
            },
            {
                "description": "Square root",
                "params": {"function": "sqrt", "value": 16}
            },
            {
                "description": "Absolute value",
                "params": {"function": "abs", "value": -5}
            },
            {
                "description": "Factorial",
                "params": {"function": "factorial", "value": 5}
            },
            {
                "description": "Exponential",
                "params": {"function": "exp", "value": 1}
            },
            {
                "description": "Power function",
                "params": {"function": "pow", "value": 2}  # This might need base parameter
            }
        ]
        self.test_tool("advanced_math", test_cases)

    def test_expression_eval(self):
        """Test expression evaluation"""
        test_cases = [
            {
                "description": "Simple arithmetic expression",
                "params": {"expression": "2 + 3 * 4"}
            },
            {
                "description": "Expression with parentheses",
                "params": {"expression": "(2 + 3) * 4"}
            },
            {
                "description": "Expression with variables",
                "params": {
                    "expression": "x * 2 + y", 
                    "variables": {"x": 5, "y": 3}
                }
            },
            {
                "description": "Complex expression",
                "params": {"expression": "sqrt(16) + 2^3"}
            },
            {
                "description": "Trigonometric expression",
                "params": {"expression": "sin(pi/2) + cos(0)"}
            },
            {
                "description": "Expression with multiple variables",
                "params": {
                    "expression": "a^2 + b^2 + c^2",
                    "variables": {"a": 3, "b": 4, "c": 5}
                }
            }
        ]
        self.test_tool("expression_eval", test_cases)

    def test_statistics(self):
        """Test statistical operations"""
        test_cases = [
            {
                "description": "Calculate mean",
                "params": {"data": [1, 2, 3, 4, 5], "operation": "mean"}
            },
            {
                "description": "Calculate median (odd count)",
                "params": {"data": [1, 3, 2, 5, 4], "operation": "median"}
            },
            {
                "description": "Calculate median (even count)",
                "params": {"data": [1, 2, 3, 4], "operation": "median"}
            },
            {
                "description": "Calculate mode",
                "params": {"data": [1, 2, 2, 3, 4, 2, 5], "operation": "mode"}
            },
            {
                "description": "Calculate standard deviation",
                "params": {"data": [1, 2, 3, 4, 5], "operation": "std_dev"}
            },
            {
                "description": "Calculate variance",
                "params": {"data": [1, 2, 3, 4, 5], "operation": "variance"}
            },
            {
                "description": "Large dataset",
                "params": {"data": list(range(1, 101)), "operation": "mean"}
            }
        ]
        self.test_tool("statistics", test_cases)

    def test_unit_conversion(self):
        """Test unit conversions"""
        test_cases = [
            {
                "description": "Length: meters to feet",
                "params": {"value": 10, "fromUnit": "meters", "toUnit": "feet", "category": "length"}
            },
            {
                "description": "Weight: kilograms to pounds",
                "params": {"value": 5, "fromUnit": "kg", "toUnit": "lbs", "category": "weight"}
            },
            {
                "description": "Temperature: Celsius to Fahrenheit",
                "params": {"value": 25, "fromUnit": "celsius", "toUnit": "fahrenheit", "category": "temperature"}
            },
            {
                "description": "Volume: liters to gallons",
                "params": {"value": 10, "fromUnit": "liters", "toUnit": "gallons", "category": "volume"}
            },
            {
                "description": "Area: square meters to square feet",
                "params": {"value": 10, "fromUnit": "sqm", "toUnit": "sqft", "category": "area"}
            },
            {
                "description": "Length: inches to centimeters",
                "params": {"value": 12, "fromUnit": "inches", "toUnit": "cm", "category": "length"}
            }
        ]
        self.test_tool("unit_conversion", test_cases)

    def test_financial(self):
        """Test financial calculations"""
        test_cases = [
            {
                "description": "Simple interest calculation",
                "params": {
                    "operation": "simple_interest",
                    "principal": 1000,
                    "rate": 5,
                    "time": 2
                }
            },
            {
                "description": "Compound interest calculation",
                "params": {
                    "operation": "compound_interest",
                    "principal": 1000,
                    "rate": 5,
                    "time": 2,
                    "periods": 12
                }
            },
            {
                "description": "Loan payment calculation",
                "params": {
                    "operation": "loan_payment",
                    "principal": 200000,
                    "rate": 4.5,
                    "time": 30
                }
            },
            {
                "description": "ROI calculation",
                "params": {
                    "operation": "roi",
                    "principal": 1000,
                    "futureValue": 1500
                }
            },
            {
                "description": "Present value calculation",
                "params": {
                    "operation": "present_value",
                    "futureValue": 1500,
                    "rate": 5,
                    "time": 3
                }
            },
            {
                "description": "Future value calculation",
                "params": {
                    "operation": "future_value",
                    "principal": 1000,
                    "rate": 6,
                    "time": 5
                }
            }
        ]
        self.test_tool("financial", test_cases)

    def run_comprehensive_test(self):
        """Run all tests"""
        print("🧮 CALCULATOR SERVER COMPREHENSIVE TEST SUITE")
        print("="*60)
        
        start_time = time.time()
        
        # Test all tools
        self.test_basic_math()
        self.test_advanced_math()
        self.test_expression_eval()
        self.test_statistics()
        self.test_unit_conversion()
        self.test_financial()
        
        # Generate summary report
        end_time = time.time()
        self.generate_report(end_time - start_time)

    def generate_report(self, duration: float):
        """Generate comprehensive test report"""
        print(f"\n{'='*60}")
        print("📊 TEST SUMMARY REPORT")
        print(f"{'='*60}")
        print(f"Total Tests: {self.total_tests}")
        print(f"✅ Passed: {self.passed_tests}")
        print(f"❌ Failed: {self.failed_tests}")
        print(f"Success Rate: {(self.passed_tests/self.total_tests)*100:.1f}%")
        print(f"Duration: {duration:.2f} seconds")
        
        # Detailed results by tool
        print(f"\n{'='*60}")
        print("📋 DETAILED RESULTS BY TOOL")
        print(f"{'='*60}")
        
        for tool_name, results in self.test_results.items():
            passed = sum(1 for r in results if r["status"] == "PASSED")
            total = len(results)
            print(f"\n🔧 {tool_name.upper()}: {passed}/{total} tests passed")
            
            for result in results:
                if result["status"] == "FAILED":
                    print(f"   ❌ {result['test']}: {result['error']}")
                else:
                    print(f"   ✅ {result['test']}")

if __name__ == "__main__":
    tester = CalculatorServerTester()
    tester.run_comprehensive_test()