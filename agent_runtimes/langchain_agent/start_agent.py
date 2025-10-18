#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Startup script for the MCP Langchain Agent
"""

# Standard
import asyncio
import logging
import sys
from pathlib import Path

import uvicorn

# Third-Party
from dotenv import load_dotenv

try:
    # Local
    from .config import get_example_env, get_settings, validate_environment
except ImportError:
    # Third-Party
    from config import get_example_env, get_settings, validate_environment

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def setup_environment():
    """Setup environment and validate configuration"""
    # Load .env file if it exists
    env_file = Path(".env")
    if env_file.exists():
        load_dotenv(env_file)
        logger.info(f"Loaded environment from {env_file}")
    else:
        logger.info("No .env file found, using system environment")

    # Validate environment
    validation = validate_environment()

    if validation["warnings"]:
        logger.warning("Configuration warnings:")
        for warning in validation["warnings"]:
            logger.warning(f"  - {warning}")

    if not validation["valid"]:
        logger.error("Configuration errors:")
        for issue in validation["issues"]:
            logger.error(f"  - {issue}")

        logger.info("Example .env file:")
        print(get_example_env())
        sys.exit(1)

    return get_settings()


async def test_agent_initialization():
    """Test that the agent can be initialized"""
    try:
        # Local
        from .agent_langchain import LangchainMCPAgent

        settings = get_settings()
        agent = LangchainMCPAgent.from_config(settings)

        logger.info("Testing agent initialization...")
        await agent.initialize()

        tools = agent.get_available_tools()
        logger.info(f"Agent initialized successfully with {len(tools)} tools")

        # Test gateway connection
        if await agent.test_gateway_connection():
            logger.info("Gateway connection test: SUCCESS")
        else:
            logger.warning("Gateway connection test: FAILED")

        return True

    except Exception as e:
        logger.error(f"Agent initialization failed: {e}")
        return False


def main():
    """Main startup function"""
    logger.info("Starting MCP Langchain Agent")

    # Setup environment
    try:
        settings = setup_environment()
        logger.info(f"Configuration loaded: Gateway URL = {settings.mcp_gateway_url}")
        if settings.tools_allowlist:
            logger.info(f"Tool allowlist: {settings.tools_allowlist}")
    except Exception as e:
        logger.error(f"Environment setup failed: {e}")
        sys.exit(1)

    # Test agent initialization
    if not asyncio.run(test_agent_initialization()):
        logger.error("Agent initialization test failed")
        response = input("Continue anyway? (y/N): ")
        if response.lower() != "y":
            sys.exit(1)

    # Start the FastAPI server
    logger.info("Starting FastAPI server...")

    try:
        uvicorn.run(
            "agent_runtimes.langchain_agent.app:app",
            host="0.0.0.0",
            port=8000,
            reload=settings.debug_mode,
            log_level="info" if not settings.debug_mode else "debug",
            access_log=True,
        )
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server failed to start: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
