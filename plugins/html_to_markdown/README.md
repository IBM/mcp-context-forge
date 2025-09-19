# HTML To Markdown Plugin

> Author: Mihai Criveti
> Version: 0.1.0

Converts HTML ResourceContent to Markdown by mapping headings, links, images, and pre/code blocks, and stripping unsafe tags.

## Hooks
- resource_post_fetch

## Example
```yaml
- name: "HTMLToMarkdownPlugin"
  kind: "plugins.html_to_markdown.html_to_markdown.HTMLToMarkdownPlugin"
  hooks: ["resource_post_fetch"]
  mode: "permissive"
  priority: 120
```

## Design
- Applies after resource fetch to convert HTML into Markdown using lightweight regex transforms.
- Handles headings, paragraphs, links, images, and fenced code for <pre><code> blocks.
- Removes <script> and <style> contents and strips remaining tags; normalizes whitespace.

## Limitations
- Regex-based conversion may miss complex structures (nested lists, tables, inline styles).
- Does not preserve CSS-based formatting or JS-rendered content.
- Code language detection for fenced blocks is not attempted.

## TODOs
- Integrate an HTML→Markdown library for better fidelity (tables/lists).
- Add configurable allowlists for tags/attributes to keep in the output.
- Optional mode to emit plain text only (no Markdown).
