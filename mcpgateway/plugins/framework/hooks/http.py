# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/models/http.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Pydantic models for http hooks and payloads.
"""

# Third-Party
from pydantic import RootModel

# First-Party
from mcpgateway.plugins.framework.models import PluginPayload, PluginResult


class HttpHeaderPayload(RootModel[dict[str, str]], PluginPayload):
    """An HTTP dictionary of headers used in the pre/post HTTP forwarding hooks."""

    def __iter__(self):  # type: ignore[no-untyped-def]
        """Custom iterator function to override root attribute.

        Returns:
            A custom iterator for header dictionary.
        """
        return iter(self.root)

    def __getitem__(self, item: str) -> str:
        """Custom getitem function to override root attribute.

        Args:
            item: The http header key.

        Returns:
            A custom accesser for the header dictionary.
        """
        return self.root[item]

    def __setitem__(self, key: str, value: str) -> None:
        """Custom setitem function to override root attribute.

        Args:
            key: The http header key.
            value: The http header value to be set.
        """
        self.root[key] = value

    def __len__(self) -> int:
        """Custom len function to override root attribute.

        Returns:
            The len of the header dictionary.
        """
        return len(self.root)


HttpHeaderPayloadResult = PluginResult[HttpHeaderPayload]
