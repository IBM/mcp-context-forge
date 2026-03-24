# Tool Call Anomaly Detection Plugin

> Author: Anuj Shrivastava
> Version: 0.1.0

Learns per-user/agent tool-calling baselines and flags behavioral anomalies in real time — burst invocations, access to unfamiliar tools, unusual frequency patterns, and off-hours activity.

## Hooks
- `tool_pre_invoke` — Scores the incoming call against the user's baseline; warns or blocks above threshold
- `tool_post_invoke` — Records the call into the baseline and enriches response metadata with risk scores

## Configuration

```yaml
- name: "ToolCallAnomalyDetection"
  kind: "plugins.tool_call_anomaly_detection.tool_call_anomaly_detection.ToolCallAnomalyDetectionPlugin"
  description: "Detects anomalous tool-calling patterns per user/agent using behavioral baselines"
  version: "0.1.0"
  author: "Anuj Shrivastava"
  hooks: ["tool_pre_invoke", "tool_post_invoke"]
  tags: ["security", "anomaly-detection", "behavioral", "audit"]
  mode: "disabled"  # "permissive" to observe, "enforce" to block
  priority: 201
  conditions: []
  config:
    learning_window_seconds: 3600   # Baseline learning period per user
    burst_window_seconds: 60        # Sliding window for burst detection
    burst_threshold: 20             # Max calls in burst window before scoring
    novelty_score_weight: 0.35      # Weight for never-seen-tool signal
    burst_score_weight: 0.35        # Weight for burst-rate signal
    frequency_score_weight: 0.15    # Weight for unusual frequency signal
    block_threshold: 0.8            # Composite score to block (enforce mode)
    warn_threshold: 0.5             # Composite score to warn
    max_history_per_user: 1000      # Max call records kept per user
    off_hours_start: 22             # Off-hours begin (24h)
    off_hours_end: 6                # Off-hours end (24h)
    off_hours_score_bonus: 0.15     # Extra score added during off-hours
    action: "warn"                  # "warn" or "block"
```

## Features

### Behavioral Baseline Learning
During the configurable learning window, the plugin records each user's tool-calling patterns without scoring. After the window closes, deviations from the established baseline are flagged.

### Anomaly Signals
- **Novelty** — Tool name never seen in the user's history
- **Burst** — Call rate exceeds threshold within the sliding window
- **Frequency** — Tool called significantly more than its historical average
- **Off-hours** — Activity outside normal working hours adds a score bonus

### Operating Modes
- **disabled** — Plugin inactive
- **permissive** — Scores and logs anomalies but never blocks
- **enforce** — Blocks calls that exceed `block_threshold`

### Metadata Exposed
- `anomaly_risk_score` — Composite risk score (0.0–1.0)
- `anomaly_signals` — Dict of individual signal scores (novelty, burst, frequency)
- `anomaly_off_hours` — Whether off-hours bonus was applied
- `anomaly_action` — Action taken (allow / warn / block)

## Testing

```bash
pytest tests/unit/plugins/test_tool_call_anomaly_detection.py -v
```
