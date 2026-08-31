# 🧪 ContextForge v0.9.0 - YAML-Based Manual Testing Suite

**Maintainable, scalable manual testing with YAML test definitions**

## 📁 Clean Directory Structure

### 🧪 **YAML Test Definitions** (`testcases/` directory)
| File | Purpose | Tests | Priority |
|------|---------|-------|----------|
| `testcases/setup_instructions.yaml` | Environment setup | 17 | CRITICAL |
| `testcases/migration_tests.yaml` | **Migration validation (MAIN TEST)** | 8 | CRITICAL |
| `testcases/admin_ui_tests.yaml` | Admin UI testing | 10 | CRITICAL |
| `testcases/api_authentication.yaml` | Authentication API | 10 | HIGH |
| `testcases/api_teams.yaml` | Teams API | 10 | HIGH |
| `testcases/api_servers.yaml` | Servers API | 10 | HIGH |
| `testcases/security_tests.yaml` | Security testing | 10 | HIGH |

### 🎯 **Generation & Output**
| File | Purpose |
|------|---------|
| `generate_test_plan.py` | **Single generator script** |
| `test-plan.xlsx` | Generated Excel file |
| `README.md` | This documentation |

## 🚀 **Quick Start**

### **Generate Excel Test Plan**
```bash
# Generate Excel file from YAML definitions
python3 generate_test_plan.py

# Result: test-plan.xlsx (clean, formatted, no corruption)
```

### **Use Excel File**
```bash
# Open generated Excel file
open test-plan.xlsx

# Features:
# - 7+ worksheets with complete test data
# - Excel table formatting for filtering/sorting
# - Priority color coding (Critical/High/Medium)
# - Tester tracking columns
# - Complete step-by-step instructions
```

### **Update Tests**
```bash
# Edit YAML files to modify tests
vi testcases/migration_tests.yaml         # Edit migration tests
vi testcases/api_authentication.yaml      # Edit auth API tests

# Regenerate Excel
python3 generate_test_plan.py             # Fresh Excel with updates
```

## 🎯 **Key Advantages**

### ✅ **Maintainable**
- **YAML files**: Easy to read and edit
- **One file per worksheet**: Clean separation of concerns
- **Version controllable**: Track changes in individual files
- **No Excel editing**: Update YAML, regenerate Excel

### ✅ **Scalable**
- **Add new worksheets**: Create new YAML file
- **Modify tests**: Edit YAML and regenerate
- **Bulk updates**: Script-friendly YAML format
- **Template driven**: Consistent test structure

### ✅ **Tester Friendly**
- **Clean Excel output**: No corruption issues
- **Table filtering**: Excel tables for easy sorting
- **Complete instructions**: Step-by-step guidance
- **Progress tracking**: Status, tester, date columns

## 📋 **YAML File Structure**

Each YAML file follows this structure:

```yaml
worksheet_name: "Test Area Name"
description: "What this worksheet tests"
priority: "CRITICAL|HIGH|MEDIUM|LOW"
estimated_time: "Time estimate"

headers:
  - "Test ID"
  - "Description"
  - "Steps"
  - "Expected"
  - "Status"
  - "Tester"
  # ... more columns

tests:
  - test_id: "TEST-001"
    description: "Test description"
    steps: |
      1. Step one
      2. Step two
    expected: "Expected result"
    priority: "CRITICAL"
    # ... more fields
```

## 🎯 **Main Migration Test**

**Focus**: Verify old servers are visible after migration

**Key Files**:
- `migration_tests.yaml` → **MIG-003**: "OLD SERVERS VISIBLE"
- `admin_ui_tests.yaml` → **UI-003**: "Server List View"

**Critical Test**: Ensure all pre-migration servers appear in admin UI

## 👥 **For 10 Testers**

### **Test Coordinators**
```bash
# Generate fresh Excel for distribution
python3 generate_test_plan.py

# Distribute test-plan.xlsx to testers
# Assign different worksheets to different testers
```

### **Individual Testers**
```bash
# Open Excel file
open test-plan.xlsx

# Work through assigned worksheets
# Record results in Status/Actual/Comments columns
# Focus on CRITICAL tests first
```

### **Test Maintainers**
```bash
# Update test definitions
vi <test_area>.yaml

# Add new test areas
cp template.yaml new_test_area.yaml

# Regenerate Excel
python3 generate_test_plan.py
```

## 🔧 **Technical Benefits**

### **Easy Maintenance**
- Edit YAML files instead of complex Python code
- Clear, readable test definitions
- No Excel corruption from manual editing
- Version control friendly

### **Quality Control**
- YAML validation catches syntax errors
- Consistent test structure across all areas
- Easy to review changes in pull requests
- Template-driven test creation

### **Flexibility**
- Add new test areas by creating YAML files
- Modify test structure by updating YAML schema
- Generate different output formats (Excel, CSV, HTML)
- Script-friendly for automation

## 📊 **Generated Excel Features**

- **Clean formatting**: Professional appearance
- **Excel tables**: Built-in filtering and sorting
- **Priority coding**: Visual priority indicators
- **Progress tracking**: Tester name, date, status columns
- **No corruption**: Proper file handling prevents Excel repair warnings
- **Complete coverage**: All test areas included

## 💡 **Pro Tips**

- **Edit YAML files** to modify tests (much easier than Excel)
- **Regenerate often** to get fresh, clean Excel files
- **Use vi/vim** for YAML editing with syntax highlighting
- **Validate YAML** before generating (python3 -c "import yaml; yaml.safe_load(open('file.yaml'))")
- **Version control** YAML files to track test evolution

This YAML-based approach makes the test suite much more maintainable and scalable for ongoing ContextForge validation!

## Concurrency Tests (`concurrency/` directory)

Manual concurrency tests validate data consistency under concurrent access. These tests require a live ContextForge instance backed by PostgreSQL and Redis.

| Test ID | Script | Makefile Target | Description |
|---------|--------|-----------------|-------------|
| CONC-02 | `concurrency/conc_02_gateways_read_during_write.py` | `make conc-02-gateways` | Gateway read-during-write consistency |

### Running Concurrency Tests

Concurrency tests are **not** part of automated CI. They require manual setup of infrastructure (PostgreSQL, Redis, gateway, translator) and a JWT token.

**Prerequisites:**

1. PostgreSQL and Redis running (e.g., via Docker)
2. ContextForge gateway running against PostgreSQL + Redis
3. A translator endpoint (e.g., `python -m mcpgateway.translate --stdio "uvx mcp-server-git" --port 9000`)
4. A valid JWT token exported as `CONC_TOKEN`

**Quick start (CONC-02):**

```bash
# Start infrastructure
docker run -d --name conc-postgres -p 5432:5432 \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=concurrent_test postgres:16
docker run -d --name conc-redis -p 6379:6379 redis:7

# Start gateway (Terminal A)
DATABASE_URL='postgresql+psycopg://postgres:postgres@127.0.0.1:5432/concurrent_test' \
REDIS_URL='redis://127.0.0.1:6379/0' CACHE_TYPE='redis' \
JWT_SECRET_KEY='my-test-key-but-now-longer-than-32-bytes' \
SSRF_ALLOW_LOCALHOST=true SSRF_ALLOW_PRIVATE_NETWORKS=true \
make dev

# Start translator (Terminal B)
python -m mcpgateway.translate --stdio "uvx mcp-server-git" --port 9000

# Generate token and run (Terminal C)
export CONC_TOKEN="$(python3 -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 120 --secret my-test-key-but-now-longer-than-32-bytes)"
make conc-02-gateways
```

**Tuning parameters (via environment variables):**

| Variable | Default | Description |
|----------|---------|-------------|
| `CONC_RW_DURATION_SEC` | 20 | Test duration in seconds |
| `CONC_RW_READERS` | 5 | Number of concurrent reader workers |
| `CONC_RW_WRITERS` | 1 | Number of concurrent writer workers |
| `CONC_RW_TIMEOUT_SEC` | 20 | HTTP request timeout |
| `CONC_BASE_URL` | `http://127.0.0.1:8000` | Gateway base URL |
| `CONC_GATEWAY_URL` | `http://127.0.0.1:9000/sse` | Translator endpoint URL |

**Adding new concurrency tests:**

Follow the naming convention:
- Script: `concurrency/conc_NN_<description>.py`
- Shell runner: `concurrency/run_conc_NN_<description>.sh`
- Results: `concurrency/conc_NN_<description>_results.md`
- Makefile target: `conc-NN-<description>`

See `concurrency/conc_02_gateways_results.md` for the full runbook and results template.
