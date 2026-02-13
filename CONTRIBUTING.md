# CONTRIBUTING

## Contributing In General

Our project welcomes external contributions. If you have an itch, please feel
free to scratch it.

To contribute code or documentation, please submit a [pull request](https://github.com/ibm/mcp-context-forge/pulls).

A good way to familiarize yourself with the codebase and contribution process is
to look for and tackle low-hanging fruit in the [issue tracker](https://github.com/ibm/mcp-context-forge/issues).
Before embarking on a more ambitious contribution, please quickly [get in touch](#communication) with us.

**Note: We appreciate your effort, and want to avoid a situation where a contribution
requires extensive rework (by you or by us), sits in backlog for a long time, or
cannot be accepted at all!**

### Proposing new features

If you would like to implement a new feature, please [raise an issue](https://github.com/ibm/mcp-context-forge/issues)
before sending a pull request so the feature can be discussed. This is to avoid
you wasting your valuable time working on a feature that the project developers
are not interested in accepting into the code base.

### Fixing bugs

If you would like to fix a bug, please [raise an issue](https://github.com/ibm/mcp-context-forge/issues) before sending a
pull request so it can be tracked.

### Merge approval

The project maintainers use LGTM (Looks Good To Me) in comments on the code
review to indicate acceptance. A change requires LGTMs from two of the
maintainers of each component affected.

For a list of the maintainers, see the [MAINTAINERS.md](MAINTAINERS.md) page.

## Legal

Each source file must include a license header for the Apache
Software License 2.0. Using the SPDX format is the simplest approach.
e.g.

```python
# Copyright <holder> All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
```

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

## Communication

Please feel free to connect with us through the [issue tracker](https://github.com/ibm/mcp-context-forge/issues).

## Setup

For setup instructions, please see the [Quick Start sections](README.md#quick-start---pypi) in the README, or refer to the [Installation](README.md#installation) section for detailed instructions.

## Testing

Before submitting changes, run the test suite as outlined in the [Bug-fix PR template](.github/PULL_REQUEST_TEMPLATE/bug_fix.md):

1. `make lint` - passes all linters
2. `make test` - all unit + integration tests green
3. `make coverage` - ≥ 90%

## Coding style guidelines

- **Python >= 3.11** with type hints
- **Formatting**: Black (line length 200), isort (profile=black)
- **Linting**: Ruff, Pylint per `pyproject.toml`
- **Naming**: `snake_case` functions, `PascalCase` classes, `UPPER_CASE` constants

See [CLAUDE.md](CLAUDE.md#code-style--standards) for complete coding standards.

### Python File Headers

All Python source files (`.py`) must begin with the following standardized header. This ensures consistency and proper licensing across the codebase.

The header format is as follows:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module Description.
Location: ./path/to/your/file.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: "Author One, Author Two"

Your detailed module documentation begins here...
"""
```

You can automatically check and fix file headers using the provided `make` targets. For detailed usage and examples, please see the [File Header Management section](docs/docs/development/module-documentation.md) in our development documentation.
