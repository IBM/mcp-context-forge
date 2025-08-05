## Contributing In General
Our project welcomes external contributions. If you have an itch, please feel
free to scratch it.

To contribute code or documentation, please submit a **FIXME** [pull request](https://github.com/ibm/mcp-context-forge/pulls).

A good way to familiarize yourself with the codebase and contribution process is
to look for and tackle low-hanging fruit in the **FIXME** [issue tracker](https://github.com/ibm/mcp-context-forge/issues).
Before embarking on a more ambitious contribution, please quickly [get in touch](#communication) with us.

**Note: We appreciate your effort, and want to avoid a situation where a contribution
requires extensive rework (by you or by us), sits in backlog for a long time, or
cannot be accepted at all!**

### Proposing new features

If you would like to implement a new feature, please **FIXME** [raise an issue](https://github.com/ibm/mcp-context-forge/issues)
before sending a pull request so the feature can be discussed. This is to avoid
you wasting your valuable time working on a feature that the project developers
are not interested in accepting into the code base.

### Fixing bugs

If you would like to fix a bug, please **FIXME** [raise an issue](https://github.com/ibm/mcp-context-forge/issues) before sending a
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

```
/*
Copyright <holder> All Rights Reserved.

SPDX-License-Identifier: Apache-2.0
*/
```

We have tried to make it as easy as possible to make contributions. This
applies to how we handle the legal aspects of contribution. We use the
same approach - the [Developer's Certificate of Origin 1.1 (DCO)](https://github.com/hyperledger/fabric/blob/master/docs/source/DCO1.1.txt) - that the Linux(r) Kernel [community](https://elinux.org/Developer_Certificate_Of_Origin)
uses to manage code contributions.

We simply ask that when submitting a patch for review, the developer
must include a sign-off statement in the commit message.

Here is an example Signed-off-by line, which indicates that the
submitter accepts the DCO:

```
Signed-off-by: John Doe <john.doe@example.com>
```

You can include this automatically when you commit a change to your
local git repository using the following command:

```
git commit -s
```

## Communication
**FIXME** Please feel free to connect with us on our [Slack channel](link).

## Setup
**FIXME** Please add any special setup instructions for your project to help the developer
become productive quickly.

## Testing
**FIXME** Please provide information that helps the developer test any changes they make
before submitting.

## Coding style guidelines
**FIXME** Optional, but recommended: please share any specific style guidelines you might
have for your project.

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

You can automatically check and fix file headers using the provided `make` targets. For detailed usage and examples, please see the [File Header Management section](../docs/docs/development/module-documentation.md) in our development documentation.
