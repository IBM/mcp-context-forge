
## 8. Security and Protection

### 8.1 Timeout Protection

```python
# Per-plugin execution timeout
async def _execute_with_timeout(self, plugin: PluginRef, ...) -> PluginResult[T]:
    return await asyncio.wait_for(
        plugin_run(plugin, payload, context),
        timeout=self.timeout  # Default: 30 seconds
    )
```

### 8.2 Payload Size Validation

```python
MAX_PAYLOAD_SIZE = 1_000_000  # 1MB

def _validate_payload_size(self, payload: Any) -> None:
    """Prevent memory exhaustion from large payloads"""
    if hasattr(payload, "args") and payload.args:
        total_size = sum(len(str(v)) for v in payload.args.values())
        if total_size > MAX_PAYLOAD_SIZE:
            raise PayloadSizeError(f"Payload size {total_size} exceeds limit")
```

### 8.3 Input Validation

```python
# URL validation for external plugins
@field_validator("url")
@classmethod
def validate_url(cls, url: str | None) -> str | None:
    if url:
        return SecurityValidator.validate_url(url)  # Validates against SSRF
    return url

# Script validation for STDIO plugins
@field_validator("script")
@classmethod
def validate_script(cls, script: str | None) -> str | None:
    if script:
        file_path = Path(script)
        if not file_path.is_file():
            raise ValueError(f"Script {script} does not exist")
        if file_path.suffix != ".py":
            raise ValueError(f"Script {script} must have .py extension")
    return script
```

### 8.4 Error Isolation

```python
# Plugin failures don't crash the gateway
try:
    result = await self._execute_with_timeout(plugin, ...)
except asyncio.TimeoutError:
    logger.error(f"Plugin {plugin.name} timed out")
    if plugin.mode == PluginMode.ENFORCE:
        raise PluginError(f"Plugin timeout: {plugin.name}")
except Exception as e:
    logger.error(f"Plugin {plugin.name} failed: {e}")
    if plugin.mode == PluginMode.ENFORCE:
        raise PluginError(f"Plugin error: {plugin.name}")
    # Continue with next plugin in permissive mode
```

