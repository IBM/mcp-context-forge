# -*- coding: utf-8 -*-
"""Resolve plugin display metadata from installed packages."""

# Standard
from importlib import metadata as importlib_metadata
import sys
from typing import Any, Dict, Mapping, Optional, Tuple

# Third-Party
from cpex.framework.models import Config
from cpex.framework.utils import parse_class_name


def _safe_str(value: Any) -> Optional[str]:
    """Return non-empty strings only."""
    return value if isinstance(value, str) and value else None


def _module_name_from_kind(kind: Optional[str]) -> Optional[str]:
    """Extract the importable module name from a plugin kind."""
    if not kind:
        return None

    if ":" in kind:
        module_name = kind.split(":", 1)[0]
    else:
        module_name, _class_name = parse_class_name(kind)

    return module_name or None


def _distribution_metadata(
    module_name: Optional[str],
    package_map: Mapping[str, list[str]],
    distribution_cache: Dict[str, Tuple[Optional[str], Optional[str], Optional[str]]],
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Resolve version, author, and description from installed distribution metadata."""
    if not module_name:
        return None, None, None

    top_level_package = module_name.split(".", 1)[0]
    candidate_distributions = list(package_map.get(top_level_package, []))
    candidate_distributions.extend([module_name, top_level_package, top_level_package.replace("_", "-")])

    seen = set()
    for distribution_name in candidate_distributions:
        if distribution_name in seen:
            continue
        seen.add(distribution_name)

        if distribution_name not in distribution_cache:
            try:
                distribution = importlib_metadata.distribution(distribution_name)
            except importlib_metadata.PackageNotFoundError:
                distribution_cache[distribution_name] = (None, None, None)
            else:
                package_metadata = distribution.metadata
                author = package_metadata.get("Author") or package_metadata.get("Maintainer") or package_metadata.get("Author-email")
                distribution_cache[distribution_name] = (_safe_str(distribution.version), _safe_str(author), _safe_str(package_metadata.get("Summary")))

        metadata = distribution_cache[distribution_name]
        if any(metadata):
            return metadata

    return None, None, None


def _loaded_module_metadata(module_name: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Resolve metadata from an already-loaded module without importing disabled plugins."""
    if not module_name:
        return None, None, None

    module = sys.modules.get(module_name)
    if module is None:
        return None, None, None

    return _safe_str(getattr(module, "__version__", None)), _safe_str(getattr(module, "__author__", None)), _safe_str(getattr(module, "__description__", None))


def resolve_plugin_metadata(
    plugin_config: Any,
    package_map: Optional[Mapping[str, list[str]]] = None,
    distribution_cache: Optional[Dict[str, Tuple[Optional[str], Optional[str], Optional[str]]]] = None,
) -> Dict[str, str]:
    """Resolve display metadata for a plugin config."""
    kind = _safe_str(getattr(plugin_config, "kind", None)) if plugin_config else None
    module_name = _module_name_from_kind(kind)
    resolved_package_map = package_map if package_map is not None else importlib_metadata.packages_distributions()
    resolved_distribution_cache = distribution_cache if distribution_cache is not None else {}
    dist_version, dist_author, dist_description = _distribution_metadata(module_name, resolved_package_map, resolved_distribution_cache)
    module_version, module_author, module_description = _loaded_module_metadata(module_name)

    return {
        "description": dist_description or module_description or (_safe_str(getattr(plugin_config, "description", None)) if plugin_config else None) or "",
        "author": dist_author or module_author or (_safe_str(getattr(plugin_config, "author", None)) if plugin_config else None) or "Unknown",
        "version": dist_version or module_version or (_safe_str(getattr(plugin_config, "version", None)) if plugin_config else None) or "0.0.0",
    }


def enrich_config_plugin_metadata(config: Config) -> Config:
    """Return config with plugin display metadata resolved once at load time."""
    if not config.plugins:
        return config

    package_map = importlib_metadata.packages_distributions()
    distribution_cache: Dict[str, Tuple[Optional[str], Optional[str], Optional[str]]] = {}
    plugins = []
    changed = False

    for plugin in config.plugins:
        metadata = resolve_plugin_metadata(plugin, package_map=package_map, distribution_cache=distribution_cache)
        update = {}
        if metadata["description"] or plugin.description is not None:
            update["description"] = metadata["description"]
        if metadata["author"] != "Unknown" or plugin.author is not None:
            update["author"] = metadata["author"]
        if metadata["version"] != "0.0.0" or plugin.version is not None:
            update["version"] = metadata["version"]

        plugins.append(plugin.model_copy(update=update) if update else plugin)
        changed = changed or any(getattr(plugin, key) != value for key, value in update.items())

    if not changed:
        return config
    return config.model_copy(update={"plugins": plugins}, deep=True)
