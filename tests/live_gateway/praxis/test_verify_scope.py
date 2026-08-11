"""Unit contracts for the read-only Praxis delivery scope verifier."""

from pathlib import Path

from tests.live_gateway.praxis.scope_dependencies import classify_dependency_facts, DependencyFacts
from tests.live_gateway.praxis.scope_git import added_lines_for_untracked, parse_changed_inventory
from tests.live_gateway.praxis.verify_scope import classify_added_line, is_allowed_path


def test_scope_paths_allow_task_21_and_22_surfaces_and_reject_unrelated_paths() -> None:
    allowed = Path("tests/live_gateway/praxis/test_live_praxis.py")

    # When/Then: only the bounded implementation surface is accepted.
    assert is_allowed_path(allowed)
    assert is_allowed_path(Path("mcpgateway/services/praxis_legacy_telemetry.py"))
    assert is_allowed_path(Path("docs/Makefile"))
    assert is_allowed_path(Path("docs/docs/architecture/index.md"))
    assert is_allowed_path(Path("docs/docs/deployment/helm.md"))
    assert is_allowed_path(Path("docs/docs/manage/configuration.md"))
    assert is_allowed_path(Path("tests/unit/mcpgateway/test_main.py"))
    assert not is_allowed_path(Path("docs/docs/manage/praxis.md"))
    assert not is_allowed_path(Path("docs/docs/deployment/unrelated.md"))
    assert not is_allowed_path(Path("mcpgateway/services/praxis_legacy_telemetry_extra.py"))
    assert not is_allowed_path(Path("tests/unit/mcpgateway/test_main_extra.py"))
    assert not is_allowed_path(Path("tests/live_gateway/mcp/test_mcp_rbac_transport.py"))


def test_scope_allows_only_exact_generated_secrets_baseline_path() -> None:
    # Given/When/Then: the audited generated baseline is allowed without widening its path.
    assert is_allowed_path(Path(".secrets.baseline"))
    assert not is_allowed_path(Path(".secrets.baseline.extra"))
    assert not is_allowed_path(Path("nested/.secrets.baseline"))


def test_scope_patterns_use_structured_test_and_explanation_allowances() -> None:
    # Given: production behavior, a deny-path assertion, and an explicit explanation.
    production = "from praxis_forge.control import Controller"
    test_assertion = 'assert "praxis_forge" not in production_imports'
    explanation = "# scope-allow: traffic-negative proves traffic remains rejected"

    # When/Then: production integration is rejected without flagging proof text.
    assert classify_added_line(Path("mcpgateway/main.py"), production) == "praxis_forge_import"
    assert classify_added_line(Path("tests/live_gateway/praxis/test_live_praxis.py"), test_assertion) is None
    assert classify_added_line(Path("tests/live_gateway/praxis/test_live_praxis.py"), explanation) is None
    assert classify_added_line(Path("tests/unit/test_praxis_compose_contract.py"), "PRAXIS_TRAFFIC_ENABLED=true") is None


def test_scope_patterns_reject_forbidden_production_shapes() -> None:
    # Given/When/Then: each forbidden implementation shape has a stable category.
    assert classify_added_line(Path("mcpgateway/main.py"), "bundle_path = f'/users/{user_id}/praxis.yaml'") == "per_user_bundle"
    assert classify_added_line(Path("mcpgateway/main.py"), 'USER_CONFIG_KEY = "UserConfig"') == "per_user_bundle"
    assert classify_added_line(Path("mcpgateway/services/dataplane_publisher.py"), 'USER_CONFIG_KEY = "UserConfig"') is None
    assert classify_added_line(Path("docker-compose.yml"), "driver_opts: {type: nfs}") == "rwx_storage"
    assert classify_added_line(Path("mcpgateway/main.py"), "PRAXIS_TRAFFIC_ENABLED = True") == "praxis_traffic"


def test_scope_inventory_includes_deleted_renamed_and_untracked_paths() -> None:
    # Given: tracked deletion/rename output plus one nonignored untracked file.
    tracked = "D\0docs/deleted.md\0R100\0old/name.py\0new/name.py\0"
    untracked = "docs/untracked-forbidden.md\0"

    # When: the deterministic inventory is parsed.
    paths = parse_changed_inventory(tracked, untracked)

    # Then: absent sources, both rename identities, and untracked paths remain visible.
    assert paths == (
        Path("docs/deleted.md"),
        Path("docs/untracked-forbidden.md"),
        Path("new/name.py"),
        Path("old/name.py"),
    )


def test_scope_added_lines_scans_untracked_nonignored_file(tmp_path: Path) -> None:
    # Given: an untracked prohibited file whose content never appears in git diff.
    path = Path("docs/untracked-forbidden.md")
    absolute = tmp_path / path
    absolute.parent.mkdir(parents=True)
    absolute.write_text("from praxis_forge.control import Controller\n", encoding="utf-8")

    # When: untracked content is treated as wholly added.
    added = added_lines_for_untracked(tmp_path, (path,))

    # Then: the forbidden line is available to normal pattern classification.
    assert added == ((path, "from praxis_forge.control import Controller"),)
    assert classify_added_line(*added[0]) == "praxis_forge_import"


def test_dependency_facts_derive_exact_f4_observations() -> None:
    # Given: only the Task 20-approved base/current dependency observations.
    facts = DependencyFacts(
        python_added=frozenset(),
        base_direct_names=frozenset({"cpex", "serde_yaml"}),
        base_lock_names=frozenset({"nix", "rustls-pemfile", "sha2", "tempfile"}),
        current_lock_names=frozenset({"hex", "nix", "sha2", "tempfile"}),
        added_direct=frozenset({"async-trait", "cpex", "nix", "praxis", "praxis-core", "praxis-filter", "prost", "serde_yaml"}),
        cryptography_existing=True,
        sha2_existing_reused=True,
        tempfile_dev_reused=True,
        tar_archive_used=True,
        praxis_source_valid=True,
    )

    # When: dependency evidence is classified.
    result = classify_dependency_facts(facts)

    # Then: output is derived from observations and exactly matches F4.
    assert result.violations == ()
    assert result.approved == (
        "cryptography-existing",
        "hex",
        "nix",
        "praxis@ed46eb5",
        "sha2-existing",
        "tar",
        "tempfile-dev",
    )


def test_dependency_facts_reject_unapproved_rust_and_python_additions() -> None:
    # Given: otherwise valid evidence with one extra direct dependency per ecosystem.
    facts = DependencyFacts(
        python_added=frozenset({"unapproved-python"}),
        base_direct_names=frozenset(),
        base_lock_names=frozenset({"nix", "rustls-pemfile", "sha2", "tempfile"}),
        current_lock_names=frozenset({"hex", "nix", "rustls-pemfile", "sha2", "tempfile"}),
        added_direct=frozenset({"nix", "praxis", "praxis-core", "praxis-filter", "rustls-pemfile"}),
        cryptography_existing=True,
        sha2_existing_reused=True,
        tempfile_dev_reused=True,
        tar_archive_used=True,
        praxis_source_valid=True,
    )

    # When: dependency evidence is classified.
    result = classify_dependency_facts(facts)

    # Then: neither extra dependency can hide behind the approved labels.
    assert result.approved == ()
    assert result.violations == ("python:unapproved-python", "rust:rustls-pemfile")
