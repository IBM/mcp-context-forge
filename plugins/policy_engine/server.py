#!/usr/bin/env python3
"""
Standalone Policy Engine Server

Runs the Policy Engine API and Admin UI independently from the main MCP Gateway.
Provides:
- REST API: /api/policy-engine/*
- Admin Dashboard: /admin/policy-engine/*
"""

# Standard
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Third-Party
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
import uvicorn

# First-Party
from plugins.policy_engine.admin import router as admin_router
from plugins.policy_engine.api import dashboard_router
from plugins.policy_engine.api import router as api_router

# Create FastAPI app
app = FastAPI(
    title="Policy Engine",
    description="Standalone Policy Engine for security compliance checking",
    version="0.1.0",
)

# Include routers
app.include_router(api_router)
app.include_router(dashboard_router)
app.include_router(admin_router)


# Redirect root to dashboard
@app.get("/", include_in_schema=False)
async def root():
    """Redirect to dashboard."""
    return RedirectResponse(url="/admin/policy-engine/dashboard")


@app.get("/admin", include_in_schema=False)
async def admin_root():
    """Redirect to admin dashboard."""
    return RedirectResponse(url="/admin/policy-engine/dashboard")


@app.get("/admin/policy-engine", include_in_schema=False)
async def policy_engine_root():
    """Redirect to policy engine dashboard."""
    return RedirectResponse(url="/admin/policy-engine/dashboard")


if __name__ == "__main__":
    print("""
    ╔════════════════════════════════════════════════════════════╗
    ║        Policy Engine - Standalone Server                   ║
    ╠════════════════════════════════════════════════════════════╣
    ║                                                            ║
    ║  Admin Dashboard:                                          ║
    ║  → http://localhost:8001/admin/policy-engine/dashboard     ║
    ║                                                            ║
    ║  REST API:                                                 ║
    ║  → http://localhost:8001/api/policy-engine/policies        ║
    ║  → http://localhost:8001/api/policy-engine/waivers         ║
    ║                                                            ║
    ║  API Docs:                                                 ║
    ║  → http://localhost:8001/docs                              ║
    ║                                                            ║
    ╚════════════════════════════════════════════════════════════╝
    """)

    uvicorn.run(
        "plugins.policy_engine.server:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info",
    )
