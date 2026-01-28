# License Header Injector Plugin

Injects a language-appropriate license header into code outputs.

Hooks
- tool_post_invoke
- resource_post_fetch

Configuration (example)
```yaml
- name: "LicenseHeaderInjector"
  kind: "plugins.license_header_injector.license_header_injector.LicenseHeaderInjectorPlugin"
  hooks: ["tool_post_invoke", "resource_post_fetch"]
  mode: "permissive"
  priority: 185
  config:
    header_template: |
      SPDX-License-Identifier: Apache-2.0
      Copyright (c) 2025
    languages: ["python", "javascript", "typescript", "go", "java", "c", "cpp", "shell"]
    max_size_kb: 512
    dedupe_marker: "SPDX-License-Identifier:"
```

Notes
- Uses simple comment prefixes/suffixes per language; defaults to `#` style if unknown.
- Skips if `dedupe_marker` already exists in the text.
