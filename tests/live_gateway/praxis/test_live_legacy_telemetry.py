"""Live authenticated proof for Task 21 legacy telemetry."""

from .conftest import LiveStack


def test_live_authenticated_heartbeat_inventory_and_readiness(live_stack: LiveStack) -> None:
    attestation = live_stack.api.request(
        "PUT",
        "/v1/praxis/legacy/inventory-attestation",
        {
            "consumers": [],
            "private_state_present": False,
            "shadow_diff_count": 0,
            "task20_e2e_passed": True,
            "launcher_fleet_compatible": True,
        },
    )
    assert attestation.status == 200
    assert attestation.json()["actor"] == "admin@example.com"

    heartbeat = live_stack.api.request("POST", "/v1/praxis/legacy/heartbeat", {"version": "1.2.0", "path": "control_plane_grpc"})
    assert heartbeat.status == 202
    assert heartbeat.json()["identity"] == "admin@example.com"

    inventory = live_stack.api.request("GET", "/v1/praxis/legacy/inventory")
    assert inventory.status == 200
    consumers = inventory.json()["consumers"]
    assert isinstance(consumers, list) and len(consumers) == 1
    first_consumer = consumers[0]
    assert isinstance(first_consumer, dict)
    assert first_consumer["observability_class"] == "server_observable"
    readiness = live_stack.api.request("GET", "/v1/praxis/legacy/removal-readiness")
    assert readiness.status == 200
    blockers = readiness.json()["blockers"]
    assert isinstance(blockers, list)
    assert "active_consumer" in blockers
