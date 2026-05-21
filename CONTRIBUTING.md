# CONTRIBUTING

## Contributing In General

Our project welcomes external contributions. If you have an itch, please feel
free to scratch it.

To contribute code or documentation, please submit a [pull request](https://github.com/ibm/mcp-context-forge/pulls).

A good way to familiarize yourself with the codebase and contribution process is
to look for and tackle low-hanging fruit in the [issue tracker](https://github.com/ibm/mcp-context-forge/issues).

**Note: We appreciate your effort, and want to avoid a situation where a contribution
requires extensive rework (by you or by us), sits in backlog for a long time, or
cannot be accepted at all!**

### 🚦 Issue readiness

Do not start implementation on issues labeled `triage`, including issues you
opened. Wait until maintainers accept or scope the issue, remove the `triage`
label, or explicitly invite contributions.

### Proposing new features

If you would like to implement a new feature, please [raise an issue](https://github.com/ibm/mcp-context-forge/issues)
before sending a pull request so the feature can be discussed. This is to avoid
you wasting your valuable time working on a feature that the project developers
are not interested in accepting into the code base.

### Fixing bugs

If you would like to fix a bug, please [raise an issue](https://github.com/ibm/mcp-context-forge/issues) before sending a
pull request so it can be tracked.

## ✅ Pull Request Standards

All pull requests must be reviewable by a human maintainer. The same standard
applies to hand-written, AI-assisted, and agentic changes.

### ✅ Before opening a PR

- Link the issue the PR addresses.
- Confirm the issue is not labeled `triage`.
- Keep the PR focused on one concern.
- Include testing evidence, or explain why testing evidence is not feasible.
- Use `Closes #123` only when the PR fully resolves that issue.

### 📏 Scope and reviewability

Be considerate of reviewer time. A PR is too large when it mixes unrelated
concerns or would take a reviewer too long to understand with confidence.
Thousands of lines of AI-assisted or agent-generated changes can make a PR
effectively unreviewable, even when the intent is good.

If you expect work to become large, open an issue or draft PR before starting.
Describe the intended sequence of changes and ask maintainers how they want the
work split. Large initiatives should be planned as a sequence of reviewable PRs
instead of one broad PR.

Keep tests with the code they validate. Tests should usually be in the same PR
as the behavior change, bug fix, or refactor they cover.

If you find an unrelated bug or improvement while working on a PR, open a new
issue and handle it in a separate PR. Do not expand the current PR to include
unrelated work.

### 🧪 Evidence and description

Every PR must include a clear summary and testing evidence. Provide the commands
you ran and their results. Include screenshots, videos, logs, reproduction steps,
or validation steps where they help reviewers verify the change.

If testing evidence is not feasible, say why in the PR and describe the risk.
Maintainers may ask for more evidence before reviewing or merging.

Keep commits understandable. Squash noisy fixups when they do not help reviewers
or future readers.

### 👀 Maintainer review process

Draft PRs are useful for early feedback, but CI does not run until the PR is
marked ready for review.

All PRs require manual review. Maintainers generally will not review PRs when:

- the issue is still labeled `triage`;
- CI is failing;
- the PR has merge conflicts;
- the scope is unclear or too broad;
- testing evidence is missing;
- unrelated concerns are mixed together.

In these cases, maintainers should ask the author to split, clarify, or update
the PR before doing a detailed review.

### 🌱 First-time contributors

Good first issues are the best place to start. If an issue is unclear, ask on
the issue before investing heavily in an implementation.

### 🤖 AI-assisted and agentic development

AI-assisted and agentic development are allowed. PR owners remain responsible for
understanding, testing, and explaining every change they submit. Do not submit
bulk generated code that you cannot explain or validate.

### Merge approval

The project maintainers use LGTM (Looks Good To Me) in comments on the code
review to indicate acceptance. A change requires an LGTM from at least one
maintainer.

## Legal

We have tried to make it as easy as possible to make contributions. This
applies to how we handle the legal aspects of contribution. We use the
same approach - the [Developer's Certificate of Origin 1.1 (DCO)](https://github.com/hyperledger/fabric/blob/master/docs/source/DCO1.1.txt) - that the Linux(r) Kernel [community](https://elinux.org/Developer_Certificate_Of_Origin)
uses to manage code contributions.

We simply ask that when submitting a patch for review, the developer
must include a sign-off statement in the commit message.

Here is an example Signed-off-by line, which indicates that the
submitter accepts the DCO:

```text
Signed-off-by: John Doe <john.doe@example.com>
```

You can include this automatically when you commit a change to your
local git repository using the following command:

```bash
git commit -s
```
