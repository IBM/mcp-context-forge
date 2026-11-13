# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/sigv4.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

AWS Signature Version 4 request signing for upstream gateways.

The signature covers the method, canonical URI, query, signed headers and the SHA-256
of the exact body, and carries a timestamp. A signature therefore cannot live in a stored
header: ``SigV4Auth.auth_flow()`` runs once per outbound request, including requests on
pooled upstream sessions and retries, and signs each request afresh.

``SigV4Auth`` serves httpx2 clients (the MCP SDK transports). ``SigV4HttpxAuth`` serves
httpx clients (REST invocation and health probes). Both delegate to ``SigV4Signer``,
which uses only the standard library.
"""

# Future
from __future__ import annotations

# Standard
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import re
from typing import Any, Callable, Dict, Mapping, Optional, Tuple
from urllib.parse import parse_qsl, quote, urlsplit

# Third-Party
import httpx
import httpx2

ALGORITHM = "AWS4-HMAC-SHA256"
UNSIGNED_PAYLOAD = "UNSIGNED-PAYLOAD"
SIGV4_SENSITIVE_KEYS = frozenset({"secret_access_key", "session_token"})
SIGV4_CONFIG_KEYS = frozenset({"access_key_id", "secret_access_key", "session_token", "region", "service"})
_SCOPE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_ACCESS_KEY_ID = re.compile(r"^[A-Za-z0-9]{16,128}$")
_WHITESPACE = re.compile(r"\s+")
_SIGNED_HEADER_PREFIX = "x-amz-"


class SigV4ConfigError(ValueError):
    """Raised when a SigV4 configuration is incomplete or malformed."""


@dataclass(frozen=True)
class SigV4Credentials:
    """Credentials and scope for one SigV4 upstream.

    Secret fields are excluded from ``repr`` so an accidental log line cannot leak them.
    """

    access_key_id: str
    secret_access_key: str = field(repr=False)
    region: str
    service: str
    session_token: Optional[str] = field(default=None, repr=False)

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "SigV4Credentials":
        """Build credentials from a plaintext ``sigv4_config`` mapping.

        Args:
            config: Mapping with ``access_key_id``, ``secret_access_key``, ``region``,
                ``service`` and an optional ``session_token``.

        Returns:
            SigV4Credentials: Validated credentials.

        Raises:
            SigV4ConfigError: If a required field is missing or a field is malformed.

        Examples:
            >>> creds = SigV4Credentials.from_config(
            ...     {"access_key_id": "AKIDEXAMPLE0000000", "secret_access_key": "s" * 40, "region": "us-east-1", "service": "execute-api"}
            ... )
            >>> creds.region
            'us-east-1'
            >>> "s" * 40 in repr(creds)
            False
        """
        validate_sigv4_config(config)
        return cls(
            access_key_id=str(config["access_key_id"]).strip(),
            secret_access_key=str(config["secret_access_key"]).strip(),
            region=str(config["region"]).strip(),
            service=str(config["service"]).strip(),
            session_token=(str(config["session_token"]).strip() or None) if config.get("session_token") else None,
        )

    @property
    def key_fingerprint(self) -> str:
        """Return a non-secret identifier for the access key, safe for audit records.

        Returns:
            str: First 12 hex characters of the SHA-256 of the access key ID.
        """
        return hashlib.sha256(self.access_key_id.encode("utf-8")).hexdigest()[:12]


def validate_sigv4_config(config: Any) -> Dict[str, Any]:
    """Validate the shape of a plaintext ``sigv4_config`` mapping.

    Args:
        config: Candidate configuration.

    Returns:
        Dict[str, Any]: A copy of the configuration with surrounding whitespace removed.

    Raises:
        SigV4ConfigError: If ``config`` is not a mapping, has unknown keys, lacks a required
            field, or holds a malformed region, service or access key ID.

    Examples:
        >>> validate_sigv4_config({"access_key_id": "AKIDEXAMPLE0000000", "secret_access_key": "x", "region": "us-east-1", "service": "s3"})["service"]
        's3'
        >>> validate_sigv4_config({"region": "us-east-1"})  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        mcpgateway.utils.sigv4.SigV4ConfigError: sigv4_config.access_key_id is required
    """
    if not isinstance(config, Mapping):
        raise SigV4ConfigError("sigv4_config must be an object")
    unknown = sorted(str(key) for key in config if key not in SIGV4_CONFIG_KEYS)
    if unknown:
        raise SigV4ConfigError(f"sigv4_config has unsupported keys: {', '.join(unknown)}")
    cleaned: Dict[str, Any] = {}
    for key in ("access_key_id", "secret_access_key", "region", "service"):
        value = config.get(key)
        if not isinstance(value, str) or not value.strip():
            raise SigV4ConfigError(f"sigv4_config.{key} is required")
        cleaned[key] = value.strip()
    if not _SCOPE_NAME.match(cleaned["region"]):
        raise SigV4ConfigError("sigv4_config.region must contain only lowercase letters, digits and hyphens")
    if not _SCOPE_NAME.match(cleaned["service"]):
        raise SigV4ConfigError("sigv4_config.service must contain only lowercase letters, digits and hyphens")
    if not _ACCESS_KEY_ID.match(cleaned["access_key_id"]):
        raise SigV4ConfigError("sigv4_config.access_key_id must be 16 to 128 letters or digits")
    session_token = config.get("session_token")
    if session_token is not None:
        if not isinstance(session_token, str):
            raise SigV4ConfigError("sigv4_config.session_token must be a string")
        if session_token.strip():
            cleaned["session_token"] = session_token.strip()
    return cleaned


def _hmac(key: bytes, message: str) -> bytes:
    """Return HMAC-SHA256 of ``message`` under ``key``.

    Args:
        key: HMAC key.
        message: Text to authenticate.

    Returns:
        bytes: Raw digest.
    """
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def derive_signing_key(secret_access_key: str, datestamp: str, region: str, service: str) -> bytes:
    """Derive the SigV4 signing key for one date, region and service.

    Args:
        secret_access_key: AWS secret access key.
        datestamp: Date in ``YYYYMMDD`` form.
        region: AWS region name.
        service: AWS service name.

    Returns:
        bytes: Signing key.
    """
    key = _hmac(("AWS4" + secret_access_key).encode("utf-8"), datestamp)
    key = _hmac(key, region)
    key = _hmac(key, service)
    return _hmac(key, "aws4_request")


def _canonical_uri(raw_path: str, *, double_encode: bool) -> str:
    """Return the canonical URI for a request path.

    Args:
        raw_path: Path exactly as sent on the wire (already percent-encoded).
        double_encode: Encode the path a second time and resolve dot segments, as every
            service except S3 requires.

    Returns:
        str: Canonical URI.
    """
    path = raw_path or "/"
    if not double_encode:
        return path
    segments: list[str] = []
    for segment in path.split("/"):
        if segment == "..":
            if segments:
                segments.pop()
        elif segment not in ("", "."):
            segments.append(segment)
    normalized = "/" + "/".join(segments)
    if segments and path.endswith("/"):
        normalized += "/"
    return quote(normalized, safe="/~")


def _canonical_query(raw_query: str) -> str:
    """Return the canonical query string, sorted and strictly percent-encoded.

    Args:
        raw_query: Query string exactly as sent on the wire.

    Returns:
        str: Canonical query string.
    """
    pairs = parse_qsl(raw_query, keep_blank_values=True)
    encoded = sorted((quote(name, safe="-_.~"), quote(value, safe="-_.~")) for name, value in pairs)
    return "&".join(f"{name}={value}" for name, value in encoded)


def _signed_header_names(headers: Mapping[str, str]) -> Tuple[str, ...]:
    """Select the header names that take part in the signature.

    Args:
        headers: Request headers.

    Returns:
        Tuple[str, ...]: Sorted lower-case header names.
    """
    names = {"host"}
    for name in headers:
        lowered = name.lower()
        if lowered == "content-type" or lowered.startswith(_SIGNED_HEADER_PREFIX):
            names.add(lowered)
    return tuple(sorted(names))


class SigV4Signer:
    """Compute SigV4 ``Authorization`` headers for outbound requests.

    The signer holds no per-request state. The signing key is cached per
    (date, region, service), so a request costs one canonical-request hash plus one HMAC.
    """

    def __init__(self, credentials: SigV4Credentials, *, unsigned_payload: bool = False, clock: Optional[Callable[[], datetime]] = None) -> None:
        """Create a signer.

        Args:
            credentials: Credentials and scope to sign with.
            unsigned_payload: Send ``UNSIGNED-PAYLOAD`` instead of hashing the body.
            clock: Time source returning an aware UTC datetime. Defaults to the system clock.
        """
        self.credentials = credentials
        self.unsigned_payload = unsigned_payload
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._cached_key: Optional[Tuple[str, bytes]] = None
        self._double_encode = credentials.service != "s3"

    def _signing_key(self, datestamp: str) -> bytes:
        """Return the signing key for ``datestamp``, deriving it at most once per day.

        Args:
            datestamp: Date in ``YYYYMMDD`` form.

        Returns:
            bytes: Signing key.
        """
        cached = self._cached_key
        if cached is not None and cached[0] == datestamp:
            return cached[1]
        key = derive_signing_key(self.credentials.secret_access_key, datestamp, self.credentials.region, self.credentials.service)
        self._cached_key = (datestamp, key)
        return key

    def sign(self, method: str, url: str, headers: Mapping[str, str], body: bytes) -> Dict[str, str]:
        """Return the headers that authenticate one request.

        Args:
            method: HTTP method.
            url: Request URL as sent on the wire.
            headers: Headers the request already carries, including ``Host``.
            body: Exact request body bytes.

        Returns:
            Dict[str, str]: ``x-amz-date``, ``x-amz-content-sha256``, ``Authorization`` and,
            when the credentials hold one, ``x-amz-security-token``.

        Raises:
            SigV4ConfigError: If the request carries no ``Host`` header.
        """
        now = self._clock()
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        payload_hash = UNSIGNED_PAYLOAD if self.unsigned_payload else hashlib.sha256(body).hexdigest()

        working = {name.lower(): value for name, value in headers.items() if name.lower() != "authorization"}
        working["x-amz-date"] = amz_date
        working["x-amz-content-sha256"] = payload_hash
        if self.credentials.session_token:
            working["x-amz-security-token"] = self.credentials.session_token
        if "host" not in working:
            raise SigV4ConfigError("Cannot sign a request without a Host header")

        authorization = self.authorization_header(method, url, working, payload_hash, amz_date)
        signed = {"x-amz-date": amz_date, "x-amz-content-sha256": payload_hash, "Authorization": authorization}
        if self.credentials.session_token:
            signed["x-amz-security-token"] = self.credentials.session_token
        return signed

    def authorization_header(self, method: str, url: str, headers: Mapping[str, str], payload_hash: str, amz_date: str) -> str:
        """Build the ``Authorization`` header value for a fully prepared header set.

        Args:
            method: HTTP method.
            url: Request URL as sent on the wire.
            headers: Lower-case header names mapped to values, including every header to sign.
            payload_hash: Hex SHA-256 of the body, or ``UNSIGNED-PAYLOAD``.
            amz_date: Timestamp in ``YYYYMMDDTHHMMSSZ`` form.

        Returns:
            str: Header value.
        """
        parts = urlsplit(url)
        names = _signed_header_names(headers)
        canonical_headers = "".join(f"{name}:{_WHITESPACE.sub(' ', headers[name]).strip()}\n" for name in names)
        signed_headers = ";".join(names)
        canonical_request = "\n".join(
            [
                method.upper(),
                _canonical_uri(parts.path, double_encode=self._double_encode),
                _canonical_query(parts.query),
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        datestamp = amz_date[:8]
        scope = f"{datestamp}/{self.credentials.region}/{self.credentials.service}/aws4_request"
        string_to_sign = "\n".join([ALGORITHM, amz_date, scope, hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()])
        signature = hmac.new(self._signing_key(datestamp), string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{ALGORITHM} Credential={self.credentials.access_key_id}/{scope}, SignedHeaders={signed_headers}, Signature={signature}"


def _apply_signature(signer: SigV4Signer, request: Any) -> None:
    """Sign ``request`` in place, replacing any earlier signature headers.

    Args:
        signer: Signer to use.
        request: An ``httpx.Request`` or ``httpx2.Request`` with its body loaded.
    """
    for stale in ("authorization", "x-amz-date", "x-amz-content-sha256", "x-amz-security-token"):
        if stale in request.headers:
            del request.headers[stale]
    signed = signer.sign(request.method, str(request.url), dict(request.headers), request.content)
    for name, value in signed.items():
        request.headers[name] = value


class SigV4Auth(httpx2.Auth):
    """httpx2 auth that signs every request, including requests on pooled clients and retries."""

    requires_request_body = True

    def __init__(self, signer: SigV4Signer) -> None:
        """Wrap a signer.

        Args:
            signer: Signer that produces the signature headers.
        """
        self.signer = signer

    def auth_flow(self, request: httpx2.Request):
        """Sign the request, then send it.

        Args:
            request: Outbound request with its body loaded.

        Yields:
            httpx2.Request: The signed request.
        """
        _apply_signature(self.signer, request)
        yield request


class SigV4HttpxAuth(httpx.Auth):
    """httpx auth that signs every request, including retries."""

    requires_request_body = True

    def __init__(self, signer: SigV4Signer) -> None:
        """Wrap a signer.

        Args:
            signer: Signer that produces the signature headers.
        """
        self.signer = signer

    def auth_flow(self, request: httpx.Request):
        """Sign the request, then send it.

        Args:
            request: Outbound request with its body loaded.

        Yields:
            httpx.Request: The signed request.
        """
        _apply_signature(self.signer, request)
        yield request


def build_sigv4_signer(config: Mapping[str, Any], *, unsigned_payload: bool = False) -> SigV4Signer:
    """Build a signer from a plaintext ``sigv4_config``.

    Args:
        config: Plaintext configuration.
        unsigned_payload: Send ``UNSIGNED-PAYLOAD`` instead of hashing the body.

    Returns:
        SigV4Signer: Signer for the configuration.
    """
    return SigV4Signer(SigV4Credentials.from_config(config), unsigned_payload=unsigned_payload)


def encrypt_sigv4_secret(field: str, secret: str) -> str:
    """Encrypt one SigV4 secret field with the AES-GCM cipher that protects gateway ``auth_value``.

    The cipher derives its key once per process, so runtime decryption stays cheap enough for
    the request path. A memory-hard KDF would block the event loop on every signed call.
    The field name is bound into the ciphertext, so one field's value cannot be moved into another.

    Args:
        field: Name of the config field, one of ``SIGV4_SENSITIVE_KEYS``.
        secret: Plaintext value of that field.

    Returns:
        str: Encrypted, base64url-encoded value.

    Raises:
        SigV4ConfigError: If ``field`` is not a SigV4 secret field.

    Examples:
        >>> from mcpgateway.utils import services_auth
        >>> services_auth.settings.auth_encryption_secret = "doctest-secret"  # pragma: allowlist secret
        >>> blob = encrypt_sigv4_secret("session_token", "example-value")
        >>> blob != "example-value"
        True
        >>> decrypt_sigv4_secret("session_token", blob)
        'example-value'
        >>> decrypt_sigv4_secret("secret_access_key", blob) is None
        True
    """
    if field not in SIGV4_SENSITIVE_KEYS:
        raise SigV4ConfigError(f"{field} is not a SigV4 secret field")
    # First-Party
    from mcpgateway.utils.services_auth import encode_auth  # pylint: disable=import-outside-toplevel

    encoded = encode_auth({field: secret})
    return encoded or ""


def decrypt_sigv4_secret(field: str, stored: str) -> Optional[str]:
    """Decrypt one stored SigV4 secret field.

    Args:
        field: Name of the config field the value was stored under.
        stored: Value produced by ``encrypt_sigv4_secret`` for the same field.

    Returns:
        Optional[str]: Plaintext secret, or None when ``stored`` is not a valid encrypted value.

    Examples:
        >>> from mcpgateway.utils import services_auth
        >>> services_auth.settings.auth_encryption_secret = "doctest-secret"  # pragma: allowlist secret
        >>> decrypt_sigv4_secret("session_token", "not-an-encrypted-value") is None
        True
    """
    # First-Party
    from mcpgateway.utils.services_auth import decode_auth  # pylint: disable=import-outside-toplevel

    try:
        payload = decode_auth(stored)
    except Exception:  # pylint: disable=broad-except
        return None
    value = payload.get(field) if isinstance(payload, dict) else None
    return value if isinstance(value, str) and value else None


def is_encrypted_sigv4_secret(field: str, value: str) -> bool:
    """Return whether ``value`` is an encrypted SigV4 secret for ``field`` under the current key.

    The cipher authenticates its input, so a plaintext secret never passes this check.

    Args:
        field: Name of the config field the value belongs to.
        value: Candidate stored value.

    Returns:
        bool: True when ``value`` decrypts successfully.

    Examples:
        >>> from mcpgateway.utils import services_auth
        >>> services_auth.settings.auth_encryption_secret = "doctest-secret"  # pragma: allowlist secret
        >>> is_encrypted_sigv4_secret("session_token", encrypt_sigv4_secret("session_token", "example-value"))
        True
        >>> is_encrypted_sigv4_secret("session_token", "example-value")
        False
    """
    return decrypt_sigv4_secret(field, value) is not None


def decrypt_stored_sigv4_config(stored: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a stored ``sigv4_config`` with its secret fields decrypted.

    Args:
        stored: Configuration as persisted, with encrypted ``secret_access_key`` and ``session_token``.

    Returns:
        Dict[str, Any]: Plaintext configuration for runtime use only. Never log or persist it.

    Raises:
        SigV4ConfigError: If a secret field cannot be decrypted.
    """
    plain: Dict[str, Any] = dict(stored)
    for key in SIGV4_SENSITIVE_KEYS:
        value = plain.get(key)
        if isinstance(value, str) and value:
            decrypted = decrypt_sigv4_secret(key, value)
            if decrypted is None:
                raise SigV4ConfigError(f"sigv4_config.{key} could not be decrypted; re-supply the credential")
            plain[key] = decrypted
    return plain


def build_stored_sigv4_auth(stored: Optional[Mapping[str, Any]]) -> Optional[SigV4Auth]:
    """Build an httpx2 auth object from a persisted ``sigv4_config``.

    Args:
        stored: Persisted configuration, or None for a gateway without SigV4.

    Returns:
        Optional[SigV4Auth]: The auth object, or None when ``stored`` is empty.
    """
    if not stored:
        return None
    return SigV4Auth(build_sigv4_signer(decrypt_stored_sigv4_config(stored)))


def build_stored_sigv4_httpx_auth(stored: Optional[Mapping[str, Any]]) -> Optional[SigV4HttpxAuth]:
    """Build an httpx auth object from a persisted ``sigv4_config``.

    Args:
        stored: Persisted configuration, or None for a gateway without SigV4.

    Returns:
        Optional[SigV4HttpxAuth]: The auth object, or None when ``stored`` is empty.
    """
    if not stored:
        return None
    return SigV4HttpxAuth(build_sigv4_signer(decrypt_stored_sigv4_config(stored)))


def with_sigv4_auth(client_factory: Callable[..., Any], signing_auth: Optional[httpx2.Auth]) -> Callable[..., Any]:
    """Make an httpx2 client factory attach ``signing_auth`` to every client it builds.

    Every upstream factory already forwards its ``auth`` argument to ``httpx2.AsyncClient``.
    The wrapper supplies that argument, so the MCP transports and the pooled session
    registry sign without further changes.

    Args:
        client_factory: Factory accepting ``headers``, ``timeout`` and ``auth``.
        signing_auth: Auth object to attach, or None to leave the factory unchanged.

    Returns:
        Callable[..., Any]: ``client_factory`` itself when ``signing_auth`` is None, otherwise a wrapper.
    """
    if signing_auth is None:
        return client_factory

    def _signing_factory(headers: Optional[Dict[str, str]] = None, timeout: Any = None, auth: Any = None) -> Any:  # pylint: disable=unused-argument
        """Build a client with the SigV4 auth attached.

        Args:
            headers: Optional headers for the client.
            timeout: Optional timeout for the client.
            auth: Ignored. SigV4 signing owns request authentication.

        Returns:
            Any: The client built by the wrapped factory.
        """
        return client_factory(headers, timeout, signing_auth)

    return _signing_factory


def build_gateway_sigv4_auth(auth_type: Optional[str], stored: Optional[Mapping[str, Any]]) -> Optional[SigV4Auth]:
    """Build the httpx2 signer for a gateway, or None when the gateway does not use SigV4.

    Args:
        auth_type: The gateway ``auth_type``.
        stored: The persisted ``sigv4_config`` of the gateway.

    Returns:
        Optional[SigV4Auth]: The signer for a SigV4 gateway, otherwise None.

    Raises:
        SigV4ConfigError: If the gateway uses SigV4 but holds no usable credentials.

    Examples:
        >>> build_gateway_sigv4_auth("bearer", None) is None
        True
        >>> build_gateway_sigv4_auth("sigv4", None)  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        mcpgateway.utils.sigv4.SigV4ConfigError: auth_type 'sigv4' requires a stored sigv4_config
    """
    if auth_type != "sigv4":
        return None
    signing_auth = build_stored_sigv4_auth(stored)
    if signing_auth is None:
        raise SigV4ConfigError("auth_type 'sigv4' requires a stored sigv4_config")
    return signing_auth


def sigv4_client_factory(signing_auth: Optional[httpx2.Auth]) -> Optional[Callable[..., Any]]:
    """Return a default httpx2 client factory that signs every request.

    Prompt and completion calls pass no client factory of their own. A SigV4 gateway needs
    one so the signer reaches the client.

    Args:
        signing_auth: Auth object to attach, or None for a gateway without SigV4.

    Returns:
        Optional[Callable[..., Any]]: A factory, or None when ``signing_auth`` is None.

    Examples:
        >>> sigv4_client_factory(None) is None
        True
    """
    if signing_auth is None:
        return None

    def _default_factory(headers: Optional[Dict[str, str]] = None, timeout: Any = None, auth: Any = None) -> Any:
        """Build a plain httpx2 client that verifies TLS with the gateway default.

        Args:
            headers: Optional headers for the client.
            timeout: Optional timeout for the client.
            auth: Optional auth for the client.

        Returns:
            Any: The configured ``httpx2.AsyncClient``.
        """
        # First-Party
        from mcpgateway.services.http_client_service import get_default_verify, get_httpx2_timeout  # pylint: disable=import-outside-toplevel

        return httpx2.AsyncClient(follow_redirects=False, headers=headers, timeout=timeout if timeout else get_httpx2_timeout(), auth=auth, verify=get_default_verify())

    return with_sigv4_auth(_default_factory, signing_auth)
