"""
api.py - REST ENDPOINTS

Admin API for the policy engine plugin.

Provides endpoints for:
- Policy Management: Create, read, update, delete policies
- Waiver Management: Create, approve, reject waiver requests
- Monitoring: View server compliance status and evaluation history
- Assessment Evaluation: Submit assessments for policy evaluation
"""

# Standard
from datetime import datetime
from typing import Any, Dict, List, Optional

# Third-Party
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

# Local
from .models import Policy
from .plugin import get_plugin


# Request/Response Models
class ApproveWaiverRequest(BaseModel):
    """Model for approving a waiver request."""

    approved_by: str
    expires_at: Optional[str] = None


class RejectWaiverRequest(BaseModel):
    """Model for rejecting a waiver request."""

    reason: str


# Create two routers
router = APIRouter(prefix="/api/policy-engine", tags=["policy-engine"])
dashboard_router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ============================================================================
# DASHBOARD ENDPOINTS
# ============================================================================


@router.get("/dashboard/summary")
async def get_dashboard_summary() -> Dict[str, Any]:
    """
    Get dashboard summary statistics.

    Returns:
        Summary with policy count, waiver count, evaluation stats
    """
    plugin = get_plugin()
    policies = plugin.list_policies()
    waivers = plugin.list_waivers()
    evaluations = plugin.get_evaluation_history()

    # Count pending waivers
    pending_waivers = [w for w in waivers if w.get("status") == "pending"]
    approved_waivers = [w for w in waivers if w.get("status") == "approved"]

    # Count evaluations by status
    passed_evals = [e for e in evaluations if e.get("passed")]
    blocked_evals = [e for e in evaluations if not e.get("passed")]

    return {
        "total_policies": len(policies),
        "total_waivers": len(waivers),
        "pending_waivers": len(pending_waivers),
        "approved_waivers": len(approved_waivers),
        "total_evaluations": len(evaluations),
        "passed_evaluations": len(passed_evals),
        "blocked_evaluations": len(blocked_evals),
        "compliance_rate": (len(passed_evals) / len(evaluations) * 100) if evaluations else 0,
    }


@router.get("/dashboard/servers")
async def get_dashboard_servers() -> List[Dict[str, Any]]:
    """
    Get list of servers with their compliance status.

    Returns:
        List of servers with evaluation results
    """
    plugin = get_plugin()
    evaluations = plugin.get_evaluation_history()

    # Group evaluations by server
    servers_dict: Dict[str, Dict[str, Any]] = {}

    for eval_record in evaluations:
        server_id = eval_record.get("server_id", "Unknown")
        if server_id not in servers_dict:
            servers_dict[server_id] = {
                "server_id": server_id,
                "total_evals": 0,
                "passed": 0,
                "blocked": 0,
                "latest_status": None,
                "latest_score": 0,
                "latest_timestamp": None,
            }

        servers_dict[server_id]["total_evals"] += 1
        if eval_record.get("passed"):
            servers_dict[server_id]["passed"] += 1
        else:
            servers_dict[server_id]["blocked"] += 1

        servers_dict[server_id]["latest_status"] = eval_record.get("status")
        servers_dict[server_id]["latest_score"] = eval_record.get("score")
        servers_dict[server_id]["latest_timestamp"] = eval_record.get("timestamp")

    return list(servers_dict.values())


# ============================================================================
# DASHBOARD ROUTER ENDPOINTS (at /api/dashboard/)
# ============================================================================


@dashboard_router.get("/summary")
async def dashboard_get_summary() -> Dict[str, Any]:
    """Get dashboard summary statistics."""
    plugin = get_plugin()
    policies = plugin.list_policies()
    waivers = plugin.list_waivers()
    evaluations = plugin.get_evaluation_history()

    pending_waivers = [w for w in waivers if w.get("status") == "pending"]
    approved_waivers = [w for w in waivers if w.get("status") == "approved"]

    passed_evals = [e for e in evaluations if e.get("passed")]
    blocked_evals = [e for e in evaluations if not e.get("passed")]

    return {
        "total_policies": len(policies),
        "total_waivers": len(waivers),
        "pending_waivers": len(pending_waivers),
        "approved_waivers": len(approved_waivers),
        "total_evaluations": len(evaluations),
        "passed_evaluations": len(passed_evals),
        "blocked_evaluations": len(blocked_evals),
        "compliance_rate": (len(passed_evals) / len(evaluations) * 100) if evaluations else 0,
    }


@dashboard_router.get("/servers")
async def dashboard_get_servers() -> List[Dict[str, Any]]:
    """Get list of servers with their compliance status."""
    plugin = get_plugin()
    evaluations = plugin.get_evaluation_history()

    servers_dict: Dict[str, Dict[str, Any]] = {}

    for eval_record in evaluations:
        server_id = eval_record.get("server_id", "Unknown")
        if server_id not in servers_dict:
            servers_dict[server_id] = {
                "server_id": server_id,
                "total_evals": 0,
                "passed": 0,
                "blocked": 0,
                "latest_status": None,
                "latest_score": 0,
                "latest_timestamp": None,
            }

        servers_dict[server_id]["total_evals"] += 1
        if eval_record.get("passed"):
            servers_dict[server_id]["passed"] += 1
        else:
            servers_dict[server_id]["blocked"] += 1

        servers_dict[server_id]["latest_status"] = eval_record.get("status")
        servers_dict[server_id]["latest_score"] = eval_record.get("score")
        servers_dict[server_id]["latest_timestamp"] = eval_record.get("timestamp")

    return list(servers_dict.values())


# ============================================================================
# ASSESSMENT EVALUATION ENDPOINT
# ============================================================================


@router.post("/evaluate")
async def evaluate_assessment(
    assessment: Dict[str, Any],
    server_id: Optional[str] = None,
    policy_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Evaluate an assessment against a policy.

    This is the main endpoint called by MCP Gateway or security scanners
    to check if a server passes policy compliance.

    Args:
        assessment: Assessment/scan results with findings
        server_id: Optional server identifier
        policy_id: Optional policy ID to use (defaults to policy 1)

    Returns:
        Decision object with allow/block and compliance details
    """
    plugin = get_plugin()
    return plugin.evaluate_assessment(assessment, server_id, policy_id)


# ============================================================================
# POLICY ENDPOINTS
# ============================================================================


@router.get("/policies")
async def list_policies(environment: Optional[str] = None) -> List[Policy]:
    """
    List all policies, optionally filtered by environment.

    Args:
        environment: Optional filter (dev, staging, production)

    Returns:
        List of policies
    """
    plugin = get_plugin()
    return plugin.list_policies(environment)


@router.post("/policies")
async def create_policy(policy: Policy) -> Policy:
    """
    Create a new policy.

    Args:
        policy: Policy object with name, description, environment, and rules

    Returns:
        Created policy with ID
    """
    if not policy.name:
        raise HTTPException(status_code=400, detail="Policy name is required")
    if not policy.rules:
        raise HTTPException(status_code=400, detail="Policy rules are required")

    plugin = get_plugin()
    return plugin.create_policy(policy)


@router.get("/policies/{policy_id}")
async def get_policy(policy_id: int) -> Policy:
    """
    Get a specific policy by ID.

    Args:
        policy_id: ID of the policy

    Returns:
        Policy details

    Raises:
        HTTPException: 404 if policy not found
    """
    plugin = get_plugin()
    policy = plugin.get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return policy


@router.put("/policies/{policy_id}")
async def update_policy(policy_id: int, policy: Policy) -> Policy:
    """
    Update an existing policy.

    Args:
        policy_id: ID of the policy to update
        policy: Updated policy object

    Returns:
        Updated policy

    Raises:
        HTTPException: 404 if policy not found
    """
    plugin = get_plugin()
    updated = plugin.update_policy(policy_id, policy)
    if not updated:
        raise HTTPException(status_code=404, detail="Policy not found")
    return updated


@router.delete("/policies/{policy_id}")
async def delete_policy(policy_id: int) -> Dict[str, str]:
    """
    Delete a policy.

    Args:
        policy_id: ID of the policy to delete

    Returns:
        Status message

    Raises:
        HTTPException: 404 if policy not found
    """
    plugin = get_plugin()
    success = plugin.delete_policy(policy_id)
    if not success:
        raise HTTPException(status_code=404, detail="Policy not found")
    return {"status": "Policy deleted successfully"}


# ============================================================================
# WAIVER ENDPOINTS
# ============================================================================


@router.post("/waivers")
async def create_waiver_request(
    server_id: str,
    rule_name: str,
    reason: str,
    requested_by: str,
    duration_days: int = Query(30, ge=1, le=90),
) -> Dict[str, Any]:
    """
    Create a new waiver request.

    A waiver temporarily allows a failed rule to pass for a specific server.
    Waivers require approval and have an expiration date.

    Args:
        server_id: Server identifier
        rule_name: Name of rule to waive
        reason: Reason for the waiver
        requested_by: User requesting the waiver
        duration_days: Duration in days (1-90, default 30)

    Returns:
        Created waiver object
    """
    plugin = get_plugin()
    return plugin.create_waiver(server_id, rule_name, reason, requested_by, duration_days)


@router.get("/waivers")
async def list_waivers(server_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List all waivers, optionally filtered by server.

    Args:
        server_id: Optional filter by server ID

    Returns:
        List of waivers
    """
    plugin = get_plugin()
    return plugin.list_waivers(server_id)


@router.get("/waivers/pending")
async def list_pending_waivers() -> List[Dict[str, Any]]:
    """
    Get pending waiver requests.

    Returns:
        List of pending waivers
    """
    plugin = get_plugin()
    all_waivers = plugin.list_waivers()
    return [w for w in all_waivers if w.get("status") == "pending"]


@router.get("/waivers/active")
async def list_active_waivers() -> List[Dict[str, Any]]:
    """
    Get approved/active waivers.

    Returns:
        List of approved waivers
    """
    plugin = get_plugin()
    all_waivers = plugin.list_waivers()
    now = datetime.utcnow()
    return [w for w in all_waivers if w.get("status") == "approved" and w.get("expires_at", now) > now]


@router.post("/waivers/{waiver_id}/approve")
async def approve_waiver(waiver_id: str, request: ApproveWaiverRequest) -> Dict[str, Any]:
    """
    Approve a waiver request.

    Args:
        waiver_id: ID of the waiver
        request: Approval request with approved_by field and optional expires_at

    Returns:
        Updated waiver

    Raises:
        HTTPException: 404 if waiver not found
    """
    plugin = get_plugin()
    result = plugin.approve_waiver(waiver_id, request.approved_by, request.expires_at)
    if not result:
        raise HTTPException(status_code=404, detail="Waiver not found")
    return result


@router.post("/waivers/{waiver_id}/reject")
async def reject_waiver(waiver_id: str, request: RejectWaiverRequest) -> Dict[str, str]:
    """
    Reject a waiver request.

    Args:
        waiver_id: ID of the waiver
        request: Rejection request with reason field

    Returns:
        Status message
    """
    plugin = get_plugin()
    waiver = plugin.waiver_manager.get_waiver(waiver_id)
    if not waiver:
        raise HTTPException(status_code=404, detail="Waiver not found")

    plugin.waiver_manager.reject_waiver(waiver_id, request.reason)
    return {"status": "Waiver rejected"}


@router.delete("/waivers/{waiver_id}")
async def revoke_waiver(waiver_id: str) -> Dict[str, str]:
    """
    Revoke an active waiver.

    Args:
        waiver_id: ID of the waiver to revoke

    Returns:
        Status message

    Raises:
        HTTPException: 404 if waiver not found
    """
    plugin = get_plugin()
    result = plugin.waiver_manager.revoke_waiver(waiver_id)
    if not result:
        raise HTTPException(status_code=404, detail="Waiver not found")
    return {"status": "Waiver revoked"}


# ============================================================================
# COMPLIANCE & MONITORING ENDPOINTS
# ============================================================================


@router.get("/evaluation-history")
async def get_evaluation_history(server_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get evaluation history for audit trail.

    Args:
        server_id: Optional filter by server ID

    Returns:
        List of past evaluations
    """
    plugin = get_plugin()
    return plugin.get_evaluation_history(server_id)


@router.get("/health")
async def health_check() -> Dict[str, str]:
    """
    Health check endpoint.

    Returns:
        Status object
    """
    return {
        "status": "healthy",
        "service": "policy-engine",
        "version": "0.1.0",
    }
