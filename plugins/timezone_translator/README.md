# Timezone Translator Plugin

Converts detected ISO-like timestamps between server and user timezones.

Hooks
- tool_pre_invoke (to_server)
- tool_post_invoke (to_user)

Configuration (example)
```yaml
- name: "TimezoneTranslator"
  kind: "plugins.timezone_translator.timezone_translator.TimezoneTranslatorPlugin"
  hooks: ["tool_pre_invoke", "tool_post_invoke"]
  mode: "permissive"
  priority: 175
  config:
    user_tz: "America/New_York"
    server_tz: "UTC"
    direction: "to_user"   # or "to_server"
    fields: ["start_time", "end_time"]
```

Notes
- Matches ISO-like timestamps only; non-ISO formats pass through unchanged.
