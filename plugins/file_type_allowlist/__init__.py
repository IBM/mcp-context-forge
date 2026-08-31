# -*- coding: utf-8 -*-
"""File Type Allowlist Plugin.

Location: ./plugins/file_type_allowlist/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Allows only configured MIME types or file extensions for resource fetches.
Performs checks in pre-fetch (by URI/ext) and post-fetch (by ResourceContent MIME).
"""
