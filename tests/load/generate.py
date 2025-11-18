# -*- coding: utf-8 -*-
"""Main CLI for generating load test data.

Usage:
    python -m tests.load.generate --profile production
    python -m tests.load.generate --config tests/load/configs/custom.yaml
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

import yaml
from faker import Faker
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mcpgateway.config import settings

from .generators import (
    UserGenerator,
    TeamGenerator,
    TeamMemberGenerator,
    TokenGenerator,
    GatewayGenerator,
    ToolGenerator,
    ResourceGenerator,
    PromptGenerator,
    ServerGenerator,
    A2AAgentGenerator,
    ServerToolAssociationGenerator,
    ServerResourceAssociationGenerator,
    ServerPromptAssociationGenerator,
    ServerA2AAssociationGenerator,
    ToolMetricsGenerator,
    ResourceMetricsGenerator,
    PromptMetricsGenerator,
    ServerMetricsGenerator,
    A2AAgentMetricsGenerator,
    TokenUsageLogGenerator,
    EmailAuthEventGenerator,
    PermissionAuditLogGenerator,
    MCPSessionGenerator,
    MCPMessageGenerator,
    ResourceSubscriptionGenerator,
    TeamInvitationGenerator,
    TeamJoinRequestGenerator,
    TokenRevocationGenerator,
    OAuthTokenGenerator,
)
from .utils.progress import MultiProgressTracker, SimpleProgressTracker
from .utils.validation import DataValidator
from rich.console import Console


# Logger setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Generator registry
GENERATORS = {
    # Core entities
    "users": UserGenerator,
    "teams": TeamGenerator,
    "team_members": TeamMemberGenerator,
    "tokens": TokenGenerator,
    "gateways": GatewayGenerator,
    "tools": ToolGenerator,
    "resources": ResourceGenerator,
    "prompts": PromptGenerator,
    "servers": ServerGenerator,
    "a2a_agents": A2AAgentGenerator,
    # Associations
    "server_tool_associations": ServerToolAssociationGenerator,
    "server_resource_associations": ServerResourceAssociationGenerator,
    "server_prompt_associations": ServerPromptAssociationGenerator,
    "server_a2a_associations": ServerA2AAssociationGenerator,
    # Metrics
    "tool_metrics": ToolMetricsGenerator,
    "resource_metrics": ResourceMetricsGenerator,
    "prompt_metrics": PromptMetricsGenerator,
    "server_metrics": ServerMetricsGenerator,
    "a2a_agent_metrics": A2AAgentMetricsGenerator,
    # Activity logs
    "token_usage_logs": TokenUsageLogGenerator,
    "email_auth_events": EmailAuthEventGenerator,
    "permission_audit_logs": PermissionAuditLogGenerator,
    # Sessions
    "mcp_sessions": MCPSessionGenerator,
    "mcp_messages": MCPMessageGenerator,
    "resource_subscriptions": ResourceSubscriptionGenerator,
    # Workflow state
    "team_invitations": TeamInvitationGenerator,
    "team_join_requests": TeamJoinRequestGenerator,
    "token_revocations": TokenRevocationGenerator,
    "oauth_tokens": OAuthTokenGenerator,
}


def load_config(config_path: str) -> Dict[str, Any]:
    """Load configuration from YAML file.

    Args:
        config_path: Path to YAML config file

    Returns:
        Configuration dictionary
    """
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def get_profile_path(profile: str) -> str:
    """Get path to profile configuration.

    Args:
        profile: Profile name (small, medium, large, production)

    Returns:
        Path to profile config file
    """
    base_path = Path(__file__).parent / "configs"
    return str(base_path / f"{profile}.yaml")


def create_database_session(config: Dict[str, Any]):
    """Create database session from configuration.

    Args:
        config: Configuration dictionary

    Returns:
        SQLAlchemy session
    """
    database_url = settings.database_url
    pool_size = config.get("database", {}).get("pool_size", 20)
    max_overflow = config.get("database", {}).get("max_overflow", 40)
    pool_timeout = config.get("database", {}).get("pool_timeout", 30)

    engine = create_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        echo=False,
    )

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


def generate_data(config: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    """Generate load test data.

    Args:
        config: Configuration dictionary
        dry_run: If True, don't actually insert data

    Returns:
        Generation statistics
    """
    # Initialize console and progress tracking
    console = Console()
    simple_progress = SimpleProgressTracker(console)

    profile_name = config.get('profile', {}).get('name', 'unknown')
    simple_progress.print_step(f"Starting load data generation (Profile: {profile_name})")

    logger.info("Starting load data generation...")
    logger.info(f"Profile: {profile_name}")

    start_time = time.time()
    stats = {}

    # Setup
    db = create_database_session(config)
    faker = Faker(config.get("realism", {}).get("faker_locale", "en_US"))

    # Set random seed for reproducibility
    seed = config.get("global", {}).get("random_seed", 42)
    Faker.seed(seed)

    # Determine generation order (respects dependencies)
    generation_order = config.get("generation_order", list(GENERATORS.keys()))

    # Initialize multi-progress tracker if not dry run
    progress_tracker = None
    use_progress = config.get("global", {}).get("progress_bar", True) and not dry_run

    if use_progress:
        progress_tracker = MultiProgressTracker(console)

        # Pre-calculate all generator counts and add tasks
        simple_progress.print_step("Calculating record counts...")
        for generator_name in generation_order:
            if generator_name in GENERATORS:
                generator_class = GENERATORS[generator_name]
                temp_generator = generator_class(db, config, faker, logger)
                count = temp_generator.get_count()
                progress_tracker.add_task(
                    generator_name,
                    count,
                    f"{generator_name:30}"
                )

        simple_progress.print_success(f"Planning to generate {progress_tracker.total_records:,} total records")

    try:
        if use_progress and progress_tracker:
            # Use rich live display for progress
            with progress_tracker.live_display():
                for generator_name in generation_order:
                    if generator_name not in GENERATORS:
                        logger.warning(f"Unknown generator: {generator_name}")
                        continue

                    generator_class = GENERATORS[generator_name]
                    generator = generator_class(db, config, faker, logger, progress_tracker=progress_tracker)

                    # Run generator with progress tracking
                    gen_stats = generator.run()
                    stats[generator_name] = gen_stats

                    # Explicitly refresh display after each generator completes
                    progress_tracker.refresh()
        else:
            # Dry run or no progress bar - simple output
            for generator_name in generation_order:
                if generator_name not in GENERATORS:
                    logger.warning(f"Unknown generator: {generator_name}")
                    continue

                generator_class = GENERATORS[generator_name]
                generator = generator_class(db, config, faker, logger)
                count = generator.get_count()

                if dry_run:
                    simple_progress.print_info(f"[DRY RUN] Would generate {count:,} {generator_name}")
                    stats[generator_name] = {"generated": count, "inserted": 0, "dry_run": True, "duration": 0}
                    continue

                simple_progress.print_step(f"Generating {generator_name}...")
                gen_stats = generator.run()
                stats[generator_name] = gen_stats
                simple_progress.print_success(f"Completed {generator_name}: {gen_stats['generated']:,} records")

        # Calculate totals
        total_generated = sum(s.get("generated", 0) for s in stats.values())
        total_inserted = sum(s.get("inserted", 0) for s in stats.values())

        elapsed_time = time.time() - start_time

        summary = {
            "profile": config.get("profile", {}).get("name", "custom"),
            "timestamp": datetime.now().isoformat(),
            "duration_seconds": elapsed_time,
            "total_generated": total_generated,
            "total_inserted": total_inserted,
            "records_per_second": total_generated / elapsed_time if elapsed_time > 0 else 0,
            "generator_stats": stats,
            "dry_run": dry_run,
        }

        # Print summary
        console.print()
        simple_progress.print_summary(total_generated, elapsed_time, profile_name)

        # Validate if enabled
        if config.get("validation", {}).get("enabled", True) and not dry_run:
            console.print()
            simple_progress.print_step("Running validation checks...")
            validator = DataValidator(db, logger)
            validation_results = validator.validate_all()
            summary["validation"] = validation_results

            if validation_results.get("all_passed", False):
                simple_progress.print_success("All validation checks passed!")
            else:
                simple_progress.print_warning("Some validation checks failed")

        return summary

    except Exception as e:
        logger.error(f"Generation failed: {e}", exc_info=True)
        simple_progress.print_error(f"Generation failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate production-scale load test data for MCP Gateway",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--profile",
        type=str,
        choices=["small", "medium", "large", "production", "massive"],
        help="Load profile to use"
    )

    parser.add_argument(
        "--config",
        type=str,
        help="Path to custom configuration file"
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel workers (default: 1)"
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        help="Batch insert size (overrides config)"
    )

    parser.add_argument(
        "--seed",
        type=int,
        help="Random seed for reproducibility"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be generated without inserting"
    )

    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip post-generation validation"
    )

    parser.add_argument(
        "--output",
        type=str,
        help="Output report path (JSON)"
    )

    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level"
    )

    args = parser.parse_args()

    # Set log level
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # Load configuration
    if args.config:
        config_path = args.config
    elif args.profile:
        config_path = get_profile_path(args.profile)
    else:
        logger.error("Must specify either --profile or --config")
        sys.exit(1)

    if not Path(config_path).exists():
        logger.error(f"Configuration file not found: {config_path}")
        sys.exit(1)

    config = load_config(config_path)

    # Apply CLI overrides
    if args.batch_size:
        config.setdefault("global", {})["batch_size"] = args.batch_size

    if args.seed is not None:
        config.setdefault("global", {})["random_seed"] = args.seed

    if args.skip_validation:
        config.setdefault("validation", {})["enabled"] = False

    # Generate data
    try:
        summary = generate_data(config, dry_run=args.dry_run)

        # Save report
        output_path = args.output or config.get("reporting", {}).get("output_file")
        if output_path:
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)

            with open(output_file, 'w') as f:
                json.dump(summary, f, indent=2, default=str)

            logger.info(f"Report saved to: {output_file}")

        sys.exit(0)

    except Exception as e:
        logger.error(f"Failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
