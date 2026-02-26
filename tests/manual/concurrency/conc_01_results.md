# CONC-01 Manual Results (Temporary Notes)

Date: 2026-02-25
Environment:
- Base URL: `http://localhost:8000`
- Auth: Bearer token via `CONC_TOKEN`
- Script: `tests/manual/concurrency/conc_01_parallel_create.py`

## Preconditions
- Health check passed: `GET /health` -> `200`
- Auth check passed: `GET /servers?limit=1` with bearer token -> `200`

## Run 1
Command:
```bash
export CONC_N=20
python tests/manual/concurrency/conc_01_parallel_create.py
```

Observed distribution:
- `201`: `1`
- `409`: `19`

Assertions:
- `success(201) == 1` -> pass
- `conflict(409) == 19` -> pass
- `unique_name_count(conc-01-server-1772033334024) == 1` -> pass

Verdict: `PASS`

## Run 2
Command:
```bash
export CONC_N=100
export CONC_TIMEOUT_SEC=20
python tests/manual/concurrency/conc_01_parallel_create.py
```

Observed distribution:
- `201`: `1`
- `409`: `99`

Assertions:
- `success(201) == 1` -> pass
- `conflict(409) == 99` -> pass
- `unique_name_count(conc-01-server-1772033371211) == 1` -> pass

Verdict: `PASS`

## Run 3 (DB-level uniqueness enabled)
Command:
```bash
export CONC_DB_CHECK=1
python tests/manual/concurrency/conc_01_parallel_create.py
```

Observed distribution:
- `201`: `1`
- `409`: `99`

Assertions:
- `success(201) == 1` -> pass
- `conflict(409) == 99` -> pass
- `unique_name_count(conc-01-server-1772034408616) == 1` -> pass
- `db_unique_name_count(conc-01-server-1772034408616) == 1` -> pass

Verdict: `PASS`

## Run 4 (single-command default matrix)
Command:
```bash
python tests/manual/concurrency/conc_01_parallel_create.py
```

Observed matrix cases:
- `api_smoke_20`:
  - `201`: `1`
  - `409`: `19`
  - `unique_name_count(...)`: `1`
  - Verdict: `PASS`
- `api_100`:
  - `201`: `1`
  - `409`: `99`
  - `unique_name_count(...)`: `1`
  - Verdict: `PASS`
- `api_db_100`:
  - `201`: `1`
  - `409`: `99`
  - `unique_name_count(...)`: `1`
  - `db_unique_name_count(...)`: `1`
  - Verdict: `PASS`

Summary:
- total: `3`
- passed: `3`
- failed: `0`

## Notes
- This validates API-level same-name create conflict behavior for CONC-01 Slice A.
- This note now includes API-level uniqueness verification (`unique_name_count == 1`) for each run.
- This note now includes DB-level uniqueness verification for Run 3.
- This note now includes a single-command default matrix run that validates all target cases.
