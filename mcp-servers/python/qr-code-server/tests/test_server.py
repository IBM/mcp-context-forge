import asyncio
import json
import types


def test_echo_tool_schema_importable():
    # Basic import test ensures package structure is valid
    mod = __import__('qr_code_server.server', fromlist=['server'])
    assert isinstance(mod, types.ModuleType)


def test_echo_tool_logic_snapshot():
    from qr_code_server.server import call_tool

    async def run():
        result = await call_tool('echo', {'text': 'hello'})
        payload = json.loads(result[0].text)
        assert payload['ok'] is True
        assert payload['echo'] == 'hello'

    asyncio.get_event_loop().run_until_complete(run())

