# 🧪 MCP Gateway v0.7.0 - Manual Testing Suite

**Complete manual testing for post-migration validation**

## 📁 Directory Contents

### 🧪 **Test Files** (Run Individually)
| File | Purpose | Priority | Time |
|------|---------|----------|------|
| `setup_instructions.py` | Environment setup | CRITICAL | 30-60 min |
| `migration_tests.py` | **Migration validation (MAIN TEST)** | CRITICAL | 60-90 min |
| `admin_ui_tests.py` | Admin UI testing | CRITICAL | 60-120 min |
| `api_authentication_tests.py` | Authentication API | HIGH | 30-60 min |
| `api_teams_tests.py` | Teams API | HIGH | 30-60 min |
| `api_servers_tests.py` | Servers API | HIGH | 45-90 min |
| `database_tests.py` | Database compatibility | HIGH | 60-120 min |
| `security_tests.py` | Security testing | MEDIUM | 90-180 min |

### 🎯 **Coordination Files**
| File | Purpose |
|------|---------|
| `run_all_tests.py` | Master test coordinator |
| `generate_test_plan.sh` | **Excel generator entrypoint** |
| `generate_test_plan_xlsx.py` | Excel generator (Python) |

### 📊 **Output Files**
| File | Purpose |
|------|---------|
| `test-plan.xlsx` | **Complete Excel test plan (8 worksheets, 54 tests)** |
| `README.md` | This documentation |

## 🚀 **Quick Start**

### **Generate Excel Test Plan**
```bash
# Generate clean Excel file from Python test files
./generate_test_plan.sh

# Result: test-plan.xlsx (ready for 10 testers)
```

### **For Testers - Option 1: Excel File**
```bash
# Open the generated Excel file
open test-plan.xlsx  # or double-click in file manager

# Follow worksheets in order:
# 1. Setup Instructions
# 2. Migration Tests (MAIN TEST - server visibility)  
# 3. Admin UI Tests
# 4. API Authentication
# 5. API Teams
# 6. API Servers
# 7. Database Tests
# 8. Security Tests
```

### **For Testers - Option 2: Python Files**
```bash
# Run individual test areas
python3 setup_instructions.py        # Environment setup
python3 migration_tests.py           # Critical migration tests
python3 admin_ui_tests.py            # UI validation (server visibility)

# Get help for any test file
python3 <test_file>.py --help
```

### **For Testers - Option 3: Coordinated**
```bash
# Interactive test coordination
python3 run_all_tests.py

# Quick critical tests only
python3 run_all_tests.py --critical-only
```

## 🎯 **Main Migration Test**

**THE KEY TEST**: Verify old servers are visible after migration

**Primary Test Files**:
- `migration_tests.py` → **MIG-003**: "OLD SERVERS VISIBLE"
- `admin_ui_tests.py` → **UI-003**: "Server List View"  
- `test-plan.xlsx` → **Migration Tests** worksheet

**What to validate**:
1. ✅ Admin UI shows all servers (including pre-migration)
2. ✅ Server details are accessible
3. ✅ No empty server list

## 📋 **Test Execution Guide**

### **For New Testers**
1. **Setup**: `python3 setup_instructions.py` (interactive guide)
2. **Migration**: `python3 migration_tests.py` (critical validation)
3. **UI**: `python3 admin_ui_tests.py` (main server visibility test)
4. **APIs**: Run remaining test files as time permits

### **For Experienced Testers** 
1. **Excel**: Open `test-plan.xlsx` and work through worksheets
2. **Filter**: Use Excel table filtering for specific test areas
3. **Critical**: Focus on CRITICAL priority tests first

### **For Test Coordinators**
1. **Generate**: `./generate_test_plan.sh` (create fresh Excel)
2. **Assign**: Distribute test files to 10 testers
3. **Track**: Collect JSON result files from testers
4. **Summary**: Use `run_all_tests.py` for overall results

## 🔧 **Technical Details**

### **File Dependencies**
- All test Python files are **independent** (no dependencies between them)
- `generate_test_plan_xlsx.py` reads test data from Python files
- `run_all_tests.py` coordinates execution of individual files
- Each test file generates its own JSON results file

### **Excel Generation Process**
```bash
./generate_test_plan.sh
  ↓
  Calls: python3 generate_test_plan_xlsx.py
  ↓  
  Reads: All *_tests.py files
  ↓
  Generates: test-plan.xlsx (8 worksheets, Excel tables)
  ↓
  Result: Clean file, no corruption, ready for testers
```

### **Test Result Tracking**
Each test file can generate JSON results:
- `migration_test_results.json`
- `auth_test_results.json`
- `admin_ui_test_results.json`
- etc.

## ⚠️ **Critical Success Criteria**

### **MUST PASS for Production**
1. ✅ **Migration Tests**: All critical tests pass
2. ✅ **Server Visibility**: Old servers visible in admin UI  
3. ✅ **Authentication**: Email and basic auth work
4. ✅ **Team Assignments**: All resources have proper teams

### **SHOULD PASS for Quality**
1. ✅ API endpoints respond correctly
2. ✅ Admin UI fully functional
3. ✅ Security defenses active
4. ✅ Performance acceptable

## 💡 **Pro Tips**

- **Start with setup_instructions.py** - it guides environment preparation
- **Focus on migration_tests.py** - contains the main server visibility test
- **Use --help** with any test file for detailed usage
- **Take screenshots** of UI issues for debugging
- **Record exact error messages** for troubleshooting
- **Test both SQLite and PostgreSQL** if possible

## 🎯 **Expected Outcomes**

After successful testing:
- ✅ Old servers are visible in admin UI (main migration fix)
- ✅ All multitenancy features work correctly
- ✅ APIs respond with proper team-based filtering
- ✅ Admin interface is fully functional
- ✅ Database migration completed without issues
- ✅ Security measures are active and effective

This testing suite ensures your MCP Gateway v0.7.0 migration was successful!