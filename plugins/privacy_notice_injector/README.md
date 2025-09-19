# Privacy Notice Injector Plugin

Adds a configurable privacy notice to the rendered prompt by modifying the first user message or inserting a separate message.

Hooks
- prompt_post_fetch

Configuration (example)
```yaml
- name: "PrivacyNoticeInjector"
  kind: "plugins.privacy_notice_injector.privacy_notice_injector.PrivacyNoticeInjectorPlugin"
  hooks: ["prompt_post_fetch"]
  mode: "permissive"
  priority: 60
  config:
    notice_text: "Privacy notice: Do not include PII, secrets, or confidential information."
    placement: "append"             # prepend | append | separate_message
    marker: "[PRIVACY]"             # used to avoid duplicate injection
```

Notes
- Uses `Role.USER` messages; when none exist, appends a new user message with the notice.
- If any message already contains the `marker`, it skips injection to avoid duplicates.
