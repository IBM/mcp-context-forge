#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP Gateway v0.7.0 - Database Compatibility Tests

Testing both SQLite and PostgreSQL compatibility including:
- Migration execution and rollback
- Data integrity and constraints  
- Performance characteristics
- Advanced database features

Usage:
    python3 tests/manual/database_tests.py --sqlite
    python3 tests/manual/database_tests.py --postgresql
    python3 tests/manual/database_tests.py --both
"""

import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime

# Database test cases
DATABASE_TESTS = {
    "sqlite": [
        {
            "id": "SQLite-001", 
            "feature": "Migration Execution",
            "description": "Test migration on SQLite database",
            "commands": [
                "# Set SQLite database URL",
                "export DATABASE_URL=sqlite:///./test_migration.db",
                "# Run migration",
                "python3 -m mcpgateway.bootstrap_db",
                "# Check tables created", 
                "sqlite3 test_migration.db '.tables'"
            ],
            "expected": "All multitenancy tables created: email_users, email_teams, etc.",
            "performance": "Fast",
            "validation": "sqlite3 test_migration.db 'SELECT COUNT(*) FROM email_users;'"
        },
        {
            "id": "SQLite-002",
            "feature": "Team Data Population", 
            "description": "Verify old resources get team assignments",
            "commands": [
                "# Check servers have team assignments",
                "sqlite3 mcp.db 'SELECT COUNT(*) FROM servers WHERE team_id IS NOT NULL;'",
                "# Check tools have team assignments", 
                "sqlite3 mcp.db 'SELECT COUNT(*) FROM tools WHERE team_id IS NOT NULL;'",
                "# Check for any NULL team assignments",
                "sqlite3 mcp.db 'SELECT COUNT(*) FROM servers WHERE team_id IS NULL;'"
            ],
            "expected": "All resources have team_id populated, no NULL values",
            "performance": "Fast",
            "validation": "Zero NULL team_id values in resource tables"
        },
        {
            "id": "SQLite-003",
            "feature": "Connection Pool Management",
            "description": "Test SQLite connection handling",
            "commands": [
                "# Set connection pool size", 
                "export DB_POOL_SIZE=50",
                "# Start gateway and test concurrent connections",
                "make dev &",
                "# Run multiple concurrent API calls",
                "for i in {1..20}; do curl http://localhost:4444/health & done; wait"
            ],
            "expected": "Connections managed within SQLite limits (~50 max)",
            "performance": "Good with limitations",
            "validation": "No connection errors, stable performance"
        },
        {
            "id": "SQLite-004", 
            "feature": "JSON Field Operations",
            "description": "Test JSON data storage and querying",
            "commands": [
                "# Check JSON fields in tools table",
                "sqlite3 mcp.db 'SELECT name, schema FROM tools LIMIT 5;'",
                "# Test JSON field updates",
                "sqlite3 mcp.db 'UPDATE tools SET schema = json_set(schema, \"$.test\", \"value\") WHERE id = (SELECT id FROM tools LIMIT 1);'"
            ],
            "expected": "JSON data stored and queried correctly",
            "performance": "Good",
            "validation": "JSON fields readable and updateable"
        },
        {
            "id": "SQLite-005",
            "feature": "Backup and Restore",
            "description": "Test file-based backup/restore",
            "commands": [
                "# Create backup",
                "cp mcp.db backup_test.db", 
                "# Make some changes",
                "sqlite3 mcp.db 'INSERT INTO email_teams (id, name, slug, created_by, is_personal, visibility, is_active, created_at, updated_at) VALUES (\"test-backup\", \"Backup Test\", \"backup-test\", \"admin@example.com\", 0, \"private\", 1, datetime(\"now\"), datetime(\"now\"));'",
                "# Restore from backup",
                "cp backup_test.db mcp.db",
                "# Verify restore worked", 
                "sqlite3 mcp.db 'SELECT COUNT(*) FROM email_teams WHERE name = \"Backup Test\";'"
            ],
            "expected": "File-based backup and restore works perfectly",
            "performance": "Excellent",
            "validation": "Data restored exactly, test data should be gone"
        }
    ],
    "postgresql": [
        {
            "id": "PG-001",
            "feature": "Migration Execution",
            "description": "Test migration on PostgreSQL database", 
            "commands": [
                "# Set PostgreSQL database URL",
                "export DATABASE_URL=postgresql://postgres:password@localhost:5432/mcp_test",
                "# Create test database",
                "createdb mcp_test",
                "# Run migration",
                "python3 -m mcpgateway.bootstrap_db",
                "# Check tables",
                "psql mcp_test -c '\\\\dt' | grep email"
            ],
            "expected": "All tables created with PostgreSQL-specific data types",
            "performance": "Fast",
            "validation": "psql mcp_test -c 'SELECT COUNT(*) FROM email_users;'"
        },
        {
            "id": "PG-002", 
            "feature": "Advanced Data Types",
            "description": "Test UUID, JSONB, and advanced PostgreSQL features",
            "commands": [
                "# Check UUID columns",
                "psql mcp_test -c 'SELECT id FROM email_teams LIMIT 1;'",
                "# Test JSONB operations", 
                "psql mcp_test -c 'SELECT config FROM servers WHERE config IS NOT NULL LIMIT 1;'",
                "# Test advanced queries",
                "psql mcp_test -c 'SELECT * FROM tools WHERE schema @> \\'{\"type\":\"object\"}\\';'"
            ],
            "expected": "Advanced PostgreSQL data types work correctly",
            "performance": "Excellent",
            "validation": "UUIDs valid, JSONB queries work"
        },
        {
            "id": "PG-003",
            "feature": "High Concurrency",
            "description": "Test PostgreSQL connection pool and concurrency",
            "commands": [
                "# Set high connection pool",
                "export DB_POOL_SIZE=200",
                "# Start gateway",
                "make dev &", 
                "# Run high concurrency test",
                "for i in {1..100}; do curl http://localhost:4444/health & done; wait"
            ],
            "expected": "High concurrency supported (200+ connections)",
            "performance": "Excellent", 
            "validation": "All requests succeed, no connection errors"
        },
        {
            "id": "PG-004",
            "feature": "JSONB Advanced Operations",
            "description": "Test JSONB indexing and complex queries",
            "commands": [
                "# Test JSONB containment",
                "psql mcp_test -c 'SELECT name FROM tools WHERE schema @> \\'{\"type\":\"object\"}\\';'",
                "# Test JSONB path queries",
                "psql mcp_test -c 'SELECT name FROM tools WHERE schema #> \\'{properties}\\' IS NOT NULL;'",
                "# Create JSONB index",
                "psql mcp_test -c 'CREATE INDEX IF NOT EXISTS idx_tools_schema_gin ON tools USING gin(schema);'"
            ],
            "expected": "JSONB indexing and querying work efficiently", 
            "performance": "Excellent",
            "validation": "Complex JSONB queries execute quickly"
        },
        {
            "id": "PG-005",
            "feature": "Full-Text Search",
            "description": "Test PostgreSQL full-text search capabilities",
            "commands": [
                "# Test full-text search",
                "psql mcp_test -c 'SELECT name FROM tools WHERE to_tsvector(name) @@ plainto_tsquery(\"time\");'",
                "# Test search ranking",
                "psql mcp_test -c 'SELECT name, ts_rank(to_tsvector(name), plainto_tsquery(\"time\")) as rank FROM tools WHERE to_tsvector(name) @@ plainto_tsquery(\"time\") ORDER BY rank DESC;'"
            ],
            "expected": "Advanced full-text search with ranking works",
            "performance": "Excellent",
            "validation": "FTS returns relevant results with ranking"
        }
    ]
}


def run_database_tests(db_type="both"):
    """Run database compatibility tests."""
    
    print(f"🗄️ DATABASE COMPATIBILITY TESTING")
    print("=" * 60)
    print(f"🎯 Testing: {db_type.upper()}")
    
    if db_type == "both":
        print("\\n🔧 Testing both SQLite and PostgreSQL")
        sqlite_results = run_db_test_suite("sqlite")
        postgresql_results = run_db_test_suite("postgresql") 
        return {"sqlite": sqlite_results, "postgresql": postgresql_results}
    else:
        return run_db_test_suite(db_type)


def run_db_test_suite(db_type):
    """Run tests for specific database type."""
    
    tests = DATABASE_TESTS.get(db_type, [])
    if not tests:
        print(f"❌ No tests defined for {db_type}")
        return []
    
    print(f"\\n🗄️ {db_type.upper()} TESTING")
    print("=" * 40)
    
    results = []
    
    for test in tests:
        print(f"\\n{'='*50}")
        print(f"🧪 {test['id']}: {test['feature']}")
        print(f"Description: {test['description']}")
        
        print(f"\\n💻 Commands to execute:")
        for cmd in test['commands']:
            if cmd.startswith('#'):
                print(f"   {cmd}")  # Comment
            else:
                print(f"   $ {cmd}")  # Command
        
        print(f"\\n✅ Expected: {test['expected']}")
        print(f"⚡ Performance: {test['performance']}")
        
        # Manual execution
        response = input(f"\\nExecute {test['id']}? (y/n/skip): ").lower()
        
        if response == 'skip':
            results.append({"id": test['id'], "status": "SKIP"})
            continue
        elif response == 'y':
            success = input("Did test complete successfully? (y/n): ").lower()
            performance = input(f"Performance rating (Fast/Good/Slow): ") or test['performance']
            
            status = "PASS" if success == 'y' else "FAIL"
            
            results.append({
                "id": test['id'],
                "feature": test['feature'],
                "status": status,
                "performance": performance,
                "timestamp": datetime.now().isoformat()
            })
    
    return results


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--help":
            print("🗄️ Database Tests")
            print("Usage:")
            print("  python3 tests/manual/database_tests.py --sqlite      # SQLite tests only")
            print("  python3 tests/manual/database_tests.py --postgresql  # PostgreSQL tests only") 
            print("  python3 tests/manual/database_tests.py --both        # Both databases")
            print("  python3 tests/manual/database_tests.py --help        # This help")
        elif sys.argv[1] == "--sqlite":
            run_database_tests("sqlite")
        elif sys.argv[1] == "--postgresql":
            run_database_tests("postgresql")
        elif sys.argv[1] == "--both":
            run_database_tests("both")
        else:
            print("❌ Unknown option. Use --help")
    else:
        # Default to both
        try:
            results = run_database_tests("both") 
            print("\\n🎉 Database testing complete!")
        except Exception as e:
            print(f"❌ Error: {e}")
            sys.exit(1)