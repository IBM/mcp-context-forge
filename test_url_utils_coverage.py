#!/usr/bin/env python3
"""Quick test to cover the missing line in url_utils.py"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from mcpgateway.utils.url_utils import get_protocol_from_request
from unittest.mock import Mock

# Create mock request without x-forwarded-proto header
mock_request = Mock()
mock_request.headers = {}
mock_request.url.scheme = "https"

# This should hit the return request.url.scheme line
result = get_protocol_from_request(mock_request)
print(f"Protocol: {result}")