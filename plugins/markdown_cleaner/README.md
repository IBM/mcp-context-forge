# Markdown Cleaner Plugin

> Author: Mihai Criveti
> Version: 0.1.0

Tidies Markdown by normalizing headings, list markers, code fences, and collapsing excess blank lines.

## Hooks
- prompt_post_fetch
- resource_post_fetch

## Design
- Normalizes headings (ensures a space after #), list markers, and collapses 3+ blank lines to 2.
- Removes empty code fences and standardizes newlines.
- Operates on prompt-rendered text and resource text content.

## Limitations
- Does not reflow paragraphs; avoids heavy formatting that might alter meaning.
- Markdown lint rules are minimal and not configurable here.

## TODOs
- Add optional rules for table normalization and hard-wraps.
- Configurable rule set and severity (info/fix/block).
