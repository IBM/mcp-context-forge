# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/unix/test_client_integration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Integration tests for Unix socket external plugin client.
These tests spawn a real Unix socket server subprocess and test actual communication.
"""

# Standard
import os
import stat
import subprocess
import sys
import time
import uuid

# Third-Party
import pytest

# Check if grpc/protobuf is available (Unix socket uses protobuf from grpc package)
try:
    import grpc  # noqa: F401

    HAS_GRPC = True
except ImportError:
    HAS_GRPC = False

pytestmark = pytest.mark.skipif(not HAS_GRPC, reason="grpc not installed (required for protobuf)")

# First-Party
from mcpgateway.common.models import Message, PromptResult, Role, TextContent
from mcpgateway.plugins.framework import (
    ConfigLoader,
    GlobalContext,
    PluginContext,
    PluginLoader,
    PluginManager,
    PromptHookType,
    PromptPosthookPayload,
    PromptPrehookPayload,
)


def _wait_for_socket(path: str, timeout: float = 15.0, proc: subprocess.Popen | None = None) -> None:
    """Wait until a Unix domain socket path exists and is ready."""
    start = time.time()
    while time.time() - start < timeout:
        if proc and proc.poll() is not None:
            output = ""
            if proc.stdout:
                output = proc.stdout.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Server exited before socket created. Output:\n{output}")
        try:
            if os.path.exists(path) and stat.S_ISSOCK(os.stat(path).st_mode):
                # Give it a moment to be fully ready
                time.sleep(0.1)
                return
        except FileNotFoundError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for socket: {path}")


@pytest.fixture
def unix_server_proc():
    """Start a Unix socket plugin server subprocess."""
    # Use /tmp directly to keep socket path short (macOS has ~104 char limit)
    short_id = uuid.uuid4().hex[:8]
    socket_path = f"/tmp/unix-test-{short_id}.sock"

    current_env = os.environ.copy()
    current_env["PLUGINS_CONFIG_PATH"] = "tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml"
    current_env["PYTHONPATH"] = "."
    current_env["PLUGINS_TRANSPORT"] = "unix"
    current_env["UNIX_SOCKET_PATH"] = socket_path

    try:
        with subprocess.Popen(
            [sys.executable, "mcpgateway/plugins/framework/external/unix/server/runtime.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=current_env,
        ) as server_proc:
            _wait_for_socket(socket_path, proc=server_proc)
            yield server_proc, socket_path
            server_proc.terminate()
            server_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        server_proc.kill()
        server_proc.wait(timeout=3)
    finally:
        if os.path.exists(socket_path):
            os.unlink(socket_path)


@pytest.mark.skipif(sys.platform.startswith("win"), reason="Unix domain sockets are not supported on Windows.")
@pytest.mark.asyncio
async def test_unix_client_invoke_hook(unix_server_proc):
    """Test Unix socket client can invoke hooks on a real server."""
    server_proc, socket_path = unix_server_proc
    assert not server_proc.poll(), "Server failed to start"

    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_unix_external_plugin.yaml")
    config.plugins[0].unix_socket.path = socket_path

    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
    try:
        # Test prompt_pre_fetch hook
        prompt = PromptPrehookPayload(prompt_id="test_prompt", args={"user": "What a crapshow!"})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
        result = await plugin.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, prompt, context)

        # The ReplaceBadWordsPlugin replaces "crap" -> "crud" -> "yikes"
        assert result.modified_payload.args["user"] == "What a yikesshow!"

        # Verify plugin is connected
        assert plugin.connected is True
    finally:
        await plugin.shutdown()
        await loader.shutdown()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="Unix domain sockets are not supported on Windows.")
@pytest.mark.asyncio
async def test_unix_client_post_hook(unix_server_proc):
    """Test Unix socket client can invoke post-fetch hooks."""
    server_proc, socket_path = unix_server_proc
    assert not server_proc.poll(), "Server failed to start"

    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_unix_external_plugin.yaml")
    config.plugins[0].unix_socket.path = socket_path

    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
    try:
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))

        # Test prompt_post_fetch hook
        message = Message(content=TextContent(type="text", text="What the crud?"), role=Role.USER)
        prompt_result = PromptResult(messages=[message])
        payload_result = PromptPosthookPayload(prompt_id="test_prompt", result=prompt_result)

        result = await plugin.invoke_hook(PromptHookType.PROMPT_POST_FETCH, payload_result, context)

        assert len(result.modified_payload.result.messages) == 1
        # "crud" -> "yikes"
        assert result.modified_payload.result.messages[0].content.text == "What the yikes?"
    finally:
        await plugin.shutdown()
        await loader.shutdown()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="Unix domain sockets are not supported on Windows.")
@pytest.mark.asyncio
async def test_unix_client_multiple_calls(unix_server_proc):
    """Test Unix socket client handles multiple sequential calls."""
    server_proc, socket_path = unix_server_proc
    assert not server_proc.poll(), "Server failed to start"

    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_unix_external_plugin.yaml")
    config.plugins[0].unix_socket.path = socket_path

    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
    try:
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))

        # Make multiple calls to verify connection reuse
        for i in range(5):
            prompt = PromptPrehookPayload(prompt_id="test_prompt", args={"user": f"Test crap {i}"})
            result = await plugin.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, prompt, context)
            assert result.modified_payload.args["user"] == f"Test yikes {i}"
    finally:
        await plugin.shutdown()
        await loader.shutdown()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="Unix domain sockets are not supported on Windows.")
@pytest.mark.asyncio
async def test_unix_client_context_propagation(unix_server_proc):
    """Test that context is properly propagated through Unix socket calls."""
    server_proc, socket_path = unix_server_proc
    assert not server_proc.poll(), "Server failed to start"

    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_unix_external_plugin.yaml")
    config.plugins[0].unix_socket.path = socket_path

    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
    try:
        # Create context with initial state
        global_context = GlobalContext(
            request_id="test-req-123",
            server_id="test-server",
            user="test-user",
            tenant_id="test-tenant",
        )
        context = PluginContext(global_context=global_context)

        prompt = PromptPrehookPayload(prompt_id="test_prompt", args={"user": "Hello!"})
        result = await plugin.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, prompt, context)

        # Verify the call succeeded
        assert result.continue_processing is True
    finally:
        await plugin.shutdown()
        await loader.shutdown()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="Unix domain sockets are not supported on Windows.")
@pytest.mark.asyncio
async def test_unix_client_high_throughput(unix_server_proc):
    """Test Unix socket client handles high throughput."""
    server_proc, socket_path = unix_server_proc
    assert not server_proc.poll(), "Server failed to start"

    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_unix_external_plugin.yaml")
    config.plugins[0].unix_socket.path = socket_path

    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
    try:
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))

        # Make many rapid calls
        import time

        start = time.perf_counter()
        num_calls = 50
        for i in range(num_calls):
            prompt = PromptPrehookPayload(prompt_id="test_prompt", args={"user": "crap"})
            result = await plugin.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, prompt, context)
            assert result.modified_payload.args["user"] == "yikes"

        elapsed = time.perf_counter() - start
        rate = num_calls / elapsed

        # Unix sockets should be fast - use lenient threshold for CI/slow environments
        assert rate > 10, f"Rate too slow: {rate:.0f} calls/sec"
    finally:
        await plugin.shutdown()
        await loader.shutdown()


# =============================================================================
# PluginManager Integration Tests
# =============================================================================

# Fixed socket path for PluginManager tests (matches valid_unix_external_plugin_manager.yaml)
PLUGIN_MANAGER_SOCKET_PATH = "/tmp/mcpgateway-pm-test.sock"


@pytest.fixture
def unix_server_proc_for_manager():
    """Start a Unix socket plugin server on the fixed path for PluginManager tests."""
    current_env = os.environ.copy()
    current_env["PLUGINS_CONFIG_PATH"] = "tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml"
    current_env["PYTHONPATH"] = "."
    current_env["PLUGINS_TRANSPORT"] = "unix"
    current_env["UNIX_SOCKET_PATH"] = PLUGIN_MANAGER_SOCKET_PATH

    # Clean up any existing socket
    if os.path.exists(PLUGIN_MANAGER_SOCKET_PATH):
        os.unlink(PLUGIN_MANAGER_SOCKET_PATH)

    try:
        with subprocess.Popen(
            [sys.executable, "mcpgateway/plugins/framework/external/unix/server/runtime.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=current_env,
        ) as server_proc:
            _wait_for_socket(PLUGIN_MANAGER_SOCKET_PATH, proc=server_proc)
            yield server_proc
            server_proc.terminate()
            server_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        server_proc.kill()
        server_proc.wait(timeout=3)
    finally:
        if os.path.exists(PLUGIN_MANAGER_SOCKET_PATH):
            os.unlink(PLUGIN_MANAGER_SOCKET_PATH)


@pytest.mark.skipif(sys.platform.startswith("win"), reason="Unix domain sockets are not supported on Windows.")
@pytest.mark.asyncio
async def test_unix_plugin_manager_invoke_hook(unix_server_proc_for_manager):
    """Test PluginManager can invoke hooks through Unix socket external plugin."""
    server_proc = unix_server_proc_for_manager
    assert not server_proc.poll(), "Server failed to start"

    # Reset PluginManager singleton state
    PluginManager.reset()

    plugin_manager = PluginManager(
        config="tests/unit/mcpgateway/plugins/fixtures/configs/valid_unix_external_plugin_manager.yaml"
    )

    try:
        await plugin_manager.initialize()

        # Verify plugin was loaded
        assert plugin_manager.plugin_count == 1

        # Test prompt_pre_fetch hook through PluginManager
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"user": "What a crapshow!"})
        global_context = GlobalContext(request_id="test-1", server_id="test-server")

        result, contexts = await plugin_manager.invoke_hook(
            PromptHookType.PROMPT_PRE_FETCH.value,
            payload,
            global_context,
        )

        # Verify the transformation happened
        assert result.modified_payload.args["user"] == "What a yikesshow!"
        assert result.continue_processing is True

    finally:
        await plugin_manager.shutdown()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="Unix domain sockets are not supported on Windows.")
@pytest.mark.asyncio
async def test_unix_plugin_manager_multiple_hooks(unix_server_proc_for_manager):
    """Test PluginManager can invoke multiple hook types through Unix socket."""
    server_proc = unix_server_proc_for_manager
    assert not server_proc.poll(), "Server failed to start"

    PluginManager.reset()
    plugin_manager = PluginManager(
        config="tests/unit/mcpgateway/plugins/fixtures/configs/valid_unix_external_plugin_manager.yaml"
    )

    try:
        await plugin_manager.initialize()

        global_context = GlobalContext(request_id="test-1", server_id="test-server")

        # Test prompt_pre_fetch
        pre_payload = PromptPrehookPayload(prompt_id="test_prompt", args={"user": "This is crap!"})
        result, _ = await plugin_manager.invoke_hook(
            PromptHookType.PROMPT_PRE_FETCH.value,
            pre_payload,
            global_context,
        )
        assert result.modified_payload.args["user"] == "This is yikes!"

        # Test prompt_post_fetch
        message = Message(content=TextContent(type="text", text="What crud!"), role=Role.USER)
        prompt_result = PromptResult(messages=[message])
        post_payload = PromptPosthookPayload(prompt_id="test_prompt", result=prompt_result)

        result, _ = await plugin_manager.invoke_hook(
            PromptHookType.PROMPT_POST_FETCH.value,
            post_payload,
            global_context,
        )
        assert result.modified_payload.result.messages[0].content.text == "What yikes!"

    finally:
        await plugin_manager.shutdown()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="Unix domain sockets are not supported on Windows.")
@pytest.mark.asyncio
async def test_unix_plugin_manager_context_persistence(unix_server_proc_for_manager):
    """Test that context is maintained across multiple PluginManager calls."""
    server_proc = unix_server_proc_for_manager
    assert not server_proc.poll(), "Server failed to start"

    PluginManager.reset()
    plugin_manager = PluginManager(
        config="tests/unit/mcpgateway/plugins/fixtures/configs/valid_unix_external_plugin_manager.yaml"
    )

    try:
        await plugin_manager.initialize()

        global_context = GlobalContext(
            request_id="ctx-test-123",
            server_id="test-server",
            user="test-user",
            tenant_id="test-tenant",
        )

        # Make multiple calls and verify context flows through
        for i in range(3):
            payload = PromptPrehookPayload(prompt_id="test_prompt", args={"user": f"Test crap {i}"})
            result, contexts = await plugin_manager.invoke_hook(
                PromptHookType.PROMPT_PRE_FETCH.value,
                payload,
                global_context,
            )
            assert result.modified_payload.args["user"] == f"Test yikes {i}"
            assert result.continue_processing is True

    finally:
        await plugin_manager.shutdown()
