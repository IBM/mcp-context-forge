"""
admin.py - ADMIN UI ROUTES

Serves HTML pages for the policy engine admin dashboard.

Provides routes for:
- Dashboard: Overview of compliance status
- Policies: Policy management interface
- Waivers: Waiver request and approval interface
- Servers: Server compliance details
"""

# Standard
import logging
from pathlib import Path
from typing import Any, Dict

# Third-Party
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/policy-engine", tags=["admin-ui"])
_TEMPLATE_PATH = Path(__file__).parent / "ui"


def render_template(template_name: str, context: Dict[str, Any] = None) -> str:
    """
    Render an HTML template with context.

    Args:
        template_name: Name of template file (e.g., 'dashboard.html')
        context: Dictionary of template variables

    Returns:
        Rendered HTML string
    """
    context = context or {}
    template_file = _TEMPLATE_PATH / template_name

    if not template_file.exists():
        logger.warning(f"Template not found: {template_file}")
        return f"<h1>Template Not Found</h1><p>{template_name}</p>"

    try:
        with open(template_file, "r") as f:
            html = f.read()

        # Simple variable replacement (in production, use Jinja2)
        for key, value in context.items():
            placeholder = "{{ " + key + " }}"
            html = html.replace(placeholder, str(value))

        return html
    except Exception as e:
        logger.error(f"Error rendering template {template_name}: {e}")
        return f"<h1>Error Rendering Template</h1><p>{str(e)}</p>"


# ============================================================================
# ADMIN UI ROUTES
# ============================================================================


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request) -> str:
    """
    Render the main dashboard page.

    Shows overall compliance status and stats.

    Returns:
        HTML response
    """
    return render_template("dashboard.html", {"title": "Policy Engine Dashboard", "page": "dashboard"})


@router.get("/policies", response_class=HTMLResponse)
async def policies_page(request: Request) -> str:
    """
    Render the policies management page.

    Allows creating, reading, updating, and deleting policies.

    Returns:
        HTML response
    """
    return render_template("policies.html", {"title": "Policies Management", "page": "policies"})


@router.get("/policies/new", response_class=HTMLResponse)
async def new_policy_page(request: Request) -> str:
    """
    Render the new policy creation page.

    Returns:
        HTML response
    """
    return render_template("policies.html", {"title": "Create New Policy", "page": "policies", "mode": "create"})


@router.get("/policies/{policy_id}/edit", response_class=HTMLResponse)
async def edit_policy_page(request: Request, policy_id: int) -> str:
    """
    Render the policy edit page.

    Args:
        policy_id: ID of the policy to edit

    Returns:
        HTML response
    """
    return render_template("policies.html", {"title": "Edit Policy", "page": "policies", "policy_id": policy_id, "mode": "edit"})


@router.get("/policies/{policy_id}", response_class=HTMLResponse)
async def view_policy_page(request: Request, policy_id: int) -> str:
    """
    Render the policy details page.

    Args:
        policy_id: ID of the policy

    Returns:
        HTML response
    """
    return render_template("policies.html", {"title": "Policy Details", "page": "policies", "policy_id": policy_id, "mode": "view"})


@router.get("/evaluations", response_class=HTMLResponse)
async def evaluations_page(request: Request) -> str:
    """
    Render the policy evaluations page.

    Shows evaluation history with filtering by server and policy.

    Returns:
        HTML response
    """
    return render_template("evaluations.html", {"title": "Policy Evaluations", "page": "evaluations"})


@router.get("/waivers", response_class=HTMLResponse)
async def waivers_page(request: Request) -> str:
    """
    Render the waivers management page.

    Shows pending waiver requests, approved waivers, and allows approval/rejection.

    Returns:
        HTML response
    """
    return render_template("waivers.html", {"title": "Waivers Management", "page": "waivers"})


@router.get("/waivers/pending", response_class=HTMLResponse)
async def pending_waivers_page(request: Request) -> str:
    """
    Render the pending waivers page.

    Shows only pending waiver requests awaiting approval.

    Returns:
        HTML response
    """
    return render_template("waivers.html", {"title": "Pending Waivers", "page": "waivers", "filter": "pending"})


@router.get("/waivers/{waiver_id}/review", response_class=HTMLResponse)
async def review_waiver_page(request: Request, waiver_id: str) -> str:
    """
    Render the waiver review page.

    Allows approval or rejection of a pending waiver.

    Args:
        waiver_id: ID of the waiver to review

    Returns:
        HTML response
    """
    return render_template("waivers.html", {"title": "Review Waiver", "page": "waivers", "waiver_id": waiver_id, "mode": "review"})


@router.get("/servers", response_class=HTMLResponse)
async def servers_page(request: Request) -> str:
    """
    Render the servers compliance dashboard.

    Shows all registered servers and their compliance status.

    Returns:
        HTML response
    """
    return render_template("dashboard.html", {"title": "Servers Compliance", "page": "servers"})


@router.get("/servers/{server_id}", response_class=HTMLResponse)
async def server_details_page(request: Request, server_id: str) -> str:
    """
    Render detailed compliance view for a specific server.

    Shows evaluation history, active waivers, and rule status.

    Args:
        server_id: ID of the server

    Returns:
        HTML response
    """
    return render_template("dashboard.html", {"title": f"Server Details: {server_id}", "page": "server-details", "server_id": server_id})


@router.get("/servers/{server_id}/history", response_class=HTMLResponse)
async def server_history_page(request: Request, server_id: str) -> str:
    """
    Render the evaluation history page for a server.

    Shows timeline of compliance evaluations for a specific server.

    Args:
        server_id: ID of the server

    Returns:
        HTML response
    """
    return render_template("dashboard.html", {"title": f"Evaluation History: {server_id}", "page": "server-history", "server_id": server_id})


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> str:
    """
    Render the settings/configuration page.

    Allows configuration of waiver defaults, max duration, etc.

    Returns:
        HTML response
    """
    return render_template("dashboard.html", {"title": "Policy Engine Settings", "page": "settings"})


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def load_template(template_name: str) -> str:
    """
    Load an HTML template from the templates directory.

    Args:
        template_name: Name of the template file

    Returns:
        HTML content
    """
    template_file = _TEMPLATE_PATH / template_name

    if not template_file.exists():
        return f"<h1>Error: Template {template_name} not found</h1>"

    try:
        return template_file.read_text()
    except Exception as e:
        return f"<h1>Error loading template: {str(e)}</h1>"


# def render_template(template_name: str, context: Dict[str, Any]) -> str:
#     """
#     Render a template with the given context.

#     Args:
#         template_name: Name of the template file
#         context: Dictionary of variables to pass to the template

#     Returns:
#         Rendered HTML
#     """
#     html = load_template(template_name)

#     # Simple variable interpolation (can be enhanced with Jinja2)
#     for key, value in context.items():
#         placeholder = f"{{{{ {key} }}}}"
#         html = html.replace(placeholder, str(value))

#     return html
