import json
import time
import uuid

import jwt
from locust import FastHttpUser, between, task


JWT_SECRET = "my-test-key"
JWT_AUDIENCE = "mcpgateway-api"
JWT_ISSUER = "mcpgateway"
JWT_SUBJECT = "admin@example.com"
PROMPT_NAME = "fast-time-sse-schedule-meeting"


def make_token() -> str:
    now = int(time.time())
    payload = {
        "sub": JWT_SUBJECT,
        "preferred_username": JWT_SUBJECT,
        "email": JWT_SUBJECT,
        "is_admin": True,
        "aud": JWT_AUDIENCE,
        "iss": JWT_ISSUER,
        "exp": now + 3600,
        "iat": now,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


class SecretDetectionUser(FastHttpUser):
    wait_time = between(0.01, 0.05)

    def on_start(self) -> None:
        token = make_token()
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _rpc(self, arguments: dict[str, str], name: str, expect_plugin_block: bool = False) -> None:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "prompts/get",
            "params": {
                "name": PROMPT_NAME,
                "arguments": arguments,
            },
        }
        with self.client.post("/rpc", data=json.dumps(payload), headers=self.headers, name=name, catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"unexpected HTTP {response.status_code}")
                return
            try:
                body = response.json()
            except Exception as exc:
                response.failure(f"invalid JSON response: {exc}")
                return

            error = body.get("error")
            if expect_plugin_block:
                if error and error.get("code") == -32602 and "SecretsDetection" in json.dumps(error):
                    response.success()
                else:
                    response.failure(f"expected secrets plugin block, got: {body}")
                return

            if error:
                response.failure(f"unexpected RPC error: {error}")
                return
            response.success()

    @task(3)
    def clean_prompt_request(self) -> None:
        self._rpc(
            {
                "participants": "Dublin,London",
                "duration": "30",
                "preferred_hours": "9 AM - 5 PM",
            },
            "/rpc prompts/get [clean]",
        )

    @task(3)
    def secret_prompt_request(self) -> None:
        self._rpc(
            {
                "participants": "AKIA1234567890ABCDEF,London",
                "duration": "30",
                "preferred_hours": "9 AM - 5 PM",
            },
            "/rpc prompts/get [secret-blocked]",
            expect_plugin_block=True,
        )
