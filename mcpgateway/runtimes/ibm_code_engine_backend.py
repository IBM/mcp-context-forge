# -*- coding: utf-8 -*-
# ruff: noqa: D102,D107
"""IBM Code Engine runtime backend implementation."""

# Standard
import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

# First-Party
from mcpgateway.runtimes.base import RuntimeBackend, RuntimeBackendCapabilities, RuntimeBackendDeployRequest, RuntimeBackendDeployResult, RuntimeBackendError, RuntimeBackendStatus

logger = logging.getLogger(__name__)


class IBMCodeEngineRuntimeBackend(RuntimeBackend):  # pragma: no cover - exercised in environment-dependent integration flows.
    """IBM Code Engine runtime backend using ibmcloud CLI."""

    def __init__(
        self,
        ibmcloud_binary: str = "ibmcloud",
        project_name: Optional[str] = None,
        region: Optional[str] = None,
        registry_secret: Optional[str] = None,
    ):
        self.ibmcloud_binary = ibmcloud_binary
        self.project_name = project_name
        self.region = region
        self.registry_secret = registry_secret

    def get_capabilities(self) -> RuntimeBackendCapabilities:
        return RuntimeBackendCapabilities(
            backend="ibm_code_engine",
            supports_compose=False,
            supports_github_build=True,
            supports_allowed_hosts=False,
            supports_readonly_fs=False,
            supports_custom_capabilities=False,
            supports_pids_limit=False,
            supports_network_egress_toggle=True,
            max_cpu=12.0,
            max_memory_gb=48.0,
            max_timeout_seconds=600,
            notes=[
                "Compose is not supported on IBM Code Engine.",
                "Guardrails are partially enforced by CE platform controls.",
                "Network allowlist by host is not supported (on/off style controls only).",
            ],
        )

    async def deploy(self, request: RuntimeBackendDeployRequest) -> RuntimeBackendDeployResult:
        await self._ensure_project_selected()

        source = request.source
        source_type = request.source_type
        if source_type == "compose":
            raise RuntimeBackendError("IBM Code Engine backend does not support compose deployments")

        image = source.get("image")
        logs: List[str] = []

        if source_type == "github" and not image:
            image = await self._build_from_github(request)
            logs.append(f"Built image for GitHub source: {image}")

        if not image:
            raise RuntimeBackendError("IBM Code Engine deployment requires image, or GitHub source with registry build target")

        app_name = self._app_name(request.runtime_id, request.name)
        resources = request.resources or {}
        cpu = str(resources.get("cpu") or "0.25")
        memory = str(resources.get("memory") or "256M")
        min_scale = str(resources.get("min_scale") if resources.get("min_scale") is not None else 0)
        max_scale = str(resources.get("max_scale") if resources.get("max_scale") is not None else 10)

        env_pairs = request.environment or {}
        env_args: List[str] = []
        for key, value in env_pairs.items():
            env_args.extend(["--env", f"{key}={value}"])

        exists = await self._application_exists(app_name)
        base_cmd = [
            self.ibmcloud_binary,
            "ce",
            "application",
            "update" if exists else "create",
            "--name",
            app_name,
            "--image",
            image,
            "--cpu",
            cpu,
            "--memory",
            memory,
            "--min-scale",
            min_scale,
            "--max-scale",
            max_scale,
        ]
        if not exists:
            base_cmd.extend(["--port", str(source.get("port", 8080))])
        if self.registry_secret:
            base_cmd.extend(["--registry-secret", self.registry_secret])
        if env_args:
            base_cmd.extend(env_args)

        await self._run(base_cmd, timeout=900)
        app_status = await self._get_application_json(app_name)
        endpoint = self._extract_endpoint(app_status)

        return RuntimeBackendDeployResult(
            status="running",
            runtime_ref=app_name,
            endpoint_url=endpoint,
            image=image,
            logs=logs,
            backend_response={"deployment_mode": "application", "application": app_name, "application_status": app_status},
        )

    async def get_status(self, runtime_ref: str, metadata: Optional[Dict[str, Any]] = None) -> RuntimeBackendStatus:
        await self._ensure_project_selected()
        info = await self._get_application_json(runtime_ref)
        status_value = str(info.get("status") or info.get("state") or info.get("conditions", [{}])[0].get("status", "")).lower()
        mapped = "running" if status_value in {"ready", "true", "running", "active"} else "stopped" if status_value in {"stopped", "inactive"} else "error"
        return RuntimeBackendStatus(status=mapped, endpoint_url=self._extract_endpoint(info), backend_response=info)

    async def start(self, runtime_ref: str, metadata: Optional[Dict[str, Any]] = None) -> RuntimeBackendStatus:
        await self._ensure_project_selected()
        await self._run([self.ibmcloud_binary, "ce", "application", "update", "--name", runtime_ref, "--min-scale", "1"], timeout=300)
        return await self.get_status(runtime_ref)

    async def stop(self, runtime_ref: str, metadata: Optional[Dict[str, Any]] = None) -> RuntimeBackendStatus:
        await self._ensure_project_selected()
        await self._run([self.ibmcloud_binary, "ce", "application", "update", "--name", runtime_ref, "--min-scale", "0"], timeout=300)
        status = await self.get_status(runtime_ref)
        # CE scales down asynchronously; expose explicit stopped semantic to runtime API.
        return RuntimeBackendStatus(status="stopped", endpoint_url=status.endpoint_url, backend_response=status.backend_response)

    async def delete(self, runtime_ref: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        await self._ensure_project_selected()
        await self._run([self.ibmcloud_binary, "ce", "application", "delete", "--name", runtime_ref, "-f"], timeout=300)

    async def logs(self, runtime_ref: str, metadata: Optional[Dict[str, Any]] = None, tail: int = 200) -> List[str]:
        await self._ensure_project_selected()
        out = await self._run([self.ibmcloud_binary, "ce", "application", "logs", "--name", runtime_ref, "--tail", str(tail)], timeout=240)
        return out.splitlines()

    async def _build_from_github(self, request: RuntimeBackendDeployRequest) -> str:
        """Build image via CE build configuration from GitHub source.

        Args:
            request: Backend deployment request containing GitHub build details.

        Returns:
            str: Built image reference.

        Raises:
            RuntimeBackendError: If build configuration is missing or build fails.
        """
        source = request.source
        repo = source.get("repo")
        branch = source.get("branch", "main")
        dockerfile = source.get("dockerfile", "Dockerfile")
        registry = source.get("registry")
        if not repo:
            raise RuntimeBackendError("GitHub source is missing repo")
        if not registry:
            raise RuntimeBackendError("GitHub source on CE requires 'registry' image target")

        repo_url = repo if repo.startswith(("http://", "https://", "git@")) else f"https://github.com/{repo}"
        clean_name = re.sub(r"[^a-zA-Z0-9-]", "-", request.name.lower()).strip("-")[:35]
        build_name = f"{clean_name}-{request.runtime_id[:8]}-build"
        buildrun_name = f"{build_name}-run"
        target_image = f"{registry.rstrip('/')}:{request.runtime_id[:12]}"

        # Reconcile build config (create or update).
        if await self._build_exists(build_name):
            await self._run(
                [
                    self.ibmcloud_binary,
                    "ce",
                    "build",
                    "update",
                    "--name",
                    build_name,
                    "--source",
                    f"{repo_url}#{branch}",
                    "--strategy",
                    "dockerfile",
                    "--dockerfile",
                    dockerfile,
                    "--image",
                    target_image,
                ],
                timeout=600,
            )
        else:
            await self._run(
                [
                    self.ibmcloud_binary,
                    "ce",
                    "build",
                    "create",
                    "--name",
                    build_name,
                    "--source",
                    f"{repo_url}#{branch}",
                    "--strategy",
                    "dockerfile",
                    "--dockerfile",
                    dockerfile,
                    "--image",
                    target_image,
                ],
                timeout=600,
            )

        await self._run([self.ibmcloud_binary, "ce", "buildrun", "submit", "--name", buildrun_name, "--build", build_name], timeout=600)
        await self._wait_for_buildrun(buildrun_name, timeout_seconds=3600)
        return target_image

    async def _wait_for_buildrun(self, buildrun_name: str, timeout_seconds: int = 3600) -> None:
        """Poll buildrun status until completion.

        Args:
            buildrun_name: Code Engine buildrun name.
            timeout_seconds: Maximum wait time in seconds.

        Raises:
            RuntimeBackendError: If buildrun fails or times out.
        """
        waited = 0
        interval = 10
        while waited <= timeout_seconds:
            out = await self._run([self.ibmcloud_binary, "ce", "buildrun", "get", "--name", buildrun_name, "--output", "json"], timeout=120)
            try:
                payload = json.loads(out)
            except json.JSONDecodeError:
                payload = {}

            status_value = str(payload.get("status") or payload.get("state") or "").lower()
            if status_value in {"succeeded", "success", "ready", "complete"}:
                return
            if status_value in {"failed", "error"}:
                raise RuntimeBackendError(f"Code Engine buildrun failed: {status_value}")

            await asyncio.sleep(interval)
            waited += interval

        raise RuntimeBackendError(f"Timed out waiting for buildrun {buildrun_name}")

    async def _application_exists(self, app_name: str) -> bool:
        try:
            await self._run([self.ibmcloud_binary, "ce", "application", "get", "--name", app_name], timeout=120)
            return True
        except RuntimeBackendError:
            return False

    async def _build_exists(self, build_name: str) -> bool:
        try:
            await self._run([self.ibmcloud_binary, "ce", "build", "get", "--name", build_name], timeout=120)
            return True
        except RuntimeBackendError:
            return False

    async def _get_application_json(self, app_name: str) -> Dict[str, Any]:
        out = await self._run([self.ibmcloud_binary, "ce", "application", "get", "--name", app_name, "--output", "json"], timeout=120)
        try:
            payload = json.loads(out)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass
        return {"raw": out}

    @staticmethod
    def _extract_endpoint(payload: Dict[str, Any]) -> Optional[str]:
        direct_keys = ["endpoint", "url", "publicUrl", "public_url"]
        for key in direct_keys:
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        if isinstance(payload.get("status"), dict):
            for key in direct_keys:
                value = payload["status"].get(key)
                if isinstance(value, str) and value:
                    return value
        return None

    @staticmethod
    def _app_name(runtime_id: str, name: str) -> str:
        clean_name = re.sub(r"[^a-zA-Z0-9-]", "-", name.lower()).strip("-")
        return f"{clean_name[:40]}-{runtime_id[:8]}"

    async def _ensure_project_selected(self) -> None:
        if self.project_name:
            await self._run([self.ibmcloud_binary, "ce", "project", "select", "--name", self.project_name], timeout=120)

    async def _run(self, cmd: List[str], timeout: int = 300) -> str:
        logger.debug("Code Engine command: %s", " ".join(cmd))
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise RuntimeBackendError(f"Command timed out ({timeout}s): {' '.join(cmd)}") from exc

        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            raise RuntimeBackendError(f"Command failed ({process.returncode}): {' '.join(cmd)}\n{err or out}")
        return out
