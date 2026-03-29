# -*- coding: utf-8 -*-
"""Location: ./plugins/policy_templates/registry.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Security Team

Template registry for the Policy Templates Library plugin.

Responsible for loading YAML template files from one or more directories,
maintaining an in-memory index, and providing search and filter operations
used by callers that need to discover available templates.
"""

# Standard
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

# Third-Party
import yaml

# Local
from .models import PolicyTemplate, PolicyTemplateMetadata, PolicyTemplateSpec, TemplateParameter, ValidationRule, TemplateTest, TestGiven, TestPrincipal, ParameterType, PolicyEngine, RiskLevel, TestExpectation

logger = logging.getLogger(__name__)


def _coerce_parameter_type(raw: str) -> ParameterType:
    """Map a raw YAML string to a ParameterType enum value.

    Args:
        raw: The raw string from the YAML file.

    Returns:
        Corresponding ParameterType enum member, defaulting to STRING.
    """
    mapping: Dict[str, ParameterType] = {
        "string": ParameterType.STRING,
        "list": ParameterType.LIST,
        "boolean": ParameterType.BOOLEAN,
        "bool": ParameterType.BOOLEAN,
        "integer": ParameterType.INTEGER,
        "int": ParameterType.INTEGER,
        "dict": ParameterType.DICT,
    }
    return mapping.get(str(raw).lower(), ParameterType.STRING)


def _coerce_engine(raw: str) -> PolicyEngine:
    """Map a raw YAML string to a PolicyEngine enum value.

    Args:
        raw: The raw engine string from the YAML file.

    Returns:
        Corresponding PolicyEngine enum member, defaulting to CEDAR.
    """
    mapping: Dict[str, PolicyEngine] = {
        "cedar": PolicyEngine.CEDAR,
        "opa": PolicyEngine.OPA,
        "native": PolicyEngine.NATIVE,
    }
    return mapping.get(str(raw).lower(), PolicyEngine.CEDAR)


def _coerce_risk_level(raw: str) -> RiskLevel:
    """Map a raw YAML string to a RiskLevel enum value.

    Args:
        raw: The raw risk level string from the YAML file.

    Returns:
        Corresponding RiskLevel enum member, defaulting to MEDIUM.
    """
    mapping: Dict[str, RiskLevel] = {
        "low": RiskLevel.LOW,
        "medium": RiskLevel.MEDIUM,
        "high": RiskLevel.HIGH,
        "critical": RiskLevel.CRITICAL,
    }
    return mapping.get(str(raw).lower(), RiskLevel.MEDIUM)


def _parse_template_from_dict(data: Dict[str, Any], source_path: str) -> Optional[PolicyTemplate]:
    """Parse a raw YAML dictionary into a PolicyTemplate model.

    Args:
        data: Dictionary loaded from a YAML template file.
        source_path: Filesystem path of the source file (for diagnostics).

    Returns:
        Populated PolicyTemplate model, or None if parsing fails.
    """
    try:
        meta_raw = data.get("metadata", {})
        spec_raw = data.get("spec", {})

        # Parse metadata
        metadata = PolicyTemplateMetadata(
            name=meta_raw.get("name", ""),
            version=str(meta_raw.get("version", "1.0.0")),
            description=meta_raw.get("description", ""),
            category=meta_raw.get("category", "uncategorized"),
            compliance_frameworks=list(meta_raw.get("compliance_frameworks", [])),
            risk_level=_coerce_risk_level(meta_raw.get("risk_level", "medium")),
            author=meta_raw.get("author", ""),
            last_reviewed=str(meta_raw.get("last_reviewed", "")),
            tags=list(meta_raw.get("tags", [])),
        )

        # Parse parameters
        parameters: List[TemplateParameter] = []
        for p in spec_raw.get("parameters", []):
            parameters.append(
                TemplateParameter(
                    name=p.get("name", ""),
                    type=_coerce_parameter_type(p.get("type", "string")),
                    description=p.get("description", ""),
                    default=p.get("default"),
                    required=bool(p.get("required", False)),
                )
            )

        # Parse validation rules
        validation_rules: List[ValidationRule] = []
        for v in spec_raw.get("validation", []):
            validation_rules.append(
                ValidationRule(
                    rule=v.get("rule", ""),
                    check=v.get("check", "True"),
                )
            )

        # Parse tests
        tests: List[TemplateTest] = []
        for t in spec_raw.get("tests", []):
            given_raw = t.get("given", {})
            principal_raw = given_raw.get("principal", {})
            # Extract role, promote remaining keys to attributes
            role = principal_raw.get("role", "")
            attributes = {k: v for k, v in principal_raw.items() if k != "role"}
            tests.append(
                TemplateTest(
                    name=t.get("name", ""),
                    given=TestGiven(
                        principal=TestPrincipal(role=role, **attributes),
                        action=given_raw.get("action", ""),
                        resource=str(given_raw.get("resource", "")),
                        context=dict(given_raw.get("context", {})),
                    ),
                    expect=TestExpectation(t.get("expect", "deny")),
                )
            )

        # Build spec
        spec = PolicyTemplateSpec(
            engine=_coerce_engine(spec_raw.get("engine", "cedar")),
            parameters=parameters,
            template=spec_raw.get("template", ""),
            validation=validation_rules,
            tests=tests,
        )

        return PolicyTemplate(
            apiVersion=data.get("apiVersion", "contextforge.io/v1"),
            kind=data.get("kind", "PolicyTemplate"),
            metadata=metadata,
            spec=spec,
            source_path=source_path,
        )

    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Failed to parse template from %s: %s", source_path, exc)
        return None


class PolicyTemplateRegistry:
    """In-memory registry of policy templates loaded from YAML files.

    Supports loading from multiple template directories, search by keyword,
    filter by compliance framework, and category listing.

    Typical usage::

        registry = PolicyTemplateRegistry()
        registry.load(["plugins/policy_templates/templates"])
        template = registry.get("hipaa-phi-protection")
        results = registry.search("audit")
        hipaa_templates = registry.get_by_compliance("HIPAA")
    """

    def __init__(self) -> None:
        """Initialize an empty template registry."""
        self._templates: Dict[str, PolicyTemplate] = {}

    def load(self, template_dirs: List[str]) -> int:
        """Load all YAML template files from the given directories recursively.

        Walks each directory, attempts to parse every .yaml/.yml file it finds,
        and adds successfully parsed templates to the in-memory index.

        Args:
            template_dirs: List of directory paths to scan for template files.

        Returns:
            Number of templates successfully loaded.
        """
        loaded = 0
        for dir_str in template_dirs:
            dir_path = Path(dir_str)
            if not dir_path.exists():
                logger.warning("Template directory does not exist: %s", dir_path)
                continue
            for yaml_file in sorted(dir_path.rglob("*.yaml")):
                loaded += self._load_file(yaml_file)
            for yaml_file in sorted(dir_path.rglob("*.yml")):
                loaded += self._load_file(yaml_file)
        logger.info("PolicyTemplateRegistry: loaded %d templates from %d directories", loaded, len(template_dirs))
        return loaded

    def _load_file(self, path: Path) -> int:
        """Parse a single YAML file and register the template if valid.

        Args:
            path: Path to the YAML template file.

        Returns:
            1 if the template was loaded successfully, 0 otherwise.
        """
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if not isinstance(data, dict):
                logger.debug("Skipping non-dict YAML file: %s", path)
                return 0
            if data.get("kind") != "PolicyTemplate":
                logger.debug("Skipping non-PolicyTemplate YAML file: %s", path)
                return 0
            template = _parse_template_from_dict(data, str(path))
            if template is None:
                return 0
            name = template.metadata.name
            if name in self._templates:
                logger.debug("Overwriting duplicate template name '%s' from %s", name, path)
            self._templates[name] = template
            return 1
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Error loading template file %s: %s", path, exc)
            return 0

    def get(self, name: str) -> Optional[PolicyTemplate]:
        """Retrieve a template by its exact name.

        Args:
            name: The unique template name (e.g., 'hipaa-phi-protection').

        Returns:
            The matching PolicyTemplate, or None if not found.
        """
        return self._templates.get(name)

    def list_all(self) -> List[PolicyTemplate]:
        """Return all registered templates in alphabetical order by name.

        Returns:
            Sorted list of all loaded PolicyTemplate objects.
        """
        return sorted(self._templates.values(), key=lambda t: t.metadata.name)

    def search(self, query: str) -> List[PolicyTemplate]:
        """Search templates by keyword across name, description, category, and tags.

        The search is case-insensitive and matches any template whose name,
        description, category, or tags contain the query substring.

        Args:
            query: Keyword or phrase to search for.

        Returns:
            List of matching PolicyTemplate objects sorted by name.
        """
        q = query.lower()
        results: List[PolicyTemplate] = []
        for template in self._templates.values():
            meta = template.metadata
            haystack = " ".join(
                [
                    meta.name,
                    meta.description,
                    meta.category,
                    " ".join(meta.tags),
                    " ".join(meta.compliance_frameworks),
                ]
            ).lower()
            if q in haystack:
                results.append(template)
        return sorted(results, key=lambda t: t.metadata.name)

    def get_by_compliance(self, framework: str) -> List[PolicyTemplate]:
        """Return all templates that address a specific compliance framework.

        Args:
            framework: Compliance framework name (e.g., 'HIPAA', 'PCI-DSS').

        Returns:
            List of PolicyTemplate objects tagged with the given framework.
        """
        fw_upper = framework.upper()
        results = [t for t in self._templates.values() if fw_upper in [f.upper() for f in t.metadata.compliance_frameworks]]
        return sorted(results, key=lambda t: t.metadata.name)

    def list_categories(self) -> List[str]:
        """Return a deduplicated sorted list of all template categories.

        Returns:
            Sorted list of unique category path strings.
        """
        cats = {t.metadata.category for t in self._templates.values()}
        return sorted(cats)

    def filter(
        self,
        category: Optional[str] = None,
        compliance_framework: Optional[str] = None,
        engine: Optional[str] = None,
        risk_level: Optional[str] = None,
    ) -> List[PolicyTemplate]:
        """Filter templates by one or more criteria simultaneously.

        All supplied criteria are combined with AND logic.  Omitted criteria
        are not applied.

        Args:
            category: Category path prefix to filter by (e.g., 'compliance').
            compliance_framework: Compliance framework name to filter by.
            engine: Policy engine name to filter by (cedar, opa, native).
            risk_level: Risk level to filter by (low, medium, high, critical).

        Returns:
            List of templates matching all supplied criteria, sorted by name.
        """
        results = list(self._templates.values())

        if category:
            cat_lower = category.lower()
            results = [t for t in results if t.metadata.category.lower().startswith(cat_lower)]

        if compliance_framework:
            fw_upper = compliance_framework.upper()
            results = [t for t in results if fw_upper in [f.upper() for f in t.metadata.compliance_frameworks]]

        if engine:
            engine_lower = engine.lower()
            results = [t for t in results if t.spec.engine.value.lower() == engine_lower]

        if risk_level:
            rl_lower = risk_level.lower()
            results = [t for t in results if t.metadata.risk_level.value.lower() == rl_lower]

        return sorted(results, key=lambda t: t.metadata.name)

    @property
    def count(self) -> int:
        """Return the total number of templates currently in the registry.

        Returns:
            Integer count of loaded templates.
        """
        return len(self._templates)
