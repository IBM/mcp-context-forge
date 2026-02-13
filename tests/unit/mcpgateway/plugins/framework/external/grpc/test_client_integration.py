# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/grpc/test_client_integration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Integration tests for gRPC external plugin client.
These tests spawn a real gRPC server subprocess and test actual communication.
"""

# Standard
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

# Third-Party
import pytest

# Check if grpc is available
try:
    import grpc  # noqa: F401

    HAS_GRPC = True
except ImportError:
    HAS_GRPC = False

pytestmark = pytest.mark.skipif(not HAS_GRPC, reason="grpc not installed")

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
    ToolHookType,
    ToolPreInvokePayload,
    ToolPostInvokePayload,
)


def _get_free_port() -> int:
    """Get an available TCP port for testing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float = 15.0, proc: subprocess.Popen | None = None) -> None:
    """Wait until a TCP port is accepting connections."""
    start = time.time()
    while time.time() - start < timeout:
        if proc and proc.poll() is not None:
            output = ""
            if proc.stdout:
                output = proc.stdout.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Server exited before port opened. Output:\n{output}")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((host, port)) == 0:
                return
        time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for {host}:{port}")


@pytest.fixture
def grpc_server_proc():
    """Start a gRPC plugin server subprocess."""
    current_env = os.environ.copy()
    port = _get_free_port()
    current_env["PLUGINS_CONFIG_PATH"] = "tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml"
    current_env["PYTHONPATH"] = "."
    current_env["PLUGINS_TRANSPORT"] = "grpc"
    current_env["PLUGINS_GRPC_SERVER_HOST"] = "127.0.0.1"
    current_env["PLUGINS_GRPC_SERVER_PORT"] = str(port)

    try:
        with subprocess.Popen(
            [sys.executable, "mcpgateway/plugins/framework/external/grpc/server/runtime.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=current_env,
        ) as server_proc:
            _wait_for_port("127.0.0.1", port, proc=server_proc)
            yield server_proc, port
            server_proc.terminate()
            server_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        server_proc.kill()
        server_proc.wait(timeout=3)


@pytest.mark.asyncio
async def test_grpc_client_invoke_hook(grpc_server_proc):
    """Test gRPC client can invoke hooks on a real server."""
    server_proc, port = grpc_server_proc
    assert not server_proc.poll(), "Server failed to start"

    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_grpc_external_plugin.yaml")
    config.plugins[0].grpc.target = f"127.0.0.1:{port}"

    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
    try:
        # Test prompt_pre_fetch hook
        prompt = PromptPrehookPayload(prompt_id="test_prompt", args={"user": "What a crapshow!"})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
        result = await plugin.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, prompt, context)

        # The ReplaceBadWordsPlugin replaces "crap" -> "crud" -> "yikes"
        assert result.modified_payload.args["user"] == "What a yikesshow!"

        # Verify plugin config was retrieved from server
        assert plugin.config.name == "ReplaceBadWordsPlugin"
        assert plugin.config.description == "A plugin for finding and replacing words."
        assert plugin.config.kind == "external"
    finally:
        await plugin.shutdown()
        await loader.shutdown()


@pytest.mark.asyncio
async def test_grpc_client_post_hook(grpc_server_proc):
    """Test gRPC client can invoke post-fetch hooks."""
    server_proc, port = grpc_server_proc
    assert not server_proc.poll(), "Server failed to start"

    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_grpc_external_plugin.yaml")
    config.plugins[0].grpc.target = f"127.0.0.1:{port}"

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


@pytest.mark.asyncio
async def test_grpc_client_context_propagation(grpc_server_proc):
    """Test that context is properly propagated through gRPC calls."""
    server_proc, port = grpc_server_proc
    assert not server_proc.poll(), "Server failed to start"

    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_grpc_external_plugin.yaml")
    config.plugins[0].grpc.target = f"127.0.0.1:{port}"

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


@pytest.fixture
def grpc_server_proc_uds(tmp_path):
    """Start a gRPC plugin server subprocess using Unix domain socket."""
    import uuid

    # Use /tmp directly to keep socket path short (macOS has ~104 char limit)
    short_id = uuid.uuid4().hex[:8]
    uds_path = f"/tmp/grpc-test-{short_id}.sock"

    current_env = os.environ.copy()
    current_env["PLUGINS_CONFIG_PATH"] = "tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml"
    current_env["PYTHONPATH"] = "."
    current_env["PLUGINS_TRANSPORT"] = "grpc"
    current_env["PLUGINS_GRPC_SERVER_UDS"] = uds_path

    try:
        with subprocess.Popen(
            [sys.executable, "mcpgateway/plugins/framework/external/grpc/server/runtime.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=current_env,
        ) as server_proc:
            # Wait for socket file to be created
            _wait_for_socket(uds_path, proc=server_proc)
            yield server_proc, uds_path
            server_proc.terminate()
            server_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        server_proc.kill()
        server_proc.wait(timeout=3)
    finally:
        if os.path.exists(uds_path):
            os.unlink(uds_path)


def _wait_for_socket(path: str, timeout: float = 15.0, proc: subprocess.Popen | None = None) -> None:
    """Wait until a Unix domain socket path exists."""
    import stat

    start = time.time()
    while time.time() - start < timeout:
        if proc and proc.poll() is not None:
            output = ""
            if proc.stdout:
                output = proc.stdout.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Server exited before socket created. Output:\n{output}")
        try:
            if os.path.exists(path) and stat.S_ISSOCK(os.stat(path).st_mode):
                return
        except FileNotFoundError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for socket: {path}")


@pytest.mark.skipif(sys.platform.startswith("win"), reason="Unix domain sockets are not supported on Windows.")
@pytest.mark.asyncio
async def test_grpc_client_over_uds(grpc_server_proc_uds):
    """Test gRPC client can communicate over Unix domain socket."""
    server_proc, uds_path = grpc_server_proc_uds
    assert not server_proc.poll(), "Server failed to start"

    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_grpc_external_plugin.yaml")
    # Switch from TCP to UDS
    config.plugins[0].grpc.target = None
    config.plugins[0].grpc.uds = uds_path

    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
    try:
        prompt = PromptPrehookPayload(prompt_id="test_prompt", args={"user": "What a crapshow!"})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
        result = await plugin.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, prompt, context)

        assert result.modified_payload.args["user"] == "What a yikesshow!"
    finally:
        await plugin.shutdown()
        await loader.shutdown()


# =============================================================================
# PluginManager Integration Tests
# =============================================================================

@pytest.fixture
def grpc_server_proc_for_manager(tmp_path):
    """Start a gRPC plugin server and return a matching PluginManager config file."""
    current_env = os.environ.copy()
    port = _get_free_port()
    current_env["PLUGINS_CONFIG_PATH"] = "tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml"
    current_env["PYTHONPATH"] = "."
    current_env["PLUGINS_TRANSPORT"] = "grpc"
    current_env["PLUGINS_GRPC_SERVER_HOST"] = "127.0.0.1"
    current_env["PLUGINS_GRPC_SERVER_PORT"] = str(port)

    template_config = Path("tests/unit/mcpgateway/plugins/fixtures/configs/valid_grpc_external_plugin_manager.yaml")
    dynamic_config = tmp_path / "valid_grpc_external_plugin_manager.dynamic.yaml"
    dynamic_config.write_text(
        template_config.read_text(encoding="utf-8").replace("127.0.0.1:50151", f"127.0.0.1:{port}"),
        encoding="utf-8",
    )

    try:
        with subprocess.Popen(
            [sys.executable, "mcpgateway/plugins/framework/external/grpc/server/runtime.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=current_env,
        ) as server_proc:
            _wait_for_port("127.0.0.1", port, proc=server_proc)
            yield server_proc, str(dynamic_config)
            server_proc.terminate()
            server_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        server_proc.kill()
        server_proc.wait(timeout=3)


@pytest.mark.asyncio
async def test_grpc_plugin_manager_invoke_hook(grpc_server_proc_for_manager):
    """Test PluginManager can invoke hooks through gRPC external plugin."""
    server_proc, config_path = grpc_server_proc_for_manager
    assert not server_proc.poll(), "Server failed to start"

    # Reset PluginManager singleton state
    PluginManager.reset()

    plugin_manager = PluginManager(config=config_path)

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


@pytest.mark.asyncio
async def test_grpc_plugin_manager_multiple_hooks(grpc_server_proc_for_manager):
    """Test PluginManager can invoke multiple hook types through gRPC."""
    server_proc, config_path = grpc_server_proc_for_manager
    assert not server_proc.poll(), "Server failed to start"

    PluginManager.reset()
    plugin_manager = PluginManager(config=config_path)

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


@pytest.mark.asyncio
async def test_grpc_plugin_manager_context_persistence(grpc_server_proc_for_manager):
    """Test that context is maintained across multiple PluginManager calls."""
    server_proc, config_path = grpc_server_proc_for_manager
    assert not server_proc.poll(), "Server failed to start"

    PluginManager.reset()
    plugin_manager = PluginManager(config=config_path)

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
