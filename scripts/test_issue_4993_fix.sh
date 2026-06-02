#!/bin/bash
# Testing script for Issue #4993 fix
# Tests that concurrent bootstrap processes no longer race on orphaned resource assignments
#
# Prerequisites:
#   - PostgreSQL running and accessible
#   - Virtual environment activated (source .venv/bin/activate)
#   - DATABASE_URL environment variable set (or defaults to local PostgreSQL)
#
# Usage:
#   bash scripts/test_issue_4993_fix.sh

set -e

echo "=========================================="
echo "Issue #4993 Fix - Race Condition Test"
echo "=========================================="
echo ""

# Check if we're in a virtual environment
if [ -z "$VIRTUAL_ENV" ]; then
    echo "❌ Error: Virtual environment not activated"
    echo "Please run: source .venv/bin/activate"
    exit 1
fi

# Default DATABASE_URL if not set
DEFAULT_DB_URL="postgresql+psycopg://postgres:mysecretpassword@localhost:5432/mcp"
DB_URL="${DATABASE_URL:-$DEFAULT_DB_URL}"
DB_URL_CLEAN="${DB_URL/+psycopg/}"

echo "Configuration:"
echo "  Database: ${DB_URL}"
echo "  Test workers: 30 per run"
echo "  Test iterations: 5"
echo "  Orphaned tools per test: 30"
echo ""

# Verify PostgreSQL connection
echo "Checking PostgreSQL connection..."
if ! python -c "
import psycopg
try:
    conn = psycopg.connect('${DB_URL_CLEAN}')
    conn.close()
    print('✅ PostgreSQL connection successful')
except Exception as e:
    print(f'❌ Failed to connect to PostgreSQL: {e}')
    exit(1)
" 2>/dev/null; then
    echo "❌ Cannot connect to PostgreSQL"
    echo "Please ensure PostgreSQL is running and DATABASE_URL is correct"
    exit 1
fi

echo ""

# Test parameters
NUM_TESTS=5
WORKERS_PER_TEST=30
ORPHANED_TOOLS=30

race_detected=0
total_conflicts=0

for test_num in $(seq 1 $NUM_TESTS); do
    echo "=========================================="
    echo "Test Run $test_num/$NUM_TESTS"
    echo "=========================================="
    
    # Setup: Insert orphaned tools
    echo "[1/4] Setting up $ORPHANED_TOOLS orphaned tools..."
    python << SETUP
import psycopg
import uuid
import os

num_tools = ${ORPHANED_TOOLS}
conn = psycopg.connect('${DB_URL_CLEAN}')
cur = conn.cursor()

# Clean up previous test tools
cur.execute("DELETE FROM tools WHERE name LIKE 'issue4993-test-tool%'")

# Insert orphaned tools
for i in range(num_tools):
    tool_id = uuid.uuid4().hex
    tool_name = f'issue4993-test-tool-{i:03d}'
    cur.execute("""
        INSERT INTO tools (
            id, original_name, name, description, input_schema,
            custom_name, custom_name_slug, integration_type, request_type,
            enabled, deprecated, reachable, jsonpath_filter, tags, version, visibility,
            created_at, updated_at
        ) VALUES (%s, %s, %s, %s, '{}'::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, 
            '[]'::jsonb, %s, %s, NOW(), NOW())
    """, (tool_id, tool_name, tool_name, f'Test tool {i}', tool_name, tool_name,
          'MCP', 'SSE', True, False, True, '', 1, 'private'))

conn.commit()
cur.execute("SELECT COUNT(*) FROM tools WHERE team_id IS NULL AND name LIKE 'issue4993-test-tool%'")
count = cur.fetchone()[0]
print(f"✓ Created {count} orphaned tools")
conn.close()
SETUP
    
    # Launch concurrent workers
    echo "[2/4] Launching $WORKERS_PER_TEST concurrent workers..."
    rm -f test_issue4993_*.log 2>/dev/null || true
    
    start_time=$(date +%s)
    for i in $(seq 1 $WORKERS_PER_TEST); do
        (python -m mcpgateway.bootstrap_db > test_issue4993_$i.log 2>&1) &
    done
    
    # Wait for all workers
    wait
    end_time=$(date +%s)
    duration=$((end_time - start_time))
    
    echo "[3/4] All workers completed in ${duration}s"
    
    # Analyze results
    echo "[4/4] Analyzing results..."
    
    # Check for name conflicts (evidence of race condition)
    conflicts=$(grep -c "Name conflict" test_issue4993_*.log 2>/dev/null | grep -v ":0$" | wc -l | tr -d ' ')
    
    if [ "$conflicts" -gt 0 ]; then
        echo "  ❌ RACE DETECTED: $conflicts worker(s) saw name conflicts"
        race_detected=$((race_detected + 1))
        total_conflicts=$((total_conflicts + conflicts))
        
        # Show which workers saw conflicts
        echo "  Workers with conflicts:"
        grep -l "Name conflict" test_issue4993_*.log 2>/dev/null | head -5 | while read log; do
            count=$(grep -c "Name conflict" "$log")
            echo "    - $log: $count conflicts"
        done
    else
        echo "  ✅ No race condition detected"
    fi
    
    # Verify advisory lock usage
    lock_acquisitions=$(grep -c "Acquired lock for bootstrap helpers" test_issue4993_*.log 2>/dev/null | grep -v ":0$" | wc -l | tr -d ' ')
    if [ "$lock_acquisitions" -gt 0 ]; then
        echo "  ✅ Advisory lock used by $lock_acquisitions worker(s)"
    fi
    
    # Check database state
    python << CHECK
import psycopg
conn = psycopg.connect('${DB_URL_CLEAN}')
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM tools WHERE name LIKE 'issue4993-test-tool%' AND team_id IS NULL")
orphaned = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM tools WHERE name LIKE 'issue4993-test-tool%' AND team_id IS NOT NULL")
assigned = cur.fetchone()[0]

# Check for renamed tools (indicates race condition occurred)
cur.execute("SELECT COUNT(*) FROM tools WHERE name ~ 'issue4993-test-tool-[0-9]+-[0-9]+'")
renamed = cur.fetchone()[0]

print(f"  Database state: {orphaned} orphaned, {assigned} assigned, {renamed} renamed")

if orphaned > 0:
    print(f"  ⚠️  WARNING: {orphaned} tools remain orphaned")
if renamed > 0:
    print(f"  ⚠️  WARNING: {renamed} tools were renamed (race occurred)")

conn.close()
CHECK
    
    echo ""
done

# Cleanup test logs
echo "Cleaning up test logs..."
rm -f test_issue4993_*.log

# Final summary
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo "Total test runs: $NUM_TESTS"
echo "Races detected: $race_detected out of $NUM_TESTS"
echo "Total workers with conflicts: $total_conflicts"
echo ""

if [ "$race_detected" -eq 0 ]; then
    echo "✅✅✅ SUCCESS! No race conditions detected!"
    echo ""
    echo "The fix is working correctly. Multiple concurrent workers"
    echo "are properly serialized through the advisory lock mechanism."
    exit 0
else
    echo "❌ Race conditions detected in $race_detected test run(s)"
    echo ""
    echo "This indicates the race condition is not fully resolved."
    echo "Please review the fix implementation."
    exit 1
fi
