# Policy Templates Library Plugin

A comprehensive library of pre-built, compliance-ready policy templates for MCP Context Forge.

## Overview

The Policy Templates Library plugin provides 20+ production-quality policy templates covering:

- **HIPAA / HITECH** — PHI protection, audit logging, data access controls
- **PCI-DSS** — Cardholder data protection, network segmentation
- **SOX** — Financial controls, separation of duties
- **GDPR** — Data subject rights, consent management
- **RBAC** — Basic, hierarchical, and dynamic role-based access control
- **ABAC** — Attribute-based, time-based, and location-based access control
- **MCP-Specific** — Tool access tiers, server isolation, agent permissions, resource quotas
- **Industry** — Healthcare clinical access, finance trading controls, government clearance-based access

## Architecture

```
plugins/policy_templates/
├── __init__.py              # Public API exports
├── policy_templates.py      # Main plugin class (PolicyTemplateLibraryPlugin)
├── models.py                # Pydantic domain models
├── registry.py              # In-memory template registry (load/search/filter)
├── instantiator.py          # Template rendering with parameter substitution
├── test_runner.py           # Mock policy evaluation for embedded test cases
├── recommender.py           # Template recommendation and gap analysis
├── plugin-manifest.yaml     # Plugin metadata
└── templates/               # YAML template files
    ├── compliance/
    │   ├── hipaa/
    │   ├── pci-dss/
    │   ├── sox/
    │   └── gdpr/
    ├── rbac/
    ├── abac/
    ├── mcp-specific/
    └── industry/
        ├── healthcare/
        ├── finance/
        └── government/
```

## Configuration

Add to `plugins/config.yaml`:

```yaml
- name: "PolicyTemplateLibrary"
  kind: "plugins.policy_templates.policy_templates.PolicyTemplateLibraryPlugin"
  hooks: ["startup"]
  mode: "disabled"
  priority: 90
  config:
    template_dirs:
      - "plugins/policy_templates/templates"
    validate_on_instantiate: true
    run_tests_before_deploy: true
```

## Usage

### Accessing the Plugin

```python
from mcpgateway.plugins.framework import get_plugin_manager

pm = get_plugin_manager()
plugin = pm.get_plugin("PolicyTemplateLibrary")
```

### Listing Templates

```python
registry = plugin.get_registry()
for template in registry.list_all():
    print(template.metadata.name, template.metadata.category)
```

### Searching Templates

```python
results = registry.search("hipaa")
by_framework = registry.get_by_compliance("PCI-DSS")
categories = registry.list_categories()
```

### Instantiating a Template

```python
policy = plugin.instantiate("hipaa-phi-protection", {
    "phi_resource_pattern": "phi-*",
    "healthcare_roles": ["physician", "nurse", "admin"],
    "audit_all_access": True,
})
print(policy.policy_content)
```

### Running Tests

```python
report = plugin.run_tests("hipaa-phi-protection")
print(f"Tests: {report.passed}/{report.total} passed")
for result in report.results:
    status = "PASS" if result.passed else "FAIL"
    print(f"  [{status}] {result.test_name}: {result.reason}")
```

### Template Recommendations

```python
from plugins.policy_templates.models import RequirementsSpec

requirements = RequirementsSpec(
    compliance_frameworks=["HIPAA", "SOX"],
    industry="healthcare",
    risk_levels=["high", "critical"],
)
recommendations = plugin.recommend(requirements)
for rec in recommendations:
    print(f"{rec.template_name} (score={rec.score:.2f}): {rec.reason}")
```

### Gap Analysis

```python
analysis = plugin.analyze_gaps(
    requirements=requirements,
    deployed_categories=["compliance/hipaa"],
)
print(f"Coverage: {analysis.coverage_score:.0%}")
for gap in analysis.gaps:
    print(f"Gap in {gap.framework}: missing {gap.missing_categories}")
```

## Template Format

Templates are YAML files with the following structure:

```yaml
apiVersion: contextforge.io/v1
kind: PolicyTemplate
metadata:
  name: my-policy-template
  version: 1.0.0
  description: "Description of what this template enforces"
  category: compliance/hipaa
  compliance_frameworks: [HIPAA]
  risk_level: high
  author: ContextForge Security Team
  last_reviewed: "2024-01-15"
spec:
  engine: cedar  # cedar | opa | native
  parameters:
    - name: my_param
      type: string  # string | list | boolean | integer | dict
      description: "Parameter description"
      default: "default-value"
      required: true
  template: |
    // Policy body with {my_param} substitution
  validation:
    - rule: "my_param must not be empty"
      check: "len(parameters.get('my_param', '')) > 0"
  tests:
    - name: "Test description"
      given:
        principal:
          role: admin
        action: read
        resource: my-resource
      expect: allow  # allow | deny
```

## Dependencies

- Python >= 3.11
- pydantic >= 2.0
- PyYAML
