#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docker Compose Generator for Infrastructure Profiles

Generates docker-compose.yml files from infrastructure profile configurations.
Supports PostgreSQL version switching, instance scaling, and resource tuning.
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, Any
import yaml


DOCKER_COMPOSE_TEMPLATE = """version: '3.8'

services:
  postgres:
    image: postgres:{postgres_version}
    container_name: postgres_perf
    environment:
      POSTGRES_DB: mcpgateway
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    command:
      - "postgres"
{postgres_config_commands}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

{redis_service}

{gateway_services}

{load_balancer}

volumes:
  postgres_data:
{redis_volume}
"""

GATEWAY_SERVICE_TEMPLATE = """  gateway{instance_suffix}:
    build:
      context: .
      dockerfile: Containerfile.lite
    container_name: gateway{instance_suffix}
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@postgres:5432/mcpgateway
{redis_url}
      - HOST=0.0.0.0
      - PORT=4444
      - LOG_LEVEL=INFO
      - GUNICORN_WORKERS={gunicorn_workers}
      - GUNICORN_THREADS={gunicorn_threads}
      - GUNICORN_TIMEOUT={gunicorn_timeout}
      - DB_POOL_SIZE={db_pool_size}
      - DB_POOL_MAX_OVERFLOW={db_pool_max_overflow}
      - DB_POOL_TIMEOUT={db_pool_timeout}
{redis_pool}
      - JWT_SECRET_KEY=my-test-key
      - MCPGATEWAY_ADMIN_API_ENABLED=true
      - MCPGATEWAY_UI_ENABLED=true
    ports:
      - "{port_mapping}:4444"
    depends_on:
      postgres:
        condition: service_healthy
{redis_depends}
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:4444/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
"""

REDIS_SERVICE = """  redis:
    image: redis:7-alpine
    container_name: redis_perf
    ports:
      - "6379:6379"
    command: redis-server{redis_config}
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
"""

NGINX_LOAD_BALANCER = """  nginx:
    image: nginx:alpine
    container_name: nginx_lb
    ports:
      - "8000:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
{nginx_depends}
"""


class DockerComposeGenerator:
    """Generate docker-compose.yml from infrastructure and server profiles"""

    def __init__(self, config_file: Path):
        self.config_file = config_file
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        with open(self.config_file) as f:
            return yaml.safe_load(f)

    def generate(self, infrastructure_profile: str, server_profile: str = "standard", postgres_version: str = None, instances: int = None, output_file: Path = None) -> str:
        """
        Generate docker-compose.yml content

        Args:
            infrastructure_profile: Infrastructure profile name
            server_profile: Server profile name
            postgres_version: Override PostgreSQL version
            instances: Override number of gateway instances
            output_file: Path to write output (if None, returns string)

        Returns:
            Generated docker-compose.yml content
        """
        # Get profiles
        infra = self.config.get("infrastructure_profiles", {}).get(infrastructure_profile)
        if not infra:
            raise ValueError(f"Infrastructure profile '{infrastructure_profile}' not found")

        server = self.config.get("server_profiles", {}).get(server_profile)
        if not server:
            raise ValueError(f"Server profile '{server_profile}' not found")

        # Override values if provided
        pg_version = postgres_version or infra.get("postgres_version", "17-alpine")
        num_instances = instances or infra.get("gateway_instances", 1)
        redis_enabled = infra.get("redis_enabled", False)

        # Generate PostgreSQL configuration commands
        postgres_commands = self._generate_postgres_config(infra)

        # Generate Redis service
        redis_service = ""
        redis_volume = ""
        if redis_enabled:
            redis_config = self._generate_redis_config(infra)
            redis_service = REDIS_SERVICE.format(redis_config=redis_config)
            redis_volume = "  redis_data:"

        # Generate gateway services
        gateway_services = self._generate_gateway_services(num_instances, server, redis_enabled)

        # Generate load balancer if multiple instances
        load_balancer = ""
        if num_instances > 1:
            load_balancer = self._generate_load_balancer(num_instances)
            # Also generate nginx.conf
            self._generate_nginx_config(num_instances, output_file)

        # Assemble final docker-compose
        compose_content = DOCKER_COMPOSE_TEMPLATE.format(
            postgres_version=pg_version,
            postgres_config_commands=postgres_commands,
            redis_service=redis_service,
            gateway_services=gateway_services,
            load_balancer=load_balancer,
            redis_volume=redis_volume,
        )

        # Write to file if specified
        if output_file:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, "w") as f:
                f.write(compose_content)
            print(f"✅ Generated: {output_file}")

        return compose_content

    def _generate_postgres_config(self, infra: Dict) -> str:
        """Generate PostgreSQL configuration command arguments"""
        commands = []

        pg_configs = {
            "shared_buffers": "postgres_shared_buffers",
            "effective_cache_size": "postgres_effective_cache_size",
            "max_connections": "postgres_max_connections",
            "work_mem": "postgres_work_mem",
            "maintenance_work_mem": "postgres_maintenance_work_mem",
            "random_page_cost": "postgres_random_page_cost",
            "effective_io_concurrency": "postgres_effective_io_concurrency",
        }

        for pg_param, config_key in pg_configs.items():
            if config_key in infra:
                value = infra[config_key]
                commands.append(f'      - "-c"\n      - "{pg_param}={value}"')

        return "\n".join(commands) if commands else ""

    def _generate_redis_config(self, infra: Dict) -> str:
        """Generate Redis configuration arguments"""
        config_parts = []

        if "redis_maxmemory" in infra:
            config_parts.append(f" --maxmemory {infra['redis_maxmemory']}")

        if "redis_maxmemory_policy" in infra:
            config_parts.append(f" --maxmemory-policy {infra['redis_maxmemory_policy']}")

        return "".join(config_parts)

    def _generate_gateway_services(self, num_instances: int, server_profile: Dict, redis_enabled: bool) -> str:
        """Generate gateway service definitions"""
        services = []

        for i in range(num_instances):
            instance_suffix = f"_{i + 1}" if num_instances > 1 else ""
            port_mapping = "4444" if num_instances == 1 else f"{4444 + i}"

            redis_url = ""
            redis_pool = ""
            redis_depends = ""

            if redis_enabled:
                redis_url = "      - REDIS_URL=redis://redis:6379"
                redis_pool = f"      - REDIS_POOL_SIZE={server_profile.get('redis_pool_size', 10)}"
                redis_depends = """      redis:
        condition: service_healthy"""

            service = GATEWAY_SERVICE_TEMPLATE.format(
                instance_suffix=instance_suffix,
                redis_url=redis_url,
                gunicorn_workers=server_profile.get("gunicorn_workers", 4),
                gunicorn_threads=server_profile.get("gunicorn_threads", 4),
                gunicorn_timeout=server_profile.get("gunicorn_timeout", 120),
                db_pool_size=server_profile.get("db_pool_size", 20),
                db_pool_max_overflow=server_profile.get("db_pool_max_overflow", 40),
                db_pool_timeout=server_profile.get("db_pool_timeout", 30),
                redis_pool=redis_pool,
                port_mapping=port_mapping,
                redis_depends=redis_depends,
            )

            services.append(service)

        return "\n".join(services)

    def _generate_load_balancer(self, num_instances: int) -> str:
        """Generate nginx load balancer service"""
        depends = []
        for i in range(num_instances):
            suffix = f"_{i + 1}"
            depends.append(f"      - gateway{suffix}")

        return NGINX_LOAD_BALANCER.format(nginx_depends="\n".join(depends))

    def _generate_nginx_config(self, num_instances: int, output_file: Path):
        """Generate nginx.conf for load balancing"""
        if not output_file:
            return

        upstreams = []
        for i in range(num_instances):
            suffix = f"_{i + 1}"
            upstreams.append(f"        server gateway{suffix}:4444 max_fails=3 fail_timeout=30s;")

        nginx_conf = f"""events {{
    worker_connections 1024;
}}

http {{
    upstream gateway_backend {{
{chr(10).join(upstreams)}
    }}

    server {{
        listen 80;

        location / {{
            proxy_pass http://gateway_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Timeouts
            proxy_connect_timeout 60s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;

            # Health checks
            proxy_next_upstream error timeout invalid_header http_500 http_502 http_503;
        }}

        location /health {{
            access_log off;
            proxy_pass http://gateway_backend/health;
        }}
    }}
}}
"""

        nginx_file = output_file.parent / "nginx.conf"
        with open(nginx_file, "w") as f:
            f.write(nginx_conf)
        print(f"✅ Generated: {nginx_file}")


def main():
    parser = argparse.ArgumentParser(description="Generate docker-compose.yml from infrastructure profiles")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"), help="Configuration file path")
    parser.add_argument("--infrastructure", required=True, help="Infrastructure profile name")
    parser.add_argument("--server-profile", default="standard", help="Server profile name")
    parser.add_argument("--postgres-version", help="PostgreSQL version (e.g., 17-alpine)")
    parser.add_argument("--instances", type=int, help="Number of gateway instances")
    parser.add_argument("--output", type=Path, default=Path("docker-compose.perf.yml"), help="Output file path")
    parser.add_argument("--list-profiles", action="store_true", help="List available profiles and exit")

    args = parser.parse_args()

    try:
        generator = DockerComposeGenerator(args.config)

        if args.list_profiles:
            print("\n=== Infrastructure Profiles ===")
            for name, profile in generator.config.get("infrastructure_profiles", {}).items():
                desc = profile.get("description", "No description")
                instances = profile.get("gateway_instances", 1)
                pg_version = profile.get("postgres_version", "N/A")
                print(f"  {name:20} - {desc}")
                print(f"    {'':20}   Instances: {instances}, PostgreSQL: {pg_version}")

            print("\n=== Server Profiles ===")
            for name, profile in generator.config.get("server_profiles", {}).items():
                desc = profile.get("description", "No description")
                workers = profile.get("gunicorn_workers", "N/A")
                threads = profile.get("gunicorn_threads", "N/A")
                print(f"  {name:20} - {desc}")
                print(f"    {'':20}   Workers: {workers}, Threads: {threads}")

            return 0

        # Generate docker-compose
        generator.generate(infrastructure_profile=args.infrastructure, server_profile=args.server_profile, postgres_version=args.postgres_version, instances=args.instances, output_file=args.output)

        print("\n✅ Successfully generated docker-compose configuration")
        print(f"   Infrastructure: {args.infrastructure}")
        print(f"   Server Profile: {args.server_profile}")
        print(f"   Output: {args.output}")

        return 0

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
