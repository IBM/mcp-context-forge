# -*- coding: utf-8 -*-
# ruff: noqa: D102,D107
"""Docker runtime backend implementation."""

# Standard
import asyncio
import json
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Dict, List, Optional

# First-Party
from mcpgateway.runtimes.base import RuntimeBackend, RuntimeBackendCapabilities, RuntimeBackendDeployRequest, RuntimeBackendDeployResult, RuntimeBackendError, RuntimeBackendStatus

logger = logging.getLogger(__name__)


class DockerRuntimeBackend(RuntimeBackend):  # pragma: no cover - exercised in environment-dependent integration flows.
    """Docker-based runtime backend."""

    def __init__(
        self,
        docker_binary: str = "docker",
        default_network: Optional[str] = None,
        allowed_registries: Optional[List[str]] = None,
        docker_socket: Optional[str] = None,
    ):
        self.docker_binary = docker_binary
        self.default_network = default_network
        self.allowed_registries = allowed_registries or []
        self.docker_socket = docker_socket

    def get_capabilities(self) -> RuntimeBackendCapabilities:
        return RuntimeBackendCapabilities(
            backend="docker",
            supports_compose=True,
            supports_github_build=True,
            supports_allowed_hosts=True,
            supports_readonly_fs=True,
            supports_custom_capabilities=True,
            supports_pids_limit=True,
            supports_network_egress_toggle=True,
            notes=["Docker backend supports docker image, github build, and compose sources."],
        )

    async def deploy(self, request: RuntimeBackendDeployRequest) -> RuntimeBackendDeployResult:
        """Deploy a runtime as a Docker container or compose project.

        Args:
            request: Runtime deployment request with source, resources, and guardrails.

        Returns:
            RuntimeBackendDeployResult: Backend deployment metadata and endpoint details.

        Raises:
            RuntimeBackendError: If source data is invalid or Docker commands fail.
        """
        source_type = request.source_type
        if source_type == "compose":
            return await self._deploy_compose(request)

        image = request.source.get("image")
        logs: List[str] = []
        warnings: List[Dict[str, Any]] = []

        if source_type == "github":
            image, build_logs = await self._build_image_from_github(request)
            logs.extend(build_logs)

        if not image:
            raise RuntimeBackendError("Docker deployment requires an image")
        if not self._is_registry_allowed(image):
            raise RuntimeBackendError(f"Image registry is not allowlisted: {image}")

        container_name = self._container_name(request.runtime_id, request.name)
        cmd = [self.docker_binary, "run", "-d", "--name", container_name, "--label", f"mcpgateway.runtime_id={request.runtime_id}"]

        resources = request.resources or {}
        if resources.get("cpu"):
            cmd.extend(["--cpus", str(resources["cpu"])])
        if resources.get("memory"):
            cmd.extend(["--memory", str(resources["memory"])])

        guardrails = request.guardrails or {}
        network = guardrails.get("network", {})
        filesystem = guardrails.get("filesystem", {})
        caps = guardrails.get("capabilities", {})
        selected_network: Optional[str] = None

        # If egress is disabled, isolate network entirely unless explicit ports are needed.
        if network.get("egress_allowed") is False:
            selected_network = "none"
            cmd.extend(["--network", "none"])
        elif self.default_network:
            selected_network = self.default_network
            cmd.extend(["--network", self.default_network])

        if filesystem.get("read_only_root"):
            cmd.append("--read-only")

        if caps.get("drop_all", True):
            cmd.extend(["--cap-drop", "ALL"])
        for cap in caps.get("add", []):
            cmd.extend(["--cap-add", str(cap)])

        max_pids = resources.get("max_pids")
        if max_pids:
            cmd.extend(["--pids-limit", str(max_pids)])

        seccomp = guardrails.get("seccomp")
        if seccomp:
            seccomp_value = str(seccomp).strip()
            if seccomp_value.lower() not in {"runtime/default", "default", "docker/default"}:
                cmd.extend(["--security-opt", f"seccomp={seccomp_value}"])
            else:
                warnings.append(
                    {
                        "field": "guardrails.seccomp",
                        "message": f"Ignoring seccomp profile '{seccomp_value}' and using Docker default profile",
                        "backend": "docker",
                    }
                )
        apparmor = guardrails.get("apparmor")
        if apparmor:
            apparmor_value = str(apparmor).strip()
            if self._apparmor_profile_available(apparmor_value):
                cmd.extend(["--security-opt", f"apparmor={apparmor_value}"])
            else:
                warnings.append(
                    {
                        "field": "guardrails.apparmor",
                        "message": f"Ignoring unavailable AppArmor profile '{apparmor_value}' and using Docker default profile",
                        "backend": "docker",
                    }
                )

        for key, value in (request.environment or {}).items():
            cmd.extend(["-e", f"{key}={value}"])

        cmd.append(image)
        run_cmd = request.source.get("command")
        if run_cmd:
            if isinstance(run_cmd, list):
                cmd.extend([str(arg) for arg in run_cmd])
            else:
                cmd.append(str(run_cmd))

        try:
            stdout = await self._run(cmd, timeout=900)
        except RuntimeBackendError as exc:
            message = str(exc).lower()
            if selected_network and selected_network != "none" and "network" in message and "not found" in message:
                cmd_without_network = self._without_network_option(cmd)
                container_name = self._container_name_from_run_command(cmd)
                if container_name:
                    try:
                        await self._run([self.docker_binary, "rm", "-f", container_name], timeout=120)
                    except RuntimeBackendError:
                        logger.debug(
                            "Ignoring cleanup failure for retry container %s",
                            container_name,
                        )
                warnings.append(
                    {
                        "field": "guardrails.network",
                        "message": f"Docker network '{selected_network}' not found. Retrying deployment without explicit network.",
                        "backend": "docker",
                    }
                )
                stdout = await self._run(cmd_without_network, timeout=900)
            else:
                raise
        runtime_ref = stdout.strip().splitlines()[-1]
        endpoint_url = await self._resolve_container_endpoint(runtime_ref)

        return RuntimeBackendDeployResult(
            status="running",
            runtime_ref=runtime_ref,
            endpoint_url=endpoint_url,
            image=image,
            logs=logs,
            warnings=warnings,
            backend_response={"deployment_mode": "container", "container_name": container_name},
        )

    async def get_status(self, runtime_ref: str, metadata: Optional[Dict[str, Any]] = None) -> RuntimeBackendStatus:
        metadata = metadata or {}
        deployment_mode = metadata.get("deployment_mode", "container")
        if deployment_mode == "compose":
            project_name = metadata.get("compose_project")
            compose_path = metadata.get("compose_file_path")
            if project_name and compose_path:
                cmd = self._compose_cmd(compose_path, project_name, ["ps", "--status", "running", "--format", "json"])
                try:
                    out = await self._run(cmd, timeout=60)
                    running = False
                    if out.strip():
                        try:
                            payload = json.loads(out)
                            if isinstance(payload, list):
                                running = len(payload) > 0
                            elif isinstance(payload, dict):
                                running = bool(payload)
                            else:
                                running = True
                        except json.JSONDecodeError:
                            running = True
                    return RuntimeBackendStatus(status="running" if running else "stopped", backend_response={"compose_status_json": out})
                except RuntimeBackendError:
                    return RuntimeBackendStatus(status="error", backend_response={"compose_project": project_name})

        status = await self._run([self.docker_binary, "inspect", "-f", "{{.State.Status}}", runtime_ref], timeout=60)
        normalized = status.strip().lower()
        mapped = "running" if normalized == "running" else "stopped" if normalized in {"created", "restarting", "paused", "exited"} else "error"
        endpoint_url = await self._resolve_container_endpoint(runtime_ref)
        return RuntimeBackendStatus(status=mapped, endpoint_url=endpoint_url, backend_response={"raw_status": normalized})

    async def start(self, runtime_ref: str, metadata: Optional[Dict[str, Any]] = None) -> RuntimeBackendStatus:
        """Start a stopped runtime deployment.

        Args:
            runtime_ref: Runtime identifier (container id/name or compose main service ref).
            metadata: Optional backend metadata with deployment mode information.

        Returns:
            RuntimeBackendStatus: Updated runtime status after start operation.
        """
        metadata = metadata or {}
        if metadata.get("deployment_mode") == "compose":
            project_name = metadata.get("compose_project")
            compose_path = metadata.get("compose_file_path")
            if project_name and compose_path:
                await self._run(self._compose_cmd(compose_path, project_name, ["start"]), timeout=120)
                return RuntimeBackendStatus(status="running", backend_response={"compose_project": project_name})
        await self._run([self.docker_binary, "start", runtime_ref], timeout=120)
        return RuntimeBackendStatus(status="running")

    async def stop(self, runtime_ref: str, metadata: Optional[Dict[str, Any]] = None) -> RuntimeBackendStatus:
        """Stop a running runtime deployment.

        Args:
            runtime_ref: Runtime identifier (container id/name or compose main service ref).
            metadata: Optional backend metadata with deployment mode information.

        Returns:
            RuntimeBackendStatus: Updated runtime status after stop operation.
        """
        metadata = metadata or {}
        if metadata.get("deployment_mode") == "compose":
            project_name = metadata.get("compose_project")
            compose_path = metadata.get("compose_file_path")
            if project_name and compose_path:
                await self._run(self._compose_cmd(compose_path, project_name, ["stop"]), timeout=120)
                return RuntimeBackendStatus(status="stopped", backend_response={"compose_project": project_name})
        await self._run([self.docker_binary, "stop", runtime_ref], timeout=120)
        return RuntimeBackendStatus(status="stopped")

    async def delete(self, runtime_ref: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Delete runtime resources for container or compose deployment.

        Args:
            runtime_ref: Runtime identifier (container id/name or compose main service ref).
            metadata: Optional backend metadata with deployment mode information.
        """
        metadata = metadata or {}
        if metadata.get("deployment_mode") == "compose":
            project_name = metadata.get("compose_project")
            compose_path = metadata.get("compose_file_path")
            if project_name and compose_path:
                await self._run(self._compose_cmd(compose_path, project_name, ["down", "--remove-orphans"]), timeout=180)
                return
        await self._run([self.docker_binary, "rm", "-f", runtime_ref], timeout=120)

    async def logs(self, runtime_ref: str, metadata: Optional[Dict[str, Any]] = None, tail: int = 200) -> List[str]:
        """Fetch runtime logs from Docker container or compose project.

        Args:
            runtime_ref: Runtime identifier (container id/name or compose main service ref).
            metadata: Optional backend metadata with deployment mode information.
            tail: Maximum number of log lines to request from the backend.

        Returns:
            List[str]: Log lines returned by Docker.
        """
        metadata = metadata or {}
        if metadata.get("deployment_mode") == "compose":
            project_name = metadata.get("compose_project")
            compose_path = metadata.get("compose_file_path")
            if project_name and compose_path:
                out = await self._run(self._compose_cmd(compose_path, project_name, ["logs", "--tail", str(tail)]), timeout=120)
                return out.splitlines()

        out = await self._run([self.docker_binary, "logs", "--tail", str(tail), runtime_ref], timeout=120)
        return out.splitlines()

    async def _build_image_from_github(self, request: RuntimeBackendDeployRequest) -> tuple[str, List[str]]:
        """Clone and build image from GitHub source.

        Args:
            request: Backend deployment request containing GitHub build details.

        Returns:
            tuple[str, List[str]]: Built image reference and build log messages.

        Raises:
            RuntimeBackendError: If repository or build configuration is invalid.
        """
        source = request.source
        repo = source.get("repo")
        branch = source.get("branch", "main")
        dockerfile = source.get("dockerfile", "Dockerfile")
        build_args = source.get("build_args", {}) or {}
        push_to_registry = bool(source.get("push_to_registry", False))
        registry = source.get("registry")

        if not repo:
            raise RuntimeBackendError("GitHub source is missing 'repo'")

        repo_url = repo if repo.startswith(("http://", "https://", "git@")) else f"https://github.com/{repo}.git"
        tag_base = re.sub(r"[^a-zA-Z0-9_.-]", "-", request.name.lower())[:64]
        local_tag = f"mcpgateway-runtime/{tag_base}:{request.runtime_id[:12]}"
        logs: List[str] = []

        with tempfile.TemporaryDirectory(prefix=f"mcpruntime-{request.runtime_id[:8]}-") as temp_dir:
            clone_dir = Path(temp_dir) / "src"
            await self._run(["git", "clone", "--depth", "1", "--branch", str(branch), repo_url, str(clone_dir)], timeout=600)
            logs.append(f"Cloned repository {repo} ({branch})")

            cmd = [self.docker_binary, "build", "-t", local_tag, "-f", dockerfile]
            for key, value in build_args.items():
                cmd.extend(["--build-arg", f"{key}={value}"])
            cmd.append(str(clone_dir))
            await self._run(cmd, timeout=1800)
            logs.append(f"Built image {local_tag}")

            final_tag = local_tag
            if push_to_registry and registry:
                registry = registry.rstrip("/")
                if "/" not in registry:
                    raise RuntimeBackendError("Registry path must include a namespace/repository")
                final_tag = f"{registry}:{request.runtime_id[:12]}"
                await self._run([self.docker_binary, "tag", local_tag, final_tag], timeout=120)
                await self._run([self.docker_binary, "push", final_tag], timeout=1800)
                logs.append(f"Pushed image {final_tag}")

        return final_tag, logs

    async def _deploy_compose(self, request: RuntimeBackendDeployRequest) -> RuntimeBackendDeployResult:
        """Deploy a runtime from a compose file and return runtime metadata.

        Args:
            request: Runtime deployment request containing compose source details.

        Returns:
            RuntimeBackendDeployResult: Runtime deployment metadata for compose mode.

        Raises:
            RuntimeBackendError: If compose source configuration is missing or invalid.
        """
        source = request.source
        compose_content = source.get("compose_file")
        main_service = source.get("main_service")
        if not compose_content or not main_service:
            raise RuntimeBackendError("Compose deployment requires compose_file and main_service")

        runtime_dir = Path(tempfile.gettempdir()) / "mcpgateway-runtime" / request.runtime_id
        runtime_dir.mkdir(parents=True, exist_ok=True)
        compose_path = runtime_dir / "docker-compose.runtime.yaml"

        if "\n" in str(compose_content) or "services:" in str(compose_content):
            compose_path.write_text(str(compose_content), encoding="utf-8")
        else:
            source_path = Path(str(compose_content))
            if not source_path.exists():
                raise RuntimeBackendError(f"Compose file not found: {source_path}")
            shutil.copy2(source_path, compose_path)

        project_name = f"mcpruntime-{request.runtime_id[:12]}"
        await self._run(self._compose_cmd(str(compose_path), project_name, ["up", "-d"]), timeout=900)
        container_id = (await self._run(self._compose_cmd(str(compose_path), project_name, ["ps", "-q", str(main_service)]), timeout=120)).strip()
        if not container_id:
            container_id = f"{project_name}:{main_service}"

        endpoint_url = await self._resolve_container_endpoint(container_id) if ":" not in container_id else None
        return RuntimeBackendDeployResult(
            status="running",
            runtime_ref=container_id,
            endpoint_url=endpoint_url,
            logs=[f"Started compose project {project_name}"],
            backend_response={
                "deployment_mode": "compose",
                "compose_project": project_name,
                "compose_file_path": str(compose_path),
                "main_service": main_service,
            },
        )

    def _is_registry_allowed(self, image: str) -> bool:
        """Validate whether an image registry is included in the allowlist.

        Args:
            image: Docker image reference to validate.

        Returns:
            bool: True when the registry is allowed, otherwise False.
        """
        if not self.allowed_registries:
            return True

        registry = self._extract_registry(image)
        for allowed in self.allowed_registries:
            allowed_clean = allowed.strip().lower()
            if not allowed_clean:
                continue
            if registry == allowed_clean or image.lower().startswith(f"{allowed_clean}/"):
                return True
        return False

    @staticmethod
    def _extract_registry(image: str) -> str:
        """Extract normalized registry hostname from a Docker image reference.

        Args:
            image: Docker image reference.

        Returns:
            str: Registry hostname or the default Docker Hub registry.
        """
        first = image.split("/", 1)[0].lower()
        if "." in first or ":" in first or first == "localhost":
            return first
        return "docker.io"

    @staticmethod
    def _container_name(runtime_id: str, name: str) -> str:
        """Create a deterministic Docker container name for a runtime.

        Args:
            runtime_id: Runtime deployment identifier.
            name: Runtime display name.

        Returns:
            str: Docker-safe container name with runtime id suffix.
        """
        normalized = re.sub(r"[^a-zA-Z0-9_.-]", "-", name.lower()).strip("-")
        return f"mcpruntime-{normalized[:40]}-{runtime_id[:8]}"

    def _compose_cmd(self, compose_file: str, project_name: str, args: List[str]) -> List[str]:
        """Build a docker compose command for the runtime project.

        Args:
            compose_file: Path to the compose file.
            project_name: Compose project name.
            args: Additional compose subcommand arguments.

        Returns:
            List[str]: Full docker compose command argument list.
        """
        return [self.docker_binary, "compose", "-p", project_name, "-f", compose_file, *args]

    @staticmethod
    def _without_network_option(cmd: List[str]) -> List[str]:
        """Return a command list with the ``--network`` option removed.

        Args:
            cmd: Docker command arguments.

        Returns:
            List[str]: Command arguments without explicit network selection.
        """
        result: List[str] = []
        skip_next = False
        for index, token in enumerate(cmd):
            if skip_next:
                skip_next = False
                continue
            # "--network" is a Docker CLI flag, not a secret.
            if token == "--network" and index + 1 < len(cmd):  # nosec B105
                skip_next = True
                continue
            result.append(token)
        return result

    @staticmethod
    def _container_name_from_run_command(cmd: List[str]) -> Optional[str]:
        """Extract container name from a ``docker run`` command argument list.

        Args:
            cmd: Docker command arguments.

        Returns:
            Optional[str]: Configured container name when present.
        """
        for index, token in enumerate(cmd):
            # "--name" is a Docker CLI flag, not a secret.
            if token == "--name" and index + 1 < len(cmd):  # nosec B105
                return str(cmd[index + 1])
        return None

    @staticmethod
    def _apparmor_profile_available(profile_name: str) -> bool:
        """Check whether an AppArmor profile is available on the host.

        Args:
            profile_name: AppArmor profile to validate.

        Returns:
            bool: True when the profile exists and is loaded, else False.
        """
        if not profile_name:
            return False
        profiles_path = Path("/sys/kernel/security/apparmor/profiles")
        try:
            if not profiles_path.exists():
                return False
            entries = profiles_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return False
        prefix = f"{profile_name} "
        return any(entry.startswith(prefix) for entry in entries)

    async def _resolve_container_endpoint(self, runtime_ref: str) -> Optional[str]:
        """Resolve an HTTP endpoint URL from Docker port mappings when available.

        Args:
            runtime_ref: Container identifier to inspect.

        Returns:
            Optional[str]: Local endpoint URL if a host port is discovered, else None.
        """
        try:
            out = await self._run([self.docker_binary, "port", runtime_ref], timeout=30)
            for line in out.splitlines():
                if "->" not in line:
                    continue
                right = line.split("->", 1)[1].strip()
                host_port = right.split(":")[-1]
                if host_port.isdigit():
                    return f"http://127.0.0.1:{host_port}"
        except RuntimeBackendError:
            return None
        return None

    async def _run(self, cmd: List[str], timeout: int = 300) -> str:
        """Run a Docker CLI command and return stdout or raise on failure.

        Args:
            cmd: Command tokens to execute.
            timeout: Maximum command runtime in seconds.

        Returns:
            str: Decoded stdout from the command.

        Raises:
            RuntimeBackendError: If command times out or exits with non-zero status.
        """
        logger.debug("Docker runtime command: %s", " ".join(cmd))
        subprocess_env = None
        if self.docker_socket and not os.environ.get("DOCKER_HOST"):
            subprocess_env = dict(os.environ)
            subprocess_env["DOCKER_HOST"] = f"unix://{self.docker_socket}"
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=subprocess_env,
            )
        except FileNotFoundError as exc:
            raise RuntimeBackendError(f"Command not found: {cmd[0]}. Ensure runtime backend dependencies are installed in the gateway container.") from exc
        except PermissionError as exc:
            raise RuntimeBackendError(f"Permission denied while executing: {' '.join(cmd)}") from exc
        except OSError as exc:
            raise RuntimeBackendError(f"Failed to start command: {' '.join(cmd)} ({exc})") from exc
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
