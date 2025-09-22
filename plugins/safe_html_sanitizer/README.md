# Safe HTML Sanitizer Plugin

Sanitizes fetched HTML to neutralize common XSS vectors:
- Removes dangerous tags (script, iframe, object, embed, meta, link)
- Strips inline event handlers (on*) and optionally style attributes
- Blocks javascript:, vbscript:, and data: URLs (configurable data:image/*)
- Removes HTML comments (optional)
- Optionally converts sanitized HTML to plain text

Hook
- resource_post_fetch

Configuration (example)
```yaml
- name: "SafeHTMLSanitizer"
  kind: "plugins.safe_html_sanitizer.safe_html_sanitizer.SafeHTMLSanitizerPlugin"
  hooks: ["resource_post_fetch"]
  mode: "enforce"
  priority: 119  # run before HTML→Markdown at 120
  config:
    allowed_tags: ["a","p","div","span","strong","em","code","pre","ul","ol","li","h1","h2","h3","h4","h5","h6","blockquote","img","br","hr","table","thead","tbody","tr","th","td"]
    allowed_attrs:
      "*": ["id","class","title","alt"]
      a: ["href","rel","target"]
      img: ["src","width","height","alt","title"]
    remove_comments: true
    drop_unknown_tags: true
    strip_event_handlers: true
    sanitize_css: true
    allow_data_images: false
    remove_bidi_controls: true
    to_text: false
```

Notes
- For maximum safety, keep `allow_data_images: false` unless images are necessary.
- The sanitizer uses Python's stdlib HTMLParser to rebuild allowed HTML; it avoids regex-only sanitization.
