# Header Injector Plugin

Injects custom HTTP headers into resource fetches by merging into `payload.metadata.headers`.

Hook
- resource_pre_fetch

Configuration (example)
```yaml
- name: "HeaderInjector"
  kind: "plugins.header_injector.header_injector.HeaderInjectorPlugin"
  hooks: ["resource_pre_fetch"]
  mode: "permissive"
  priority: 70
  config:
    headers:
      User-Agent: "MCP-Context-Forge/1.0"
      X-Trace-ID: "{{ uuid4() }}"
    uri_prefixes: ["https://api.example.com/", "https://assets.example.com/"]
```

Notes
- The gateway's resource fetcher should honor `metadata.headers`; this plugin only prepares the metadata.
