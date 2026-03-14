"""python file with the models for the policy engine plugin"""

# Standard
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

# Third-Party
from pydantic import BaseModel


class Severity(str, Enum):
    """Severity levels for policy violations."""

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


# Predefined rules available in the system
AVAILABLE_RULES = [
    {"name": "max_critical_vulnerabilities", "description": "Maximum number of critical vulnerabilities allowed", "type": "number"},
    {"name": "max_high_vulnerabilities", "description": "Maximum number of high vulnerabilities allowed", "type": "number"},
    {"name": "sbom_required", "description": "Require a Software Bill of Materials (SBOM)", "type": "boolean"},
    {"name": "min_trust_score", "description": "Minimum trust score required", "type": "number"},
    {"name": "no_root_execution", "description": "Prohibit root execution", "type": "boolean"},
]


class Rule(BaseModel):
    """Rule model"""

    rule: str
    value: Any
    severity: Optional[Severity] = None


class Waiver(BaseModel):
    """Waiver model"""

    server_id: str
    rule: str
    reason: str
    expires_at: datetime
    approved_by: str
    created_at: datetime = datetime.now()


class Policy(BaseModel):
    """Policy model"""

    id: Optional[int] = None
    name: str
    description: Optional[str] = None
    environment: str  # dev, staging, production
    rules: Dict[str, Any]  # rule_name -> value
    created_at: Optional[datetime] = None


class RuleEvaluationResult(BaseModel):
    """Result of evaluating a single rule"""

    rule_name: str
    passed: bool
    message: str
    severity: Severity
    details: Dict[str, Any] = {}
    waived: bool = False
    waiver_id: Optional[str] = None


class PolicyEvaluationResult(BaseModel):
    """Result of evaluating entire policy"""

    policy_name: str
    passed: bool
    score: float  # 0-100
    rule_results: list[RuleEvaluationResult] = []
    compliance_status: str  # "PASSED", "BLOCKED", "WARNED"
    waivers_applied: list[str] = []
