# -*- coding: utf-8 -*-
"""Direct core-auth endpoint benchmark.

Compares Python core auth and Rust auth sidecar without MCP runtime overhead.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import uuid

from locust import FastHttpUser, between, task


def _cfg(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


JWT_SECRET_KEY = _cfg("JWT_SECRET_KEY", "my-test-key-but-now-longer-than-32-bytes")
JWT_ALGORITHM = _cfg("JWT_ALGORITHM", "HS256")
JWT_AUDIENCE = _cfg("JWT_AUDIENCE", "mcpgateway-api")
JWT_ISSUER = _cfg("JWT_ISSUER", "mcpgateway")
JWT_USERNAME = _cfg("PLATFORM_ADMIN_EMAIL", "admin@example.com")
AUTH_ENCRYPTION_SECRET = _cfg("AUTH_ENCRYPTION_SECRET", "my-test-salt")
AUTH_PATH = _cfg("CORE_AUTH_BENCH_PATH", "/_internal/core/auth/authenticate")
TARGET_PATH = _cfg("CORE_AUTH_BENCH_TARGET_PATH", "/mcp")
AUTH_LANE = _cfg("CORE_AUTH_BENCH_LANE", "session_jwt")
AUTH_MODE = _cfg("CORE_AUTH_BENCH_MODE", "rust_sidecar")
API_TOKEN = _cfg("CORE_AUTH_BENCH_API_TOKEN", "")


def _runtime_auth_header() -> str:
    payload = f"{AUTH_ENCRYPTION_SECRET}:contextforge-internal-mcp-runtime-v1".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _generate_jwt(token_use: str | None, teams=None, is_admin: bool = False) -> str:
    import jwt  # pylint: disable=import-outside-toplevel

    payload = {
        "username": JWT_USERNAME,
        "sub": JWT_USERNAME,
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        "iat": datetime.now(timezone.utc),
        "aud": JWT_AUDIENCE,
        "iss": JWT_ISSUER,
        "jti": str(uuid.uuid4()),
    }
    if token_use:
        payload["token_use"] = token_use
    if teams is not None:
        payload["teams"] = teams
    if is_admin:
        payload["is_admin"] = True
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def _build_authorization() -> str:
    if AUTH_LANE == "session_jwt":
        return f"Bearer {_generate_jwt('session', ['team-a'], False)}"
    if AUTH_LANE == "session_admin_jwt":
        return f"Bearer {_generate_jwt('session', None, True)}"
    if AUTH_LANE == "api_jwt":
        return f"Bearer {_generate_jwt(None, ['team-a'], False)}"
    if AUTH_LANE == "revoked_jwt":
        return f"Bearer {_generate_jwt(None, ['team-a'], False)}"
    if AUTH_LANE == "api_token":
        if not API_TOKEN:
            raise RuntimeError("CORE_AUTH_BENCH_API_TOKEN is required for api_token lane")
        return f"Bearer {API_TOKEN}"
    raise RuntimeError(f"Unsupported CORE_AUTH_BENCH_LANE={AUTH_LANE}")


class CoreAuthUser(FastHttpUser):
    wait_time = between(0.001, 0.005)

    def on_start(self) -> None:
        self.authorization = _build_authorization()
        self.headers = {
            "content-type": "application/json",
            "x-contextforge-mcp-runtime": "auth",
            "x-contextforge-mcp-runtime-auth": _runtime_auth_header(),
        }

    @task
    def authenticate(self) -> None:
        if AUTH_MODE == "python_internal":
            body = {
                "method": "POST",
                "path": TARGET_PATH,
                "queryString": "",
                "headers": {
                    "authorization": self.authorization,
                },
                "clientIp": "198.51.100.77",
            }
        elif AUTH_MODE == "rust_sidecar":
            body = {
                "method": "POST",
                "path": TARGET_PATH,
                "queryString": "",
                "authorization": self.authorization,
                "clientIp": "198.51.100.77",
            }
        else:
            raise RuntimeError(f"Unsupported CORE_AUTH_BENCH_MODE={AUTH_MODE}")
        with self.client.post(
            AUTH_PATH,
            data=json.dumps(body),
            headers=self.headers,
            name=f"core-auth:{AUTH_LANE}",
            catch_response=True,
        ) as response:
            if response.status_code >= 500:
                response.failure(f"unexpected {response.status_code}")
                return
            if AUTH_LANE == "revoked_jwt":
                if response.status_code != 401:
                    response.failure(f"expected 401, got {response.status_code}")
                return
            if response.status_code != 200:
                response.failure(f"expected 200, got {response.status_code}")
