# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/validators.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Madhav Kandukuri

SecurityValidator for MCP Gateway
This module re-exports the SecurityValidator class from mcpgateway.common.validators
for backward compatibility.

The canonical location for SecurityValidator is mcpgateway.common.validators.
This module exists to maintain backward compatibility with code that imports from
mcpgateway.validators.

Example usage:
    >>> from mcpgateway.validators import SecurityValidator
    >>> SecurityValidator.sanitize_display_text('<b>Test</b>', 'test')
    '&lt;b&gt;Test&lt;/b&gt;'
    >>> SecurityValidator.validate_name('valid_name-123', 'test')
    'valid_name-123'
    >>> SecurityValidator.validate_identifier('my.test.id_123', 'test')
    'my.test.id_123'
    >>> SecurityValidator.validate_json_depth({'a': {'b': 1}})
    >>> SecurityValidator.validate_json_depth({'a': 1})
"""

# First-Party
# Re-export SecurityValidator from canonical location
# pylint: disable=unused-import
from mcpgateway.common.validators import SecurityValidator  # noqa: F401

__all__ = ["SecurityValidator"]
