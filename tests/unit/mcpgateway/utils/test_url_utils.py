import pytest
from unittest.mock import Mock
from mcpgateway.utils.url_utils import get_protocol_from_request


@pytest.mark.parametrize("headers, expected",
                         [({"x-forwarded-proto": "http"}, "http"),  # case with header
                          ({}, "https"),  # fallback to request.url.scheme
    ],
)
def test_get_protocol_from_request(headers, expected):
    """Test get_protocol_from_request with and without x-forwarded-proto header."""
    mock_request = Mock()
    mock_request.headers = headers
    mock_request.url.scheme = "https"

    result = get_protocol_from_request(mock_request)
    assert result == expected
