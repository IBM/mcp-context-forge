# PR Review Cycle State

See AGENTS.md § PR Review Workflow for the procedure.

## Current cycle: ____

[ ] Conducting review
[ ] Implementing suggestions

## Validation gate (see AGENTS.md table for commands)

[ ] 1. Lint  (`make ruff interrogate pylint`)
[ ] 2. Tests  (`make test`)
[ ] 3. Coverage  (`make coverage diff-cover`)
[ ] 4. Gateway stack  (`make docker-nuke docker-prod-rust testing-up RUST_MCP_MODE=`)
[ ] 5. MCP protocol  (`make test-mcp-protocol-e2e test-mcp-rbac test-protocol-compliance`)
[ ] 6. Secrets scan  (`make detect-secrets-scan`)
