# -*- coding: utf-8 -*-
"""Location: ./tests/loadtest/locustfile_secret_detection.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Focused load test for secrets detection plugin performance comparison.
This locustfile is specifically designed to benchmark the secrets detection plugin
by sending prompts with and without secrets to measure detection overhead.
Usage:
    make load-test-secret-detection-compare
Environment Variables:
    SECRET_DETECTION_LOADTEST_HOST: Target host URL (default: http://localhost:8080)
    SECRET_DETECTION_LOADTEST_USERS: Number of concurrent users (default: 100)
    SECRET_DETECTION_LOADTEST_SPAWN_RATE: Users spawned per second (default: 10)
    SECRET_DETECTION_LOADTEST_RUN_TIME: Test duration (default: 60s)
    MCPGATEWAY_BEARER_TOKEN: JWT token for authenticated requests
"""

import os
import random
from locust import between, task
from locust.contrib.fasthttp import FastHttpUser


class SecretsDetectionUser(FastHttpUser):
    """User that sends prompts with and without secrets to test detection performance."""

    wait_time = between(0.1, 0.5)

    def on_start(self):
        """Initialize user with auth token."""
        self.token = os.getenv("MCPGATEWAY_BEARER_TOKEN", "")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        # Track secret detection effectiveness
        self.secrets_blocked_count = 0
        self.secrets_not_blocked_count = 0

        # Sample prompts without secrets (clean)
        self.clean_prompts = [
            "What are the best practices for Kubernetes deployment?",
            "Explain microservices architecture patterns.",
            "How do I configure Docker networking?",
            "What is the difference between REST and gRPC?",
            "Describe service mesh architectures.",
        ]

        # Sample prompts with secrets (should be blocked)
        self.secret_prompts = [
            "AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE AWS_SECRET_ACCESS_KEY=FAKESecretAccessKeyForTestingEXAMPLE0000",  # pragma: allowlist secret
            "Here's my Slack token: xoxr-fake-000000000-fake000000000-fakefakefakefake",
            "Google API key: AIzaFAKE_KEY_FOR_TESTING_ONLY_fake12345",
            "JWT: eyJfake_header_12345.eyJfake_payload_1234.fake_signature_12345678",
            "Database key: 00face00dead00beef00cafe00fade0000000000000000000000000000000000",  # pragma: allowlist secret
        ]

    @task(7)  # 70% of traffic (7/(7+3))
    def get_prompt_clean(self):
        """Fetch a prompt without secrets (70% of traffic)."""
        prompt_text = random.choice(self.clean_prompts)
        with self.client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "prompts/get",
                "params": {"name": "test-prompt", "arguments": {"query": prompt_text}},
            },
            headers=self.headers,
            name="/rpc prompts/get [clean]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")

    @task(3)  # 30% of traffic (3/(7+3))
    def get_prompt_with_secret_expect_block(self):
        """Fetch a prompt with secrets (30% of traffic - should be blocked)."""
        prompt_text = random.choice(self.secret_prompts)
        with self.client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "prompts/get",
                "params": {"name": "test-prompt", "arguments": {"query": prompt_text}},
            },
            headers=self.headers,
            name="/rpc prompts/get [secret-blocked]",
            catch_response=True,
        ) as response:
            # Expect 403 when secrets are detected and blocked
            if response.status_code == 403:
                self.secrets_blocked_count += 1
                response.success()
            elif response.status_code == 200:
                # Secret was not blocked - this indicates secrets detection may not be working
                self.secrets_not_blocked_count += 1
                response.success()  # Don't fail the load test, but track it
                if self.secrets_not_blocked_count % 10 == 0:
                    print(f"⚠️  Warning: {self.secrets_not_blocked_count} secrets not blocked (may indicate detection disabled)")
            else:
                response.failure(f"Unexpected status {response.status_code}")
