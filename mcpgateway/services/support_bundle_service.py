# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/support_bundle_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Support Bundle Service - Generate diagnostic bundles for troubleshooting.

This module provides functionality to create comprehensive support bundles containing
system diagnostics, logs, configuration, and other debugging information. Sensitive
data is handled differently depending on where it appears: settings.json
deterministically excludes every field the Settings model marks as a secret (see
SupportBundleService._secret_field_names()); environment.json masks environment
variables by name pattern; and logs/ apply best-effort regex redaction, which is not
a guarantee against every possible secret shape.

Features:
- Version and system information collection
- Log file collection with size limits and best-effort sanitization
- Environment configuration with name-based secret masking
- Database connection info (credentials stripped from URLs)
- Platform and dependency information
- ZIP archive generation with timestamped filenames

Examples:
    >>> from mcpgateway.services.support_bundle_service import SupportBundleService
    >>> service = SupportBundleService()
    >>> bundle_path = service.generate_bundle()
    >>> bundle_path.exists()
    True
    >>> bundle_path.name.startswith('mcpgateway-support-')
    True
    >>> bundle_path.suffix
    '.zip'
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import re
import socket
import tempfile
from types import UnionType
from typing import Any, Dict, get_args, get_origin, Optional, Union
import zipfile

# Third-Party
import orjson
from pydantic import BaseModel, Field, SecretStr

# First-Party
from mcpgateway import __version__
from mcpgateway.config import settings
from mcpgateway.db import engine

# Field names that indicate a secret when the setting is string-typed.
#
# Deliberately narrower than SupportBundleService._is_secret(): bare "token"
# and "key" match ~60 harmless settings (token_expiry, password_min_length,
# csrf_token_name, ...) and redacting those would gut the bundle's value for
# the debugging it exists to support. _is_secret() can afford to be broad
# because it inspects raw environment variables whose names are unknown;
# here the field set is known and typed.
#
# This regex is a backstop, not the policy: new secret settings must be typed
# SecretStr, which _secret_field_names() rule 1 always catches regardless of
# name. The regex only catches the mistake of forgetting to do that, and it
# fails open for a plausible name it doesn't match, e.g. webhook_signing_key,
# encryption_salt, or hmac_pepper. Do not rely on it as the primary control.
_SECRET_NAME_RE = re.compile(r"secret|password|passwd|credential|passphrase|private_key|api_key", re.IGNORECASE)

# String settings matching _SECRET_NAME_RE that are not themselves secrets.
_SAFE_STRING_FIELDS = frozenset({"jwt_private_key_path"})


class SupportBundleConfig(BaseModel):
    """Configuration for support bundle generation.

    Attributes:
        include_logs: Include log files in bundle
        include_env: Include environment configuration
        include_system_info: Include system diagnostics
        max_log_size_mb: Maximum log file size to include (MB)
        log_tail_lines: Number of log lines to include (0 = all)
        output_dir: Directory for bundle output
    """

    include_logs: bool = Field(default=True, description="Include log files in bundle")
    include_env: bool = Field(default=True, description="Include environment configuration")
    include_system_info: bool = Field(default=True, description="Include system diagnostics")
    max_log_size_mb: float = Field(default=10.0, description="Maximum log file size in MB")
    log_tail_lines: int = Field(default=1000, description="Number of log lines to include (0 = all)")
    output_dir: Optional[Path] = Field(default=None, description="Output directory for bundle")


class SupportBundleService:
    """Service for generating support bundles with sanitized diagnostic information.

    This service collects system information, logs, and configuration data while
    automatically sanitizing sensitive information like passwords, tokens, and API keys.

    Examples:
        >>> from mcpgateway.services.support_bundle_service import SupportBundleService, SupportBundleConfig
        >>> service = SupportBundleService()
        >>> config = SupportBundleConfig(log_tail_lines=500)
        >>> bundle_path = service.generate_bundle(config)
        >>> bundle_path.exists()
        True
        >>> bundle_path.suffix
        '.zip'
    """

    # Patterns for sanitizing sensitive data in logs
    SENSITIVE_PATTERNS = [
        (re.compile(r'password["\']?\s*[:=]\s*["\']?([^"\'\s,}]+)', re.IGNORECASE), r"password: *****"),
        (re.compile(r'token["\']?\s*[:=]\s*["\']?([^"\'\s,}]+)', re.IGNORECASE), r"token: *****"),
        (re.compile(r'api[_-]?key["\']?\s*[:=]\s*["\']?([^"\'\s,}]+)', re.IGNORECASE), r"api_key: *****"),
        (re.compile(r'secret["\']?\s*[:=]\s*["\']?([^"\'\s,}]+)', re.IGNORECASE), r"secret: *****"),
        (re.compile(r"bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE), r"bearer *****"),
        (re.compile(r'authorization:\s*["\']?([^"\'\s,}]+)', re.IGNORECASE), r"authorization: *****"),
        # Database / service URLs (scheme-agnostic to catch legacy or misconfigured DSNs)
        (re.compile(r"(\w[\w+.-]*)://([^:]+):([^@]+)@"), r"\1://\2:*****@"),
        # JWT tokens (eyJ pattern)
        (re.compile(r"eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+"), r"eyJ*****"),
    ]

    def __init__(self):
        """Initialize the support bundle service."""
        self.hostname = socket.gethostname()
        self.timestamp = datetime.now(timezone.utc)

    def _is_secret(self, key: str) -> bool:
        """Check if an environment variable key represents a secret.

        Args:
            key: Environment variable name

        Returns:
            bool: True if the key likely contains sensitive data

        Examples:
            >>> service = SupportBundleService()
            >>> service._is_secret("DATABASE_PASSWORD")
            True
            >>> service._is_secret("API_KEY")
            True
            >>> service._is_secret("RATELIMITER_REDIS_URL")
            True
            >>> service._is_secret("DEBUG")
            False
        """
        key_upper = key.upper()
        # Check for common secret keywords
        if any(tok in key_upper for tok in ("SECRET", "TOKEN", "PASS", "KEY")):
            return True
        # URL-shaped settings routinely carry inline credentials in their
        # userinfo component; mask by name suffix rather than maintaining an
        # exact-match entry per URL setting (see database_url / redis_url
        # below, kept for variables whose names predate this rule).
        if key_upper.endswith("_URL"):
            return True
        # Check for specific secret environment variables
        secret_vars = {
            "BASIC_AUTH_USER",
            "BASIC_AUTH_PASSWORD",
            "DATABASE_URL",
            "REDIS_URL",
            "JWT_SECRET_KEY",
            "AUTH_ENCRYPTION_SECRET",
        }
        return key_upper in secret_vars

    @staticmethod
    def _is_string_annotation(annotation: Any) -> bool:
        """Check whether a field annotation is ``str`` or ``Optional[str]``.

        Container annotations such as ``Dict[str, str]`` are rejected so that
        a mapping setting is never mistaken for a scalar secret.

        Args:
            annotation: The declared annotation of a Pydantic model field.

        Returns:
            bool: True if the annotation resolves to a plain or optional string.

        Examples:
            >>> from typing import Dict, Optional
            >>> SupportBundleService._is_string_annotation(str)
            True
            >>> SupportBundleService._is_string_annotation(Optional[str])
            True
            >>> SupportBundleService._is_string_annotation(Dict[str, str])
            False
            >>> SupportBundleService._is_string_annotation(int)
            False
        """
        if annotation is str:
            return True
        if get_origin(annotation) in (Union, UnionType):
            return all(arg is str or arg is type(None) for arg in get_args(annotation))
        return False

    @classmethod
    def _secret_field_names(cls, model: type[BaseModel] | None = None) -> set[str]:
        """Compute the set of settings fields that must never reach the bundle.

        A field is a secret when either:

        1. ``SecretStr`` appears anywhere in its annotation — directly,
           ``Optional[SecretStr]``, or nested in a container such as
           ``Dict[str, SecretStr]`` or ``List[SecretStr]`` — the primary rule,
           so any correctly typed secret added in future is covered without
           touching this module; or
        2. it is string-typed, its name matches :data:`_SECRET_NAME_RE`, and it
           is not in :data:`_SAFE_STRING_FIELDS` — a backstop for plain-string
           secrets that were not typed as ``SecretStr``. New secret settings
           must be typed ``SecretStr``; that is the enforced rule. This name
           regex only catches the mistake of forgetting to.

        Args:
            model: Pydantic model class to inspect. Defaults to the
                application :class:`~mcpgateway.config.Settings` model;
                overridable so the rule can be exercised against a throwaway
                model in tests without depending on the real settings shape.

        Returns:
            set[str]: Field names to exclude from ``settings.json``.

        Examples:
            >>> names = SupportBundleService._secret_field_names()
            >>> "jwt_secret_key" in names
            True
            >>> "csrf_secret_key" in names
            True
            >>> "token_expiry" in names
            False
        """
        # First-Party
        from mcpgateway.config import Settings  # pylint: disable=import-outside-toplevel

        model = model or Settings

        secret_names: set[str] = set()
        for name, field in model.model_fields.items():
            annotation = field.annotation
            if annotation is SecretStr or SecretStr in get_args(annotation):
                secret_names.add(name)
                continue
            if name in _SAFE_STRING_FIELDS:
                continue
            if _SECRET_NAME_RE.search(name) and cls._is_string_annotation(annotation):
                secret_names.add(name)
        return secret_names

    def _sanitize_url(self, url: Optional[str]) -> Optional[str]:
        """Redact credentials from URLs.

        Args:
            url: URL to sanitize

        Returns:
            Optional[str]: Sanitized URL or None

        Examples:
            >>> service = SupportBundleService()
            >>> service._sanitize_url("postgresql://user:password@localhost/db")  # pragma: allowlist secret
            'postgresql://user:*****@localhost/db'
            >>> service._sanitize_url("http://example.com")
            'http://example.com'
        """
        if not url:
            return None
        # Remove password from URLs
        for pattern, replacement in self.SENSITIVE_PATTERNS:
            url = pattern.sub(replacement, url)
        return url

    def _sanitize_line(self, line: str) -> str:
        """Sanitize a single line of text by removing sensitive data.

        Args:
            line: Line to sanitize

        Returns:
            str: Sanitized line

        Examples:
            >>> service = SupportBundleService()
            >>> service._sanitize_line('password: secret123')
            'password: *****'
            >>> service._sanitize_line('debug: true')
            'debug: true'
        """
        for pattern, replacement in self.SENSITIVE_PATTERNS:
            line = pattern.sub(replacement, line)
        return line

    def _collect_version_info(self) -> Dict[str, Any]:
        """Collect version and application information.

        Returns:
            Dict containing version information

        Examples:
            >>> service = SupportBundleService()
            >>> info = service._collect_version_info()
            >>> 'app_version' in info
            True
            >>> 'python_version' in info
            True
        """
        return {
            "app_name": settings.app_name,
            "app_version": __version__,
            "mcp_protocol_version": settings.protocol_version,
            "python_version": platform.python_version(),
            "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "hostname": self.hostname,
            "timestamp": self.timestamp.isoformat(),
        }

    def _collect_system_info(self) -> Dict[str, Any]:
        """Collect system diagnostics and metrics.

        Returns:
            Dict containing system information

        Examples:
            >>> service = SupportBundleService()
            >>> info = service._collect_system_info()
            >>> 'platform' in info
            True
        """
        info = {
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
            },
            "python": {
                "version": platform.python_version(),
                "implementation": platform.python_implementation(),
                "compiler": platform.python_compiler(),
            },
            "database": {
                "dialect": engine.dialect.name,
                "url": self._sanitize_url(settings.database_url),
            },
        }

        # Try to collect psutil metrics if available
        try:
            # Third-Party
            import psutil  # pylint: disable=import-outside-toplevel

            info["system"] = {
                "cpu_count": psutil.cpu_count(logical=True),
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "memory_total_mb": round(psutil.virtual_memory().total / 1_048_576),
                "memory_used_mb": round(psutil.virtual_memory().used / 1_048_576),
                "disk_total_gb": round(psutil.disk_usage("/").total / 1_073_741_824, 2),
                "disk_used_gb": round(psutil.disk_usage("/").used / 1_073_741_824, 2),
            }
        except ImportError:
            info["system"] = {"note": "psutil not installed, skipping system metrics"}

        return info

    def _collect_env_config(self) -> Dict[str, str]:
        """Collect environment configuration with secrets redacted.

        Returns:
            Dict of environment variables (secrets redacted)

        Examples:
            >>> service = SupportBundleService()
            >>> env = service._collect_env_config()
            >>> 'PATH' in env or len(env) >= 0  # May vary by environment
            True
        """
        return {k: "*****" if self._is_secret(k) else v for k, v in os.environ.items()}

    def _collect_settings(self) -> Dict[str, Any]:
        """Collect application settings with secret fields excluded.

        Returns:
            Dict of application settings

        Examples:
            >>> service = SupportBundleService()
            >>> config = service._collect_settings()
            >>> 'host' in config
            True
        """
        # Exclusions are computed from the Settings model rather than
        # hand-maintained: a hardcoded list silently goes stale as new settings
        # are added, so a field added later is omitted from it by default.
        config = settings.model_dump(exclude=self._secret_field_names())

        # Sanitize every string-valued *_url setting (database_url, redis_url,
        # ratelimiter_redis_url, elasticsearch_url, ...) generically rather
        # than naming each one: these routinely carry inline credentials
        # (redis://:password@host:6379) and the set of URL settings grows
        # independently of this module. Iterate a snapshot of the keys since
        # the loop mutates config in place.
        for key in list(config.keys()):
            if key.endswith("_url") and isinstance(config[key], str):
                config[key] = self._sanitize_url(config[key])

        return config

    def _collect_logs(self, config: SupportBundleConfig) -> Dict[str, str]:
        """Collect log files with sanitization and size limits.

        Args:
            config: Bundle configuration

        Returns:
            Dict mapping log file names to sanitized content

        Examples:
            >>> service = SupportBundleService()
            >>> config = SupportBundleConfig(log_tail_lines=100)
            >>> logs = service._collect_logs(config)
            >>> isinstance(logs, dict)
            True
        """
        logs = {}

        # Collect main log file
        log_file = settings.log_file or "mcpgateway.log"
        log_folder = settings.log_folder or "logs"
        log_path = Path(log_folder) / log_file

        if log_path.exists():
            try:
                file_size_mb = log_path.stat().st_size / 1_048_576
                if file_size_mb > config.max_log_size_mb:
                    logs[log_file] = f"[Log file too large: {file_size_mb:.2f} MB > {config.max_log_size_mb} MB limit]\n"
                else:
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()

                    # Tail lines if configured
                    if config.log_tail_lines > 0 and len(lines) > config.log_tail_lines:
                        lines = lines[-config.log_tail_lines :]
                        lines.insert(0, f"[Showing last {config.log_tail_lines} lines]\n")

                    # Sanitize each line
                    sanitized_lines = [self._sanitize_line(line) for line in lines]
                    logs[log_file] = "".join(sanitized_lines)

            except Exception as e:
                logs[log_file] = f"[Error reading log file: {e}]\n"
        else:
            logs[log_file] = "[Log file not found]\n"

        return logs

    def _create_manifest(self, config: SupportBundleConfig) -> Dict[str, Any]:
        """Create bundle manifest with metadata.

        Args:
            config: Bundle configuration

        Returns:
            Dict containing bundle manifest

        Examples:
            >>> service = SupportBundleService()
            >>> config = SupportBundleConfig()
            >>> manifest = service._create_manifest(config)
            >>> 'bundle_version' in manifest
            True
        """
        return {
            "bundle_version": "1.0",
            "generated_at": self.timestamp.isoformat(),
            "hostname": self.hostname,
            "app_version": __version__,
            "configuration": {
                "include_logs": config.include_logs,
                "include_env": config.include_env,
                "include_system_info": config.include_system_info,
                "log_tail_lines": config.log_tail_lines,
            },
            "warning": "This bundle may contain sensitive information. Review before sharing.",
        }

    def generate_bundle(self, config: Optional[SupportBundleConfig] = None) -> Path:
        """Generate a complete support bundle as a ZIP file.

        Args:
            config: Optional bundle configuration

        Returns:
            Path: Path to the generated ZIP file

        Examples:
            >>> from mcpgateway.services.support_bundle_service import SupportBundleService, SupportBundleConfig
            >>> service = SupportBundleService()
            >>> config = SupportBundleConfig(log_tail_lines=100, output_dir=Path("/tmp"))
            >>> bundle_path = service.generate_bundle(config)
            >>> bundle_path.exists()
            True
            >>> bundle_path.name.startswith('mcpgateway-support-')
            True
            >>> bundle_path.suffix
            '.zip'
        """
        if config is None:
            config = SupportBundleConfig()

        # Determine output directory
        output_dir = config.output_dir or Path(tempfile.gettempdir())
        output_dir.mkdir(parents=True, exist_ok=True)

        # Create timestamped filename
        timestamp_str = self.timestamp.strftime("%Y-%m-%d-%H%M%S")
        bundle_filename = f"mcpgateway-support-{timestamp_str}.zip"
        bundle_path = output_dir / bundle_filename

        # Create ZIP file
        with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add manifest
            manifest = self._create_manifest(config)
            zf.writestr("MANIFEST.json", orjson.dumps(manifest, option=orjson.OPT_INDENT_2))

            # Add version info
            version_info = self._collect_version_info()
            zf.writestr("version.json", orjson.dumps(version_info, option=orjson.OPT_INDENT_2))

            # Add system info
            if config.include_system_info:
                system_info = self._collect_system_info()
                zf.writestr("system_info.json", orjson.dumps(system_info, option=orjson.OPT_INDENT_2))

            # Add settings
            if config.include_env:
                app_settings = self._collect_settings()
                zf.writestr("settings.json", orjson.dumps(app_settings, default=str, option=orjson.OPT_INDENT_2))

                # Add environment variables
                env_config = self._collect_env_config()
                zf.writestr("environment.json", orjson.dumps(env_config, option=orjson.OPT_INDENT_2))

            # Add logs
            if config.include_logs:
                logs = self._collect_logs(config)
                for log_name, log_content in logs.items():
                    zf.writestr(f"logs/{log_name}", log_content)

            # Add README
            readme = f"""# ContextForge Support Bundle

This bundle contains diagnostic information for troubleshooting ContextForge issues.

## Contents

- MANIFEST.json: Bundle metadata and generation info
- version.json: Application and dependency versions
- system_info.json: Platform and system metrics
- settings.json: Application configuration (secret fields excluded)
- environment.json: Environment variables (credential-like names masked)
- logs/: Application logs (known credential patterns redacted)

## Security Notice

This bundle applies different guarantees depending on the file:

- settings.json: every field the application's configuration model marks as
  a secret (passwords, tokens, API keys, JWT/CSRF/identity-claims signing
  keys, and similar) is deterministically excluded, not just masked.
- environment.json: variables whose names look credential-like are masked.
  A secret exposed under an unexpected variable name could be missed.
- logs/: known credential patterns (passwords, tokens, API keys, bearer
  auth headers, JWTs, URL-embedded credentials) are redacted on a
  best-effort basis. Free-form log messages can still contain sensitive
  data that does not match any known pattern.

Review the contents before sharing this bundle with support or external
parties, especially the logs/ directory.

## Usage

Extract the ZIP file and review the JSON files for diagnostic information.
Pay special attention to logs/ for error messages and stack traces.

---
Generated: {self.timestamp.isoformat()}
Hostname: {self.hostname}
Version: {__version__}
"""

            zf.writestr("README.md", readme)

        return bundle_path


def create_support_bundle(config: Optional[SupportBundleConfig] = None) -> Path:
    """Convenience function to create a support bundle.

    Args:
        config: Optional bundle configuration

    Returns:
        Path to the generated bundle ZIP file

    Examples:
        >>> from mcpgateway.services.support_bundle_service import create_support_bundle, SupportBundleConfig
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as tmpdir:
        ...     config = SupportBundleConfig(log_tail_lines=500, output_dir=Path(tmpdir))
        ...     bundle_path = create_support_bundle(config)
        ...     bundle_path.suffix
        '.zip'
    """
    service = SupportBundleService()
    return service.generate_bundle(config)
