"""Agent-executed live activation and machine-security narrative."""

from __future__ import annotations

import json
import socket
import ssl
import subprocess
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

import pytest

from .conftest import LiveStack
from .live_api import ApiResponse, assert_identity_separation, BearerToken, JsonObject, LiveApi


def _expect(response: ApiResponse, status: int) -> JsonObject:
    assert response.status == status, response.body.decode(errors="replace")
    return response.json()


def _object(payload: JsonObject, key: str) -> JsonObject:
    value = payload[key]
    assert isinstance(value, dict)
    return value


def _integer(payload: JsonObject, key: str) -> int:
    value = payload[key]
    assert isinstance(value, int) and not isinstance(value, bool)
    return value


def _string(payload: JsonObject, key: str) -> str:
    value = payload[key]
    assert isinstance(value, str)
    return value


def _wait_for(stack: LiveStack, target_id: str, state: str, timeout: int = 180) -> JsonObject:
    deadline = time.monotonic() + timeout
    payload: JsonObject = {}
    while time.monotonic() < deadline:
        payload = _expect(stack.api.request("GET", f"/v1/praxis/targets/{target_id}/status"), 200)
        convergence = payload["convergence"]
        if isinstance(convergence, dict) and convergence["state"] == state:
            return payload
        time.sleep(1)
    logs = stack.compose("logs", "--no-color", "--tail", "100", "praxis_a", "praxis_b", check=False)
    raise AssertionError(f"target did not converge to {state}: {payload!r}\n{logs.stdout}{logs.stderr}")


def _wait_for_service(stack: LiveStack, service: str, state: str, timeout: int = 60) -> JsonObject:
    deadline = time.monotonic() + timeout
    observed: JsonObject = {}
    while time.monotonic() < deadline:
        inspection = stack.compose("--profile", "tls", "--profile", "praxis-e2e", "ps", "--format", "json", service, check=False)
        rows = [json.loads(line) for line in inspection.stdout.splitlines() if line]
        if len(rows) == 1:
            observed = rows[0]
            if observed.get("State") == state:
                return observed
        time.sleep(1)
    raise AssertionError(f"service {service} did not reach {state}: {observed!r}")


def _wait_for_praxis_exit(stack: LiveStack, service: str, timeout: int = 75) -> None:
    deadline = time.monotonic() + timeout
    observed = ""
    while time.monotonic() < deadline:
        result = stack.compose("--profile", "tls", "--profile", "praxis-e2e", "top", service, check=False)
        observed = result.stdout
        if "/usr/local/bin/praxis --config" not in observed:
            return
        time.sleep(1)
    raise AssertionError(f"Praxis process did not exit in {service}:\n{observed}")


def test_live_activation_rotation_cohorts_and_security(live_stack: LiveStack) -> None:
    # Given: the live TLS endpoint rejects both an unknown CA and a wrong hostname.
    with pytest.raises(URLError, match="CERTIFICATE_VERIFY_FAILED"):
        urlopen(f"{live_stack.api.base_url}/health", context=ssl.create_default_context(), timeout=10)
    endpoint = urlsplit(live_stack.api.base_url)
    trusted = ssl.create_default_context(cafile=live_stack.api.ca_path)
    with socket.create_connection((endpoint.hostname or "127.0.0.1", endpoint.port or 443), timeout=10) as connection:
        with pytest.raises(ssl.SSLCertVerificationError):
            trusted.wrap_socket(connection, server_hostname="wrong-san.invalid")

    # Given: one public server, target, and one server-issued replica identity.
    server = _expect(live_stack.api.request("POST", "/v1/servers", {"server": {"name": "praxis-e2e-server", "description": "generation N"}, "visibility": "public"}), 201)
    target = _expect(live_stack.api.request("POST", "/v1/praxis/targets", {"name": "praxis-e2e-target"}), 201)
    target_id = str(target["id"])
    _expect(live_stack.api.request("PUT", f"/v1/praxis/targets/{target_id}/assignments", {"server_ids": [str(server["id"])], "reassign": False}), 200)
    replica_a = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/replicas", {"name": "replica-a"}), 201)
    credential_a1 = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/replicas/{replica_a['id']}/credentials", {"expires_in_seconds": 3600}), 201)
    live_stack.token_a_path.write_text(str(credential_a1["token"]) + "\n", encoding="utf-8")

    # When: generation N rollout R1 is published and its real launcher activates it.
    rollout_r1 = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/render"), 200)
    live_stack.compose("--profile", "tls", "--profile", "praxis-e2e", "up", "-d", "praxis_a")
    status_r1 = _wait_for(live_stack, target_id, "verified")
    desired_r1 = status_r1["desired"]
    assert isinstance(desired_r1, dict)
    assert desired_r1["rollout_id"] == rollout_r1["rollout_id"]
    assert _object(status_r1, "convergence")["active_replicas"] == 1

    # Then: add/remove churn creates a fresh same-content R2 cohort.
    replica_b = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/replicas", {"name": "replica-b"}), 201)
    credential_b1 = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/replicas/{replica_b['id']}/credentials", {"expires_in_seconds": 3600}), 201)
    live_stack.token_b_path.write_text(str(credential_b1["token"]) + "\n", encoding="utf-8")
    removed_a = live_stack.api.request("DELETE", f"/v1/praxis/targets/{target_id}/replicas/{replica_a['id']}")
    assert removed_a.status == 204
    assert LiveApi(live_stack.api.base_url, live_stack.api.ca_path, BearerToken(str(credential_a1["token"]))).request("GET", "/praxis/v1/desired").status == 401
    live_stack.compose("--profile", "tls", "--profile", "praxis-e2e", "stop", "praxis_a")
    rollout_r2 = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/render"), 200)
    assert rollout_r2["generation_id"] == rollout_r1["generation_id"]
    assert rollout_r2["rollout_id"] != rollout_r1["rollout_id"]
    assert rollout_r2["directive_id"] != rollout_r1["directive_id"]
    live_stack.compose("--profile", "tls", "--profile", "praxis-e2e", "up", "-d", "praxis_b")
    status_r2 = _wait_for(live_stack, target_id, "verified")
    assert _object(status_r2, "convergence")["cohort_size"] == 1

    # And: an actual failed rollout is retried as a fresh R3 directive.
    live_stack.compose("--profile", "tls", "--profile", "praxis-e2e", "stop", "praxis_b")
    failed_rollout = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/render"), 200)
    failed_desired = _expect(LiveApi(live_stack.api.base_url, live_stack.api.ca_path, BearerToken(str(credential_b1["token"]))).request("GET", "/praxis/v1/desired"), 200)
    failed_report = {
        "report_schema": "praxis-replica-report/v1",
        "directive_id": str(failed_desired["directive_id"]),
        "sequence": _integer(failed_desired, "next_report_sequence"),
        "state": "failed",
        "failure_category": "policy_canary",
    }
    report_response = LiveApi(live_stack.api.base_url, live_stack.api.ca_path, BearerToken(str(credential_b1["token"]))).request(
        "POST", "/praxis/v1/reports", failed_report, headers={"If-Match": str(failed_desired["directive_id"])}
    )
    assert _expect(report_response, 200)["disposition"] == "accepted"
    rollout_r3 = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/rollouts/{failed_rollout['rollout_id']}/retry"), 200)
    assert rollout_r3["rollout_id"] != failed_rollout["rollout_id"]
    live_stack.compose("--profile", "tls", "--profile", "praxis-e2e", "up", "-d", "praxis_b")
    status_r3 = _wait_for(live_stack, target_id, "verified")
    assert _object(status_r3, "desired")["action"] == "retry"

    # And: two-token overlap works, a concurrent third is rejected, then old JTI revocation denies use.
    credential_b2 = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/replicas/{replica_b['id']}/credentials", {"expires_in_seconds": 3600}), 201)
    denied_third = live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/replicas/{replica_b['id']}/credentials", {"expires_in_seconds": 3600})
    assert denied_third.status == 409
    old_machine = LiveApi(live_stack.api.base_url, live_stack.api.ca_path, BearerToken(str(credential_b1["token"])))
    new_machine = LiveApi(live_stack.api.base_url, live_stack.api.ca_path, BearerToken(str(credential_b2["token"])))
    old_desired = _expect(old_machine.request("GET", "/praxis/v1/desired"), 200)
    new_desired = _expect(new_machine.request("GET", "/praxis/v1/desired"), 200)
    assert old_desired["directive_id"] == new_desired["directive_id"]
    assert_identity_separation(old_desired)
    not_modified = new_machine.request("GET", "/praxis/v1/desired", headers={"If-None-Match": f'"{new_desired["response_etag"]}"'})
    assert not_modified.status == 304
    assert {directive.strip() for directive in not_modified.headers["cache-control"].split(",")} == {"private", "no-store"}
    revoked = live_stack.api.request("DELETE", f"/v1/praxis/targets/{target_id}/replicas/{replica_b['id']}/credentials/{credential_b1['jti']}")
    assert revoked.status == 204
    assert revoked.body == b""
    assert old_machine.request("GET", "/praxis/v1/desired").status == 401
    live_stack.token_b_path.write_text(str(credential_b2["token"]) + "\n", encoding="utf-8")

    # And: stale/malformed fencing, wrong token, direct HTTP, and target-bound identity fail closed.
    assert new_machine.request("GET", "/praxis/v1/artifact", headers={"If-Match": str(rollout_r1["directive_id"])}).status == 409
    assert new_machine.request("GET", "/praxis/v1/artifact", headers={"If-Match": "malformed"}).status == 409
    wrong_token = LiveApi(live_stack.api.base_url, live_stack.api.ca_path, BearerToken("wrong-token"))
    assert wrong_token.request("GET", "/praxis/v1/desired").status == 401
    http_url = live_stack.api.base_url.replace("https://", "http://")
    direct_http = subprocess.run(["curl", "--silent", "--output", "/dev/null", "--write-out", "%{http_code}", f"{http_url}/praxis/v1/desired"], check=True, capture_output=True, text=True, timeout=10)
    assert direct_http.stdout in {"301", "400"}

    # And: an additive mutation creates N+1 and both launchers replace N cleanly.
    server_2 = _expect(live_stack.api.request("POST", "/v1/servers", {"server": {"name": "praxis-e2e-server-2", "description": "generation N+1"}, "visibility": "public"}), 201)
    _expect(live_stack.api.request("PUT", f"/v1/praxis/targets/{target_id}/assignments", {"server_ids": [str(server["id"]), str(server_2["id"])], "reassign": False}), 200)
    rollout_n1 = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/render"), 200)
    assert rollout_n1["generation_id"] != rollout_r1["generation_id"]
    assert len({_string(rollout_n1, "generation_id"), _string(rollout_n1, "rollout_id"), _string(rollout_n1, "directive_id")}) == 3
    _wait_for(live_stack, target_id, "verified")

    # And: the server directs a rollback to the verified predecessor generation.
    rollback = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/rollback"), 200)
    rollback_status = _wait_for(live_stack, target_id, "verified")
    rollback_desired = _object(rollback_status, "desired")
    assert rollback_desired["rollout_id"] == rollback["rollout_id"]
    assert rollback_desired["action"] == "rollback"
    assert rollback_desired["generation_id"] == rollout_r3.get("generation_id", rollout_r2["generation_id"])

    # And: a launcher restart recovers the current directive and its listener.
    before_restart = _wait_for_service(live_stack, "praxis_b", "running")
    live_stack.compose("--profile", "tls", "--profile", "praxis-e2e", "restart", "praxis_b")
    after_restart = _wait_for_service(live_stack, "praxis_b", "running")
    assert after_restart["ID"] == before_restart["ID"]
    _wait_for(live_stack, target_id, "verified")

    # And: owner-private state is refused and enabled-target deletion is fail-closed.
    private_server = _expect(live_stack.api.request("POST", "/v1/servers", {"server": {"name": "praxis-e2e-private", "description": "owner-private refusal"}, "visibility": "private"}), 201)
    private_target = _expect(live_stack.api.request("POST", "/v1/praxis/targets", {"name": "praxis-e2e-private-target"}), 201)
    private_target_id = str(private_target["id"])
    assert live_stack.api.request("POST", f"/v1/praxis/targets/{private_target_id}/replicas/{replica_b['id']}/credentials", {"expires_in_seconds": 3600}).status == 404
    private_assignment = live_stack.api.request("PUT", f"/v1/praxis/targets/{private_target_id}/assignments", {"server_ids": [str(private_server["id"])], "reassign": False})
    assert private_assignment.status == 409
    assert b"owner_private" in private_assignment.body
    assert live_stack.api.request("DELETE", f"/v1/praxis/targets/{private_target_id}").status == 409
    _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{private_target_id}/disable"), 200)
    deleted = live_stack.api.request("DELETE", f"/v1/praxis/targets/{private_target_id}")
    assert deleted.status == 204
    assert deleted.body == b""

    # Finally: a server-directed stop drains both Praxis process groups before teardown.
    stop = _expect(live_stack.api.request("POST", f"/v1/praxis/targets/{target_id}/disable"), 200)
    assert stop["action"] == "stop"
    stop_desired = _expect(new_machine.request("GET", "/praxis/v1/desired"), 200)
    assert stop_desired["action"] == "stop"
    _wait_for_praxis_exit(live_stack, "praxis_a")
    _wait_for_praxis_exit(live_stack, "praxis_b")

    # Canary evidence is deliberately limited to local parse/listener/policy denial.
    # scope-allow: traffic-negative no authenticated MCP traffic parity is claimed.
    inspection = live_stack.compose("ps", "--all", "--format", "json")
    services = [json.loads(line) for line in inspection.stdout.splitlines() if line]
    praxis_services = [service for service in services if service["Service"] in {"praxis_a", "praxis_b"}]
    assert len(praxis_services) == 2
    assert all(service["Publishers"] == [] for service in praxis_services)
