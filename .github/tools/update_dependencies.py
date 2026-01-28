#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Asynchronous Python dependency updater with persistent caching,
comment preservation, and multiple configuration options.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This script supports updating dependencies in both pyproject.toml and requirements.txt
files, optionally creates a backup (by default named `.depupdate.<timestamp>`),
and updates dependency version constraints based on the latest versions
available on PyPI. For pyproject.toml files, it processes both [project].dependencies
and [project.optional-dependencies], **preserves comments by default** (with an option
to remove them), sorts dependencies alphabetically by default (optional), and provides
colored output showing the status of each dependency.

Features:
    1. Support for both pyproject.toml and requirements.txt formats.
    2. Validate TOML before and after modification (including checking for `[project]`).
    3. Creates a timestamped backup of the original file by default (e.g. `.depupdate.1678891234`)
       (can be disabled with `--no-backup`).
    4. Uses an optional local YAML file (`.depsorter.yml`) to override defaults.
    5. Allows command-line overrides of concurrency, timeouts, log level, etc.
    6. **Persistent** caching of the latest PyPI versions for a configurable TTL (default 10 minutes),
       stored by default in `.depsorter_cache.json`.
    7. Handles optional comment removal.
    8. Dry-run mode for previewing changes without applying them.
    9. Can choose how to update version constraints:
       - pinned (== latest)
       - gte (>= latest) (default)
       - lte (<= latest)
    10. Can ignore specific dependencies from being updated.

Example usage:
    $ python update_dependencies.py --file pyproject.toml --log-level DEBUG --verbose --dry-run
    $ python update_dependencies.py --file pyproject.toml --backup my_backup.toml
    $ python update_dependencies.py --file pyproject.toml --no-backup
    $ python update_dependencies.py --file requirements.txt --version-spec pinned
    $ python update_dependencies.py --concurrency 5
    $ python update_dependencies.py --no-sort
    $ python update_dependencies.py --sort
    $ python update_dependencies.py --http-timeout 5 --http-client-timeout 20
    $ python update_dependencies.py --remove-comments
    $ python update_dependencies.py --cache-ttl 120  # 2-minute cache
    $ python update_dependencies.py --cache-ttl 0    # 0 cache (always fetch latest)
    $ python update_dependencies.py --cache-file .my_cache.json
    $ python update_dependencies.py --version-spec pinned
    $ python update_dependencies.py --ignore-dependency starlette
    $ python update_dependencies.py --ignore-dependency starlette --ignore-dependency fastapi
"""

# Standard
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sys
import time
from typing import (
    Any,
    cast,
    Dict,
    List,
    NamedTuple,
    Optional,
    Set,
    Tuple,
    TypeVar,
    Union,
)

# Third-Party
from colorama import Fore, init, Style
import httpx
import tomlkit
from tomlkit.items import Array, Comment, Item, String
import yaml

# =====================================================================
# GLOBAL CONFIGURATION AND CONSTANTS
# =====================================================================

#: Default path to dependency file.
DEFAULT_DEPENDENCY_FILE = "pyproject.toml"

#: Default concurrency for async HTTP requests.
DEFAULT_CONCURRENCY = 3

#: Default timeout for **each** individual HTTP request (seconds).
DEFAULT_HTTP_TIMEOUT = 10.0

#: Default overall timeout for the HTTP client (seconds).
DEFAULT_HTTP_CLIENT_TIMEOUT = 15.0

#: Default cache TTL in seconds (10 minutes).
DEFAULT_CACHE_TTL = 600.0

#: Default path for cache file.
DEFAULT_CACHE_FILE = ".depsorter_cache.json"

#: Default log format.
DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

#: Default date format for logs.
DEFAULT_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: Regex pattern for splitting dependencies into (name, extras, spec).
DEP_PATTERN = re.compile(r"^(?P<name>[A-Za-z0-9_.\-]+)(?P<extras>\[.*?\])?(?P<spec>.*)$")

#: ANSI color settings
COLOR_SUCCESS = Fore.GREEN
COLOR_WARNING = Fore.YELLOW
COLOR_ERROR = Fore.RED
COLOR_INFO = Fore.CYAN
COLOR_HIGHLIGHT = Fore.MAGENTA
COLOR_SKIP = Fore.BLUE

#: Exit codes
EXIT_SUCCESS = 0
EXIT_FILE_ERROR = 1
EXIT_PARSING_ERROR = 2
EXIT_HTTP_ERROR = 3
EXIT_PROCESSING_ERROR = 4
EXIT_INTERRUPTED = 130

# Configure global logger
logging.basicConfig(
    level=logging.INFO,
    format=DEFAULT_LOG_FORMAT,
    datefmt=DEFAULT_LOG_DATE_FORMAT,
)
logger = logging.getLogger("dependency_updater")

# Initialize colorama for cross-platform colored output
init(autoreset=True)

#: Type alias for tomlkit items
TomlItem = Union[Item, String, Comment, dict, Any]

#: Type alias for dictionary of package->latest_version
VersionDict = Dict[str, Optional[str]]

#: Arbitrary type var
T = TypeVar("T")


class DependencyInfo(NamedTuple):
    """
    Container for dependency parsing results.

    Attributes:
        name: The base package name, e.g. "fastapi".
        extras: The bracketed extras, e.g. "[gunicorn]".
        spec: The version specifier, e.g. ">=0.80.0".
    """

    name: str
    extras: str
    spec: str


# ---------------------------------------------------------------------
# GLOBAL PERSISTENT CACHE FOR PYPI VERSIONS
# ---------------------------------------------------------------------

#: Global in-memory cache: package -> (version_or_None, timestamp)
_CACHE: Dict[str, Tuple[Optional[str], float]] = {}


def load_cache_from_file(path: str) -> None:
    """
    Load the cache from a JSON file into the global _CACHE dictionary.

    Logs relevant info about cache loading and any issues encountered.

    Args:
        path: Path to the JSON cache file.
    """
    global _CACHE
    cache_file = Path(path)
    if not cache_file.is_file():
        logger.debug(f"Cache file {path} not found. No cache loaded.")
        return

    try:
        with cache_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
            # data should be a dict of {pkg_name: [version, timestamp]}
            # Rebuild it as a dict of {pkg_name: (version, timestamp)}
            loaded_cache = {}
            for pkg, val in data.items():
                if isinstance(val, list) and len(val) == 2 and isinstance(val[1], (int, float)):
                    loaded_cache[pkg] = (val[0], float(val[1]))
            _CACHE = loaded_cache
            logger.info(f"\n🗂  Loaded cache from '{path}' with {len(_CACHE)} entries.\n")
    except Exception as exc:
        logger.warning(f"Could not load cache from {path}: {exc}")


def write_cache_to_file(path: str) -> None:
    """
    Write the global _CACHE dictionary to a JSON file.

    Args:
        path: Path to the JSON cache file.
    """
    global _CACHE
    try:
        with open(path, "w", encoding="utf-8") as f:
            # Convert {pkg: (version, timestamp)} to {pkg: [version, timestamp]}
            json.dump(
                {pkg: [val[0], val[1]] for pkg, val in _CACHE.items()},
                f,
                indent=2,
            )
        logger.info(f"\n💾 Wrote {len(_CACHE)} cache entries to '{path}'.\n")
    except Exception as exc:
        logger.warning(f"Error writing cache to {path}: {exc}")


def get_cached_version(pkg_name: str, cache_ttl: float) -> Optional[str]:
    """
    Retrieve a cached version for `pkg_name` if it exists and hasn't expired.

    Logs whether the cache is used or if it has expired.

    Args:
        pkg_name: The package name (e.g. "fastapi").
        cache_ttl: Maximum age (in seconds) for a cached entry.
                   If set to 0, effectively disables cache usage.

    Returns:
        The cached version string if still valid, else None.
    """
    global _CACHE

    if cache_ttl <= 0:
        logger.debug(f"Cache TTL is 0 or less; skipping cache for {pkg_name}.")
        return None

    entry = _CACHE.get(pkg_name)
    if not entry:
        logger.debug(f"No cache entry found for {pkg_name}.")
        return None

    version, fetch_time = entry
    age = time.time() - fetch_time
    if age < cache_ttl:
        logger.info(f"📦 [CACHE HIT] {pkg_name}: {version} (age={age:.1f}s, ttl={cache_ttl}s)")
        return version

    # Expired; remove and return None
    logger.info(f"♻️ [CACHE EXPIRED] {pkg_name} cache age={age:.1f}s ttl={cache_ttl}s. Removing entry.")
    del _CACHE[pkg_name]
    return None


def store_cached_version(pkg_name: str, version: Optional[str]) -> None:
    """
    Store a fetched version in the cache, along with the current timestamp.

    Args:
        pkg_name: The package name.
        version: The version string (or None if not found).
    """
    global _CACHE
    _CACHE[pkg_name] = (version, time.time())
    logger.debug(f"Storing version for {pkg_name}: {version}")


# =====================================================================
# CONFIG FILE READING
# =====================================================================


def read_depsorter_config(
    config_filename: str = ".depsorter.yml",
) -> Dict[str, Any]:
    """
    Read the config from `.depsorter.yml` if it exists.

    This allows the user to override default settings in a local YAML file.
    Any values provided here can be further overridden by command-line args.

    Logs whether a config file was found, and any issues encountered.

    Args:
        config_filename: The name/path of the YAML config file.

    Returns:
        A dictionary of configuration options. If no file is found or
        parsing fails, returns an empty dict.
    """
    logger.debug(f"Attempting to load config from '{config_filename}'.")
    config_path = Path(config_filename)
    if not config_path.is_file():
        logger.debug("No .depsorter.yml file found.")
        return {}

    try:
        with config_path.open("r", encoding="utf-8") as f:
            parsed = yaml.safe_load(f)
            if not isinstance(parsed, dict):
                logger.warning("`.depsorter.yml` is not a valid YAML dictionary.")
                return {}
            logger.info(f"📄 Local YAML config '{config_filename}' loaded successfully.")
            return parsed
    except Exception as exc:
        logger.warning(f"Error reading {config_filename}: {exc}")
        return {}


# =====================================================================
# CORE FUNCTIONALITY
# =====================================================================


async def fetch_latest_version(
    pkg_name: str,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    timeout: float,
    cache_ttl: float,
    ignored_dependencies: Set[str],
) -> Tuple[str, Optional[str]]:
    """
    Query PyPI for the latest version of a package (async), with persistent caching.

    Logs information about successes, failures, or timeouts at appropriate levels.

    Args:
        pkg_name: The name of the package to query (e.g. "fastapi").
        client: An existing `httpx.AsyncClient` for making HTTP requests.
        semaphore: A semaphore to limit concurrent requests.
        timeout: Per-request timeout in seconds.
        cache_ttl: Time-to-live for cached results in seconds.
        ignored_dependencies: Set of package names to skip updating.

    Returns:
        A tuple of `(pkg_name, version_or_None)`.
        If an error or a 404 occurs, the version is None.
    """
    # Check if this dependency should be ignored
    if pkg_name.lower() in ignored_dependencies:
        logger.info(f"🚫 [IGNORED] Skipping {pkg_name} (in ignore list)")
        return pkg_name, None

    # Check cache before hitting the semaphore
    cached_version = get_cached_version(pkg_name, cache_ttl)
    if cached_version is not None:
        return pkg_name, cached_version

    url = f"https://pypi.org/pypi/{pkg_name}/json"
    async with semaphore:
        logger.debug(f"Requesting latest version for {pkg_name} from {url}")
        try:
            resp = await client.get(url, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                version = data["info"]["version"]
                store_cached_version(pkg_name, version)
                logger.debug(f"Fetched version for {pkg_name}: {version}")
                return pkg_name, version

            logger.warning(f"⚠️ Could not get version for {pkg_name} (HTTP {resp.status_code})")
            print(f"{COLOR_WARNING}Warning: Could not get version for {pkg_name} (HTTP {resp.status_code})")
            store_cached_version(pkg_name, None)
            return pkg_name, None

        except httpx.TimeoutException:
            logger.warning(f"⚠️ Timeout while fetching version for {pkg_name}")
            print(f"{COLOR_WARNING}Timeout while fetching version for {pkg_name}")
        except httpx.HTTPError as e:
            logger.error(f"💥 HTTP error fetching version for {pkg_name}: {e}")
            print(f"{COLOR_ERROR}HTTP error fetching version for {pkg_name}: {e}")
        except Exception as e:
            logger.error(
                f"💥 Unexpected error fetching version for {pkg_name}: {e}",
                exc_info=True,
            )
            print(f"{COLOR_ERROR}Error fetching version for {pkg_name}: {e}")

    # On failure
    store_cached_version(pkg_name, None)
    return pkg_name, None


async def fetch_all_latest_versions(
    package_names: Set[str],
    concurrency: int,
    client_timeout: float,
    request_timeout: float,
    cache_ttl: float,
    ignored_dependencies: Set[str],
) -> VersionDict:
    """
    Concurrently query PyPI for the latest versions of multiple packages.

    Logs overall retrieval info and final stats.

    Args:
        package_names: A set of package names to query.
        concurrency: The max number of concurrent requests.
        client_timeout: Overall async client timeout in seconds.
        request_timeout: Per-request timeout in seconds.
        cache_ttl: Time-to-live for cached results in seconds.
        ignored_dependencies: Set of package names to skip updating.

    Returns:
        A dict mapping package name -> latest version (or None).
    """
    if not package_names:
        logger.warning("⚠️ No packages provided to fetch versions for.")
        return {}

    # Filter out ignored dependencies for fetching
    packages_to_fetch = package_names - ignored_dependencies
    ignored_count = len(package_names) - len(packages_to_fetch)

    if ignored_count > 0:
        logger.info(f"🚫 Ignoring {ignored_count} dependencies: {', '.join(sorted(ignored_dependencies & package_names))}")

    logger.info(f"\n📦 [FETCH] Gathering versions for {len(packages_to_fetch)} packages ===\n")
    semaphore = asyncio.Semaphore(concurrency)
    versions: Dict[str, Optional[str]] = {}

    async with httpx.AsyncClient(timeout=client_timeout) as client:
        tasks = [fetch_latest_version(pkg, client, semaphore, request_timeout, cache_ttl, ignored_dependencies) for pkg in packages_to_fetch]
        for future in asyncio.as_completed(tasks):
            try:
                pkg, version = await future
                versions[pkg] = version
            except Exception as e:
                logger.error(f"💥 Error processing result for {pkg}: {e}", exc_info=True)

    logger.info(f"\n✅ Retrieved versions for {len(versions)} packages.\n")
    return versions


def parse_dependency(dep_str: str) -> DependencyInfo:
    """
    Parse a dependency string (e.g., "fastapi[all]>=0.80.0") into components.

    Logs if parsing fails.

    Args:
        dep_str: The raw dependency string.

    Returns:
        A `DependencyInfo` namedtuple with (name, extras, spec).
    """
    dep_str = dep_str.strip()

    # Skip empty lines and comment-only lines
    if not dep_str or dep_str.startswith("#"):
        return DependencyInfo("", "", "")

    match = DEP_PATTERN.match(dep_str)
    if not match:
        logger.warning(f"⚠️ Could not parse dependency string: {dep_str}")
        return DependencyInfo(dep_str, "", "")

    return DependencyInfo(
        name=match.group("name"),
        extras=match.group("extras") or "",
        spec=match.group("spec"),
    )


def update_dependency_str(
    dep_str: str,
    latest_versions: VersionDict,
    version_spec: str,
    ignored_dependencies: Set[str],
) -> Tuple[str, str, bool]:
    """
    Update a single dependency string with the latest version from PyPI.

    Args:
        dep_str: Original dependency string.
        latest_versions: A dict from package -> latest version (or None).
        version_spec: One of "pinned" (==latest), "gte" (>=latest), or "lte" (<=latest).
        ignored_dependencies: Set of package names to skip updating.

    Returns:
        A tuple of (original_string, updated_string, was_ignored).
        If the latest version is unavailable or ignored, the updated string == original.
    """
    # Skip empty lines and comment-only lines
    if not dep_str or dep_str.strip().startswith("#"):
        return dep_str, dep_str, False

    dep_info = parse_dependency(dep_str)
    if not dep_info.name:  # Skip if no package name was found
        return dep_str, dep_str, False

    # Check if this dependency should be ignored
    if dep_info.name.lower() in ignored_dependencies:
        return dep_str, dep_str, True

    latest = latest_versions.get(dep_info.name)

    if latest:
        if version_spec == "pinned":
            new_dep = f"{dep_info.name}{dep_info.extras}=={latest}"
        elif version_spec == "lte":
            new_dep = f"{dep_info.name}{dep_info.extras}<={latest}"
        else:  # default "gte"
            new_dep = f"{dep_info.name}{dep_info.extras}>={latest}"
        return dep_str, new_dep, False

    return dep_str, dep_str, False


def extract_package_name(dep_str: str) -> str:
    """
    Extract the normalized (lowercase) package name from a dependency string.

    Args:
        dep_str: Raw dependency string.

    Returns:
        Lowercase package name for consistent sorting.
    """
    # Skip comment-only lines
    if not dep_str or dep_str.strip().startswith("#"):
        return ""

    dep_info = parse_dependency(dep_str)
    return dep_info.name.lower()


def update_dependency_array(
    dep_array: Array,
    latest_versions: VersionDict,
    verbose: bool,
    sort_dependencies: bool,
    remove_comments: bool,
    version_spec: str,
    ignored_dependencies: Set[str],
) -> Array:
    """
    Update a tomlkit Array of dependencies, optionally preserving comments.

    Logs updates, shows before/after states, and sorts if requested.

    Args:
        dep_array: A tomlkit `Array` object containing dependency strings.
        latest_versions: Dictionary mapping package names to their latest version.
        verbose: Whether to log verbose messages.
        sort_dependencies: If True, sort dependencies alphabetically.
        remove_comments: If True, do not preserve comments from original entries.
        version_spec: The version update strategy ("pinned", "gte", or "lte").
        ignored_dependencies: Set of package names to skip updating.

    Returns:
        A new tomlkit Array with updated (and possibly sorted) dependencies.
    """
    updated_items: List[Tuple[str, Any]] = []

    for item in dep_array:
        # If not a string or tomlkit string, skip
        if not (isinstance(item, str) or hasattr(item, "value")):
            logger.warning(f"⚠️ Skipping non-dependency item: {item}")
            continue

        dep_str = str(item)
        original, new_dep, was_ignored = update_dependency_str(dep_str, latest_versions, version_spec, ignored_dependencies)

        if was_ignored:
            print(f"{COLOR_SKIP}Ignored: {original} (in ignore list)")
        elif original == new_dep:
            print(f"{COLOR_SUCCESS}Up-to-date: Before: {original} | After: {new_dep}")
        else:
            print(f"{COLOR_WARNING}Updated: Before: {original} {Style.RESET_ALL}--> {COLOR_SUCCESS}{new_dep}")
            if verbose:
                logger.info(f"📝 Updated dependency: {original} -> {new_dep}")

        new_item = tomlkit.string(new_dep)
        # Conditionally preserve trivia (comments, indent, whitespace)
        if remove_comments:
            logger.debug(f"Skipping comment preservation for {dep_str}")
        else:
            logger.debug(f"Preserving comment for {dep_str}")
            if hasattr(item, "trivia"):
                try:
                    # Attempt to copy over all comment-related trivia
                    new_item.trivia.indent = item.trivia.indent
                    new_item.trivia.comment_ws = item.trivia.comment_ws
                    new_item.trivia.comment = item.trivia.comment
                    new_item.trivia.trail = item.trivia.trail

                    # At DEBUG -> also show what comment we are preserving
                    if item.trivia.comment:
                        logger.debug(f"Preserved comment text for {dep_str}: {item.trivia.comment}")

                except AttributeError:
                    logger.warning(f"⚠️ Could not fully preserve trivia for {dep_str}")

        updated_items.append((extract_package_name(new_dep), new_item))

    if sort_dependencies:
        logger.info("🔡 Sorting dependencies alphabetically.")
        updated_items.sort(key=lambda x: x[0])
    else:
        logger.info("🌀 Leaving dependencies unsorted as requested.")

    new_array = tomlkit.array()
    new_array.multiline(True)
    for _, item in updated_items:
        new_array.append(item)

    return new_array


def collect_unique_packages(dep_array: Array) -> Set[str]:
    """
    Collect unique package names from a tomlkit Array of dependencies.

    Args:
        dep_array: A tomlkit `Array` containing dependency entries.

    Returns:
        A set of unique package names (ignoring case).
    """
    packages: Set[str] = set()
    for item in dep_array:
        if isinstance(item, str) or hasattr(item, "value"):
            dep_info = parse_dependency(str(item))
            if dep_info.name.strip():
                packages.add(dep_info.name)
    return packages


def safe_get_array(container: Any, key: str) -> Optional[Array]:
    """
    Safely retrieve an `Array` from a container (dict-like).

    Args:
        container: The object that might have a `.get(...)` method.
        key: The key to retrieve.

    Returns:
        The tomlkit `Array` if found, otherwise None.
    """
    if not hasattr(container, "get"):
        return None

    try:
        value = container.get(key)
        if isinstance(value, Array):
            return value
    except (AttributeError, KeyError, TypeError):
        pass

    return None


def safe_get_dict_keys(container: Any) -> List[str]:
    """
    Safely retrieve keys from a container (dict-like).

    Args:
        container: The object that might have a `.keys()` method.

    Returns:
        A list of keys if the container is dict-like, otherwise empty.
    """
    if not hasattr(container, "keys"):
        return []

    try:
        return list(container.keys())
    except (AttributeError, TypeError):
        return []


# =====================================================================
# FILE PROCESSING
# =====================================================================


def is_requirements_txt(file_path: str) -> bool:
    """
    Determine if the file is a requirements.txt file based on extension.

    Args:
        file_path: Path to the file to check.

    Returns:
        True if the file appears to be a requirements.txt file, False otherwise.
    """
    return file_path.lower().endswith(".txt")


async def process_file(
    file_path: str,
    concurrency: int,
    verbose: bool,
    dry_run: bool,
    http_timeout: float,
    http_client_timeout: float,
    sort_dependencies: bool,
    remove_comments: bool,
    cache_ttl: float,
    version_spec: str,
    ignored_dependencies: Set[str],
) -> bool:
    """
    Process and update dependencies in a dependency file.

    Determines the file type based on extension and calls the appropriate processor.

    Args:
        file_path: The path to the dependency file.
        concurrency: Max number of concurrent HTTP requests.
        verbose: If True, prints/logs extra debug info.
        dry_run: If True, only prints the result without saving.
        http_timeout: Per-request timeout in seconds.
        http_client_timeout: Overall client timeout in seconds.
        sort_dependencies: Whether to sort dependencies alphabetically.
        remove_comments: If True, remove comments from updated dependencies.
        cache_ttl: Time (in seconds) to cache PyPI queries (0 disables).
        version_spec: Version update strategy ("pinned", "gte", or "lte").
        ignored_dependencies: Set of package names to skip updating.

    Returns:
        True if processing succeeded, False otherwise.
    """
    if is_requirements_txt(file_path):
        return await process_requirements(
            file_path,
            concurrency,
            verbose,
            dry_run,
            http_timeout,
            http_client_timeout,
            sort_dependencies,
            remove_comments,
            cache_ttl,
            version_spec,
            ignored_dependencies,
        )
    else:
        # Assume pyproject.toml for any other extension
        return await process_pyproject(
            file_path,
            concurrency,
            verbose,
            dry_run,
            http_timeout,
            http_client_timeout,
            sort_dependencies,
            remove_comments,
            cache_ttl,
            version_spec,
            ignored_dependencies,
        )


async def process_requirements(
    requirements_path: str,
    concurrency: int,
    verbose: bool,
    dry_run: bool,
    http_timeout: float,
    http_client_timeout: float,
    sort_dependencies: bool,
    remove_comments: bool,
    cache_ttl: float,
    version_spec: str,
    ignored_dependencies: Set[str],
) -> bool:
    """
    Process and update dependencies in a requirements.txt file.

    Reads the file, updates all dependencies, then writes
    the updated file (unless `dry_run` is True). Logs relevant actions.

    Args:
        requirements_path: The path to the requirements.txt file.
        concurrency: Max number of concurrent HTTP requests.
        verbose: If True, prints/logs extra debug info.
        dry_run: If True, only prints the resulting file without saving.
        http_timeout: Per-request timeout in seconds.
        http_client_timeout: Overall client timeout in seconds.
        sort_dependencies: Whether to sort dependencies alphabetically.
        remove_comments: If True, remove comments from requirements.
        cache_ttl: Time (in seconds) to cache PyPI queries (0 disables).
        version_spec: Version update strategy ("pinned", "gte", or "lte").
        ignored_dependencies: Set of package names to skip updating.

    Returns:
        True if processing succeeded, False otherwise.
    """
    logger.info(f"\n🔍 Processing requirements file '{requirements_path}'...\n")

    try:
        # Read the requirements file
        with open(requirements_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Collect package names and handle comments
        package_set: Set[str] = set()
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#"):
                dep_info = parse_dependency(line)
                if dep_info.name:
                    package_set.add(dep_info.name)

        if not package_set:
            logger.warning(f"⚠️ No packages found in {requirements_path}")
            print(f"{COLOR_WARNING}No packages found in {requirements_path}")
            return True

        # Fetch latest versions
        try:
            latest_versions = await fetch_all_latest_versions(
                package_set,
                concurrency,
                http_client_timeout,
                http_timeout,
                cache_ttl,
                ignored_dependencies,
            )
        except Exception as e:
            logger.error(f"💥 Error fetching versions: {e}", exc_info=True)
            print(f"{COLOR_ERROR}Error fetching versions: {e}")
            return False

        if verbose:
            print(f"\n{COLOR_INFO}Retrieved versions for {len(latest_versions)} packages\n")
            for pkg, ver in latest_versions.items():
                if ver:
                    print(f"{COLOR_INFO}{pkg} latest version: {ver}")
                else:
                    print(f"{COLOR_ERROR}No version found for {pkg}")

        # Update each line
        updated_lines = []
        for line in lines:
            original = line.strip()

            # Preserve empty lines and comments as is
            if not original or original.startswith("#"):
                if not remove_comments or not original.startswith("#"):
                    updated_lines.append(original)
                continue

            # Update dependency line
            _, updated, was_ignored = update_dependency_str(original, latest_versions, version_spec, ignored_dependencies)

            if was_ignored:
                print(f"{COLOR_SKIP}Ignored: {original} (in ignore list)")
            elif original == updated:
                print(f"{COLOR_SUCCESS}Up-to-date: Before: {original} | After: {updated}")
            else:
                print(f"{COLOR_WARNING}Updated: Before: {original} {Style.RESET_ALL}--> {COLOR_SUCCESS}{updated}")
                if verbose:
                    logger.info(f"📝 Updated dependency: {original} -> {updated}")

            updated_lines.append(updated)

        # Sort if requested
        if sort_dependencies:
            logger.info("🔡 Sorting dependencies alphabetically.")

            # Split into comments/empty lines and package lines
            comments = [line for line in updated_lines if not line or line.startswith("#")]
            packages = [line for line in updated_lines if line and not line.startswith("#")]

            # Sort package lines by package name
            packages.sort(key=extract_package_name)

            # Combine comments at the top followed by sorted packages
            updated_lines = comments + packages

        # Format final content
        new_content = "\n".join(updated_lines)

        if dry_run:
            print(f"\n🚀 {COLOR_HIGHLIGHT}Dry-run enabled. The following changes would be written to {requirements_path}:{Style.RESET_ALL}\n")
            print(new_content)
            logger.info("🚀 Dry run completed; changes not saved.")
            return True

        # Write updated content
        logger.info(f"✍️ Writing updated content to '{requirements_path}'...")
        try:
            with open(requirements_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"{COLOR_SUCCESS}Updated {requirements_path} successfully.")
            logger.info(f"✅ Successfully updated '{requirements_path}'.")
            return True
        except PermissionError:
            logger.error(f"💥 Permission denied when writing to {requirements_path}")
            print(f"{COLOR_ERROR}Permission denied when writing to {requirements_path}")
            return False
        except Exception as e:
            logger.error(f"💥 Error writing updated file: {e}", exc_info=True)
            print(f"{COLOR_ERROR}Error writing updated file: {e}")
            return False

    except FileNotFoundError:
        logger.error(f"💥 File not found: {requirements_path}")
        print(f"{COLOR_ERROR}Error: File {requirements_path} does not exist.")
        return False
    except Exception as e:
        logger.error(f"💥 Error processing {requirements_path}: {e}", exc_info=True)
        print(f"{COLOR_ERROR}Error processing {requirements_path}: {e}")
        return False


async def process_pyproject(
    pyproject_path: str,
    concurrency: int,
    verbose: bool,
    dry_run: bool,
    http_timeout: float,
    http_client_timeout: float,
    sort_dependencies: bool,
    remove_comments: bool,
    cache_ttl: float,
    version_spec: str,
    ignored_dependencies: Set[str],
) -> bool:
    """
    Process and update dependencies in a pyproject.toml file.

    Reads the file, updates all dependencies, then writes
    the updated file (unless `dry_run` is True). Validates
    the TOML before and after the update. Logs relevant actions.

    Args:
        pyproject_path: The path to the `pyproject.toml`.
        concurrency: Max number of concurrent HTTP requests.
        verbose: If True, prints/logs extra debug info.
        dry_run: If True, only prints the resulting TOML without saving.
        http_timeout: Per-request timeout in seconds.
        http_client_timeout: Overall client timeout in seconds.
        sort_dependencies: Whether to sort dependencies alphabetically.
        remove_comments: If True, remove comments from updated dependencies.
        cache_ttl: Time (in seconds) to cache PyPI queries (0 disables).
        version_spec: Version update strategy ("pinned", "gte", or "lte").
        ignored_dependencies: Set of package names to skip updating.

    Returns:
        True if processing succeeded, False otherwise.
    """
    logger.info(f"\n🔍 Validating and processing '{pyproject_path}'...\n")

    # Validate that original TOML is loadable and has [project]
    try:
        logger.debug("Reading pyproject.toml content...")
        with open(pyproject_path, "r", encoding="utf-8") as f:
            content = f.read()
        logger.debug("Attempting TOML parse...")
        doc = tomlkit.parse(content)
        logger.debug("TOML parse successful.")
    except FileNotFoundError:
        logger.error(f"💥 File not found: {pyproject_path}")
        print(f"{COLOR_ERROR}Error: File {pyproject_path} does not exist.")
        return False
    except tomlkit.exceptions.TOMLKitError as e:
        logger.error(f"💥 TOML parsing error: {e}")
        print(f"{COLOR_ERROR}Error parsing {pyproject_path}: {e}")
        return False
    except Exception as e:
        logger.error(f"💥 Error reading {pyproject_path}: {e}", exc_info=True)
        print(f"{COLOR_ERROR}Error reading {pyproject_path}: {e}")
        return False

    # Check for [project]
    if "project" not in doc:
        logger.error(f"💥 No [project] section found in {pyproject_path}")
        print(f"{COLOR_ERROR}Error: No [project] section found in {pyproject_path}.")
        return False

    project = doc["project"]

    # Perform the dependency updates
    result = await _process_dependencies(
        project,
        concurrency,
        verbose,
        http_timeout,
        http_client_timeout,
        sort_dependencies,
        remove_comments,
        cache_ttl,
        version_spec,
        ignored_dependencies,
    )
    if not result:
        return False

    # Generate updated TOML as a string
    logger.debug("Generating updated TOML content...")
    try:
        new_content = tomlkit.dumps(doc)
    except Exception as e:
        logger.error(f"💥 Error generating TOML: {e}", exc_info=True)
        print(f"{COLOR_ERROR}Error generating TOML: {e}")
        return False

    # Validate new content again (parse it, check for [project])
    logger.debug("Validating updated TOML content...")
    try:
        test_doc = tomlkit.parse(new_content)
        if "project" not in test_doc:
            logger.error("💥 Post-update content lacks [project] section.")
            print(f"{COLOR_ERROR}Error: Updated file has no [project] section!")
            return False
        logger.info("✅ Post-update TOML content validated successfully.")
    except tomlkit.exceptions.TOMLKitError as e:
        logger.error(f"💥 Post-update TOML parsing error: {e}")
        print(f"{COLOR_ERROR}Error parsing updated TOML content: {e}")
        return False

    if dry_run:
        print(f"\n🚀 {COLOR_HIGHLIGHT}Dry-run enabled. The following changes would be written to {pyproject_path}:{Style.RESET_ALL}\n")
        print(new_content)
        logger.info("🚀 Dry run completed; changes not saved.")
        return True

    # Write updated content
    logger.info(f"✍️ Writing updated content to '{pyproject_path}'...")
    try:
        with open(pyproject_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"{COLOR_SUCCESS}Updated {pyproject_path} successfully.")
        logger.info(f"✅ Successfully updated '{pyproject_path}'.")
        return True
    except PermissionError:
        logger.error(f"💥 Permission denied when writing to {pyproject_path}")
        print(f"{COLOR_ERROR}Permission denied when writing to {pyproject_path}")
        return False
    except Exception as e:
        logger.error(f"💥 Error writing updated file: {e}", exc_info=True)
        print(f"{COLOR_ERROR}Error writing updated file: {e}")
        return False


async def _process_dependencies(
    project: Any,
    concurrency: int,
    verbose: bool,
    http_timeout: float,
    http_client_timeout: float,
    sort_dependencies: bool,
    remove_comments: bool,
    cache_ttl: float,
    version_spec: str,
    ignored_dependencies: Set[str],
) -> bool:
    """
    Helper function to update [project].dependencies and [project].optional-dependencies.

    Logs relevant steps and any errors encountered.

    Args:
        project: The `[project]` table from the TOML doc.
        concurrency: Max number of concurrent HTTP requests.
        verbose: Enables verbose logging.
        http_timeout: Per-request timeout in seconds.
        http_client_timeout: Overall client timeout in seconds.
        sort_dependencies: Whether to sort dependencies.
        remove_comments: If True, skip preserving comments.
        cache_ttl: Time in seconds to keep PyPI lookups cached. (0 disables.)
        version_spec: Version update strategy ("pinned", "gte", or "lte").
        ignored_dependencies: Set of package names to skip updating.

    Returns:
        True if successful, False on errors.
    """
    package_set: Set[str] = set()

    # Gather main dependencies
    logger.info("\n--- [Main Dependencies] Collecting packages ---\n")
    deps_array = safe_get_array(project, "dependencies")
    if deps_array is not None:
        try:
            package_set |= collect_unique_packages(deps_array)
        except Exception as e:
            logger.error(f"💥 Error processing dependencies: {e}", exc_info=True)
            print(f"{COLOR_ERROR}Error processing dependencies: {e}")
            return False
    else:
        logger.info("ℹ️ No [project].dependencies found; skipping.")

    # Gather optional dependencies
    logger.info("\n--- [Optional Dependencies] Collecting packages ---\n")
    opt_deps_container = project.get("optional-dependencies", None) if hasattr(project, "get") else None
    if opt_deps_container is not None:
        for group in safe_get_dict_keys(opt_deps_container):
            logger.debug(f"Collecting packages from optional group '{group}'...")
            group_array = safe_get_array(opt_deps_container, group)
            if group_array is not None:
                try:
                    package_set |= collect_unique_packages(group_array)
                except Exception as e:
                    logger.error(
                        f"💥 Error processing optional group '{group}': {e}",
                        exc_info=True,
                    )
                    print(f"{COLOR_ERROR}Error processing optional group '{group}': {e}")
                    return False
    else:
        logger.info("ℹ️ No [project].optional-dependencies found; skipping.")

    if verbose:
        sorted_pkgs = ", ".join(sorted(package_set))
        print(f"{COLOR_INFO}Found packages: {sorted_pkgs}")
        logger.info(f"🔎 Found {len(package_set)} unique packages to update: {sorted_pkgs}")

    if not package_set:
        logger.warning("⚠️ No packages found to update.")
        print(f"{COLOR_WARNING}No packages found to update.")
        return True

    # Fetch latest versions
    try:
        latest_versions = await fetch_all_latest_versions(
            package_set,
            concurrency,
            http_client_timeout,
            http_timeout,
            cache_ttl,
            ignored_dependencies,
        )
    except Exception as e:
        logger.error(f"💥 Error fetching versions: {e}", exc_info=True)
        print(f"{COLOR_ERROR}Error fetching versions: {e}")
        return False

    if verbose:
        print(f"\n{COLOR_INFO}Retrieved versions for {len(latest_versions)} packages\n")
        for pkg, ver in latest_versions.items():
            if ver:
                print(f"{COLOR_INFO}{pkg} latest version: {ver}")
            else:
                print(f"{COLOR_ERROR}No version found for {pkg}")

    # Update [project].dependencies
    if not await _update_main_dependencies(
        project,
        latest_versions,
        verbose,
        sort_dependencies,
        remove_comments,
        version_spec,
        ignored_dependencies,
    ):
        return False

    # Update [project].optional-dependencies
    if not await _update_optional_dependencies(
        project,
        latest_versions,
        verbose,
        sort_dependencies,
        remove_comments,
        version_spec,
        ignored_dependencies,
    ):
        return False

    return True


async def _update_main_dependencies(
    project: Any,
    latest_versions: VersionDict,
    verbose: bool,
    sort_dependencies: bool,
    remove_comments: bool,
    version_spec: str,
    ignored_dependencies: Set[str],
) -> bool:
    """
    Update the [project].dependencies table in the TOML doc.

    Args:
        project: `[project]` table from the TOML doc.
        latest_versions: dict of package -> latest version.
        verbose: enables extra logging.
        sort_dependencies: whether to sort dependencies.
        remove_comments: if True, do not preserve comments.
        version_spec: version update strategy ("pinned", "gte", or "lte").
        ignored_dependencies: Set of package names to skip updating.

    Returns:
        True if successful, False otherwise.
    """
    deps_array = safe_get_array(project, "dependencies")
    if deps_array is not None:
        print(f"\n{COLOR_INFO}Updating [project].dependencies ...\n")
        try:
            if hasattr(project, "__setitem__"):
                project["dependencies"] = update_dependency_array(
                    dep_array=deps_array,
                    latest_versions=latest_versions,
                    verbose=verbose,
                    sort_dependencies=sort_dependencies,
                    remove_comments=remove_comments,
                    version_spec=version_spec,
                    ignored_dependencies=ignored_dependencies,
                )
        except Exception as e:
            logger.error(f"💥 Error updating dependencies: {e}", exc_info=True)
            print(f"{COLOR_ERROR}Error updating dependencies: {e}")
            return False
    else:
        print(f"{COLOR_WARNING}No [project].dependencies found; skipping.")
        logger.info("ℹ️ No [project].dependencies found; skipping.")

    return True


async def _update_optional_dependencies(
    project: Any,
    latest_versions: VersionDict,
    verbose: bool,
    sort_dependencies: bool,
    remove_comments: bool,
    version_spec: str,
    ignored_dependencies: Set[str],
) -> bool:
    """
    Update the [project].optional-dependencies section in the TOML doc.

    Args:
        project: `[project]` table from the TOML doc.
        latest_versions: dict of package -> latest version.
        verbose: enables extra logging.
        sort_dependencies: whether to sort dependencies.
        remove_comments: if True, skip preserving comments.
        version_spec: version update strategy ("pinned", "gte", or "lte").
        ignored_dependencies: Set of package names to skip updating.

    Returns:
        True if successful, False otherwise.
    """
    opt_deps_container = project.get("optional-dependencies", None) if hasattr(project, "get") else None
    if opt_deps_container is not None:
        print(f"\n{COLOR_INFO}Updating [project].optional-dependencies ...\n")
        for group in safe_get_dict_keys(opt_deps_container):
            group_array = safe_get_array(opt_deps_container, group)
            if group_array is not None:
                print(f"{COLOR_INFO}Updating optional group '{group}' ...")
                try:
                    if hasattr(opt_deps_container, "__setitem__"):
                        opt_deps_container[group] = update_dependency_array(
                            dep_array=group_array,
                            latest_versions=latest_versions,
                            verbose=verbose,
                            sort_dependencies=sort_dependencies,
                            remove_comments=remove_comments,
                            version_spec=version_spec,
                            ignored_dependencies=ignored_dependencies,
                        )
                except Exception as e:
                    logger.error(
                        f"💥 Error updating optional group '{group}': {e}",
                        exc_info=True,
                    )
                    print(f"{COLOR_ERROR}Error updating optional group '{group}': {e}")
                    return False
    else:
        print(f"{COLOR_WARNING}No [project].optional-dependencies found; skipping.")
        logger.info("ℹ️ No [project].optional-dependencies found; skipping.")

    return True


def create_backup(source_path: str, backup_path: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """
    Create a backup copy of the source file. By default, uses a timestamped name
    like `.depupdate.<timestamp>` in the current directory.

    Logs success or failure and returns a tuple (boolean, path_or_error).

    Args:
        source_path: Path to the original file.
        backup_path: Desired path for the backup. If None, a unique name
                     (e.g., `.depupdate.1678891234`) will be generated.

    Returns:
        A tuple (success_boolean, backup_path_or_error_message).
    """
    if not backup_path:
        # Default to a unique name based on the current timestamp:
        timestamp = int(time.time())
        backup_path = f".depupdate.{timestamp}"

    logger.info(f"⚙️ Creating backup from '{source_path}' to '{backup_path}'")

    try:
        shutil.copy(source_path, backup_path)
        logger.info(f"🗄  Backup created at: {backup_path}")
        return True, backup_path
    except PermissionError:
        error_msg = f"💥 Permission denied when creating backup at {backup_path}"
        logger.error(error_msg)
        return False, error_msg
    except FileNotFoundError:
        error_msg = f"💥 Source file {source_path} not found"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"💥 Error creating backup: {e}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg


def main() -> int:
    """
    Main entry point for the script.

    Returns:
        An integer representing the exit code.
    """
    logger.info("\n🟢========== [DepUpdater] Starting Main Execution ==========\n")

    # Read local YAML config first (if any), for override defaults:
    file_config = read_depsorter_config(".depsorter.yml")

    # CLI argument parser
    parser = argparse.ArgumentParser(
        description=(
            "Update dependency version constraints in pyproject.toml to use pinned (==), >=, or <= latest versions, preserving comments (unless removed) and optionally sorting dependencies."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--file",
        default=file_config.get("file", DEFAULT_DEPENDENCY_FILE),
        help="Path to the dependency file (pyproject.toml or requirements.txt)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=file_config.get("verbose", False),
        help="Display verbose output",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=file_config.get("dry_run", False),
        help="Show changes without writing to file",
    )
    parser.add_argument(
        "--backup",
        default=file_config.get("backup", None),
        help=("Backup file name. If not specified, a timestamped backup (e.g. .depupdate.1678891234) will be created in the current directory."),
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        default=file_config.get("no_backup", False),
        help="If set, do not create any backup file.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=file_config.get("concurrency", DEFAULT_CONCURRENCY),
        help="Number of concurrent HTTP requests",
    )
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=file_config.get("http_timeout", DEFAULT_HTTP_TIMEOUT),
        help="Timeout for individual HTTP requests in seconds",
    )
    parser.add_argument(
        "--http-client-timeout",
        type=float,
        default=file_config.get("http_client_timeout", DEFAULT_HTTP_CLIENT_TIMEOUT),
        help="Timeout for the overall HTTP client in seconds",
    )
    parser.add_argument(
        "--log-file",
        default=file_config.get("log_file", None),
        help="Path to log file (if not specified, logs to console only)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=file_config.get("log_level", "WARNING"),
        help="Set the logging level",
    )

    # Sorting flags
    sort_group = parser.add_mutually_exclusive_group()
    sort_group.add_argument(
        "--sort",
        dest="sort_dependencies",
        action="store_true",
        help="Sort dependencies alphabetically.",
    )
    sort_group.add_argument(
        "--no-sort",
        dest="sort_dependencies",
        action="store_false",
        help="Disable alphabetical sorting of dependencies.",
    )
    parser.set_defaults(sort_dependencies=file_config.get("sort_dependencies", True))

    # Remove-comments flag
    parser.add_argument(
        "--remove-comments",
        action="store_true",
        default=file_config.get("remove_comments", False),
        help="Remove comments when updating dependencies",
    )

    # Cache TTL
    parser.add_argument(
        "--cache-ttl",
        type=float,
        default=file_config.get("cache_ttl", DEFAULT_CACHE_TTL),
        help="Time in seconds to cache API lookups (default=600; 0 disables)",
    )

    # Cache file
    parser.add_argument(
        "--cache-file",
        default=file_config.get("cache_file", DEFAULT_CACHE_FILE),
        help="Path to the JSON file for storing persistent cache",
    )

    # Version spec choices
    parser.add_argument(
        "--version-spec",
        choices=["pinned", "gte", "lte"],
        default=file_config.get("version_spec", "gte"),
        help=("How to update version constraints: 'pinned' uses '==latest', 'gte' uses '>=latest', 'lte' uses '<=latest'. Default is 'gte'."),
    )

    # Ignore dependencies
    parser.add_argument(
        "--ignore-dependency",
        action="append",
        default=file_config.get("ignore_dependencies", []),
        help="Dependency to ignore (can be specified multiple times)",
    )

    args = parser.parse_args()

    # Convert ignored dependencies to lowercase set for case-insensitive comparison
    ignored_dependencies = {dep.lower() for dep in args.ignore_dependency} if args.ignore_dependency else set()

    # Configure log level
    log_level = getattr(logging, args.log_level.upper(), logging.WARNING)
    logger.setLevel(log_level)
    if args.log_file:
        file_handler = logging.FileHandler(args.log_file)
        file_handler.setFormatter(logging.Formatter(DEFAULT_LOG_FORMAT))
        logger.addHandler(file_handler)

    # Log the merged/effective configuration (at INFO level)
    logger.info("\n=== [CONFIGURATION] Effective Settings ===")
    logger.info(f"🔧 • file                  = {args.file}")
    logger.info(f"🔧 • verbose               = {args.verbose}")
    logger.info(f"🔧 • dry_run               = {args.dry_run}")
    logger.info(f"🔧 • backup                = {args.backup}")
    logger.info(f"🔧 • no_backup             = {args.no_backup}")
    logger.info(f"🔧 • concurrency           = {args.concurrency}")
    logger.info(f"🔧 • http_timeout          = {args.http_timeout}")
    logger.info(f"🔧 • http_client_timeout   = {args.http_client_timeout}")
    logger.info(f"🔧 • log_file              = {args.log_file}")
    logger.info(f"🔧 • log_level             = {args.log_level}")
    logger.info(f"🔧 • sort_dependencies     = {args.sort_dependencies}")
    logger.info(f"🔧 • remove_comments       = {args.remove_comments}")
    logger.info(f"🔧 • cache_ttl             = {args.cache_ttl}")
    logger.info(f"🔧 • cache_file            = {args.cache_file}")
    logger.info(f"🔧 • version_spec          = {args.version_spec}")
    logger.info(f"🔧 • ignore_dependencies   = {sorted(ignored_dependencies)}")
    logger.info("========================================\n")

    # ---------------------------------------------------------
    # LOAD THE PERSISTENT CACHE FIRST
    # ---------------------------------------------------------
    load_cache_from_file(args.cache_file)

    # Verify file existence and fallback to requirements.txt if needed
    file_path = args.file

    # If using default and file not found, try requirements.txt as fallback
    if not os.path.exists(file_path) and file_path == DEFAULT_DEPENDENCY_FILE:
        requirements_file = "requirements.txt"
        if os.path.exists(requirements_file):
            logger.info(f"⚠️ {file_path} not found, falling back to {requirements_file}")
            print(f"{COLOR_WARNING}{file_path} not found, using {requirements_file} instead.")
            file_path = requirements_file
        else:
            logger.error(f"💥 Neither {file_path} nor {requirements_file} found.")
            print(f"{COLOR_ERROR}Error: Neither {file_path} nor {requirements_file} exist.")
            return EXIT_FILE_ERROR
    elif not os.path.exists(file_path):
        logger.error(f"💥 File not found: {file_path}")
        print(f"{COLOR_ERROR}Error: File {file_path} does not exist.")
        return EXIT_FILE_ERROR

    # Create backup if not disabled
    if not args.no_backup:
        success, backup_result = create_backup(file_path, args.backup)
        if not success:
            print(f"{COLOR_ERROR}Error: {backup_result}")
            return EXIT_FILE_ERROR

        backup_path = cast(str, backup_result)
        print(f"{COLOR_INFO}Backup created at: {backup_path}")
    else:
        logger.info("ℹ️ Skipping backup creation due to --no-backup flag.")
        print(f"{COLOR_WARNING}No backup created (flag --no-backup was used).")

    # Process the file
    try:
        success = asyncio.run(
            process_file(
                file_path=file_path,
                concurrency=args.concurrency,
                verbose=args.verbose,
                dry_run=args.dry_run,
                http_timeout=args.http_timeout,
                http_client_timeout=args.http_client_timeout,
                sort_dependencies=args.sort_dependencies,
                remove_comments=args.remove_comments,
                cache_ttl=args.cache_ttl,
                version_spec=args.version_spec,
                ignored_dependencies=ignored_dependencies,
            )
        )
    except KeyboardInterrupt:
        logger.warning("⚠️ Operation interrupted by user")
        print(f"{COLOR_WARNING}Operation interrupted by user")
        return EXIT_INTERRUPTED
    except Exception as e:
        logger.error(f"💥 Unhandled exception: {e}", exc_info=True)
        print(f"{COLOR_ERROR}Error: An unexpected error occurred: {e}")
        return EXIT_PROCESSING_ERROR

    # ---------------------------------------------------------
    # WRITE THE UPDATED PERSISTENT CACHE
    # ---------------------------------------------------------
    write_cache_to_file(args.cache_file)

    logger.info("\n🔚========== [DepUpdater] Finished Main Execution ==========\n")
    return EXIT_SUCCESS if success else EXIT_PROCESSING_ERROR


if __name__ == "__main__":
    sys.exit(main())
