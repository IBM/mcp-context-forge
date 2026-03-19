# -*- coding: utf-8 -*-
"""Module Description.
Location: ./tests/unit/mcpgateway/utils/test_retry_manager.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Module documentation...
"""

# Standard
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.retry_manager import NON_RETRYABLE_STATUS_CODES, ResilientHttpClient, RETRYABLE_STATUS_CODES


@pytest.fixture
def client():
    return ResilientHttpClient(max_retries=settings.retry_max_attempts, base_backoff=settings.retry_base_delay, max_delay=settings.retry_max_delay, jitter_max=settings.retry_jitter_max)


def test_client_init_uses_provided_limits():
    """If client_args includes limits, ResilientHttpClient shouldn't override them."""
    limits = httpx.Limits(max_connections=1, max_keepalive_connections=1, keepalive_expiry=1.0)
    with patch("mcpgateway.utils.retry_manager.httpx.AsyncClient") as mock_async_client:
        client = ResilientHttpClient(client_args={"limits": limits})
        assert client.client_args["limits"] is limits
        assert mock_async_client.call_args.kwargs["limits"] is limits


@pytest.mark.asyncio
async def test_successful_request_no_retry(client):
    with patch.object(client.client, "request", new=AsyncMock(return_value=httpx.Response(200))) as mock_req:
        resp = await client.get("http://example.com")
        assert resp.status_code == 200
        assert mock_req.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", list(RETRYABLE_STATUS_CODES))
async def test_retry_on_retryable_status(client, status_code):
    # Always return retryable error, until max_retries reached
    mock_response = httpx.Response(status_code)
    with patch.object(client.client, "request", new=AsyncMock(return_value=mock_response)) as mock_req:
        with patch("asyncio.sleep", new=AsyncMock()):  # skip actual sleep
            resp = await client.get("http://retry.com")
            assert resp.status_code == status_code
            assert mock_req.call_count == client.max_retries


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", list(NON_RETRYABLE_STATUS_CODES))
async def test_no_retry_on_non_retryable_status(client, status_code):
    mock_response = httpx.Response(status_code)
    with patch.object(client.client, "request", new=AsyncMock(return_value=mock_response)) as mock_req:
        resp = await client.get("http://no-retry.com")
        assert mock_req.call_count == 1
        assert resp.status_code == status_code


@pytest.mark.asyncio
async def test_retry_after_header_respected(client):
    mock_resp = httpx.Response(429, headers={"Retry-After": "2"})

    with patch.object(client.client, "request", new=AsyncMock(return_value=mock_resp)) as mock_req:
        with patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
            await client.get("http://retry-after.com")
            assert mock_sleep.call_args_list[0][0][0] == 2.0
            assert mock_req.call_count == client.max_retries


@pytest.mark.asyncio
async def test_max_retry_reached_raises_exception(client):
    failing_func = AsyncMock(side_effect=httpx.ConnectTimeout("Connection failed"))

    with patch.object(client.client, "request", new=failing_func):
        with patch("asyncio.sleep", new=AsyncMock()):
            with pytest.raises(httpx.ConnectTimeout):
                await client.get("http://fail.com")
            assert failing_func.call_count == client.max_retries


@pytest.mark.asyncio
async def test_jitter_applied_properly():
    retry_max_attempts = 3
    retry_base_delay = 1.0
    retry_max_delay = 60.0
    retry_jitter_max = 5.5

    client = ResilientHttpClient(max_retries=retry_max_attempts, base_backoff=retry_base_delay, max_delay=retry_max_delay, jitter_max=retry_jitter_max)

    delays = []

    async def fake_sleep_with_jitter(base, jitter):
        delay = base + 0.1  # simulate some jitter
        delays.append(delay)

    mock_response = httpx.Response(503)

    with patch.object(client.client, "request", new=AsyncMock(return_value=mock_response)):
        with patch.object(client, "_sleep_with_jitter", new=fake_sleep_with_jitter):
            await client.get("http://jitter-test.com")

    assert len(delays) == client.max_retries
    for i, delay in enumerate(delays):
        expected_min = client.base_backoff * (2**i)
        assert expected_min <= delay <= min(expected_min + client.base_backoff * client.jitter_max, client.max_delay)


@pytest.mark.asyncio
async def test_retry_on_network_error():
    client = ResilientHttpClient()
    mock = AsyncMock(side_effect=httpx.ConnectTimeout("Timeout"))

    with patch.object(client.client, "request", new=mock):
        with patch("asyncio.sleep", new=AsyncMock()):
            with pytest.raises(httpx.ConnectTimeout):
                await client.get("http://network-error.com")
            assert mock.call_count == client.max_retries


@pytest.mark.asyncio
async def test_success_after_one_retry():
    client = ResilientHttpClient()

    responses = [httpx.Response(503), httpx.Response(200)]
    mock = AsyncMock(side_effect=responses)

    with patch.object(client.client, "request", new=mock):
        with patch("asyncio.sleep", new=AsyncMock()):
            resp = await client.get("http://succeed-later.com")
            assert resp.status_code == 200
            assert mock.call_count == 2


@pytest.mark.asyncio
async def test_backoff_delay_never_exceeds_max():
    retry_max_attempts = 3
    retry_base_delay = 30
    retry_max_delay = 40
    client = ResilientHttpClient(max_retries=retry_max_attempts, base_backoff=retry_base_delay, max_delay=retry_max_delay, jitter_max=5.5)

    delays = []

    async def fake_sleep(delay):
        delays.append(delay)

    mock = AsyncMock(return_value=httpx.Response(503))

    with patch.object(client.client, "request", new=mock):
        with patch("asyncio.sleep", new=fake_sleep):
            await client.get("http://cap-delay.com")

    for delay in delays:
        assert delay <= client.max_delay


@pytest.mark.asyncio
async def test_empty_response_handling():
    client = ResilientHttpClient()
    resp = httpx.Response(200, content=b"")

    with patch.object(client.client, "request", new=AsyncMock(return_value=resp)):
        result = await client.get("http://empty.com")
        assert result.status_code == 200
        assert result.content == b""


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
async def test_all_methods(method):
    client = ResilientHttpClient()
    response = httpx.Response(200)

    with patch.object(client.client, "request", new=AsyncMock(return_value=response)) as mock_req:
        await getattr(client, method.lower())("http://test.com", params={"x": 1})
        mock_req.assert_called_once()
        assert mock_req.call_args[0][0] == method


@pytest.mark.asyncio
async def test_non_httpx_exception_does_not_retry():
    client = ResilientHttpClient()

    with patch.object(client.client, "request", new=AsyncMock(side_effect=RuntimeError("boom"))):
        with pytest.raises(RuntimeError):
            await client.get("http://explode.com")


@pytest.mark.asyncio
async def test_invalid_retry_config_gracefully_limits():
    client = ResilientHttpClient(max_retries=1, base_backoff=-1, jitter_max=2.0)
    response = httpx.Response(503)

    with patch.object(client.client, "request", new=AsyncMock(return_value=response)):
        with patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
            await client.get("http://bad-config.com")
            # Still attempts one retry
            assert mock_sleep.call_count == 1


@pytest.mark.asyncio
async def test_retry_stops_on_first_success():
    client = ResilientHttpClient()
    responses = [httpx.Response(503), httpx.Response(200), httpx.Response(200)]
    mock = AsyncMock(side_effect=responses)

    with patch.object(client.client, "request", new=mock):
        with patch("asyncio.sleep", new=AsyncMock()):
            resp = await client.get("http://early-exit.com")
            assert resp.status_code == 200
            assert mock.call_count == 2  # stops at first success


@pytest.mark.asyncio
async def test_429_without_retry_after_header():
    client = ResilientHttpClient()
    response = httpx.Response(429, headers={})
    mock = AsyncMock(return_value=response)

    with patch.object(client.client, "request", new=mock):
        with patch("asyncio.sleep", new=AsyncMock()):
            await client.get("http://429-no-header.com")
            assert mock.call_count == client.max_retries


@pytest.mark.asyncio
async def test_exponential_backoff_increases_delay():
    client = ResilientHttpClient(base_backoff=1.0, jitter_max=0.0)
    delays = []

    async def fake_sleep_with_jitter(base, jitter):
        delays.append(base)  # no jitter, just test base

    response = httpx.Response(503)

    with patch.object(client.client, "request", new=AsyncMock(return_value=response)):
        with patch.object(client, "_sleep_with_jitter", new=fake_sleep_with_jitter):
            await client.get("http://backoff.com")

    expected_delays = [1 * (2**i) for i in range(client.max_retries)]
    assert delays == expected_delays


@pytest.mark.asyncio
async def test_stream_success(monkeypatch):
    client = ResilientHttpClient(max_retries=3, base_backoff=0.1, max_delay=1, jitter_max=0)

    class AsyncContextManager:
        async def __aenter__(self):
            resp = SimpleNamespace(status_code=200, is_success=True, aiter_bytes=lambda: asyncio.as_completed([b"data"]))
            return resp

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def mock_stream(*args, **kwargs):
        # Return the async context manager instance directly (not coroutine)
        return AsyncContextManager()

    monkeypatch.setattr(client.client, "stream", mock_stream)

    async with client.stream("GET", "http://example.com") as resp:
        assert resp.status_code == 200
        assert resp.is_success


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [201, 204])
async def test_success_codes_not_in_lists(code):
    client = ResilientHttpClient()
    response = httpx.Response(code)

    with patch.object(client.client, "request", new=AsyncMock(return_value=response)):
        result = await client.get("http://success-code.com")
        assert result.status_code == code


@pytest.mark.asyncio
async def test_custom_client_args():
    client = ResilientHttpClient(client_args={"headers": {"X-Test": "1"}, "timeout": 5.0})
    assert isinstance(client.client, httpx.AsyncClient)
    assert client.client.headers["X-Test"] == "1"
    assert client.client.timeout is not None


@pytest.mark.asyncio
async def test_request_kwargs_passed():
    client = ResilientHttpClient()
    mock = AsyncMock(return_value=httpx.Response(200))

    with patch.object(client.client, "request", new=mock):
        await client.post("http://kwarg.com", json={"foo": "bar"}, headers={"X-Test": "1"})
        args, kwargs = mock.call_args
        assert kwargs["json"] == {"foo": "bar"}
        assert kwargs["headers"]["X-Test"] == "1"


@pytest.mark.asyncio
async def test_context_manager_closes_properly(client):
    with patch.object(client.client, "aclose", new=AsyncMock()) as mock_close:
        async with client:
            pass
        mock_close.assert_called_once()


@pytest.mark.asyncio
async def test_non_retryable_status_code_logging():
    """Test that non-retryable status codes are logged correctly."""
    client = ResilientHttpClient()

    with patch("mcpgateway.utils.retry_manager.logger") as mock_logger:
        # Test with a non-retryable status code
        response_400 = SimpleNamespace(status_code=400)
        result = client._should_retry(Exception(), response_400)

        assert result is False
        mock_logger.info.assert_called_once_with("Response 400: Not retrying.")


@pytest.mark.asyncio
async def test_successful_response_return_when_not_retryable():
    """Test that successful responses are returned immediately when not retryable."""
    client = ResilientHttpClient(max_retries=3)

    # Create a response that's not in retryable codes and _should_retry returns False
    response_418 = httpx.Response(418)  # I'm a teapot - not in retryable codes

    with patch.object(client.client, "request", new=AsyncMock(return_value=response_418)) as mock_req:
        result = await client.get("http://teapot.com")

        assert result.status_code == 418
        assert mock_req.call_count == 1  # Should not retry


@pytest.mark.asyncio
async def test_stream_429_retry_after_header_handling(monkeypatch):
    """Test stream method handling of 429 responses with Retry-After headers."""
    client = ResilientHttpClient(max_retries=3, base_backoff=0.1, max_delay=1, jitter_max=0)

    call_count = 0

    class AsyncContextManager:
        async def __aenter__(self):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # First call: return 429 with Retry-After header
                resp = SimpleNamespace(status_code=429, is_success=False, headers={"Retry-After": "2"})
                return resp
            else:
                # Second call: return success
                resp = SimpleNamespace(status_code=200, is_success=True, aiter_bytes=lambda: asyncio.as_completed([b"data"]))
                return resp

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def mock_stream(*args, **kwargs):
        return AsyncContextManager()

    monkeypatch.setattr(client.client, "stream", mock_stream)

    with patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
        async with client.stream("GET", "http://ratelimit.com") as resp:
            assert resp.status_code == 200
            assert resp.is_success

    # Should have slept for the Retry-After duration
    mock_sleep.assert_called_with(2.0)


@pytest.mark.asyncio
async def test_stream_429_retry_after_invalid_value(monkeypatch):
    """Test stream method handling of 429 responses with invalid Retry-After headers."""
    client = ResilientHttpClient(max_retries=3, base_backoff=0.1, max_delay=1, jitter_max=0)

    call_count = 0

    class AsyncContextManager:
        async def __aenter__(self):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # First call: return 429 with invalid Retry-After header
                resp = SimpleNamespace(status_code=429, is_success=False, headers={"Retry-After": "invalid"})
                return resp
            else:
                # Second call: return success
                resp = SimpleNamespace(status_code=200, is_success=True, aiter_bytes=lambda: asyncio.as_completed([b"data"]))
                return resp

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def mock_stream(*args, **kwargs):
        return AsyncContextManager()

    # Mock _sleep_with_jitter to handle the single argument call
    async def mock_sleep_with_jitter(*args):
        pass  # Do nothing, just handle the call

    monkeypatch.setattr(client.client, "stream", mock_stream)
    monkeypatch.setattr(client, "_sleep_with_jitter", mock_sleep_with_jitter)

    async with client.stream("GET", "http://invalid-retry.com") as resp:
        assert resp.status_code == 200
        assert resp.is_success


@pytest.mark.asyncio
async def test_stream_non_retryable_response_handling(monkeypatch):
    """Test stream method handling of non-retryable responses."""
    client = ResilientHttpClient(max_retries=3, base_backoff=0.1, max_delay=1, jitter_max=0)

    class AsyncContextManager:
        async def __aenter__(self):
            # Return a non-retryable error response (404)
            resp = SimpleNamespace(status_code=404, is_success=False, headers={})
            return resp

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def mock_stream(*args, **kwargs):
        return AsyncContextManager()

    monkeypatch.setattr(client.client, "stream", mock_stream)

    # Should yield the non-retryable response once and return
    async with client.stream("GET", "http://notfound.com") as resp:
        assert resp.status_code == 404
        assert not resp.is_success


@pytest.mark.asyncio
async def test_stream_retryable_response_handling(monkeypatch):
    """Test stream method handling of retryable responses."""
    client = ResilientHttpClient(max_retries=2, base_backoff=0.1, max_delay=1, jitter_max=0)

    call_count = 0

    class AsyncContextManager:
        async def __aenter__(self):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # First call: return retryable error response (503)
                resp = SimpleNamespace(status_code=503, is_success=False, headers={})
                return resp
            else:
                # Second call: return success
                resp = SimpleNamespace(status_code=200, is_success=True, aiter_bytes=lambda: asyncio.as_completed([b"data"]))
                return resp

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def mock_stream(*args, **kwargs):
        return AsyncContextManager()

    # Mock _sleep_with_jitter to handle the single argument call
    async def mock_sleep_with_jitter(*args):
        pass  # Do nothing, just handle the call

    monkeypatch.setattr(client.client, "stream", mock_stream)
    monkeypatch.setattr(client, "_sleep_with_jitter", mock_sleep_with_jitter)

    async with client.stream("GET", "http://retryable.com") as resp:
        assert resp.status_code == 200
        assert resp.is_success


@pytest.mark.asyncio
async def test_stream_exception_handling_retryable(monkeypatch):
    """Test stream method handling of retryable exceptions."""
    client = ResilientHttpClient(max_retries=2, base_backoff=0.1, max_delay=1, jitter_max=0)

    call_count = 0

    def mock_stream(*args, **kwargs):
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            # First call: raise retryable exception
            raise httpx.ConnectTimeout("Connection timeout")
        else:
            # Second call: return success
            class AsyncContextManager:
                async def __aenter__(self):
                    resp = SimpleNamespace(status_code=200, is_success=True, aiter_bytes=lambda: asyncio.as_completed([b"data"]))
                    return resp

                async def __aexit__(self, exc_type, exc, tb):
                    return False

            return AsyncContextManager()

    # Mock _sleep_with_jitter to handle the single argument call
    async def mock_sleep_with_jitter(*args):
        pass  # Do nothing, just handle the call

    monkeypatch.setattr(client.client, "stream", mock_stream)
    monkeypatch.setattr(client, "_sleep_with_jitter", mock_sleep_with_jitter)

    async with client.stream("GET", "http://timeout.com") as resp:
        assert resp.status_code == 200
        assert resp.is_success


@pytest.mark.asyncio
async def test_stream_exception_handling_non_retryable(monkeypatch):
    """Test stream method handling of non-retryable exceptions."""
    client = ResilientHttpClient(max_retries=3, base_backoff=0.1, max_delay=1, jitter_max=0)

    def mock_stream(*args, **kwargs):
        # Raise non-retryable exception
        raise ValueError("Invalid parameter")

    monkeypatch.setattr(client.client, "stream", mock_stream)

    # Should raise the exception immediately without retry
    with pytest.raises(ValueError, match="Invalid parameter"):
        async with client.stream("GET", "http://invalid.com") as resp:
            pass


@pytest.mark.asyncio
async def test_stream_max_retries_with_exception(monkeypatch):
    """Test stream method when max retries is reached with exceptions."""
    client = ResilientHttpClient(max_retries=2, base_backoff=0.1, max_delay=1, jitter_max=0)

    def mock_stream(*args, **kwargs):
        # Always raise retryable exception
        raise httpx.ConnectTimeout("Connection timeout")

    # Mock _sleep_with_jitter to handle the single argument call
    async def mock_sleep_with_jitter(*args):
        pass  # Do nothing, just handle the call

    monkeypatch.setattr(client.client, "stream", mock_stream)
    monkeypatch.setattr(client, "_sleep_with_jitter", mock_sleep_with_jitter)

    # Should raise RuntimeError wrapping the last exception
    with pytest.raises(RuntimeError):
        async with client.stream("GET", "http://always-timeout.com") as resp:
            pass


@pytest.mark.asyncio
async def test_stream_max_retries_no_exception(monkeypatch):
    """Test stream method when max retries is reached without exceptions."""
    client = ResilientHttpClient(max_retries=2, base_backoff=0.1, max_delay=1, jitter_max=0)

    class AsyncContextManager:
        async def __aenter__(self):
            # Always return retryable error response (503)
            resp = SimpleNamespace(status_code=503, is_success=False, headers={})
            return resp

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def mock_stream(*args, **kwargs):
        return AsyncContextManager()

    # Mock _sleep_with_jitter to handle the single argument call
    async def mock_sleep_with_jitter(*args):
        pass  # Do nothing, just handle the call

    monkeypatch.setattr(client.client, "stream", mock_stream)
    monkeypatch.setattr(client, "_sleep_with_jitter", mock_sleep_with_jitter)

    # Should raise RuntimeError for max retries reached
    with pytest.raises(RuntimeError, match="Max retries reached opening stream"):
        async with client.stream("GET", "http://always-503.com") as resp:
            pass


@pytest.mark.asyncio
async def test_stream_sleep_with_jitter_single_argument(monkeypatch):
    """Test that _sleep_with_jitter is called with arguments in stream method."""
    client = ResilientHttpClient(max_retries=2, base_backoff=0.1, max_delay=1, jitter_max=0.1)

    class AsyncContextManager:
        async def __aenter__(self):
            # Return retryable error response (503)
            resp = SimpleNamespace(status_code=503, is_success=False, headers={})
            return resp

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def mock_stream(*args, **kwargs):
        return AsyncContextManager()

    monkeypatch.setattr(client.client, "stream", mock_stream)

    # Mock _sleep_with_jitter to capture calls
    sleep_calls = []

    async def mock_sleep_with_jitter(*args):
        sleep_calls.append(args)

    monkeypatch.setattr(client, "_sleep_with_jitter", mock_sleep_with_jitter)

    with pytest.raises(RuntimeError, match="Max retries reached opening stream"):
        async with client.stream("GET", "http://always-503.com") as resp:
            pass

    # Should have called _sleep_with_jitter with arguments (backoff + jitter range)
    assert len(sleep_calls) == 2  # Two retry attempts
    for call_args in sleep_calls:
        assert len(call_args) == 2  # arguments (backoff + jitter range)
        # Verify the argument is a number (the backoff value)
        assert isinstance(call_args[0], (int, float))
        assert isinstance(call_args[1], (int, float))


@pytest.mark.asyncio
async def test_stream_429_retry_after_zero_value(monkeypatch):
    """Test stream method handling of 429 responses with zero Retry-After value."""
    client = ResilientHttpClient(max_retries=3, base_backoff=0.1, max_delay=1, jitter_max=0)

    call_count = 0

    class AsyncContextManager:
        async def __aenter__(self):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # First call: return 429 with zero Retry-After header
                resp = SimpleNamespace(status_code=429, is_success=False, headers={"Retry-After": "0"})
                return resp
            else:
                # Second call: return success
                resp = SimpleNamespace(status_code=200, is_success=True, aiter_bytes=lambda: asyncio.as_completed([b"data"]))
                return resp

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def mock_stream(*args, **kwargs):
        return AsyncContextManager()

    # Mock _sleep_with_jitter to handle the single argument call
    async def mock_sleep_with_jitter(*args):
        pass  # Do nothing, just handle the call

    monkeypatch.setattr(client.client, "stream", mock_stream)
    monkeypatch.setattr(client, "_sleep_with_jitter", mock_sleep_with_jitter)

    # Mock asyncio.sleep to verify it's not called for zero wait time
    with patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
        async with client.stream("GET", "http://zero-retry.com") as resp:
            assert resp.status_code == 200
            assert resp.is_success

        # Should not have called asyncio.sleep for zero wait time
        # Only the backoff sleep should be called
        assert mock_sleep.call_count == 0


@pytest.mark.asyncio
async def test_stream_429_no_retry_after_header(monkeypatch):
    """Test stream method handling of 429 responses without Retry-After header."""
    client = ResilientHttpClient(max_retries=3, base_backoff=0.1, max_delay=1, jitter_max=0)

    call_count = 0

    class AsyncContextManager:
        async def __aenter__(self):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # First call: return 429 without Retry-After header
                resp = SimpleNamespace(
                    status_code=429,
                    is_success=False,
                    headers={},  # No Retry-After header
                )
                return resp
            else:
                # Second call: return success
                resp = SimpleNamespace(status_code=200, is_success=True, aiter_bytes=lambda: asyncio.as_completed([b"data"]))
                return resp

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def mock_stream(*args, **kwargs):
        return AsyncContextManager()

    # Mock _sleep_with_jitter to handle the single argument call
    async def mock_sleep_with_jitter(*args):
        pass  # Do nothing, just handle the call

    monkeypatch.setattr(client.client, "stream", mock_stream)
    monkeypatch.setattr(client, "_sleep_with_jitter", mock_sleep_with_jitter)

    async with client.stream("GET", "http://no-retry-after.com") as resp:
        assert resp.status_code == 200
        assert resp.is_success
