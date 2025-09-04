#!/bin/bash
# -*- coding: utf-8 -*-
# MCP Gateway v0.7.0 - Test Plan Generator
# 
# Generates comprehensive Excel test plan from Python test files.
# Creates clean, non-corrupted Excel file ready for 10 testers.

set -e  # Exit on any error

echo "🎯 MCP GATEWAY TEST PLAN GENERATOR"
echo "=================================="
echo "📊 Generating Excel from Python test files"
echo "👥 Ready for 10 manual testers"
echo ""

# Check prerequisites
echo "🔧 Checking prerequisites..."

if ! command -v python3 &> /dev/null; then
    echo "❌ python3 not found. Please install Python 3.11+"
    exit 1
fi

# Check openpyxl
if ! python3 -c "import openpyxl" 2>/dev/null; then
    echo "📦 Installing openpyxl..."
    pip install openpyxl
fi

echo "✅ Prerequisites OK"

# Generate Excel file
echo ""
echo "📊 Generating Excel test plan..."
python3 generate_test_plan_xlsx.py

if [ $? -eq 0 ]; then
    echo ""
    echo "🎉 SUCCESS!"
    echo "📄 Excel file created: test-plan.xlsx"
    
    if [ -f "test-plan.xlsx" ]; then
        file_size=$(stat -c%s "test-plan.xlsx" 2>/dev/null || stat -f%z "test-plan.xlsx" 2>/dev/null || echo "unknown")
        echo "📏 File size: $file_size bytes"
        
        # Test file opens
        if python3 -c "import openpyxl; wb=openpyxl.load_workbook('test-plan.xlsx'); print(f'✅ Verified: {len(wb.worksheets)} worksheets'); wb.close()" 2>/dev/null; then
            echo "✅ File verification: Opens cleanly"
        else
            echo "⚠️ File verification: Could not verify"
        fi
    fi
    
    echo ""
    echo "🎯 Next Steps:"
    echo "   1. Open test-plan.xlsx in Excel or LibreOffice"
    echo "   2. Review all worksheets (8 total)"
    echo "   3. Focus on 'Migration Tests' worksheet (main server visibility test)"
    echo "   4. Distribute to 10 testers for execution"
    echo ""
    echo "👥 Tester Options:"
    echo "   • Excel file: Open test-plan.xlsx and follow worksheets"
    echo "   • Python files: Run individual test files directly"
    echo "   • Coordinated: python3 run_all_tests.py"
    echo ""
    echo "🚀 READY FOR COMPREHENSIVE TESTING!"
    
else
    echo "❌ Excel generation failed"
    exit 1
fi