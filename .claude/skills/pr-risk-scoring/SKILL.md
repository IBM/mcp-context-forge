---
name: pr-risk-scoring
description: Score all open PRs by risk level and generate a CSV report. Use when asked to rescore, rate, or triage open PRs.
---

# PR Risk Scoring

Score all open PRs against a 6-dimension risk rubric and produce a CSV at
`todo/pr_risk_scores.csv`. The full rubric is in `review_rubric.md` in this
skill directory.

## Dimensions

1. **Zone (0-10)** — which files are touched (auth core > transport > data model > business logic > UI > docs)
2. **Size (0-5)** — lines changed and files changed
3. **Structural (0-5)** — migrations, middleware ordering, new routers
4. **Security (0-5)** — security invariant impact
5. **Test Gap (0-5)** — penalty for missing tests with prod code changes
6. **Performance (0-5)** — DB connection pressure, N+1 risks, cache bypasses

**Tiers:** 1-Deep (20-35), 2-Standard (11-19), 3-Focused (5-10), 4-Quick (0-4)

## Process

### 1. Fetch PR metadata

Use `gh pr list` with `--json number,title,url,additions,deletions,changedFiles,author,labels`
and save to a temp file. The default limit is 30 — always use `--limit 500` or
higher. Verify the count matches what GitHub reports.

### 2. Fetch file lists and approvals

For each PR, run `gh pr diff <number> --name-only` and save to a per-PR file.
This makes one API call per PR (~2-3 min for 100+ PRs). Some PRs with empty
diffs will fail — this is expected.

Then fetch approval counts per PR using `gh pr view <number> --json reviews`
and save as a two-column CSV (pr_number,approvals).

### 3. Run the scoring script

```bash
SKILL_DIR="$(git rev-parse --show-toplevel)/.claude/skills/pr-risk-scoring"
OUTPUT="$(git rev-parse --show-toplevel)/todo/pr_risk_scores.csv"
mkdir -p "$(dirname "$OUTPUT")"
python3 "$SKILL_DIR/score_prs.py" /tmp/all_prs.json /tmp/pr_files "$OUTPUT" /tmp/pr_approvals.csv
```

The script prints a tier distribution summary to stdout. Dimensions 3-6 use
filename heuristics only — reviewers should apply the full rubric from
`review_rubric.md` for Tier 1 and Tier 2 PRs.

### 4. Present results

After generating the CSV, present:

1. **Tier distribution** — count of PRs per tier
2. **Top 10 highest-risk PRs** — PR number, total score, tier, and title
3. **Estimated review hours** — Tier 1: 4-8 hrs, Tier 2: 1-2 hrs, Tier 3: 30-60 min, Tier 4: 5-15 min
4. **CSV location** — `todo/pr_risk_scores.csv`

## Maintaining the rubric

If zone mappings or scoring weights need to change, update both:
- `score_prs.py` — source of truth for automated scoring
- `review_rubric.md` — human-readable reference with full rubric detail
