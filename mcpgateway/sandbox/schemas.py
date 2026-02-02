# mcpgateway/sandbox/schemas.py

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class SandboxSubject(BaseModel):
    email: str
    roles: List[str] = []


class SandboxResource(BaseModel):
    type: str
    id: str


class SandboxTestCase(BaseModel):
    subject: SandboxSubject
    action: str
    resource: SandboxResource
    expected_decision: Optional[str] = Field(
        None, description="Expected decision (allow/deny) for comparison"
    )


class SandboxSimulationRequest(BaseModel):
    policy_draft_id: str
    test_cases: List[SandboxTestCase]


class SandboxTestResult(BaseModel):
    index: int
    decision: str
    expected_decision: Optional[str]
    passed: Optional[bool]
    explanation: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class SandboxSimulationResponse(BaseModel):
    policy_draft_id: str
    results: List[SandboxTestResult]
