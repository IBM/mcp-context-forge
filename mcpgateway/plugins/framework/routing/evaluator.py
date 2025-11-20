# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/routing/evaluator.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Policy Expression Evaluator.
Evaluates 'when' clauses for conditional plugin execution using simpleeval
with AST caching for performance.

Supports expressions like:
- args.size > 1000
- contains(agent.tags, "customer-facing")
- entity.metadata.risk_level == "high"
- (entity.type == "tool" and args.count > 10) or contains(entity.tags, "admin")
"""

# Standard
import ast
from functools import lru_cache
import logging
from typing import Any, Optional

# Third-Party
from pydantic import BaseModel, Field
from simpleeval import DEFAULT_FUNCTIONS, DEFAULT_OPERATORS, SimpleEval

logger = logging.getLogger(__name__)


class EvaluationContext(BaseModel):
    """Context for when expression evaluation in plugin routing rules.

    Contains all variables available in 'when' clause expressions.

    Attributes:
        name: Entity name (e.g., "create_customer", "my_tool").
        entity_type: Entity type ("tool", "prompt", "resource").
        entity_id: Optional entity ID.
        tags: Entity tags for matching (e.g., ["customer", "pii"]).
        metadata: Entity metadata dict (e.g., {"risk_level": "high"}).
        server_name: Name of the server this entity belongs to.
        server_id: ID of the server this entity belongs to.
        gateway_id: ID of the gateway processing the request.
        args: Tool/prompt/resource arguments (convenience accessor).
        payload: Full payload dict for accessing any field (uri, method, headers, result, etc.).
        user: User making the request.
        tenant_id: Tenant ID for multi-tenancy.

    Examples:
        >>> ctx = EvaluationContext(
        ...     name="create_customer",
        ...     entity_type="tool",
        ...     tags=["customer", "pii"],
        ...     metadata={"risk_level": "high"},
        ...     server_name="production-api",
        ...     args={"email": "test@example.com"}
        ... )
        >>> ctx.name
        'create_customer'
        >>> ctx.tags
        ['customer', 'pii']

        >>> # Use in when expression: "metadata.get('risk_level') == 'high'"
        >>> ctx.metadata["risk_level"]
        'high'

        >>> # Use in when expression: "'customer' in tags"
        >>> 'customer' in ctx.tags
        True

        >>> # Convenience accessor for common case
        >>> ctx.args["email"]
        'test@example.com'

        >>> # Full payload access for other fields
        >>> ctx2 = EvaluationContext(
        ...     name="file.env",
        ...     entity_type="resource",
        ...     payload={"uri": "file:///.env", "metadata": {"size": 1024}}
        ... )
        >>> ctx2.payload["uri"]
        'file:///.env'

        >>> # HTTP payload example
        >>> ctx3 = EvaluationContext(
        ...     name="api_endpoint",
        ...     entity_type="http",
        ...     payload={"method": "POST", "path": "/api/users", "headers": {"content-type": "application/json"}}
        ... )
        >>> ctx3.payload["method"]
        'POST'
    """

    # Entity context
    name: str = ""
    entity_type: str = ""
    entity_id: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Infrastructure context
    server_name: Optional[str] = None
    server_id: Optional[str] = None
    gateway_id: Optional[str] = None

    # Request context
    args: dict[str, Any] = Field(default_factory=dict)  # Convenience accessor (common in tools/prompts)
    payload: dict[str, Any] = Field(default_factory=dict)  # Full payload access (any field)
    user: Optional[str] = None
    tenant_id: Optional[str] = None
    agent: dict[str, Any] = Field(default_factory=dict)  # Agent context for A2A scenarios


class PolicyEvaluator:
    """Evaluates policy expressions for conditional plugin execution.

    Uses simpleeval for safe expression evaluation with AST caching for performance.
    Expressions are compiled once and cached using LRU cache.

    Supports:
    - Comparisons: ==, !=, <, >, <=, >=
    - Logical: and, or, not
    - Membership: in, contains (custom operator)
    - Existence: is_defined() function
    - Dot notation: metadata.risk_level, payload.uri
    - Literals: strings, numbers, booleans, lists
    - Parentheses: (a and b) or c

    Examples:
        >>> evaluator = PolicyEvaluator()
        >>> ctx = EvaluationContext(args={"size": 1500})
        >>> evaluator.evaluate("args.size > 1000", ctx)
        True
        >>> evaluator.evaluate("args.size <= 1000", ctx)
        False

        >>> # Test contains function with tags
        >>> ctx2 = EvaluationContext(
        ...     tags=["production", "customer-facing"]
        ... )
        >>> evaluator.evaluate('contains(tags, "production")', ctx2)
        True
        >>> evaluator.evaluate('contains(tags, "staging")', ctx2)
        False

        >>> # Test is_defined function (Note: is_defined doesn't work as expected due to
        >>> # simpleeval evaluating arguments before function call. Use 'in' operator instead)
        >>> ctx3 = EvaluationContext(args={"user_query": "test"})
        >>> evaluator.evaluate("is_defined(args.user_query)", ctx3)
        True
        >>> evaluator.evaluate('"user_query" in args', ctx3)
        True
        >>> evaluator.evaluate('"missing" in args', ctx3)
        False

        >>> # Test equality with entity_type
        >>> ctx4 = EvaluationContext(entity_type="tool", name="customer_support")
        >>> evaluator.evaluate('entity_type == "tool"', ctx4)
        True

        >>> # Test logical operators with parentheses
        >>> ctx5 = EvaluationContext(
        ...     tags=["production"],
        ...     args={"size": 1500}
        ... )
        >>> evaluator.evaluate(
        ...     'contains(tags, "production") and args.size > 1000',
        ...     ctx5
        ... )
        True

        >>> # Test 'in' operator with name
        >>> ctx6 = EvaluationContext(name="create_user")
        >>> evaluator.evaluate('name in ["create_user", "update_user"]', ctx6)
        True

        >>> # Test payload access for resources
        >>> ctx7 = EvaluationContext(
        ...     name="secrets.env",
        ...     entity_type="resource",
        ...     payload={"uri": "file:///.env", "metadata": {"size": 1024}}
        ... )
        >>> evaluator.evaluate('payload.uri.endswith(".env")', ctx7)
        True

        >>> # Test payload access for HTTP hooks
        >>> ctx8 = EvaluationContext(
        ...     entity_type="http",
        ...     payload={"method": "POST", "path": "/api/users"}
        ... )
        >>> evaluator.evaluate('payload.method == "POST"', ctx8)
        True
    """

    def __init__(self):
        """Initialize the policy evaluator with custom operators and functions."""
        self.evaluator = SimpleEval()
        self._setup_custom_operators()
        self._setup_custom_functions()
        self._setup_custom_nodes()

    def _setup_custom_operators(self):
        """Setup custom operators for the evaluator."""
        # simpleeval doesn't support adding custom infix operators to AST
        # so we just keep the default operators
        self.evaluator.operators = DEFAULT_OPERATORS.copy()

    def _setup_custom_nodes(self):
        """Setup custom AST node handlers for the evaluator."""
        # Enable list literals: [1, 2, 3]
        self.evaluator.nodes[ast.List] = lambda node: [self.evaluator._eval(x) for x in node.elts]  # pylint: disable=protected-access
        # Enable tuple literals: (1, 2, 3)
        self.evaluator.nodes[ast.Tuple] = lambda node: tuple(self.evaluator._eval(x) for x in node.elts)  # pylint: disable=protected-access

    def _setup_custom_functions(self):
        """Setup custom functions for the evaluator."""
        functions = DEFAULT_FUNCTIONS.copy()

        # Add 'is_defined' function to check if a variable exists and is not None
        # Usage: is_defined(args.user_query)
        def is_defined_func(value):
            """Check if value is defined (not None)."""
            return value is not None

        # Add 'contains' function: contains(list, value)
        # Usage: contains(entity.tags, "production")
        def contains_func(container, value):
            """Check if container contains value."""
            if container is None:
                return False
            if isinstance(container, (list, tuple, set)):
                return value in container
            if isinstance(container, str):
                return str(value) in container
            if isinstance(container, dict):
                return value in container
            return False

        functions["is_defined"] = is_defined_func
        functions["contains"] = contains_func
        self.evaluator.functions = functions

    @lru_cache(maxsize=1000)
    def _parse_expression(self, expression: str) -> ast.Expression:
        """Parse and cache expression AST.

        Uses LRU cache to store compiled ASTs for repeated expressions.
        This provides significant performance improvement for frequently
        evaluated expressions.

        Args:
            expression: The expression string to parse.

        Returns:
            Parsed AST Expression node.

        Raises:
            SyntaxError: If expression has invalid syntax.
        """
        try:
            # Parse expression and extract the expression node
            parsed = ast.parse(expression.strip(), mode="eval")
            return parsed
        except SyntaxError as e:
            logger.error(f"Failed to parse expression '{expression}': {e}")
            raise

    def evaluate(self, expression: str, context: EvaluationContext) -> bool:
        """Evaluate a policy expression against a context.

        Expressions are parsed once and cached for performance. The same
        expression evaluated multiple times will use the cached AST.

        Args:
            expression: The policy expression to evaluate.
            context: The evaluation context with variables.

        Returns:
            True if the expression evaluates to True, False otherwise.

        Raises:
            ValueError: If the expression is invalid or evaluation fails.

        Examples:
            >>> evaluator = PolicyEvaluator()
            >>> ctx = EvaluationContext(args={"count": 5})
            >>> evaluator.evaluate("args.count > 3", ctx)
            True
            >>> evaluator.evaluate("args.count < 3", ctx)
            False
        """
        if not expression or not expression.strip():
            return True

        try:
            # Parse expression (cached)
            parsed_ast = self._parse_expression(expression)

            # Set context on evaluator (simpleeval uses .names attribute)
            self.evaluator.names = {
                # Entity-related fields (also available as entity.*)
                "name": context.name,
                "entity_type": context.entity_type,
                "entity_id": context.entity_id,
                "tags": context.tags,
                "metadata": context.metadata,
                "server_name": context.server_name,
                "server_id": context.server_id,
                "gateway_id": context.gateway_id,
                # Grouped entity namespace for cleaner expressions
                "entity": {
                    "name": context.name,
                    "type": context.entity_type,
                    "id": context.entity_id,
                    "tags": context.tags,
                    "metadata": context.metadata,
                },
                # Request context
                "args": context.args,
                "payload": context.payload,
                "user": context.user,
                "tenant_id": context.tenant_id,
                "agent": context.agent,
            }

            # Evaluate using pre-parsed AST (pass the expression body, not the Module)
            result = self.evaluator.eval(expr="", previously_parsed=parsed_ast.body)

            # Convert result to boolean
            return bool(result)

        except Exception as e:
            logger.error(f"Failed to evaluate expression '{expression}': {e}")
            raise ValueError(f"Failed to evaluate expression '{expression}': {e}") from e

    def compile_expression(self, expression: str) -> Optional[ast.Expression]:
        """Pre-compile an expression for later evaluation.

        This can be used to compile expressions when loading configuration,
        allowing even faster evaluation at runtime.

        Args:
            expression: The expression to compile.

        Returns:
            Compiled AST Expression, or None if expression is empty.

        Raises:
            ValueError: If expression has invalid syntax.

        Examples:
            >>> evaluator = PolicyEvaluator()
            >>> compiled = evaluator.compile_expression("args.size > 1000")
            >>> compiled is not None
            True
        """
        if not expression or not expression.strip():
            return None

        try:
            return self._parse_expression(expression)
        except SyntaxError as e:
            raise ValueError(f"Invalid expression syntax '{expression}': {e}") from e

    def evaluate_compiled(self, compiled_expr: ast.Expression, context: EvaluationContext) -> bool:
        """Evaluate a pre-compiled expression.

        This is faster than evaluate() when the expression has been
        pre-compiled using compile_expression().

        Args:
            compiled_expr: Pre-compiled AST Expression.
            context: The evaluation context.

        Returns:
            True if the expression evaluates to True, False otherwise.

        Examples:
            >>> evaluator = PolicyEvaluator()
            >>> compiled = evaluator.compile_expression("args.count > 5")
            >>> ctx = EvaluationContext(args={"count": 10})
            >>> evaluator.evaluate_compiled(compiled, ctx)
            True
        """
        if compiled_expr is None:
            return True

        try:
            # Set context on evaluator
            self.evaluator.names = {
                "name": context.name,
                "entity_type": context.entity_type,
                "entity_id": context.entity_id,
                "tags": context.tags,
                "metadata": context.metadata,
                "server_name": context.server_name,
                "server_id": context.server_id,
                "gateway_id": context.gateway_id,
                "args": context.args,
                "payload": context.payload,
                "user": context.user,
                "tenant_id": context.tenant_id,
            }

            # Evaluate
            result = self.evaluator.eval(expr="", previously_parsed=compiled_expr.body)
            return bool(result)

        except Exception as e:
            logger.error(f"Failed to evaluate compiled expression: {e}")
            raise ValueError(f"Failed to evaluate compiled expression: {e}") from e

    def clear_cache(self):
        """Clear the expression cache.

        Useful for testing or if memory usage becomes a concern.

        Examples:
            >>> evaluator = PolicyEvaluator()
            >>> evaluator.evaluate("args.count > 5", EvaluationContext(args={"count": 10}))
            True
            >>> evaluator.clear_cache()
        """
        self._parse_expression.cache_clear()
