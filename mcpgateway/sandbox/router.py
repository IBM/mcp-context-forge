# mcpgateway/sandbox/router.py

from fastapi import APIRouter
from typing import List

from mcpgateway.sandbox.schemas import (
    SandboxSimulationRequest,
    SandboxSimulationResponse,
    SandboxTestResult,
)

# DEFINE router
router = APIRouter(
    prefix="/sandbox",
    tags=["Sandbox"],
)

#  router
@router.post(
    "/simulate",
    response_model=SandboxSimulationResponse,
    summary="Simulate policy decisions in sandbox",
)
async def simulate_policy(
    request: SandboxSimulationRequest,
):
    """
    Sandbox policy simulation (stub).
    PDP integration will be added in a follow-up issue.
    """
    results: List[SandboxTestResult] = []

    for idx, test_case in enumerate(request.test_cases):
        # stub( expected_decision
        results.append(
            SandboxTestResult(
                index=idx,
                expected=test_case.expected_decision,
                actual=test_case.expected_decision,
                passed=True,
                explanation="Stubbed sandbox result (no PDP yet)",
            )
        )

    return SandboxSimulationResponse(
        policy_draft_id=request.policy_draft_id,
        results=results,
    )
