"""Direct Compose coverage for Praxis failure, fencing, corruption, and stale LKG."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
import subprocess
import time

from .conftest import LiveStack
from .live_api import ApiResponse, JsonObject


def _expect(response: ApiResponse, status: int) -> JsonObject:
    assert response.status == status, response.body.decode(errors="replace")
    return response.json()


def _wait_for_target(stack: LiveStack, target_id: str, predicate: Callable[[JsonObject], bool], timeout: int = 180) -> JsonObject:
    deadline = time.monotonic() + timeout
    observed: JsonObject = {}
    while time.monotonic() < deadline:
        observed = _expect(stack.api.request("GET", f"/v1/praxis/targets/{target_id}/status"), 200)
        if predicate(observed):
            return observed
        time.sleep(1)
    logs = stack.compose("logs", "--no-color", "--tail", "120", "praxis_b", "praxis_failure", check=False)
    raise AssertionError(f"target state not observed: {observed!r}\n{logs.stdout}{logs.stderr}")


def _desired(payload: JsonObject) -> JsonObject:
    value = payload["desired"]
    assert isinstance(value, dict)
    return value


def _convergence(payload: JsonObject) -> JsonObject:
    value = payload["convergence"]
    assert isinstance(value, dict)
    return value


def _exec(stack: LiveStack, service: str, command: str, *, check: bool = True):
    return stack.compose("--profile", "tls", "--profile", "praxis-e2e", "exec", "-T", service, "/bin/bash", "-ec", command, check=check)


def _arm_barrier(stack: LiveStack, target_id: str) -> None:
    _exec(stack, "gateway", f"mkdir -p /tmp/praxis-e2e-control; rm -f /tmp/praxis-e2e-control/{target_id}.reached /tmp/praxis-e2e-control/{target_id}.release; touch /tmp/praxis-e2e-control/{target_id}.arm")


def _wait_for_barrier(stack: LiveStack, target_id: str) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        result = _exec(stack, "gateway", f"test -f /tmp/praxis-e2e-control/{target_id}.reached", check=False)
        if result.returncode == 0:
            return
        time.sleep(0.1)
    raise AssertionError("publication did not reach the post-revalidation barrier")


def _release_barrier(stack: LiveStack, target_id: str) -> None:
    _exec(stack, "gateway", f"touch /tmp/praxis-e2e-control/{target_id}.release")


def test_launcher_failure_corruption_refetch_and_exact_stale_lkg(live_stack: LiveStack) -> None:
    server = _expect(live_stack.api.request("POST", "/v1/servers", {"server": {"name": "praxis-failure-paths", "description": "baseline"}, "visibility": "public"}), 201)
    target = _expect(live_stack.api.request("POST", "/v1/praxis/targets", {"name": "praxis-failure-paths"}), 201)
    target_id = str(target["id"])
    _expect(live_stack.api.request("PUT", f"/v1/praxis/targets/{target_id}/assignments", {"server_ids": [str(server["id"])], "reassign": False}), 200)
    replica = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/replicas", {"name": "failure-replica"}), 201)
    credential = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/replicas/{replica['id']}/credentials", {"expires_in_seconds": 3600}), 201)
    live_stack.token_b_path.write_text(str(credential["token"]) + "\n", encoding="utf-8")

    baseline = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/render"), 200)
    live_stack.compose("--profile", "tls", "--profile", "praxis-e2e", "up", "-d", "praxis_b")
    _wait_for_target(live_stack, target_id, lambda payload: _convergence(payload)["state"] == "verified")

    live_stack.compose("--profile", "tls", "--profile", "praxis-e2e", "stop", "praxis_b")
    failed = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/render"), 200)
    live_stack.compose("--profile", "tls", "--profile", "praxis-e2e", "up", "-d", "praxis_failure")
    failure_status = _wait_for_target(live_stack, target_id, lambda payload: _desired(payload)["rollout_id"] != failed["rollout_id"])
    assert _desired(failure_status)["action"] in {"rollback", "stop"}
    failure_logs = live_stack.compose("--profile", "tls", "--profile", "praxis-e2e", "logs", "--no-color", "--tail", "120", "praxis_failure")
    assert "activation failed: ConfigValidation" in failure_logs.stdout
    live_stack.compose("--profile", "tls", "--profile", "praxis-e2e", "stop", "praxis_failure")

    retry = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/rollouts/{failed['rollout_id']}/retry"), 200)
    assert retry["rollout_id"] != failed["rollout_id"]
    live_stack.compose("--profile", "tls", "--profile", "praxis-e2e", "start", "praxis_b")
    retry_status = _wait_for_target(live_stack, target_id, lambda payload: _convergence(payload)["state"] == "verified")
    assert _desired(retry_status)["rollout_id"] == retry["rollout_id"]

    generation_id = str(baseline["generation_id"])
    sentinel = "CORRUPT-E2E-SENTINEL"
    _exec(live_stack, "praxis_b", f"printf '%s' '{sentinel}' > /var/lib/praxis/generations/{generation_id}/praxis.yaml")
    refetch = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/render"), 200)
    assert refetch["generation_id"] == generation_id
    _wait_for_target(live_stack, target_id, lambda payload: _convergence(payload)["state"] == "verified" and _desired(payload)["rollout_id"] == refetch["rollout_id"])
    recovered = _exec(live_stack, "praxis_b", f"cat /var/lib/praxis/generations/{generation_id}/praxis.yaml")
    assert sentinel not in recovered.stdout
    assert '"listeners"' in recovered.stdout

    container_id = live_stack.compose("--profile", "tls", "--profile", "praxis-e2e", "ps", "-q", "praxis_b").stdout.strip()
    network = f"{live_stack.project}_mcpnet"
    live_stack.stale_age_path.write_text("3599\n", encoding="utf-8")
    live_stack.compose("--profile", "tls", "--profile", "praxis-e2e", "exec", "-T", "gateway", "true")
    disconnect = subprocess.run(["docker", "network", "disconnect", network, container_id], check=False, capture_output=True, text=True)
    assert disconnect.returncode == 0, disconnect.stderr
    try:
        time.sleep(2)
        assert "/usr/local/bin/praxis --config" in live_stack.compose("--profile", "tls", "--profile", "praxis-e2e", "top", "praxis_b").stdout
        assert _exec(live_stack, "praxis_b", "exec 3<>/dev/tcp/127.0.0.1/9090; printf 'GET /readyz HTTP/1.1\r\nHost: localhost\r\n\r\n' >&3; grep -q '^HTTP/1.1 200' <&3", check=False).returncode == 0
        live_stack.stale_age_path.write_text("3600\n", encoding="utf-8")
        assert _exec(live_stack, "praxis_b", "grep -qx 3600 /run/praxis-e2e/stale-age-seconds", check=False).returncode == 0
        readiness_deadline = time.monotonic() + 20
        while time.monotonic() < readiness_deadline and _exec(live_stack, "praxis_b", "exec 3<>/dev/tcp/127.0.0.1/9090; printf 'GET /readyz HTTP/1.1\r\nHost: localhost\r\n\r\n' >&3; grep -q '^HTTP/1.1 503' <&3", check=False).returncode != 0:
            time.sleep(0.25)
        assert _exec(live_stack, "praxis_b", "exec 3<>/dev/tcp/127.0.0.1/9090; printf 'GET /readyz HTTP/1.1\r\nHost: localhost\r\n\r\n' >&3; grep -q '^HTTP/1.1 503' <&3", check=False).returncode == 0
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and "/usr/local/bin/praxis --config" in live_stack.compose("--profile", "tls", "--profile", "praxis-e2e", "top", "praxis_b", check=False).stdout:
            time.sleep(0.25)
        assert "/usr/local/bin/praxis --config" not in live_stack.compose("--profile", "tls", "--profile", "praxis-e2e", "top", "praxis_b", check=False).stdout
    finally:
        subprocess.run(["docker", "network", "connect", network, container_id], check=False, capture_output=True, text=True)
        live_stack.stale_age_path.write_text("0\n", encoding="utf-8")
        live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/disable")


def test_live_publication_fences_source_mutation_and_disable(live_stack: LiveStack) -> None:
    server = _expect(live_stack.api.request("POST", "/v1/servers", {"server": {"name": "praxis-fence", "description": "before"}, "visibility": "public"}), 201)
    target = _expect(live_stack.api.request("POST", "/v1/praxis/targets", {"name": "praxis-fence"}), 201)
    target_id = str(target["id"])
    _expect(live_stack.api.request("PUT", f"/v1/praxis/targets/{target_id}/assignments", {"server_ids": [str(server["id"])], "reassign": False}), 200)
    _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/replicas", {"name": "fence-replica"}), 201)
    baseline = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/render"), 200)

    _arm_barrier(live_stack, target_id)
    with ThreadPoolExecutor(max_workers=1) as pool:
        rendering = pool.submit(live_stack.api.request, "POST", f"/v1/praxis/targets/{target_id}/render")
        _wait_for_barrier(live_stack, target_id)
        _expect(live_stack.api.request("PUT", f"/v1/servers/{server['id']}", {"description": "after revalidation"}), 200)
        _release_barrier(live_stack, target_id)
        stale = rendering.result(timeout=30)
    assert stale.status == 409
    unchanged = _expect(live_stack.api.request("GET", f"/v1/praxis/targets/{target_id}/status"), 200)
    assert _desired(unchanged)["rollout_id"] == baseline["rollout_id"]

    _arm_barrier(live_stack, target_id)
    with ThreadPoolExecutor(max_workers=1) as pool:
        rendering = pool.submit(live_stack.api.request, "POST", f"/v1/praxis/targets/{target_id}/render")
        _wait_for_barrier(live_stack, target_id)
        stop = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/disable"), 200)
        _release_barrier(live_stack, target_id)
        stale = rendering.result(timeout=30)
    assert stale.status == 409
    disabled = _expect(live_stack.api.request("GET", f"/v1/praxis/targets/{target_id}/status"), 200)
    assert _desired(disabled)["rollout_id"] == stop["rollout_id"]
    assert _desired(disabled)["action"] == "stop"
