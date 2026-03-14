"""
plugin.py - PLUGIN ENTRY POINT

Implements the plugin interface for MCP Gateway.
Orchestrates the complete policy evaluation pipeline:
1. Receives assessment/scan results
2. Finds applicable policy
3. Runs evaluator
4. Returns allow/block decision
"""

# Standard
from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

# Third-Party
import yaml

# Local
from .evaluator import PolicyEvaluator
from .models import Policy, PolicyEvaluationResult
from .waivers import WaiverManager

logger = logging.getLogger(__name__)


class PolicyEnginePlugin:
    """Policy Engine Plugin for MCP Gateway.

    Evaluates assessments against policies to determine
    if a server/agent should be allowed or blocked.
    """

    def __init__(self):
        """Initialize the plugin."""
        self.waiver_manager = WaiverManager()
        self.evaluator = PolicyEvaluator(self.waiver_manager)
        # In-memory storage for policies; in production would use database
        self._policies: Dict[int, Policy] = {}
        self._policy_id_counter = 1
        self._evaluation_history: list[Dict[str, Any]] = []

        # Persistent storage paths
        self._eval_history_file = Path("/tmp/policy_engine_evaluation_history.json")
        self._policy_file = Path("/tmp/policy_engine_policies.json")

        # Load policies: from persistent storage if it exists, otherwise from YAML
        if self._policy_file.exists():
            self._load_policies()
        else:
            self._load_default_policies()

        # Load evaluation history from persistent storage
        self._load_evaluation_history()

    def _load_default_policies(self) -> None:
        """Load default policies from policies.yaml template."""
        try:
            policies_file = Path(__file__).parent / "templates" / "polices.yaml"

            if not policies_file.exists():
                logger.warning(f"Policies template not found: {policies_file}")
                return

            with open(policies_file, "r") as f:
                policies_data = yaml.safe_load(f)

            if not policies_data:
                logger.warning("No policies found in policies.yaml")
                return

            # Create policies from YAML
            for policy_data in policies_data:
                try:
                    policy = Policy(
                        id=policy_data.get("id"),
                        name=policy_data.get("name"),
                        description=policy_data.get("description"),
                        environment=policy_data.get("environment"),
                        rules=policy_data.get("rules", {}),
                    )

                    # Use the ID from YAML if provided, otherwise auto-increment
                    if policy.id:
                        self._policies[policy.id] = policy
                        self._policy_id_counter = max(self._policy_id_counter, policy.id + 1)
                    else:
                        policy_id = self._get_next_policy_id()
                        policy.id = policy_id
                        self._policies[policy_id] = policy

                    logger.info(f"Loaded default policy: {policy.name} (ID: {policy.id})")

                except Exception as e:
                    logger.error(f"Error loading policy from YAML: {e}")
                    continue

        except Exception as e:
            logger.error(f"Failed to load default policies from YAML: {e}")

    def _save_policies(self) -> None:
        """Save current policies to persistent storage."""
        try:
            policies_data = [
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description,
                    "environment": p.environment,
                    "rules": p.rules,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                }
                for p in self._policies.values()
            ]
            with open(self._policy_file, "w") as f:
                # Standard
                import json

                json.dump(policies_data, f, indent=2)
            logger.info(f"Saved {len(policies_data)} policies to persistent storage")
        except Exception as e:
            logger.error(f"Failed to save policies: {e}")

    def _load_policies(self) -> None:
        """Load policies from persistent storage."""
        try:
            # Standard
            import json

            with open(self._policy_file, "r") as f:
                policies_data = json.load(f)
            # Standard
            from datetime import datetime

            for policy_data in policies_data:
                raw_created = policy_data.get("created_at")
                created_at = datetime.fromisoformat(raw_created) if raw_created else None
                policy = Policy(
                    id=policy_data.get("id"),
                    name=policy_data.get("name"),
                    description=policy_data.get("description"),
                    environment=policy_data.get("environment"),
                    rules=policy_data.get("rules", {}),
                    created_at=created_at,
                )
                self._policies[policy.id] = policy
                self._policy_id_counter = max(self._policy_id_counter, policy.id + 1)
            logger.info(f"Loaded {len(self._policies)} policies from persistent storage")
        except Exception as e:
            logger.error(f"Failed to load policies from persistent storage: {e}")
            # Fall back to YAML
            self._load_default_policies()

    def _load_evaluation_history(self) -> None:
        """Load evaluation history from persistent storage."""
        try:
            if self._eval_history_file.exists():
                with open(self._eval_history_file, "r") as f:
                    data = json.load(f)
                    self._evaluation_history = data if isinstance(data, list) else []
                logger.info(f"Loaded {len(self._evaluation_history)} evaluations from persistent storage")
            else:
                logger.debug("No evaluation history file found, starting fresh")
        except Exception as e:
            logger.error(f"Error loading evaluation history: {e}")
            self._evaluation_history = []

    def _save_evaluation_history(self) -> None:
        """Save evaluation history to persistent storage."""
        try:
            self._eval_history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._eval_history_file, "w") as f:
                json.dump(self._evaluation_history, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving evaluation history: {e}")

    def register(self) -> Dict[str, Any]:
        """Register plugin with MCP Gateway.

        Returns:
            Plugin metadata
        """
        return {
            "name": "policy-engine",
            "version": "0.1.0",
            "description": "Policy evaluation engine for compliance checking",
            "capabilities": {
                "policies": True,
                "waivers": True,
                "compliance_scoring": True,
            },
        }

    def evaluate_assessment(
        self,
        assessment: Dict[str, Any],
        server_id: Optional[str] = None,
        policy_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Evaluate an assessment against a policy.

        This is the main entry point called by MCP Gateway
        when an assessment is submitted.

        Args:
            assessment: Assessment/scan results
            server_id: Server being assessed
            policy_id: Policy to evaluate against (if None, uses default)

        Returns:
            Decision object with allow/block and details
        """
        # Get policy
        if policy_id is None:
            policy = self._get_default_policy()
        else:
            policy = self._policies.get(policy_id)

        if policy is None:
            logger.warning(f"No policy found for evaluation (policy_id={policy_id})")
            return {
                "decision": "allow",
                "reason": "no_policy_configured",
                "score": 0.0,
            }

        # Run evaluation
        result = self.evaluator.evaluate(assessment, policy, server_id)

        # Log evaluation
        self._log_evaluation(server_id, policy_id, result)

        # Make decision
        decision = "allow" if result.passed else "block"
        if any(r.waived for r in result.rule_results):
            decision = "allow"  # Waivers override block decisions

        return {
            "decision": decision,
            "policy_name": result.policy_name,
            "score": result.score,
            "compliance_status": result.compliance_status,
            "rule_results": [
                {
                    "rule": r.rule_name,
                    "passed": r.passed,
                    "message": r.message,
                    "waived": r.waived,
                    "waiver_id": r.waiver_id,
                }
                for r in result.rule_results
            ],
            "waivers_applied": result.waivers_applied,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def create_policy(self, policy: Policy) -> Policy:
        """Create a new policy.

        Args:
            policy: Policy object

        Returns:
            Created policy with ID
        """
        # Standard
        from datetime import datetime

        policy_id = self._get_next_policy_id()
        policy.id = policy_id
        if policy.created_at is None:
            policy.created_at = datetime.utcnow()
        self._policies[policy_id] = policy
        self._save_policies()
        logger.info(f"Created policy {policy_id}: {policy.name}")
        return policy

    def get_policy(self, policy_id: int) -> Optional[Policy]:
        """Get a policy by ID.

        Args:
            policy_id: Policy ID

        Returns:
            Policy or None
        """
        return self._policies.get(policy_id)

    def list_policies(self, environment: Optional[str] = None) -> list[Policy]:
        """List policies.

        Args:
            environment: Optional filter by environment

        Returns:
            List of policies
        """
        policies = list(self._policies.values())
        if environment:
            policies = [p for p in policies if p.environment == environment]
        return policies

    def update_policy(self, policy_id: int, policy: Policy) -> Optional[Policy]:
        """Update a policy.

        Args:
            policy_id: Policy ID
            policy: Updated policy object

        Returns:
            Updated policy or None if not found
        """
        if policy_id not in self._policies:
            return None

        policy.id = policy_id
        self._policies[policy_id] = policy
        self._save_policies()
        logger.info(f"Updated policy {policy_id}")
        return policy

    def delete_policy(self, policy_id: int) -> bool:
        """Delete a policy.

        Args:
            policy_id: Policy ID

        Returns:
            True if deleted, False if not found
        """
        if policy_id not in self._policies:
            return False

        del self._policies[policy_id]
        self._save_policies()
        logger.info(f"Deleted policy {policy_id}")
        return True

    def create_waiver(
        self,
        server_id: str,
        rule_name: str,
        reason: str,
        requested_by: str,
        duration_days: int = 30,
    ) -> Dict[str, Any]:
        """Create a waiver request.

        Args:
            server_id: Server ID
            rule_name: Rule being waived
            reason: Reason for waiver
            requested_by: User requesting
            duration_days: Duration in days

        Returns:
            Created waiver
        """
        return self.waiver_manager.create_waiver(server_id, rule_name, reason, requested_by, duration_days)

    def approve_waiver(self, waiver_id: str, approved_by: str, expires_at: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Approve a waiver.

        Args:
            waiver_id: Waiver ID
            approved_by: User approving
            expires_at: Optional expiration date

        Returns:
            Updated waiver or None
        """
        return self.waiver_manager.approve_waiver(waiver_id, approved_by, expires_at)

    def list_waivers(self, server_id: Optional[str] = None) -> list[Dict[str, Any]]:
        """List waivers.

        Args:
            server_id: Optional filter by server

        Returns:
            List of waivers
        """
        return self.waiver_manager.list_waivers(server_id)

    def get_evaluation_history(self, server_id: Optional[str] = None) -> list[Dict[str, Any]]:
        """Get evaluation history.

        Args:
            server_id: Optional filter by server

        Returns:
            List of evaluations
        """
        # Reload from disk each time to get latest evaluations from CLI
        self._load_evaluation_history()
        history = self._evaluation_history
        if server_id:
            history = [e for e in history if e.get("server_id") == server_id]
        return history[-100:]  # Return last 100 evaluations

    def _get_next_policy_id(self) -> int:
        """Generate next policy ID."""
        current = self._policy_id_counter
        self._policy_id_counter += 1
        return current

    def _get_default_policy(self) -> Optional[Policy]:
        """Get default policy (lowest numbered policy).

        Returns:
            Default policy or None if none exist
        """
        if not self._policies:
            return None

        min_id = min(self._policies.keys())
        return self._policies[min_id]

    def _log_evaluation(
        self,
        server_id: Optional[str],
        policy_id: Optional[int],
        result: PolicyEvaluationResult,
    ) -> None:
        """Log an evaluation for audit trail.

        Args:
            server_id: Server ID
            policy_id: Policy ID
            result: Evaluation result
        """
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "server_id": server_id,
            "policy_id": policy_id,
            "policy_name": result.policy_name,
            "score": result.score,
            "status": result.compliance_status,
            "passed": result.passed,
        }
        self._evaluation_history.append(entry)

        # Persist to file
        self._save_evaluation_history()


# Global plugin instance
_plugin_instance: Optional[PolicyEnginePlugin] = None


def get_plugin() -> PolicyEnginePlugin:
    """Get or create plugin instance.

    Returns:
        PolicyEnginePlugin instance
    """
    global _plugin_instance
    if _plugin_instance is None:
        _plugin_instance = PolicyEnginePlugin()
    return _plugin_instance
