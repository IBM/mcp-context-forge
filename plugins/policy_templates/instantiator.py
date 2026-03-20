# -*- coding: utf-8 -*-
"""Location: ./plugins/policy_templates/instantiator.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Security Team

Template instantiation engine for the Policy Templates Library plugin.

Takes a PolicyTemplate and a caller-supplied parameter mapping, validates the
parameters against the template's parameter definitions, merges in defaults for
any omitted optional parameters, then renders the policy body using Python's
str.format_map() substitution.
"""

# Standard
import logging
from typing import Any, Dict, List, Optional, Tuple

# Local
from .models import (
    InstantiatedPolicy,
    ParameterType,
    PolicyTemplate,
    TemplateParameter,
)

logger = logging.getLogger(__name__)


class ParameterValidationError(Exception):
    """Raised when template parameters fail validation.

    Attributes:
        errors: List of human-readable error messages describing each failure.
    """

    def __init__(self, errors: List[str]) -> None:
        """Initialize with a list of validation error messages.

        Args:
            errors: One message per validation failure encountered.
        """
        self.errors = errors
        super().__init__("; ".join(errors))


class TemplateInstantiator:
    """Engine that renders a PolicyTemplate into a deployable policy string.

    Validates caller-supplied parameters, merges defaults, evaluates declarative
    validation rules, and performs ``str.format_map()`` substitution on the
    template body.

    Typical usage::

        instantiator = TemplateInstantiator(validate_on_instantiate=True)
        policy = instantiator.instantiate(template, {"phi_resource_pattern": "phi-*"})
        print(policy.policy_content)
    """

    def __init__(self, validate_on_instantiate: bool = True) -> None:
        """Initialize the instantiator.

        Args:
            validate_on_instantiate: When True, parameter validation and
                declarative rule checks are run before rendering the template.
        """
        self._validate_on_instantiate = validate_on_instantiate

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def instantiate(self, template: PolicyTemplate, parameters: Optional[Dict[str, Any]] = None) -> InstantiatedPolicy:
        """Render a template into an InstantiatedPolicy.

        Merges caller-supplied ``parameters`` with default values defined on
        the template, optionally validates the merged set, then substitutes all
        ``{param_name}`` placeholders in the template body.

        Args:
            template: The PolicyTemplate to instantiate.
            parameters: Caller-supplied parameter values.  Missing optional
                parameters are filled from their ``default`` field.

        Returns:
            An InstantiatedPolicy containing the rendered policy content and
            the resolved parameter values.

        Raises:
            ParameterValidationError: If validation is enabled and the merged
                parameters fail any constraint check.
        """
        merged = self.merge_defaults(template.spec.parameters, parameters or {})

        if self._validate_on_instantiate:
            errors = self.validate_parameters(template, merged)
            if errors:
                raise ParameterValidationError(errors)

        rendered = self._render(template.spec.template, merged, template.metadata)

        return InstantiatedPolicy(
            template_name=template.metadata.name,
            template_version=template.metadata.version,
            engine=template.spec.engine,
            parameters=merged,
            policy_content=rendered,
        )

    def validate_parameters(self, template: PolicyTemplate, parameters: Dict[str, Any]) -> List[str]:
        """Validate merged parameters against template definitions and rules.

        Checks that:
        - All ``required`` parameters are present and non-empty.
        - All declarative ``validation`` rules evaluate to True.

        Args:
            template: The template whose constraints should be enforced.
            parameters: Merged parameter dictionary to validate.

        Returns:
            List of error message strings.  Empty list means validation passed.
        """
        errors: List[str] = []

        # Check required parameters
        for param in template.spec.parameters:
            if param.required and parameters.get(param.name) is None:
                errors.append(f"Required parameter '{param.name}' is missing")

        # Evaluate declarative validation rules
        for rule in template.spec.validation:
            try:
                # Evaluate the check expression in a restricted namespace
                result = eval(rule.check, {"__builtins__": {"len": len, "isinstance": isinstance, "bool": bool, "str": str, "int": int, "list": list}}, {"parameters": parameters})  # nosec B307
                if not result:
                    errors.append(f"Validation rule failed: {rule.rule}")
            except Exception as exc:  # pylint: disable=broad-except
                errors.append(f"Validation rule error for '{rule.rule}': {exc}")

        return errors

    def merge_defaults(self, param_defs: List[TemplateParameter], supplied: Dict[str, Any]) -> Dict[str, Any]:
        """Merge caller-supplied values with template defaults.

        For each parameter definition, if the caller did not supply a value and
        the definition has a non-None ``default``, the default is used.

        Args:
            param_defs: Ordered list of TemplateParameter definitions.
            supplied: Caller-supplied parameter values (may be partial).

        Returns:
            New dictionary containing all parameter values after merging.
        """
        merged: Dict[str, Any] = {}
        for param in param_defs:
            if param.name in supplied:
                merged[param.name] = self._coerce_value(supplied[param.name], param)
            elif param.default is not None:
                merged[param.name] = param.default
        # Include any extra keys supplied by the caller that have no matching def
        for key, value in supplied.items():
            if key not in merged:
                merged[key] = value
        return merged

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _coerce_value(self, value: Any, param: TemplateParameter) -> Any:
        """Coerce a caller-supplied value to the declared parameter type.

        Best-effort coercion — on failure the original value is returned.

        Args:
            value: The raw value provided by the caller.
            param: The parameter definition specifying the target type.

        Returns:
            Coerced value, or the original value if coercion is not applicable.
        """
        try:
            if param.type == ParameterType.BOOLEAN and not isinstance(value, bool):
                return bool(value)
            if param.type == ParameterType.INTEGER and not isinstance(value, int):
                return int(value)
            if param.type == ParameterType.LIST and not isinstance(value, list):
                if isinstance(value, str):
                    return [item.strip() for item in value.split(",")]
                return [value]
        except (ValueError, TypeError):
            pass
        return value

    @staticmethod
    def _render(template_body: str, parameters: Dict[str, Any], metadata: Any) -> str:
        """Substitute {param_name} placeholders in the template body.

        Also injects metadata fields (name, version, description) into the
        substitution namespace so templates can reference {version}, {name}, etc.

        Args:
            template_body: Raw template string with {placeholder} markers.
            parameters: Resolved parameter values for substitution.
            metadata: Template metadata object supplying name/version/description.

        Returns:
            Rendered policy string with all placeholders replaced.
        """
        namespace: Dict[str, Any] = dict(parameters)
        # Inject metadata fields as convenience variables
        namespace.setdefault("version", metadata.version)
        namespace.setdefault("name", metadata.name)
        namespace.setdefault("description", metadata.description)

        # Format list parameters as comma-separated quoted strings for Cedar/OPA
        formatted: Dict[str, Any] = {}
        for key, value in namespace.items():
            if isinstance(value, list):
                formatted[key] = ", ".join(f'"{item}"' if isinstance(item, str) else str(item) for item in value)
            else:
                formatted[key] = value

        try:
            return template_body.format_map(_SafeFormatMap(formatted))
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Template rendering error: %s", exc)
            return template_body


class _SafeFormatMap(dict):
    """A dict subclass that returns the original placeholder on missing keys.

    This prevents KeyError during format_map() when the template references a
    key that was not supplied, allowing partial rendering without failure.
    """

    def __missing__(self, key: str) -> str:
        """Return the original placeholder syntax for any missing key.

        Args:
            key: The placeholder key that was not found in the mapping.

        Returns:
            The original ``{key}`` placeholder string.
        """
        return "{" + key + "}"
