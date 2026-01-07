# -*- coding: utf-8 -*-
"""Service for managing plugin routing rules.

Provides an abstraction layer for plugin route management that currently
uses YAML storage but can be migrated to database storage in the future.
"""

# Standard
from contextlib import contextmanager
import fcntl
import logging
from pathlib import Path
from typing import Any, Optional

# Third-Party
from sqlalchemy.orm import Session
import yaml

# First-Party
from mcpgateway.plugins.framework.models import (
    Config,
    EntityType,
    PluginAttachment,
    PluginHookRule,
)
from mcpgateway.plugins.framework.routing.rule_resolver import (
    RuleBasedResolver,
    RuleMatchContext,
)

logger = logging.getLogger(__name__)


class PluginRouteService:
    """Service for managing plugin routing rules.

    Provides methods to:
    - Get plugins that apply to an entity
    - Get entities that a plugin applies to
    - Add/remove simple routing rules
    - Save configuration to YAML

    This abstraction layer allows for future migration to database storage.
    """

    def __init__(self, config_path: Path):
        """Initialize the plugin route service.

        Args:
            config_path: Path to the plugin configuration YAML file.
        """
        self.config_path = config_path
        self.resolver = RuleBasedResolver()

    @property
    def config(self) -> Optional[Config]:
        """Get config from PluginManager (single source of truth).

        Returns:
            Plugin configuration from PluginManager, or None if not available.
        """
        # First-Party
        from mcpgateway.plugins.framework import get_plugin_manager

        plugin_manager = get_plugin_manager()
        return plugin_manager.config if plugin_manager else None

    @contextmanager
    def _config_write_lock(self):
        """Context manager for exclusive write access to config file.

        Acquires file lock, reloads config from disk to get latest state,
        yields for modifications, then caller must save before exit.

        This ensures multi-worker safety:
        1. Lock prevents concurrent writes
        2. Reload gets latest disk state (including other workers' changes)
        3. Modifications happen on fresh state
        4. Save persists changes atomically

        Usage:
            with self._config_write_lock():
                # modify self.config
                await self.save_config()
        """
        lock_file = self.config_path.with_suffix(".lock")
        lock_file.parent.mkdir(parents=True, exist_ok=True)

        with open(lock_file, "w") as lock_fd:
            try:
                # Acquire exclusive lock (blocks until available)
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
                logger.info(f"Acquired config write lock for {self.config_path}")

                # Reload PluginManager's config from disk to get latest state (critical for multi-worker!)
                # First-Party
                from mcpgateway.plugins.framework import get_plugin_manager

                plugin_manager = get_plugin_manager()
                if plugin_manager:
                    plugin_manager.reload_config()
                    logger.info(f"Reloaded config from disk: {len(self.config.routes) if self.config else 0} routes")

                # Yield to caller for modifications
                yield

            finally:
                # Release lock
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                logger.info(f"Released config write lock for {self.config_path}")

    async def get_routes_for_entity(
        self,
        entity_type: str,
        entity_name: str,
        entity_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        server_name: Optional[str] = None,
        server_id: Optional[str] = None,
        gateway_id: Optional[str] = None,
        hook_type: Optional[str] = None,
    ) -> list[PluginAttachment]:
        """Get ordered list of plugins that apply to an entity.

        Args:
            entity_type: Type of entity (tool, prompt, resource, etc.)
            entity_name: Name of the entity
            entity_id: Optional entity ID
            tags: Optional list of entity tags
            server_name: Optional server name for infrastructure filtering
            server_id: Optional server ID
            gateway_id: Optional gateway ID
            hook_type: Optional hook type to filter by

        Returns:
            List of PluginAttachment objects in execution order.
        """
        if not self.config or not self.config.routes:
            return []

        # Create context for rule matching
        context = RuleMatchContext(
            name=entity_name,
            entity_type=entity_type,
            entity_id=entity_id,
            tags=tags or [],
            server_name=server_name,
            server_id=server_id,
            gateway_id=gateway_id,
        )

        # Get merge strategy from config
        merge_strategy = "most_specific"
        if self.config.plugin_settings:
            merge_strategy = self.config.plugin_settings.rule_merge_strategy

        # Resolve plugins using the rule resolver
        plugins = self.resolver.resolve_for_entity(
            rules=self.config.routes,
            context=context,
            hook_type=hook_type,
            merge_strategy=merge_strategy,
        )

        return plugins

    async def get_entities_for_plugin(
        self,
        plugin_name: str,
        db: Session,
    ) -> dict[str, list[str]]:
        """Get all entities a plugin applies to (by scanning rules).

        Args:
            plugin_name: Name of the plugin
            db: Database session (for future DB-based resolution)

        Returns:
            Dictionary mapping entity types to entity names.
            Example: {"tools": ["create_customer", "update_customer"], "prompts": [...]}
        """
        if not self.config or not self.config.routes:
            return {}

        entities: dict[str, list[str]] = {}

        # Scan all rules for this plugin
        for rule in self.config.routes:
            # Check if this rule includes the plugin
            plugin_in_rule = any(p.name == plugin_name for p in rule.plugins)
            if not plugin_in_rule:
                continue

            # Add entities from this rule
            if rule.entities:
                for entity_type in rule.entities:
                    entity_type_str = entity_type.value
                    if entity_type_str not in entities:
                        entities[entity_type_str] = []

                    # If rule has specific names, add them
                    if rule.name:
                        if isinstance(rule.name, list):
                            entities[entity_type_str].extend(rule.name)
                        else:
                            entities[entity_type_str].append(rule.name)
                    else:
                        # Rule matches all entities of this type (via tags/when/catch-all)
                        # Mark as "ALL" or fetch from DB in future
                        if "ALL" not in entities[entity_type_str]:
                            entities[entity_type_str].append("ALL")

        return entities

    async def get_matching_rules(
        self,
        entity_type: str,
        entity_name: str,
        tags: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Get rules that match an entity (for display in UI).

        Args:
            entity_type: Type of entity
            entity_name: Name of entity
            tags: Optional entity tags

        Returns:
            List of rule dictionaries with metadata.
        """
        if not self.config or not self.config.routes:
            return []

        matching = []
        for i, rule in enumerate(self.config.routes):
            # Check if rule matches (basic check - no when evaluation)
            if rule.entities:
                entity_type_enum = EntityType(entity_type) if entity_type in [e.value for e in EntityType] else None
                if not entity_type_enum or entity_type_enum not in rule.entities:
                    continue

            # Check name filter
            if rule.name:
                if isinstance(rule.name, list):
                    if entity_name not in rule.name:
                        continue
                elif entity_name != rule.name:
                    continue

            # Check tag filter
            if rule.tags and tags:
                rule_tags_set = set(rule.tags)
                entity_tags_set = set(tags)
                if not rule_tags_set.intersection(entity_tags_set):
                    continue

            # This rule matches
            matching.append(
                {
                    "index": i,
                    "entities": [e.value for e in rule.entities] if rule.entities else None,
                    "name": rule.name,
                    "tags": rule.tags,
                    "hooks": rule.hooks,
                    "when": rule.when,
                    "plugins": [p.name for p in rule.plugins],
                    "priority": rule.priority,
                }
            )

        return matching

    async def add_simple_route(
        self,
        entity_type: str,
        entity_name: str,
        plugin_name: str,
        priority: int = 10,
        hooks: Optional[list[str]] = None,
        reverse_order_on_post: bool = False,
        config: Optional[dict] = None,
        when: Optional[str] = None,
        override: bool = False,
        mode: Optional[str] = None,
    ) -> None:
        """Quick-add: Create or update a simple name-based rule.

        Creates ONE rule per entity with multiple plugins:
        - entities: [tool]
          name: create_customer
          hooks: [tool_pre_invoke, tool_post_invoke]
          plugins:
            - name: pii_filter
              priority: 10
            - name: audit_logger
              priority: 20

        If a simple rule already exists for this entity, adds the plugin to that rule.
        This ensures one consolidated rule per entity (not one rule per plugin per entity).

        Thread-safe: Uses file locking to prevent concurrent write conflicts.

        Args:
            entity_type: Type of entity (tool, prompt, resource, etc.)
            entity_name: Name of entity to attach plugin to
            plugin_name: Name of plugin to attach
            priority: Plugin priority (default: 10)
            hooks: Optional list of specific hooks to target. If None, defaults to
                   both pre and post hooks for the entity type.
            reverse_order_on_post: If True, reverse plugin order for post-hooks (wrapping behavior)
            config: Optional plugin-specific configuration (JSON dict)
            when: Optional runtime condition expression
            override: If True, replace inherited config instead of merging
            mode: Optional execution mode override (normal, passthrough, observe)
        """
        with self._config_write_lock():
            if not self.config:
                raise RuntimeError("Config not loaded")

            logger.info(f"Adding route: {plugin_name} -> {entity_type}:{entity_name} (current routes: {len(self.config.routes)})")

            entity_type_enum = EntityType(entity_type)

            # Default to both hooks if none specified
            if not hooks:
                hooks = self._get_default_hooks(entity_type)

            # Look for existing simple rule for this entity (one rule per entity approach)
            # A "simple rule" is: exact entity name match, no tags, no when clause
            existing_simple_rule = None
            for rule in self.config.routes:
                if not rule.entities or entity_type_enum not in rule.entities:
                    continue
                if rule.name != entity_name:
                    continue
                if rule.tags or rule.when:
                    continue  # Skip complex rules - only looking for simple rules

                # Found existing simple rule for this entity
                existing_simple_rule = rule
                break

            if existing_simple_rule:
                # Found a simple rule for this entity - add or update plugin in it
                plugin_in_rule = None
                for p in existing_simple_rule.plugins:
                    if p.name == plugin_name:
                        plugin_in_rule = p
                        break

                if plugin_in_rule:
                    # Plugin already exists in this rule - update all configuration
                    plugin_in_rule.priority = priority
                    if config is not None:
                        plugin_in_rule.config = config
                    if when is not None:
                        plugin_in_rule.when = when
                    plugin_in_rule.override = override
                    if mode is not None:
                        plugin_in_rule.mode = mode
                    logger.info(f"Updated plugin configuration in existing rule: {plugin_name} -> {entity_type}:{entity_name}")
                else:
                    # Plugin doesn't exist - add it to the rule
                    plugin_attachment = PluginAttachment(
                        name=plugin_name,
                        priority=priority,
                        config=config if config is not None else {},
                        when=when,
                        override=override,
                        mode=mode,
                    )
                    existing_simple_rule.plugins.append(plugin_attachment)
                    logger.info(f"Added plugin to existing rule: {plugin_name} -> {entity_type}:{entity_name} (now {len(existing_simple_rule.plugins)} plugins)")

                # Merge hooks if needed
                if hooks:
                    existing_hooks = set(existing_simple_rule.hooks) if existing_simple_rule.hooks else set()
                    new_hooks = set(hooks)
                    merged_hooks = existing_hooks | new_hooks
                    existing_simple_rule.hooks = list(merged_hooks)

                # Update reverse_order_on_post if specified
                if reverse_order_on_post:
                    existing_simple_rule.reverse_order_on_post = reverse_order_on_post
            else:
                # No existing simple rule for this entity - create new one
                plugin_attachment = PluginAttachment(
                    name=plugin_name,
                    priority=priority,
                    config=config if config is not None else {},
                    when=when,
                    override=override,
                    mode=mode,
                )
                new_rule = PluginHookRule(
                    entities=[entity_type_enum],
                    name=entity_name,
                    hooks=hooks,
                    reverse_order_on_post=reverse_order_on_post,
                    plugins=[plugin_attachment],
                )

                self.config.routes.append(new_rule)
                logger.info(f"Created new simple rule: {plugin_name} -> {entity_type}:{entity_name} hooks={hooks}")

            # Save changes within the lock
            await self.save_config()
            logger.info(f"Saved config with {len(self.config.routes)} routes")

    def _get_default_hooks(self, entity_type: str) -> list[str]:
        """Get default hooks for an entity type (both pre and post).

        Args:
            entity_type: Type of entity (e.g., "tool")

        Returns:
            List of default hook types for the entity.
        """
        hook_pairs = {
            "tool": ["tool_pre_invoke", "tool_post_invoke"],
            "prompt": ["prompt_pre_fetch", "prompt_post_fetch"],
            "resource": ["resource_pre_fetch", "resource_post_fetch"],
        }
        return hook_pairs.get(entity_type, [])

    async def remove_plugin_from_entity(
        self,
        entity_type: str,
        entity_name: str,
        plugin_name: str,
        hook: Optional[str] = None,
    ) -> bool:
        """Remove plugin from entity's simple rule.

        With consolidated rules (one rule per entity), this removes the plugin
        from the entity's rule. If the rule has no plugins left, removes the rule.

        When a specific hook is provided:
        - Removes that hook from the rule's hooks list
        - If hooks list becomes empty, removes the entire rule

        When no hook is provided:
        - Removes the plugin from the rule's plugins list
        - If no plugins left in the rule, removes the entire rule

        Thread-safe: Uses file locking to prevent concurrent write conflicts.

        Args:
            entity_type: Type of entity
            entity_name: Name of entity
            plugin_name: Name of plugin to remove
            hook: Optional specific hook to remove (e.g., "tool_pre_invoke").
                  If None, removes plugin from all hooks.

        Returns:
            True if plugin was removed, False if not found.
        """
        with self._config_write_lock():
            if not self.config or not self.config.routes:
                return False

            entity_type_enum = EntityType(entity_type)
            modified = False
            rules_to_remove = []

            for i, rule in enumerate(self.config.routes):
                # Only modify simple name-based rules
                if not rule.entities or entity_type_enum not in rule.entities:
                    continue

                # Must have exact name match
                if rule.name != entity_name:
                    continue

                # Must not have tags or when (simple rule only)
                if rule.tags or rule.when:
                    continue

                # Found the simple rule for this entity
                if hook:
                    # Remove specific hook from the hooks list
                    if rule.hooks and hook in rule.hooks:
                        rule.hooks.remove(hook)
                        modified = True
                        logger.info(f"Removed hook {hook} from rule for {entity_type}:{entity_name}")

                        # If no hooks left, mark rule for removal
                        if not rule.hooks:
                            rules_to_remove.append(i)
                            logger.info("Rule has no hooks left, will be removed")
                else:
                    # No specific hook - remove the plugin from the rule's plugins list
                    plugins_before = len(rule.plugins)
                    rule.plugins = [p for p in rule.plugins if p.name != plugin_name]
                    plugins_after = len(rule.plugins)

                    if plugins_before > plugins_after:
                        modified = True
                        logger.info(f"Removed plugin {plugin_name} from rule for {entity_type}:{entity_name} ({plugins_after} plugins remaining)")

                        # If no plugins left in the rule, mark rule for removal
                        if not rule.plugins:
                            rules_to_remove.append(i)
                            logger.info("Rule has no plugins left, will be removed")

                # Only process one matching rule per entity
                break

            # Remove marked rules (in reverse order to maintain indices)
            for i in reversed(rules_to_remove):
                del self.config.routes[i]

            if modified:
                hook_msg = f" from hook {hook}" if hook else ""
                logger.info(f"Removed {plugin_name}{hook_msg} from {entity_type}:{entity_name}")
                await self.save_config()

            return modified

    def _get_other_hooks(self, entity_type: str, current_hook: str) -> list[str]:
        """Get the other hook types for an entity type.

        Args:
            entity_type: Type of entity (e.g., "tool")
            current_hook: The hook being removed

        Returns:
            List of other hook types for the entity.
        """
        # Map entity types to their hook pairs
        hook_pairs = {
            "tool": ["tool_pre_invoke", "tool_post_invoke"],
            "prompt": ["prompt_pre_fetch", "prompt_post_fetch"],
            "resource": ["resource_pre_fetch", "resource_post_fetch"],
        }

        hooks = hook_pairs.get(entity_type, [])
        return [h for h in hooks if h != current_hook]

    async def change_plugin_priority(
        self,
        entity_type: str,
        entity_name: str,
        plugin_name: str,
        hook: str,
        direction: str,
    ) -> bool:
        """Change a plugin's priority (move up or down in execution order).

        Works across multiple rules for the same entity - each plugin may be in its own rule.

        Thread-safe: Uses file locking to prevent concurrent write conflicts.

        Args:
            entity_type: Type of entity (e.g., "tool")
            entity_name: Name of entity
            plugin_name: Name of plugin to move
            hook: Hook type (e.g., "tool_pre_invoke")
            direction: "up" (run earlier, lower priority) or "down" (run later, higher priority)

        Returns:
            True if priority was changed, False if plugin not found or can't be moved.
        """
        with self._config_write_lock():
            if not self.config or not self.config.routes:
                logger.warning("No config or routes available")
                return False

            entity_type_enum = EntityType(entity_type)

            # Collect all plugins for this entity across all matching rules
            # Each entry: (rule_index, plugin_index, plugin_attachment, priority)
            entity_plugins: list[tuple[int, int, PluginAttachment]] = []

            for rule_idx, rule in enumerate(self.config.routes):
                # Only check simple name-based rules
                if not rule.entities or entity_type_enum not in rule.entities:
                    continue

                # Must have exact name match
                if rule.name != entity_name:
                    continue

                # Must not have tags or when (simple rule only)
                if rule.tags or rule.when:
                    continue

                # Check hook filter - rule must apply to this hook
                if rule.hooks and hook not in rule.hooks:
                    continue

                # Collect all plugins from this rule
                for plugin_idx, plugin in enumerate(rule.plugins):
                    # Ensure priority is set
                    if plugin.priority is None:
                        plugin.priority = 10
                    entity_plugins.append((rule_idx, plugin_idx, plugin))

            logger.info(f"Found {len(entity_plugins)} plugins for {entity_type}:{entity_name} hook={hook}")

            if not entity_plugins:
                logger.warning(f"No plugins found for {entity_type}:{entity_name}")
                return False

            # Sort by priority
            entity_plugins.sort(key=lambda x: x[2].priority or 0)

            # Find the target plugin
            target_idx = None
            for i, (rule_idx, plugin_idx, plugin) in enumerate(entity_plugins):
                if plugin.name == plugin_name:
                    target_idx = i
                    break

            if target_idx is None:
                logger.warning(f"Plugin {plugin_name} not found in entity plugins list")
                return False

            # Only one plugin - can't move
            if len(entity_plugins) == 1:
                logger.info(f"Only one plugin for {entity_type}:{entity_name}, cannot move")
                return False

            if direction == "up":
                if target_idx == 0:
                    logger.info(f"Plugin {plugin_name} is already first")
                    return False  # Already first
                # Swap with previous plugin
                swap_idx = target_idx - 1
            elif direction == "down":
                if target_idx == len(entity_plugins) - 1:
                    logger.info(f"Plugin {plugin_name} is already last")
                    return False  # Already last
                # Swap with next plugin
                swap_idx = target_idx + 1
            else:
                return False  # Invalid direction

            # Get the two plugins to swap
            target_rule_idx, target_plugin_idx, target_plugin = entity_plugins[target_idx]
            swap_rule_idx, swap_plugin_idx, swap_plugin = entity_plugins[swap_idx]

            # Swap their priorities
            target_priority = target_plugin.priority
            swap_priority = swap_plugin.priority

            # If priorities are equal, adjust them to make the swap work
            if target_priority == swap_priority:
                if direction == "up":
                    target_plugin.priority = swap_priority - 1
                else:
                    target_plugin.priority = swap_priority + 1
            else:
                target_plugin.priority = swap_priority
                swap_plugin.priority = target_priority

            logger.info(f"Swapped priority of {plugin_name} ({target_priority} -> {target_plugin.priority}) " f"with {swap_plugin.name} ({swap_priority} -> {swap_plugin.priority})")

            # Save changes within the lock
            await self.save_config()
            return True

    async def update_plugin_priority(
        self,
        entity_type: str,
        entity_name: str,
        plugin_name: str,
        new_priority: int,
    ) -> bool:
        """Update a plugin's priority to an absolute value.

        Works across multiple rules for the same entity - updates all instances of the plugin.

        Thread-safe: Uses file locking to prevent concurrent write conflicts.

        Args:
            entity_type: Type of entity (e.g., "tool")
            entity_name: Name of entity
            plugin_name: Name of plugin to update
            new_priority: New priority value to set

        Returns:
            True if priority was updated, False if plugin not found.
        """
        with self._config_write_lock():
            if not self.config or not self.config.routes:
                logger.warning("No config or routes available")
                return False

            entity_type_enum = EntityType(entity_type)
            updated = False

            # Find all rules matching this entity
            for rule in self.config.routes:
                # Only check simple name-based rules
                if not rule.entities or entity_type_enum not in rule.entities:
                    continue

                # Must have exact name match
                if rule.name != entity_name:
                    continue

                # Must not have tags or when (simple rule only)
                if rule.tags or rule.when:
                    continue

                # Update the plugin priority in this rule
                for plugin in rule.plugins:
                    if plugin.name == plugin_name:
                        old_priority = plugin.priority
                        plugin.priority = new_priority
                        logger.info(f"Updated priority for {plugin_name} on {entity_type}:{entity_name}: {old_priority} -> {new_priority}")
                        updated = True

            if not updated:
                logger.warning(f"Plugin {plugin_name} not found for {entity_type}:{entity_name}")
                return False

            # Save changes within the lock
            await self.save_config()
            return True

    async def toggle_reverse_post_hooks(
        self,
        entity_type: str,
        entity_name: str,
    ) -> bool:
        """Toggle reverse_order_on_post for all rules of an entity.

        Thread-safe: Uses file locking to prevent concurrent write conflicts.

        Args:
            entity_type: Type of entity (e.g., "tool")
            entity_name: Name of entity

        Returns:
            The new state (True if now reversed, False if normal order).
        """
        with self._config_write_lock():
            if not self.config or not self.config.routes:
                return False

            # Note: use_enum_values=True causes rule.entities to contain strings, not enums
            # Find all rules for this entity and check current state
            matching_rules = []
            current_state = False

            for rule in self.config.routes:
                if not rule.entities or entity_type not in rule.entities:
                    continue
                if rule.name != entity_name:
                    continue
                if rule.tags or rule.when:
                    continue

                matching_rules.append(rule)
                # Use first rule's state as the current state
                if not matching_rules[1:]:  # First rule
                    current_state = rule.reverse_order_on_post or False

            # Toggle to opposite state
            new_state = not current_state

            # Update all matching rules
            for rule in matching_rules:
                rule.reverse_order_on_post = new_state

            logger.info(f"Toggled reverse_order_on_post to {new_state} for {entity_type}:{entity_name} ({len(matching_rules)} rules)")

            # Save changes within the lock
            await self.save_config()
            return new_state

    def get_reverse_post_hooks_state(
        self,
        entity_type: str,
        entity_name: str,
    ) -> bool:
        """Get the current reverse_order_on_post state for an entity.

        Args:
            entity_type: Type of entity (e.g., "tool")
            entity_name: Name of entity

        Returns:
            True if reverse order is enabled, False otherwise.
        """
        if not self.config or not self.config.routes:
            return False

        # Note: use_enum_values=True causes rule.entities to contain strings, not enums
        for rule in self.config.routes:
            if not rule.entities or entity_type not in rule.entities:
                continue
            if rule.name != entity_name:
                continue
            if rule.tags or rule.when:
                continue

            # Return state from first matching rule
            return rule.reverse_order_on_post or False

        return False

    async def get_rule(self, index: int) -> Optional[PluginHookRule]:
        """Get a single routing rule by index.

        Args:
            index: Index of the rule in the routes list.

        Returns:
            The PluginHookRule at the given index, or None if not found.
        """
        if not self.config or not self.config.routes:
            return None

        if index < 0 or index >= len(self.config.routes):
            return None

        return self.config.routes[index]

    async def add_or_update_rule(
        self,
        rule: PluginHookRule,
        index: Optional[int] = None,
    ) -> int:
        """Add a new routing rule or update an existing one.

        Thread-safe: Uses file locking to prevent concurrent write conflicts.

        Args:
            rule: The PluginHookRule to add or update.
            index: If provided, updates the rule at this index. Otherwise, adds a new rule.

        Returns:
            The index of the added/updated rule.

        Raises:
            ValueError: If the index is out of range.
        """
        with self._config_write_lock():
            if not self.config:
                self.config = Config(routes=[])

            if index is not None:
                # Update existing rule
                if index < 0 or index >= len(self.config.routes):
                    raise ValueError(f"Rule index {index} is out of range")
                self.config.routes[index] = rule
                logger.info(f"Updated routing rule at index {index}: {rule.name if hasattr(rule, 'name') else 'unnamed'}")
                result_index = index
            else:
                # Add new rule
                self.config.routes.append(rule)
                new_index = len(self.config.routes) - 1
                logger.info(f"Added new routing rule at index {new_index}: {rule.name if hasattr(rule, 'name') else 'unnamed'}")
                result_index = new_index

            await self.save_config()
            return result_index

    async def delete_rule(self, index: int) -> bool:
        """Delete a routing rule by index.

        Thread-safe: Uses file locking to prevent concurrent write conflicts.

        Args:
            index: Index of the rule to delete.

        Returns:
            True if the rule was deleted, False otherwise.

        Raises:
            ValueError: If the index is out of range.
        """
        with self._config_write_lock():
            if not self.config or not self.config.routes:
                return False

            if index < 0 or index >= len(self.config.routes):
                raise ValueError(f"Rule index {index} is out of range")

            deleted_rule = self.config.routes.pop(index)
            logger.info(f"Deleted routing rule at index {index}: {deleted_rule.name if hasattr(deleted_rule, 'name') else 'unnamed'}")

            await self.save_config()
            return True

    async def save_config(self) -> None:
        """Save configuration to YAML file.

        Performs atomic write with backup to prevent data loss.
        Also clears the PluginManager routing cache to ensure changes take effect immediately.
        """
        if not self.config:
            logger.warning("No config to save")
            return

        try:
            # Create backup
            backup_path = self.config_path.with_suffix(".yaml.bak")
            if self.config_path.exists():
                # Standard
                import shutil

                shutil.copy2(self.config_path, backup_path)

            # Convert config to dict for YAML serialization
            # use_enum_values=True in Config model ensures enums are converted to strings
            data = self.config.model_dump(by_alias=True, exclude_none=True)

            # Write to temp file first (atomic write)
            temp_path = self.config_path.with_suffix(".yaml.tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                # Use safe_dump to prevent Python object serialization
                yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

            # Atomic rename
            temp_path.replace(self.config_path)

            logger.info(f"Saved plugin config to {self.config_path}")

            # Reload PluginManager config so changes take effect immediately
            # (PluginRouteService uses PluginManager's config via property, so no separate reload needed)
            # First-Party
            from mcpgateway.plugins.framework import get_plugin_manager

            plugin_manager = get_plugin_manager()
            if plugin_manager:
                plugin_manager.reload_config()
                logger.info("Reloaded PluginManager config after save")

        except Exception as e:
            logger.error(f"Failed to save plugin config: {e}")
            # Restore from backup if it exists
            if backup_path.exists():
                # Standard
                import shutil

                shutil.copy2(backup_path, self.config_path)
                logger.info("Restored from backup")
            raise


# Global instance (initialized in main.py)
_plugin_route_service: Optional[PluginRouteService] = None


def init_plugin_route_service(config_path: Path) -> None:
    """Initialize the global plugin route service.

    Args:
        config_path: Path to plugin configuration file.
    """
    global _plugin_route_service
    logger.info(f"=== INIT PLUGIN ROUTE SERVICE === path={config_path}")
    _plugin_route_service = PluginRouteService(config_path)


def get_plugin_route_service() -> PluginRouteService:
    """Get the global plugin route service instance.

    Returns:
        PluginRouteService instance.

    Raises:
        RuntimeError: If service not initialized.
    """
    if _plugin_route_service is None:
        raise RuntimeError("PluginRouteService not initialized. Call init_plugin_route_service() first.")
    return _plugin_route_service
