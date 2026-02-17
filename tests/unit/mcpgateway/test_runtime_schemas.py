# -*- coding: utf-8 -*-
"""Unit tests for runtime request/response schemas."""

# Third-Party
import pytest
from pydantic import ValidationError

# First-Party
from mcpgateway.runtime_schemas import RuntimeDeployRequest, RuntimeSource


def test_runtime_source_accepts_valid_variants():
    docker = RuntimeSource(type="docker", image="docker.io/acme/runtime:1")
    github = RuntimeSource(type="github", repo="acme/repo")
    compose = RuntimeSource(type="compose", compose_file="services:\n  app:\n    image: app", main_service="app")

    assert docker.image == "docker.io/acme/runtime:1"
    assert github.repo == "acme/repo"
    assert compose.main_service == "app"


@pytest.mark.parametrize(
    "payload,error_fragment",
    [
        ({"type": "docker"}, "requires 'image'"),
        ({"type": "github"}, "requires 'repo'"),
        ({"type": "compose", "main_service": "app"}, "requires 'compose_file'"),
        ({"type": "compose", "compose_file": "services:\n  app:\n    image: app"}, "requires 'main_service'"),
    ],
)
def test_runtime_source_requires_fields_by_type(payload, error_fragment):
    with pytest.raises(ValidationError) as exc_info:
        RuntimeSource(**payload)
    assert error_fragment in str(exc_info.value)


def test_runtime_deploy_request_accepts_source_or_catalog_id():
    with_source = RuntimeDeployRequest(
        name="runtime-with-source",
        backend="docker",
        source=RuntimeSource(type="docker", image="docker.io/acme/runtime:1"),
        endpoint_port=8080,
        endpoint_path="http",
    )
    with_catalog = RuntimeDeployRequest(name="runtime-with-catalog", backend="docker", catalog_server_id="catalog-entry-1")

    assert with_source.source is not None
    assert with_source.endpoint_port == 8080
    assert with_source.endpoint_path == "/http"
    assert with_catalog.catalog_server_id == "catalog-entry-1"


def test_runtime_deploy_request_requires_source_or_catalog_id():
    with pytest.raises(ValidationError) as exc_info:
        RuntimeDeployRequest(name="invalid-runtime", backend="docker")
    assert "Either 'source' or 'catalog_server_id' is required" in str(exc_info.value)


@pytest.mark.parametrize("endpoint_path", ["http://bad.example/path", "/http?x=1", "/http#fragment"])
def test_runtime_deploy_request_rejects_invalid_endpoint_path(endpoint_path):
    with pytest.raises(ValidationError) as exc_info:
        RuntimeDeployRequest(
            name="runtime-invalid-path",
            backend="docker",
            source=RuntimeSource(type="docker", image="docker.io/acme/runtime:1"),
            endpoint_path=endpoint_path,
        )
    assert "endpoint_path" in str(exc_info.value)
