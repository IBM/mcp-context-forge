# ATR Threat Detection Plugin

Detects AI agent threats using [ATR (Agent Threat Rules)](https://agentthreatrule.org) community rules. Pure regex-based scanning with no external API calls -- typical scan latency is <5ms.

## What It Detects

20 bundled rules covering the OWASP Agentic Top 10:

| Category | Rules | Examples |
|----------|-------|----------|
| Prompt Injection | ATR-00001, 00002, 00003 | Direct injection, indirect via external content, jailbreak |
| Tool Poisoning | ATR-00010, 00011, 00012, 00013, 00061 | Malicious tool output, instruction injection, SSRF, unauthorized calls |
| Context Exfiltration | ATR-00020, 00021, 00075 | System prompt leakage, credential exposure, memory manipulation |
| Agent Manipulation | ATR-00030, 00032 | Cross-agent attacks, goal hijacking |
| Privilege Escalation | ATR-00040, 00041 | Admin function access, scope creep |
| Excessive Autonomy | ATR-00050, 00051, 00052 | Runaway loops, resource exhaustion, cascading failures |
| Skill Compromise | ATR-00060 | Skill impersonation / supply chain attacks |
| Data Poisoning | ATR-00070 | RAG and knowledge base contamination |

## Hooks

- **prompt_pre_fetch** -- Scan prompt arguments for injection attempts
- **tool_pre_invoke** -- Scan tool name and arguments before execution
- **tool_post_invoke** -- Scan tool results for credential leaks, exfiltration, injection
- **resource_post_fetch** -- Scan fetched resource content for embedded threats

## Configuration

```yaml
config:
  block_on_detection: true   # Block when threats detected (true) or just report (false)
  min_severity: "medium"     # Minimum severity to act on: low | medium | high | critical
```

### Modes

| Mode | Behavior |
|------|----------|
| `enforce` | Block on detection, return violation |
| `permissive` | Log findings, allow processing to continue |
| `disabled` | Plugin inactive |

## Example config.yaml entry

```yaml
- name: "ATRThreatDetection"
  kind: "plugins.atr_threat_detection.atr_threat_detection.ATRThreatDetectionPlugin"
  description: "Detects AI agent threats using ATR community rules (regex-based)"
  version: "0.1.0"
  author: "ATR Project"
  hooks: ["prompt_pre_fetch", "tool_pre_invoke", "tool_post_invoke", "resource_post_fetch"]
  tags: ["security", "atr", "agent-threats", "threat-detection"]
  mode: "disabled"
  priority: 53
  conditions: []
  config:
    block_on_detection: true
    min_severity: "medium"
```

## How It Works

1. Rules are loaded from `rules.json` at initialization (20 rules, ~60 regex patterns).
2. On each hook invocation, the payload is flattened to text.
3. Each rule's compiled patterns are tested against the text.
4. If any rule matches and meets the severity threshold, a violation is returned (or metadata if in permissive mode).

## Complementary Plugins

- **secrets_detection** -- Detects API keys, tokens, and credentials
- **encoded_exfil_detection** -- Detects base64/hex encoded exfiltration payloads

ATR threat detection focuses on *behavioral* attack patterns (prompt injection, goal hijacking, privilege escalation) while the above plugins focus on *data-level* indicators.

## Source

Rules are from the [ATR Project](https://agentthreatrule.org) (MIT licensed), a community-driven open standard for AI agent threat detection with 108+ rules covering 9 threat categories.
