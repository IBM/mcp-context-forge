
## 3. Core Components

### 3.1 Plugin Base Class

The base plugin class, of which developers subclass and implement the hooks that are important for their plugins. Hook points are functions that appear interpose on existing MCP and agent-based functionality. 

```python
class Plugin:
    """Base plugin class for self-contained, in-process plugins"""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize plugin with configuration"""

    @property
    def name(self) -> str:
        """Plugin name"""

    @property
    def priority(self) -> int:
        """Plugin execution priority (lower = higher priority)"""

    @property
    def mode(self) -> PluginMode:
        """Plugin execution mode (enforce/permissive/disabled)"""

    @property
    def hooks(self) -> list[HookType]:
        """Hook points where plugin executes"""

    @property
    def conditions(self) -> list[PluginCondition] | None:
        """Conditions for plugin execution"""

    async def initialize(self) -> None:
        """Initialize plugin resources"""

    async def shutdown(self) -> None:
        """Cleanup plugin resources"""

    # Hook methods (implemented by subclasses)
    async def prompt_pre_fetch(self, payload: PromptPrehookPayload,
                              context: PluginContext) -> PromptPrehookResult: ...
    async def prompt_post_fetch(self, payload: PromptPosthookPayload,
                               context: PluginContext) -> PromptPosthookResult: ...
    async def tool_pre_invoke(self, payload: ToolPreInvokePayload,
                             context: PluginContext) -> ToolPreInvokeResult: ...
    async def tool_post_invoke(self, payload: ToolPostInvokePayload,
                              context: PluginContext) -> ToolPostInvokeResult: ...
    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload,
                                context: PluginContext) -> ResourcePreFetchResult: ...
    async def resource_post_fetch(self, payload: ResourcePostFetchPayload,
                                 context: PluginContext) -> ResourcePostFetchResult: ...
```

### 3.2 Plugin Manager

The Plugin Manager loads configured plugins and executes them at their designated hook points based on a plugin's priority.

```python
class PluginManager:
    """Singleton plugin manager for lifecycle management"""

    def __init__(self, config: str = "", timeout: int = 30): ...

    @property
    def config(self) -> Config | None:
        """Plugin manager configuration"""

    @property
    def plugin_count(self) -> int:
        """Number of loaded plugins"""

    @property
    def initialized(self) -> bool:
        """Manager initialization status"""

    async def initialize(self) -> None:
        """Initialize manager and load plugins"""

    async def shutdown(self) -> None:
        """Shutdown all plugins and cleanup"""

    def get_plugin(self, name: str) -> Optional[Plugin]:
        """Get plugin by name"""

    # Hook execution methods
    async def prompt_pre_fetch(self, payload: PromptPrehookPayload,
                              global_context: GlobalContext, ...) -> tuple[PromptPrehookResult, PluginContextTable]: ...
    async def prompt_post_fetch(self, payload: PromptPosthookPayload, ...) -> tuple[PromptPosthookResult, PluginContextTable]: ...
    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, ...) -> tuple[ToolPreInvokeResult, PluginContextTable]: ...
    async def tool_post_invoke(self, payload: ToolPostInvokePayload, ...) -> tuple[ToolPostInvokeResult, PluginContextTable]: ...
    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, ...) -> tuple[ResourcePreFetchResult, PluginContextTable]: ...
    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, ...) -> tuple[ResourcePostFetchResult, PluginContextTable]: ...
```

### 3.4 Plugin Registry

```python
class PluginInstanceRegistry:
    """Registry for plugin instance management and discovery"""

    def register(self, plugin: Plugin) -> None:
        """Register a plugin instance"""

    def unregister(self, name: str) -> None:
        """Unregister a plugin by name"""

    def get_plugin(self, name: str) -> Optional[PluginRef]:
        """Get plugin reference by name"""

    def get_plugins_for_hook(self, hook_type: HookType) -> list[PluginRef]:
        """Get all plugins registered for a specific hook"""

    def get_all_plugins(self) -> list[PluginRef]:
        """Get all registered plugins"""

    @property
    def plugin_count(self) -> int:
        """Number of registered plugins"""

    async def shutdown(self) -> None:
        """Shutdown all registered plugins"""
```

