# Quick Start Guide - Performance Testing

## 1. Install Dependencies

```bash
# Install hey (HTTP load testing tool)
brew install hey  # macOS
# OR
go install github.com/rakyll/hey@latest  # Linux/WSL
```

## 2. Start Services

```bash
# From project root
make compose-up

# Wait for services to be healthy (30-60 seconds)
```

## 3. Run Tests

```bash
# Navigate to performance tests
cd tests/performance

# Run all tests with medium load
./run-all.sh

# Or use light profile for quick testing
./run-all.sh -p light
```

## 4. View Results

Results are saved in `tests/performance/results/`

Example output:
```
Summary:
  Total:        15.2340 secs
  Slowest:      0.0856 secs
  Fastest:      0.0012 secs
  Average:      0.0152 secs
  Requests/sec: 656.28

Status code distribution:
  [200] 10000 responses
```

## Common Commands

```bash
# Run only tool benchmarks
./run-all.sh --tools-only

# Run with heavy load
./run-all.sh -p heavy

# Test remote gateway
./run-all.sh -u https://gateway.example.com

# Skip health checks if already running
SKIP_SETUP=true ./run-all.sh
```

## Troubleshooting

### Services not healthy
```bash
docker compose ps
docker compose logs gateway
make compose-down && make compose-up
```

### Authentication issues
```bash
./utils/setup-auth.sh
source .auth_token
```

### hey not found
```bash
which hey
brew install hey  # or: go install github.com/rakyll/hey@latest
```

## Next Steps

- Review [README.md](README.md) for detailed documentation
- Customize load profiles in `profiles/`
- Add custom test scenarios in `scenarios/`
- Track performance over time with baselines
