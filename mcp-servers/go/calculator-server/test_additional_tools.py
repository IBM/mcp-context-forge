#!/usr/bin/env python3
"""
Additional tests for calculator server tools with corrected parameters
"""

import json
import subprocess
import sys
from typing import Dict, Any, List

class AdditionalTester:
    def __init__(self, server_path: str = "./dist/calculator-server"):
        self.server_path = server_path

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
            response = json.loads(stdout.strip().split('\n')[0])
            return response
        except Exception as e:
            return {"error": str(e)}

    def test_unit_conversion_corrected(self):
        """Test unit conversions with correct unit names"""
        print("🔄 TESTING UNIT CONVERSION WITH CORRECT UNITS")
        print("="*50)
        
        test_cases = [
            {
                "description": "Length: meters to feet",
                "params": {"value": 10, "fromUnit": "m", "toUnit": "ft", "category": "length"}
            },
            {
                "description": "Weight: kilograms to pounds",
                "params": {"value": 5, "fromUnit": "kg", "toUnit": "lb", "category": "weight"}
            },
            {
                "description": "Temperature: Celsius to Fahrenheit",
                "params": {"value": 25, "fromUnit": "C", "toUnit": "F", "category": "temperature"}
            },
            {
                "description": "Volume: liters to gallons",
                "params": {"value": 10, "fromUnit": "l", "toUnit": "gal", "category": "volume"}
            },
            {
                "description": "Area: square meters to square feet",
                "params": {"value": 10, "fromUnit": "m2", "toUnit": "ft2", "category": "area"}
            },
            {
                "description": "Length: inches to centimeters",
                "params": {"value": 12, "fromUnit": "in", "toUnit": "cm", "category": "length"}
            },
            {
                "description": "Temperature: Kelvin to Celsius",
                "params": {"value": 298.15, "fromUnit": "K", "toUnit": "C", "category": "temperature"}
            }
        ]
        
        passed = 0
        total = len(test_cases)
        
        for i, test_case in enumerate(test_cases, 1):
            print(f"\nTest {i}: {test_case['description']}")
            print(f"Input: {test_case['params']}")
            
            response = self.send_request(f"tools/call", {
                "name": "unit_conversion",
                "arguments": test_case["params"]
            })
            
            if "result" in response:
                print(f"✅ Result: {response['result']}")
                passed += 1
            else:
                print(f"❌ Error: {response.get('error', 'Unknown error')}")
        
        print(f"\n📊 Unit Conversion Results: {passed}/{total} tests passed")

    def test_expression_eval_corrected(self):
        """Test expression evaluation with corrected syntax"""
        print("\n🧮 TESTING EXPRESSION EVALUATION WITH CORRECTED SYNTAX")
        print("="*50)
        
        test_cases = [
            {
                "description": "Power expression using ^ operator",
                "params": {"expression": "2^3 + sqrt(16)"}
            },
            {
                "description": "Expression with pi constant",
                "params": {"expression": "pi * 2"}
            },
            {
                "description": "Expression with e constant",
                "params": {"expression": "e^1"}
            },
            {
                "description": "Complex mathematical expression",
                "params": {"expression": "sqrt(25) + ln(e) + abs(-5)"}
            },
            {
                "description": "Expression with pow function",
                "params": {"expression": "pow(2, 3) + 1"}
            }
        ]
        
        passed = 0
        total = len(test_cases)
        
        for i, test_case in enumerate(test_cases, 1):
            print(f"\nTest {i}: {test_case['description']}")
            print(f"Input: {test_case['params']}")
            
            response = self.send_request(f"tools/call", {
                "name": "expression_eval",
                "arguments": test_case["params"]
            })
            
            if "result" in response:
                print(f"✅ Result: {response['result']}")
                passed += 1
            else:
                print(f"❌ Error: {response.get('error', 'Unknown error')}")
        
        print(f"\n📊 Expression Evaluation Results: {passed}/{total} tests passed")

    def test_additional_statistics_tools(self):
        """Test additional statistics tools"""
        print("\n📈 TESTING ADDITIONAL STATISTICS TOOLS")
        print("="*50)
        
        # Test stats_summary (if available)
        print("\nTesting stats_summary tool:")
        response = self.send_request(f"tools/call", {
            "name": "stats_summary",
            "arguments": {"data": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]}
        })
        
        if "result" in response:
            print(f"✅ Stats Summary Result: {response['result']}")
        else:
            print(f"❌ Stats Summary Error: {response.get('error', 'Tool not available')}")
        
        # Test percentile tool (if available)
        print("\nTesting percentile tool:")
        response = self.send_request(f"tools/call", {
            "name": "percentile",
            "arguments": {"data": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], "percentile": 90}
        })
        
        if "result" in response:
            print(f"✅ Percentile Result: {response['result']}")
        else:
            print(f"❌ Percentile Error: {response.get('error', 'Tool not available')}")

    def test_financial_advanced_tools(self):
        """Test advanced financial tools"""
        print("\n💰 TESTING ADVANCED FINANCIAL TOOLS")
        print("="*50)
        
        # Test NPV
        print("\nTesting NPV tool:")
        response = self.send_request(f"tools/call", {
            "name": "npv",
            "arguments": {"cashFlows": [-1000, 300, 400, 500, 600], "discountRate": 10}
        })
        
        if "result" in response:
            print(f"✅ NPV Result: {response['result']}")
        else:
            print(f"❌ NPV Error: {response.get('error', 'Tool not available')}")
        
        # Test IRR
        print("\nTesting IRR tool:")
        response = self.send_request(f"tools/call", {
            "name": "irr",
            "arguments": {"cashFlows": [-1000, 300, 400, 500, 600]}
        })
        
        if "result" in response:
            print(f"✅ IRR Result: {response['result']}")
        else:
            print(f"❌ IRR Error: {response.get('error', 'Tool not available')}")
        
        # Test loan_comparison
        print("\nTesting loan_comparison tool:")
        response = self.send_request(f"tools/call", {
            "name": "loan_comparison",
            "arguments": {
                "loans": [
                    {"principal": 200000, "rate": 4.5, "time": 30},
                    {"principal": 200000, "rate": 3.8, "time": 15}
                ]
            }
        })
        
        if "result" in response:
            print(f"✅ Loan Comparison Result: {response['result']}")
        else:
            print(f"❌ Loan Comparison Error: {response.get('error', 'Tool not available')}")

    def test_batch_operations(self):
        """Test batch conversion tool"""
        print("\n🔁 TESTING BATCH OPERATIONS")
        print("="*50)
        
        print("\nTesting batch_conversion tool:")
        response = self.send_request(f"tools/call", {
            "name": "batch_conversion",
            "arguments": {
                "values": [1, 2, 3, 4, 5],
                "fromUnit": "m",
                "toUnit": "ft",
                "category": "length"
            }
        })
        
        if "result" in response:
            print(f"✅ Batch Conversion Result: {response['result']}")
        else:
            print(f"❌ Batch Conversion Error: {response.get('error', 'Tool not available')}")

    def edge_case_tests(self):
        """Test edge cases and error handling"""
        print("\n⚠️  TESTING EDGE CASES AND ERROR HANDLING")
        print("="*50)
        
        # Large numbers
        print("\nTesting with very large numbers:")
        response = self.send_request(f"tools/call", {
            "name": "basic_math",
            "arguments": {"operation": "multiply", "operands": [999999999, 999999999]}
        })
        if "result" in response:
            print(f"✅ Large numbers: {response['result']}")
        else:
            print(f"❌ Large numbers error: {response.get('error')}")
        
        # Negative factorial
        print("\nTesting negative factorial:")
        response = self.send_request(f"tools/call", {
            "name": "advanced_math",
            "arguments": {"function": "factorial", "value": -5}
        })
        if "result" in response:
            print(f"✅ Negative factorial: {response['result']}")
        else:
            print(f"❌ Negative factorial error: {response.get('error')}")
        
        # Invalid expression
        print("\nTesting invalid expression:")
        response = self.send_request(f"tools/call", {
            "name": "expression_eval",
            "arguments": {"expression": "2 + + 3"}
        })
        if "result" in response:
            print(f"✅ Invalid expression: {response['result']}")
        else:
            print(f"❌ Invalid expression error: {response.get('error')}")
        
        # Empty dataset
        print("\nTesting empty dataset:")
        response = self.send_request(f"tools/call", {
            "name": "statistics",
            "arguments": {"data": [], "operation": "mean"}
        })
        if "result" in response:
            print(f"✅ Empty dataset: {response['result']}")
        else:
            print(f"❌ Empty dataset error: {response.get('error')}")

    def run_additional_tests(self):
        """Run all additional tests"""
        print("🧮 CALCULATOR SERVER ADDITIONAL COMPREHENSIVE TESTS")
        print("="*60)
        
        self.test_unit_conversion_corrected()
        self.test_expression_eval_corrected()
        self.test_additional_statistics_tools()
        self.test_financial_advanced_tools()
        self.test_batch_operations()
        self.edge_case_tests()
        
        print("\n✅ Additional testing completed!")

if __name__ == "__main__":
    tester = AdditionalTester()
    tester.run_additional_tests()