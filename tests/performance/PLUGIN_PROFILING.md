# Plugin Performance Profiling Guide

This guide explains how to use the plugin performance profiling tool in `test_plugins_performance.py`.

## Quick Start

### Run with Summary Table Only (Default)

```bash
LOG_LEVEL=ERROR \
python tests/performance/test_plugins_performance.py 2>/dev/null
```

### Run with Detailed Profiles

To see detailed profiling output for each plugin-hook combination:

```bash
LOG_LEVEL=ERROR \
python tests/performance/test_plugins_performance.py --details 2>/dev/null
```

### Show Help

```bash
python tests/performance/test_plugins_performance.py --help
```

## What It Does

The profiler:

1. **Loads the plugin manager** using `plugins/config.yaml` (initialization is NOT profiled)
2. **Profiles each enabled plugin's hooks** by:
   - Running 1000 iterations of each hook
   - Using cProfile to capture detailed performance data
   - Generating individual `.prof` files for each plugin-hook combination
3. **Generates a summary table** showing average execution times per plugin per hook
4. **Optionally prints detailed profiles** (with `--details` flag) showing top 20 functions for each plugin-hook
5. **Saves profile files** to `plugins/prof/` directory

## Command Line Options

### `--details`

Print detailed profile output for each plugin-hook combination immediately after profiling.

**Without `--details` (default)**:
- Shows profiling progress
- Prints summary table only
- Clean, concise output

**With `--details`**:
- Shows profiling progress
- Prints detailed profile (top 20 functions by cumulative time) after each hook
- Prints summary table at the end
- Verbose output for immediate analysis

**Example**:
```bash
python tests/performance/test_plugins_performance.py --details
```

Sample output for one plugin-hook:
```
• Profiling prompt_pre_fetch... ✓ 0.049ms avg (saved to tests/performance/plugins/prof/SecretsDetection_prompt_pre_fetch.prof)

================================================================================
Detailed Profile: SecretsDetection_prompt_pre_fetch.prof
================================================================================
Mon Jan 12 22:09:30 2026    tests/performance/plugins/prof/SecretsDetection_prompt_pre_fetch.prof

         192001 function calls (189001 primitive calls) in 0.049 seconds

   Ordered by: cumulative time
   List reduced from 95 to 20 due to restriction <20>

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
     1000    0.001    0.000    0.049    0.000 manager.py:690(invoke_hook_for_plugin)
     1000    0.002    0.000    0.048    0.000 manager.py:196(execute_plugin)
     ... (top 20 functions)
```

## Output

### Summary Table

The tool prints a formatted table showing:
- **Rows**: One per enabled plugin
- **Columns**: Hook types (abbreviated as P: for Prompt, T: for Tool, R: for Resource)
- **Cells**: Average time in milliseconds per invocation, or "—" if hook not implemented

Example output:

```
================================================================================
PERFORMANCE SUMMARY TABLE
================================================================================

Plugin                            P:post       P:pre      R:post       R:pre      T:post       T:pre
----------------------------------------------------------------------------------------------------
ArgumentNormalizer                     —     0.055ms           —           —           —     0.048ms
CachedToolResultPlugin                 —           —           —           —     0.031ms     0.031ms
CircuitBreaker                         —           —           —           —     0.046ms     0.041ms
CitationValidator                      —           —     0.033ms           —     0.032ms           —
CodeFormatter                          —           —     0.042ms           —     0.033ms           —
CodeSafetyLinterPlugin                 —           —           —           —     0.032ms           —
DenyListPlugin                         —     0.034ms           —           —           —           —
FileTypeAllowlistPlugin                —           —     0.033ms     0.035ms           —           —
HTMLToMarkdownPlugin                   —           —     0.032ms           —           —           —
HarmfulContentDetector                 —     0.072ms           —           —     0.094ms           —
HeaderInjector                         —           —           —     0.035ms           —           —
JSONRepairPlugin                       —           —           —           —     0.031ms           —
LicenseHeaderInjector                  —           —     0.039ms           —     0.032ms           —
MarkdownCleanerPlugin            0.039ms           —     0.038ms           —           —           —
OutputLengthGuardPlugin                —           —           —           —     0.032ms           —
PIIFilterPlugin                  0.046ms     0.102ms           —           —     0.078ms     0.056ms
ReplaceBadWordsPlugin            0.035ms     0.036ms           —           —     0.035ms     0.037ms
ResourceFilterExample                  —           —     0.038ms     0.045ms           —           —
ResponseCacheByPrompt                  —           —           —           —     0.032ms     0.032ms
RetryWithBackoffPlugin                 —           —     0.031ms           —     0.032ms           —
RobotsLicenseGuard                     —           —     0.037ms     0.033ms           —           —
SPARCStaticValidator                   —           —           —           —           —     0.038ms
SQLSanitizer                           —     0.047ms           —           —           —     0.044ms
SafeHTMLSanitizer                      —           —     0.038ms           —           —           —
SchemaGuardPlugin                      —           —           —           —     0.032ms     0.032ms
SecretsDetection                       —     0.050ms     0.041ms           —     0.065ms           —
Summarizer                             —           —     0.034ms           —     0.031ms           —
TimezoneTranslator                     —           —           —           —     0.041ms     0.032ms
URLReputationPlugin                    —           —           —     0.038ms           —           —
VirusTotalURLCheckerPlugin       0.033ms           —     0.033ms     0.038ms     0.033ms           —
Watchdog                               —           —           —           —     0.040ms     0.043ms

================================================================================
LEGEND:
  P: = Prompt hooks   T: = Tool hooks   R: = Resource hooks
  pre/post = Hook timing   — = Not implemented   ERROR = Profiling failed
  All times are average per invocation over 1000 iterations
================================================================================
```

### Profile Files

Individual profile files are saved to `plugins/prof/` directory with naming pattern:
```
{PluginName}_{hook_type}.prof
```

Examples:
- `PIIFilterPlugin_prompt_pre_fetch.prof`
- `ReplaceBadWordsPlugin_tool_pre_invoke.prof`
- `SPARCStaticValidator_tool_pre_invoke.prof`

## Analyzing Profile Files

### View Top Functions

Show the top 20 functions by cumulative time:

```bash
python -c "import pstats; p = pstats.Stats('tests/performance/plugins/prof/PIIFilterPlugin_tool_pre_invoke.prof'); p.strip_dirs().sort_stats('cumulative').print_stats(20)"
```

### Sort By Different Metrics

Sort by different performance metrics:

```python
import pstats

# By cumulative time (default)
p = pstats.Stats('tests/performance/plugins/prof/PIIFilterPlugin_tool_pre_invoke.prof')
p.sort_stats('cumulative').print_stats(20)

# By time spent in function (excluding subcalls)
p.sort_stats('time').print_stats(20)

# By number of calls
p.sort_stats('calls').print_stats(20)

# By function name
p.sort_stats('name').print_stats(20)
```

### Filter to Specific Module

Show only functions from a specific module:

```python
import pstats

p = pstats.Stats('tests/performance/plugins/prof/PIIFilterPlugin_tool_pre_invoke.prof')
p.strip_dirs()
p.sort_stats('cumulative')
p.print_stats('pii_filter')  # Only show pii_filter module functions
```

### Generate Call Graph

Use `gprof2dot` (requires `dot`):

```bash
pip install gprof2dot
gprof2dot -f pstats tests/performance/plugins/prof/SecretsDetection_prompt_pre_fetch.prof | dot -Tsvg -o tests/performance/plugins/prof/SecretsDetection_prompt_pre_fetch.svg
```

Use `snakeviz` for interactive visualization:

```bash
pip install snakeviz
snakeviz tests/performance/plugins/prof/PIIFilterPlugin_tool_pre_invoke.prof
```

This opens an interactive browser-based visualization showing:
- Function call hierarchy
- Time spent in each function
- Call counts

### Generate Flame Graphs

Use `flameprof` for flame graph visualization:

```bash
pip install flameprof
flameprof prof/PIIFilterPlugin_tool_pre_invoke.prof > flamegraph.svg
```

### Analysis Script

Analyze a single profile
```bash
python utils/analyze_profiles.py prof/PIIFilterPlugin_tool_pre_invoke.prof
```

Compare two profiles
```bash
python utils/analyze_profiles.py prof/baseline.prof prof/current.prof --compare
```

Compare all matching profiles between two directories
```bash
python utils/analyze_profiles.py prof_baseline prof_current --compare-all
```

Generate CSV report
```bash
python utils/analyze_profiles.py --all --csv results.csv
```

## Configuration

### Change Iteration Count

Edit `ITERATIONS` constant in `test_plugins_performance.py`:

```python
ITERATIONS = 5000  # Run 5000 iterations instead of 1000
```

Higher iteration counts provide more stable measurements but take longer to run.

### Profile Specific Plugins

To profile only specific plugins, edit `plugins/config.yaml` and set unwanted plugins to `mode: "disabled"`.

### Customize Sample Payloads

Edit the `create_sample_payloads()` function in `test_plugins_performance.py` to test with different input data:

```python
def create_sample_payloads() -> Dict[str, Any]:
    # Customize payloads here
    prompt_pre = PromptPrehookPayload(
        prompt_id="test_prompt",
        args={
            "user": "custom_test_data",
            # ... more args
        },
    )
    # ...
```

## Troubleshooting

### Excessive Logging

Suppress logging to see clean output:

```bash
LOG_LEVEL=ERROR python tests/performance/test_plugins_performance.py 2>/dev/null
```

### Profile Files Not Created

Check that:
1. `prof/` directory exists (created automatically)
2. You have write permissions
3. Plugin manager initializes successfully

### Inconsistent Timings

If timings vary between runs:
1. Increase `ITERATIONS` for more stable measurements
2. Close other applications
3. Run on dedicated hardware
4. Use `time` to verify system load

## Advanced Usage

### Profile Memory Usage

Use `memory_profiler` for memory analysis:

```bash
pip install memory_profiler
python -m memory_profiler tests/performance/test_plugins_performance.py
```
