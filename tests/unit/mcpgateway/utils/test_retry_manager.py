# Standard
import asyncio
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
