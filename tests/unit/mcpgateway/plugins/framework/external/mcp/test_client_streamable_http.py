# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/mcp/test_client_streamable_http.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for external client on streamable http.
"""

# Standard
import os
import socket
import stat
import subprocess
import sys
import time

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import Message, PromptResult, Role, TextContent
from mcpgateway.plugins.framework import ConfigLoader, GlobalContext, PluginContext, PluginLoader, PromptHookType, PromptPosthookPayload, PromptPrehookPayload


def _wait_for_port(host: str, port: int, timeout: float = 10.0, proc: subprocess.Popen | None = None) -> None:
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


def _wait_for_socket(path: str, timeout: float = 10.0, proc: subprocess.Popen | None = None) -> None:
    """Wait until a unix domain socket path exists."""
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


def _get_free_port() -> int:
    """Get an available TCP port for testing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def server_proc():
    current_env = os.environ.copy()
    port = _get_free_port()
    current_env["PLUGINS_CONFIG_PATH"] = "tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml"
    current_env["PYTHONPATH"] = "."
    current_env["PLUGINS_TRANSPORT"] = "http"
    current_env["PLUGINS_SERVER_HOST"] = "127.0.0.1"
    current_env["PLUGINS_SERVER_PORT"] = str(port)
    # Start the server as a subprocess
    try:
        with subprocess.Popen([sys.executable, "mcpgateway/plugins/framework/external/mcp/server/runtime.py"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=current_env) as server_proc:
            _wait_for_port("127.0.0.1", port, proc=server_proc)
            yield server_proc, port
            server_proc.terminate()
            server_proc.wait(timeout=3)  # Wait for the subprocess to complete
    except subprocess.TimeoutExpired:
        server_proc.kill()  # Force kill if timeout occurs
        server_proc.wait(timeout=3)


@pytest.mark.asyncio
async def test_client_load_streamable_http(server_proc):
    server_proc, port = server_proc
    assert not server_proc.poll(), "Server failed to start"

    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_strhttp_external_plugin_regex.yaml")
    config.plugins[0].mcp.url = f"http://127.0.0.1:{port}/mcp"

    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
    try:
        prompt = PromptPrehookPayload(prompt_id="test_prompt", args={"user": "What a crapshow!"})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
        result = await plugin.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, prompt, context)
        assert result.modified_payload.args["user"] == "What a yikesshow!"
        config = plugin.config
        assert config.name == "ReplaceBadWordsPlugin"
        assert config.description == "A plugin for finding and replacing words."
        assert config.priority == 150
        assert config.kind == "external"
        message = Message(content=TextContent(type="text", text="What the crud?"), role=Role.USER)
        prompt_result = PromptResult(messages=[message])

        payload_result = PromptPosthookPayload(prompt_id="test_prompt", result=prompt_result)

        result = await plugin.invoke_hook(PromptHookType.PROMPT_POST_FETCH, payload_result, context)
        assert len(result.modified_payload.result.messages) == 1
        assert result.modified_payload.result.messages[0].content.text == "What the yikes?"
    finally:
        await plugin.shutdown()
        await loader.shutdown()


@pytest.fixture
def server_proc1():
    current_env = os.environ.copy()
    port = _get_free_port()
    current_env["PLUGINS_CONFIG_PATH"] = "tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml"
    current_env["PYTHONPATH"] = "."
    current_env["PLUGINS_TRANSPORT"] = "http"
    current_env["PLUGINS_SERVER_HOST"] = "127.0.0.1"
    current_env["PLUGINS_SERVER_PORT"] = str(port)
    # Start the server as a subprocess
    try:
        with subprocess.Popen([sys.executable, "mcpgateway/plugins/framework/external/mcp/server/runtime.py"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=current_env) as server_proc:
            _wait_for_port("127.0.0.1", port, proc=server_proc)
            yield server_proc, port
            server_proc.terminate()
            server_proc.wait(timeout=3)  # Wait for the subprocess to complete
    except subprocess.TimeoutExpired:
        server_proc.kill()  # Force kill if timeout occurs
        server_proc.wait(timeout=3)


@pytest.mark.asyncio
async def test_client_load_strhttp_overrides(server_proc1):
    server_proc1, port = server_proc1
    assert not server_proc1.poll(), "Server failed to start"

    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_strhttp_external_plugin_overrides.yaml")
    config.plugins[0].mcp.url = f"http://127.0.0.1:{port}/mcp"

    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
    try:
        prompt = PromptPrehookPayload(prompt_id="test_prompt", args={"text": "That was innovative!"})
        result = await plugin.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, prompt, PluginContext(global_context=GlobalContext(request_id="1", server_id="2")))
        assert result.violation
        assert result.violation.reason == "Prompt not allowed"
        assert result.violation.description == "A deny word was found in the prompt"
        assert result.violation.code == "deny"
        config = plugin.config
        assert config.name == "DenyListPlugin"
        assert config.description == "a different configuration."
        assert config.priority == 150
        assert config.hooks[0] == "prompt_pre_fetch"
        assert config.hooks[1] == "prompt_post_fetch"
        assert config.kind == "external"
    finally:
        await plugin.shutdown()
        await loader.shutdown()


@pytest.fixture
def server_proc2():
    current_env = os.environ.copy()
    port = _get_free_port()
    current_env["PLUGINS_CONFIG_PATH"] = "tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml"
    current_env["PYTHONPATH"] = "."
    current_env["PLUGINS_TRANSPORT"] = "http"
    current_env["PLUGINS_SERVER_HOST"] = "127.0.0.1"
    current_env["PLUGINS_SERVER_PORT"] = str(port)
    # Start the server as a subprocess
    try:
        with subprocess.Popen([sys.executable, "mcpgateway/plugins/framework/external/mcp/server/runtime.py"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=current_env) as server_proc:
            _wait_for_port("127.0.0.1", port, proc=server_proc)
            yield server_proc, port
            server_proc.terminate()
            server_proc.wait(timeout=3)  # Wait for the subprocess to complete
    except subprocess.TimeoutExpired:
        server_proc.kill()  # Force kill if timeout occurs
        server_proc.wait(timeout=3)


@pytest.fixture
def server_proc_uds(tmp_path):
    uds_path = str(tmp_path / "mcp-plugin.sock")
    current_env = os.environ.copy()
    current_env["PLUGINS_CONFIG_PATH"] = "tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml"
    current_env["PYTHONPATH"] = "."
    current_env["PLUGINS_TRANSPORT"] = "http"
    current_env["PLUGINS_SERVER_UDS"] = uds_path
    try:
        with subprocess.Popen(
            [sys.executable, "mcpgateway/plugins/framework/external/mcp/server/runtime.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=current_env,
        ) as server_proc:
            _wait_for_socket(uds_path, proc=server_proc)
            yield server_proc, uds_path
            server_proc.terminate()
            server_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        server_proc.kill()
        server_proc.wait(timeout=3)


@pytest.mark.asyncio
async def test_client_load_strhttp_post_prompt(server_proc2):
    server_proc2, port = server_proc2
    assert not server_proc2.poll(), "Server failed to start"

    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_strhttp_external_plugin_regex.yaml")
    config.plugins[0].mcp.url = f"http://127.0.0.1:{port}/mcp"

    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
    try:
        prompt = PromptPrehookPayload(prompt_id="test_prompt", args={"user": "What a crapshow!"})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
        result = await plugin.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, prompt, context)
        assert result.modified_payload.args["user"] == "What a yikesshow!"
        config = plugin.config
        assert config.name == "ReplaceBadWordsPlugin"
        assert config.description == "A plugin for finding and replacing words."
        assert config.priority == 150
        assert config.kind == "external"

        message = Message(content=TextContent(type="text", text="What the crud?"), role=Role.USER)
        prompt_result = PromptResult(messages=[message])

        payload_result = PromptPosthookPayload(prompt_id="test_prompt", result=prompt_result)

        result = await plugin.invoke_hook(PromptHookType.PROMPT_POST_FETCH, payload_result, context)
        assert len(result.modified_payload.result.messages) == 1
        assert result.modified_payload.result.messages[0].content.text == "What the yikes?"
    finally:
        await plugin.shutdown()
        await loader.shutdown()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="Unix domain sockets are not supported on Windows.")
@pytest.mark.asyncio
async def test_client_load_streamable_http_uds(server_proc_uds):
    server_proc, uds_path = server_proc_uds
    assert not server_proc.poll(), "Server failed to start"

    config = ConfigLoader.load_config("tests/unit/mcpgateway/plugins/fixtures/configs/valid_strhttp_external_plugin_regex.yaml")
    config.plugins[0].mcp.uds = uds_path
    config.plugins[0].mcp.url = "http://localhost/mcp"

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
