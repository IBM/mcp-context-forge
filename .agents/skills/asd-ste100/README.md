# ASD-STE100 Skill — Simplified Technical English for Agent Output

A Claude Code skill that rewrites dense, ambiguous English into [ASD-STE100 Simplified Technical English](https://www.asd-ste100.org/) (STE) — the controlled-language standard the aerospace and defense industry built so aircraft maintenance instructions cannot be misread.

This skill repurposes that same discipline for a different reader: an **AI agent** parsing another agent's output, a tool description, an error message, or an inter-agent instruction, with no human in the loop to resolve ambiguity.

## Why STE, and Why for Agents

STE exists because a misread instruction on an aircraft can kill people, and the intended readers were often not native English speakers with no author to call for clarification. The standard's fix: one meaning per word, active voice, simple tenses, one instruction per sentence, short sentences, no dropped words.

An LLM agent parsing another agent's output is in a strikingly similar position — no back-channel, no way to ask "did you mean X or Y?" The same rules that keep a mechanic from misreading a torque spec keep a downstream agent from misreading a tool description or an inter-agent message.

## Before / After

| Before | After |
|---|---|
| "This tool will attempt to synchronize state across the various backends that have been configured, and if a conflict is detected it may resolve it automatically depending on the strategy that has been set, or otherwise it will surface the conflict for manual review." | "The tool tries to synchronize state across the configured backends. If it finds a conflict, it reads the configured strategy. If the strategy allows automatic resolution, the tool may resolve the conflict without a user. If the tool does not resolve the conflict, it reports the conflict for manual review." |
| "An error may have occurred while processing your request due to a possible mismatch in the expected data format, which could be caused by an outdated client version." | "Your request may have failed. The cause may be a data format that does not match what the server expects. An outdated client can cause this mismatch. Check your client version." |

More examples, including illustrations of the official STE rules themselves, in [`examples/before-after.md`](examples/before-after.md).

## What This Skill Does

1. Picks a mode. **Strict** covers procedures, error messages, and tool descriptions. **STE-flavored** covers READMEs, PR descriptions, and explanatory prose. STE-flavored keeps the sentence discipline but not the fixed-vocabulary lockdown.
2. Reads the input English text for meaning.
3. Flags every rule violation sentence-by-sentence: ambiguous word choice, present-perfect/complex tense, passive voice with an unclear actor, multi-instruction sentences, oversized noun clusters, dropped words, sentences over length, phrasal verbs, nominalized actions, semicolons, hedge stacks, and marketing adjectives.
4. Rewrites each flagged sentence — without dropping any fact, condition, or scope qualifier from the original. If a shorter phrasing would lose required precision, it keeps the longer phrasing and flags the trade-off instead of silently simplifying.
5. Outputs the rewritten text on its own — no preamble, no mode announcement, no change summary — plus a one-line `Kept as-is:` note when it deliberately left something unsimplified.

Ask for the reasoning ("show the diff", "which rules did it break") and it outputs a before/after table naming each rule instead.

The structural rules it checks are mechanical — you can point at the word or punctuation mark that breaks each one. The rules that depend on ASD's dictionary are flagged as advisory rather than enforced, and the rules that need taste are left to you.

The linter checks structural patterns only. It does not compare an original text with a rewrite, verify that requirement strength stayed the same, or prove that the rewrite preserved meaning. A zero-violation result means that the configured structural checks found no problems.

The deterministic linter checks semicolons, a short list of soft phrasal verbs (spin up, reach out, dive into, kick off, circle back, touch base), nominalizations, marketing adjectives, passive voice, present-perfect forms (including irregular participles such as "has run"), long sentences, synonym rotation, and dangling conjunctions in supported list items. It does not check noun-cluster length (that needs part-of-speech tagging) and it does not know phrasal verbs outside its list, so "take off the panel" passes. It never flags hedges or modality.

For the sentence-length check, a word is a whitespace-separated token with at least one letter or digit. Inline code in single backticks, list markers, blockquote markers, and bare punctuation such as a spaced em dash are not words.

The repo's own prose does not lint clean: the rule tables quote the patterns they forbid, and some sentences run long. Lint it with `python scripts/ste-lint.py --baseline 36 SKILL.md` and read the findings as examples, not defects.

The dangling-conjunction rule checks list markers at the start of a line with zero to three leading spaces and ASCII spaces after the marker. It supports unordered markers `-`, `*`, and `+`, and ordered numeric markers that end in `.` or `)`, such as `1.` or `1)`. It checks indented continuation lines up to the final meaningful line. It does not parse list syntax inside blockquotes, lazy continuation, or full nested-list semantics. A standalone line with four or more leading spaces is not treated as a list marker. Within an active list item, indentation at the computed content column is treated as continuation text. Fence detection follows CommonMark for blockquotes and for the fence itself. A fence opens on three or more backticks or tildes, also inside a blockquote. It closes on a run of the same character that is at least as long and has only spaces or tabs after it. A fence in a blockquote closes when the quote ends. In an HTML block, a `>` line is text and opens no fence. An HTML block starts on a block tag such as `<div>`, or on one complete tag alone on its line that does not continue a paragraph. Inline HTML such as `<span>` in a line of text starts no HTML block. In the main pass, no fence opens in an HTML block, at any quote depth. An HTML block can also sit in a blockquote, and it ends when its quote ends. The dangling-conjunction pass also tracks HTML blocks, in a list item and on the line of a list marker too. In an HTML block, no fence opens. A line with less indent than the item ends the item and the HTML block in it. On GitHub, a `<pre>` block holds code, and a comment or a `<?`, `<!X` or CDATA block holds hidden text. If such a block spans several lines, its lines before the last line are no item text, and no list item starts there. An open comment in a list item hides the text up to `-->`, also over the next items, and the text after `-->` joins the item. GitHub does the same. Outside list items, no list item starts in any HTML block. In a list item, the text of another HTML block, such as a `<div>` block, is item text with its tags. GitHub also shows the text of a `<script>`, `<style>` or `<textarea>` block, because it escapes these tags. A list marker there starts an item, and the block goes on in that item, so a fence line in it is still text. This pass does not track an HTML block in a blockquote. The main pass accepts a fence at any indent. It also accepts a closing fence up to three columns deeper than the opening fence, also at the top level. The main pass does not detect a fence on the line of a list marker. Its closing line then opens a fence, and the main pass skips the text after it. The dangling-conjunction pass detects such a fence, also after a tab. It also detects a fence in an empty item. Such a fence ends when the item ends. After a fence on a marker line, later fences in list items also end when their items end. Before that, a fence in a list item can go on after the item ends.

The intentionally invalid examples/linter-edge-cases.md file demonstrates incomplete Markdown list items. Run python scripts/ste-lint.py examples/linter-edge-cases.md to confirm that the linter reports the two expected findings. The file is a test fixture and should not be used as compliant STE prose.

It does **not** reproduce ASD's official ~900-word approved dictionary. The standard is free to obtain but not free to redistribute: Issue 9 permits reproduction only with ASD's written authority, or by eight listed categories of organisation that this project does not belong to. This skill applies the underlying *principle* (plainest available word, used the same way every time) rather than checking against a fixed word list. For certified STE-compliant documentation, use the real standard.

Full rule summary and citations: [`references/writing-rules.md`](references/writing-rules.md).

## Installation

### Quick Install (npx skills)

The fastest way to install this skill is the [skills CLI](https://skills.sh/) — no clone, no path setup. Run it from your project root:

```bash
npx skills add danyuchn/asd-ste100-skill
```

This pulls the skill from the GitHub repo and installs it for the current project. The CLI sends anonymous install telemetry (skill name and timestamp, no personal or device information) to help rank skills on the skills.sh leaderboard. Set `DISABLE_TELEMETRY=1` to opt out.

Update later with `npx skills update`.

### Clone

```bash
git clone https://github.com/danyuchn/asd-ste100-skill ~/.claude/skills/asd-ste100
```

This clones the repo into `~/.claude/skills/`, making the skill available in every Claude Code project. Best for contributors and anyone who wants a live checkout that updates with `git pull`.

## Usage

Trigger with a request to simplify or clarify English text:

```
Disambiguate this tool description
Rewrite this error message so an agent can't misparse it
Apply ASD-STE100 to this instruction
```

Or paste text and ask Claude to "disambiguate this" / "apply STE100 to this" / "reduce ambiguity in this output."

You get the rewritten text back and nothing else. To see which rules were applied, add "show the diff" or "explain the changes" to the request.

## Scope

Built for: agent-to-agent messages, tool/function descriptions, error messages, system prompts, inter-agent instructions — any English text a machine or non-native reader has to parse without a human to ask.

Not built for: creative writing, marketing copy, or anything where voice and nuance are the point — STE is deliberately flat and literal by design.

One limit worth stating up front: this fixes the form of a text, not its substance. A paragraph with nothing to say comes out short, clean, and still empty.

## Other Languages

- **Hebrew:** [g4lb/asd-ste100-hebrew-skill](https://github.com/g4lb/asd-ste100-hebrew-skill) is a Hebrew port of this skill. It includes a Hebrew linter. ASD-STE100 defines English only, so the Hebrew rules are an adaptation, not an official standard.
- **Indonesian:** [jshsinaga/asd-ste100-indonesian-skill](https://github.com/jshsinaga/asd-ste100-indonesian-skill) adapts this skill for Indonesian technical text. Its Indonesian rules are an adaptation, not an official ASD-STE100 standard.

## Related Tools

- [meiluosi/rewrite-fidelity-skill](https://github.com/meiluosi/rewrite-fidelity-skill) compares the original text with the rewrite. It flags changes in meaning and modality. It uses pattern matching, so check each flag yourself.

## Sources

- [ASD-STE100 official site](https://www.asd-ste100.org/)
- [ASD-STE100 — About STE](https://www.asd-ste100.org/about_STE.html)
- [ASD Europe — Simplified Technical English](https://www.asd-europe.org/standards-specifications/simplified-technical-english/)
- [Simplified Technical English — Wikipedia](https://en.wikipedia.org/wiki/Simplified_Technical_English)
- [TechScribe — ASD-STE100 Simplified Technical English](https://www.techscribe.co.uk/techw/asd-simplified-technical-english.htm)

## License

MIT — see [LICENSE](LICENSE).
