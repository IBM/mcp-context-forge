# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/routing/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Plugin Routing Package.
Provides resource-centric plugin routing with conditional execution,
field selection, and extensible entity types.
"""

# Import routing models from framework.models
from mcpgateway.plugins.framework.models import (
    ConfigMetadata,
    EntityType,
    FieldSelection,
    PluginAttachment,
)

# Import routing components
from mcpgateway.plugins.framework.routing.evaluator import (
    EvaluationContext,
    PolicyEvaluator,
)
from mcpgateway.plugins.framework.routing.field_selector import FieldSelector
from mcpgateway.plugins.framework.routing.rule_resolver import (
    RuleBasedResolver,
    RuleMatchContext,
)

__all__ = [
    "ConfigMetadata",
    "EntityType",
    "EvaluationContext",
    "FieldSelection",
    "FieldSelector",
    "PluginAttachment",
    "RuleBasedResolver",
    "RuleMatchContext",
    "PolicyEvaluator",
]
