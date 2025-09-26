
[Back to Plugin Specification Main Page](../plugin-framework-specification.md)

[Next: Testing Framework](./testing.md)

## 11. Development Guidelines

### 11.1 Plugin Development Workflow

1. **Design Phase**
   - Define plugin purpose and scope
   - Identify required hook points
   - Design configuration schema
   - Plan integration with external services (if needed)

2. **Implementation Phase**
   - Create plugin directory structure
   - Implement Plugin base class
   - Add configuration validation
   - Implement hook methods
   - Add comprehensive logging

3. **Testing Phase**
   - Write unit tests for plugin logic
   - Create integration tests with mock gateway
   - Test error conditions and edge cases
   - Performance testing with realistic payloads

4. **Documentation Phase**
   - Create plugin README
   - Document configuration options
   - Provide usage examples
   - Add troubleshooting guide

5. **Deployment Phase**
   - Add plugin to configuration
   - Deploy to staging environment
   - Monitor performance and errors
   - Roll out to production

### 11.2 Plugin Structure

```
plugins/my_plugin/
├── __init__.py                  # Plugin package initialization
├── plugin-manifest.yaml        # Plugin metadata
├── my_plugin.py                # Main plugin implementation
├── config.py                   # Configuration models
├── README.md                   # Plugin documentation
└── tests/
    ├── test_my_plugin.py       # Unit tests
    └── test_integration.py     # Integration tests
```

### 11.3 Plugin Manifest

```yaml
# plugins/my_plugin/plugin-manifest.yaml
description: "My custom plugin for content filtering"
author: "Development Team"
version: "1.0.0"
tags:
  - "content-filter"
  - "security"
available_hooks:
  - "prompt_pre_fetch"
  - "tool_pre_invoke"
default_config:
  enabled: true
  sensitivity: 0.8
  block_threshold: 0.9
dependencies:
  - "requests>=2.28.0"
  - "pydantic>=2.0.0"
```

### 11.4 Implementation Template

```python
from mcpgateway.plugins.framework import (
    Plugin, PluginConfig, PluginContext, PluginViolation,
    PromptPrehookPayload, PromptPrehookResult,
    HttpHeaderPayload, HttpHeaderPayloadResult
)
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

class MyPluginConfig(BaseModel):
    """Plugin-specific configuration"""
    enabled: bool = True
    sensitivity: float = 0.8
    block_threshold: float = 0.9

class MyPlugin(Plugin):
    """Custom plugin implementation"""

    def __init__(self, config: PluginConfig):
        super().__init__(config)
        self.plugin_config = MyPluginConfig.model_validate(config.config)
        logger.info(f"Initialized {self.name} v{config.version}")

    async def initialize(self) -> None:
        """Initialize plugin resources"""
        # Setup external connections, load models, etc.
        pass

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload,
                              context: PluginContext) -> PromptPrehookResult:
        """Process prompt before template rendering"""
        try:
            # Plugin logic here
            if self._should_block(payload):
                violation = PluginViolation(
                    reason="Content policy violation",
                    description="Content detected as inappropriate",
                    code="CONTENT_BLOCKED",
                    details={"confidence": 0.95}
                )
                return PromptPrehookResult(
                    continue_processing=False,
                    violation=violation
                )

            # Optional payload modification
            modified_payload = self._transform_payload(payload)
            return PromptPrehookResult(
                modified_payload=modified_payload,
                metadata={"processed": True}
            )

        except Exception as e:
            logger.error(f"Plugin {self.name} error: {e}")
            raise  # Let framework handle error based on plugin mode

    def _should_block(self, payload: PromptPrehookPayload) -> bool:
        """Plugin-specific blocking logic"""
        # Implementation here
        return False

    def _transform_payload(self, payload: PromptPrehookPayload) -> PromptPrehookPayload:
        """Transform payload if needed"""
        # Implementation here
        return payload

    async def http_pre_forwarding_call(self, payload: HttpHeaderPayload,
                                     context: PluginContext) -> HttpHeaderPayloadResult:
        """Process HTTP headers before forwarding requests"""
        try:
            modified_headers = dict(payload.root)

            # Add authentication if user context available
            if context.global_context.user:
                api_key = await self._get_api_key(context.global_context.user)
                modified_headers["X-API-Key"] = api_key

            # Add request tracking
            modified_headers["X-Plugin-Processed"] = self.name
            modified_headers["X-Request-ID"] = context.global_context.request_id

            return HttpHeaderPayloadResult(
                continue_processing=True,
                modified_payload=HttpHeaderPayload(modified_headers),
                metadata={"headers_modified": True, "plugin": self.name}
            )

        except Exception as e:
            logger.error(f"HTTP header processing failed in {self.name}: {e}")
            raise

    async def _get_api_key(self, user: str) -> str:
        """Get API key for user from secure storage"""
        # Implementation would connect to key management service
        return f"api_key_for_{user}"

    async def shutdown(self) -> None:
        """Cleanup plugin resources"""
        logger.info(f"Shutting down {self.name}")
```

### 11.5 Testing Guidelines

```python
import pytest
from mcpgateway.plugins.framework import (
    PluginConfig, PluginContext, GlobalContext,
    PromptPrehookPayload, HookType, PluginMode
)
from plugins.my_plugin.my_plugin import MyPlugin

class TestMyPlugin:

    @pytest.fixture
    def plugin_config(self):
        return PluginConfig(
            name="test_plugin",
            kind="plugins.my_plugin.my_plugin.MyPlugin",
            hooks=[HookType.PROMPT_PRE_FETCH],
            mode=PluginMode.ENFORCE,
            config={
                "enabled": True,
                "sensitivity": 0.8
            }
        )

    @pytest.fixture
    def plugin(self, plugin_config):
        return MyPlugin(plugin_config)

    @pytest.fixture
    def context(self):
        global_context = GlobalContext(request_id="test-123")
        return PluginContext(global_context=global_context)

    async def test_plugin_initialization(self, plugin):
        """Test plugin initializes correctly"""
        assert plugin.name == "test_plugin"
        assert plugin.plugin_config.enabled is True

    async def test_prompt_pre_fetch_success(self, plugin, context):
        """Test successful prompt processing"""
        payload = PromptPrehookPayload(
            name="test_prompt",
            args={"message": "Hello world"}
        )

        result = await plugin.prompt_pre_fetch(payload, context)

        assert result.continue_processing is True
        assert "processed" in result.metadata

    async def test_prompt_pre_fetch_blocked(self, plugin, context):
        """Test blocked content detection"""
        payload = PromptPrehookPayload(
            name="test_prompt",
            args={"message": "blocked content"}
        )

        # Mock plugin to block this content
        plugin._should_block = lambda _: True

        result = await plugin.prompt_pre_fetch(payload, context)

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "CONTENT_BLOCKED"

    async def test_error_handling(self, plugin, context):
        """Test plugin error handling"""
        payload = PromptPrehookPayload(name="test", args={})

        # Mock plugin to raise error
        def error_func(_):
            raise ValueError("Test error")
        plugin._should_block = error_func

        with pytest.raises(ValueError):
            await plugin.prompt_pre_fetch(payload, context)
```

### 11.6 Best Practices

#### 11.6.1 Error Handling
- Always use structured logging
- Provide clear error messages
- Include relevant context in errors
- Test error conditions thoroughly

#### 11.6.2 Performance
- Keep plugin logic lightweight
- Use async/await for I/O operations
- Implement timeout for external calls
- Cache expensive computations

#### 11.6.3 Configuration
- Validate configuration at startup
- Provide sensible defaults
- Document all configuration options
- Support environment variable overrides

#### 11.6.4 Security
- Validate all inputs
- Sanitize outputs
- Use secure communication for external services
- Follow principle of least privilege

#### 11.6.5 Observability
- Log plugin lifecycle events
- Include execution metrics
- Provide health check endpoints
- Support debugging modes

---

[Back to Plugin Specification Main Page](../plugin-framework-specification.md)

[Next: Testing Framework](./testing.md)