# Team Member RBAC Role Assignment Fix

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Assign and revoke team-scoped RBAC roles when team members are added or removed

**Architecture:** Add RBAC role management to TeamManagementService using lazy-initialized RoleService. When members are added, assign the configured `default_team_member_role`. When removed, revoke their team-scoped role. Handle edge cases like existing role assignments.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, pytest, AsyncMock

---

## Current Gap Analysis

The `DEFAULT_TEAM_MEMBER_ROLE` setting exists in config but is NOT used when:
1. `add_member_to_team()` adds a user to a team
2. `approve_join_request()` approves a join request
3. `remove_member_from_team()` removes a user (no role cleanup)

This means users added to teams have no team-scoped permissions.

---

## Task 1: Add RoleService Integration to TeamManagementService

**Files:**
- Modify: `mcpgateway/services/team_management_service.py:46-60`

**Step 1: Add _role_service property to __init__**

```python
def __init__(self, db: Session):
    """Initialize service with database session.

    Args:
        db: SQLAlchemy database session

    Examples:
        >>> from unittest.mock import Mock
        >>> service = TeamManagementService(Mock())
        >>> service.__class__.__name__
        'TeamManagementService'
        >>> hasattr(service, 'db')
        True
    """
    self.db = db
    self._role_service = None  # Lazy initialization to avoid circular imports
```

**Step 2: Add role_service property**

Add after `__init__` method (around line 60):

```python
    @property
    def role_service(self):
        """Lazy-initialized RoleService to avoid circular imports.

        Returns:
            RoleService: Instance of RoleService
        """
        if self._role_service is None:
            # First-Party
            from mcpgateway.services.role_service import RoleService  # pylint: disable=import-outside-toplevel

            self._role_service = RoleService(self.db)
        return self._role_service
```

**Step 3: Verify import pattern**

Run: `python -c "from mcpgateway.services.team_management_service import TeamManagementService; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add mcpgateway/services/team_management_service.py
git commit -m "feat: add RoleService lazy initialization to TeamManagementService"
```

---

## Task 2: Add RBAC Role Assignment in add_member_to_team

**Files:**
- Modify: `mcpgateway/services/team_management_service.py:460-550`

**Step 1: Add role assignment after successful member addition**

After line 529 (after `self._log_team_member_action(membership.id, ...)`), add:

```python
            # Assign team-scoped RBAC role to new member
            try:
                team_member_role = await self.role_service.get_role_by_name(
                    settings.default_team_member_role, scope="team"
                )
                if team_member_role:
                    # Check if user already has this role to avoid duplicates
                    existing = await self.role_service.get_user_role_assignment(
                        user_email=user_email,
                        role_id=team_member_role.id,
                        scope="team",
                        scope_id=team_id
                    )
                    if not existing:
                        await self.role_service.assign_role_to_user(
                            user_email=user_email,
                            role_id=team_member_role.id,
                            scope="team",
                            scope_id=team_id,
                            granted_by=invited_by or user_email
                        )
                        logger.info(f"Assigned {settings.default_team_member_role} role to {user_email} for team {team_id}")
                    else:
                        logger.debug(f"User {user_email} already has {settings.default_team_member_role} role for team {team_id}")
                else:
                    logger.warning(f"Role '{settings.default_team_member_role}' not found. User {user_email} added without RBAC role.")
            except Exception as role_error:
                logger.warning(f"Failed to assign role to {user_email}: {role_error}")
                # Don't fail member addition if role assignment fails
```

**Step 2: Run existing tests**

Run: `pytest tests/unit/mcpgateway/services/test_team_management_service.py::TestTeamManagementService::test_add_member_success -v`
Expected: PASS

**Step 3: Commit**

```bash
git add mcpgateway/services/team_management_service.py
git commit -m "feat: assign RBAC role when adding team member"
```

---

## Task 3: Add RBAC Role Assignment in approve_join_request

**Files:**
- Modify: `mcpgateway/services/team_management_service.py:1316-1370`

**Step 1: Add role assignment after join request approval**

After line 1354 (after `self.db.refresh(member)`), add:

```python
            # Assign team-scoped RBAC role to approved member
            try:
                team_member_role = await self.role_service.get_role_by_name(
                    settings.default_team_member_role, scope="team"
                )
                if team_member_role:
                    # Check if user already has this role to avoid duplicates
                    existing = await self.role_service.get_user_role_assignment(
                        user_email=join_request.user_email,
                        role_id=team_member_role.id,
                        scope="team",
                        scope_id=join_request.team_id
                    )
                    if not existing:
                        await self.role_service.assign_role_to_user(
                            user_email=join_request.user_email,
                            role_id=team_member_role.id,
                            scope="team",
                            scope_id=join_request.team_id,
                            granted_by=approved_by
                        )
                        logger.info(f"Assigned {settings.default_team_member_role} role to {join_request.user_email} for team {join_request.team_id}")
                    else:
                        logger.debug(f"User {join_request.user_email} already has {settings.default_team_member_role} role for team {join_request.team_id}")
                else:
                    logger.warning(f"Role '{settings.default_team_member_role}' not found. User {join_request.user_email} added without RBAC role.")
            except Exception as role_error:
                logger.warning(f"Failed to assign role to {join_request.user_email}: {role_error}")
                # Don't fail join approval if role assignment fails
```

**Step 2: Run existing tests**

Run: `pytest tests/unit/mcpgateway/services/test_team_management_service.py -k "approve_join" -v`
Expected: PASS

**Step 3: Commit**

```bash
git add mcpgateway/services/team_management_service.py
git commit -m "feat: assign RBAC role when approving join request"
```

---

## Task 4: Add RBAC Role Revocation in remove_member_from_team

**Files:**
- Modify: `mcpgateway/services/team_management_service.py:552-620`

**Step 1: Add role revocation after successful removal**

After line 598 (after `self.db.commit()`), add:

```python
            # Revoke team-scoped RBAC role from removed member
            try:
                team_member_role = await self.role_service.get_role_by_name(
                    settings.default_team_member_role, scope="team"
                )
                if team_member_role:
                    revoked = await self.role_service.revoke_role_from_user(
                        user_email=user_email,
                        role_id=team_member_role.id,
                        scope="team",
                        scope_id=team_id
                    )
                    if revoked:
                        logger.info(f"Revoked {settings.default_team_member_role} role from {user_email} for team {team_id}")
                    else:
                        logger.debug(f"No {settings.default_team_member_role} role to revoke for {user_email} on team {team_id}")
                else:
                    logger.warning(f"Role '{settings.default_team_member_role}' not found. Cannot revoke role from {user_email}.")
            except Exception as role_error:
                logger.warning(f"Failed to revoke role from {user_email}: {role_error}")
                # Don't fail member removal if role revocation fails
```

**Step 2: Run existing tests**

Run: `pytest tests/unit/mcpgateway/services/test_team_management_service.py -k "remove_member" -v`
Expected: PASS

**Step 3: Commit**

```bash
git add mcpgateway/services/team_management_service.py
git commit -m "feat: revoke RBAC role when removing team member"
```

---

## Task 5: Write Unit Tests for RBAC Role Assignment

**Files:**
- Modify: `tests/unit/mcpgateway/services/test_team_management_service.py`

**Step 1: Add test for add_member_to_team with role assignment**

Add after existing `test_add_member_success` test (around line 520):

```python
    @pytest.mark.asyncio
    async def test_add_member_assigns_rbac_role(self, service, mock_db, mock_team, mock_user):
        """Test that adding a member assigns the configured RBAC role."""
        # Setup mocks
        mock_db.query.return_value.filter.return_value.first.return_value = None  # No existing membership
        mock_db.query.return_value.filter.return_value.count.return_value = 1  # Member count
        
        # Mock role service
        mock_role = MagicMock()
        mock_role.id = "role123"
        mock_role.is_active = True
        
        with patch.object(service, 'role_service', new_callable=MagicMock) as mock_role_service:
            mock_role_service.get_role_by_name = AsyncMock(return_value=mock_role)
            mock_role_service.get_user_role_assignment = AsyncMock(return_value=None)
            mock_role_service.assign_role_to_user = AsyncMock(return_value=MagicMock())
            
            # Patch get_team_by_id and user lookup
            with patch.object(service, 'get_team_by_id', new_callable=AsyncMock) as mock_get_team:
                mock_get_team.return_value = mock_team
                with patch.object(mock_db, 'query') as mock_query:
                    # Setup user lookup
                    def mock_query_side_effect(model):
                        mock_result = MagicMock()
                        if model == EmailUser:
                            mock_result.filter.return_value.first.return_value = mock_user
                        elif model == EmailTeamMember:
                            mock_result.filter.return_value.first.return_value = None  # No existing
                            mock_result.filter.return_value.count.return_value = 1
                        return mock_result
                    mock_query.side_effect = mock_query_side_effect
                    
                    # Execute
                    result = await service.add_member_to_team(
                        team_id="team123",
                        user_email="user@example.com",
                        role="member",
                        invited_by="admin@example.com"
                    )
                    
                    # Verify
                    assert result is True
                    mock_role_service.get_role_by_name.assert_called_once_with("viewer", scope="team")
                    mock_role_service.assign_role_to_user.assert_called_once()
                    call_args = mock_role_service.assign_role_to_user.call_args[1]
                    assert call_args['user_email'] == "user@example.com"
                    assert call_args['role_id'] == "role123"
                    assert call_args['scope'] == "team"
                    assert call_args['scope_id'] == "team123"
```

**Step 2: Add test for add_member_to_team with existing role (no duplicate)**

```python
    @pytest.mark.asyncio
    async def test_add_member_skips_role_if_already_assigned(self, service, mock_db, mock_team, mock_user):
        """Test that adding a member skips role assignment if already has role."""
        # Setup mocks
        mock_db.query.return_value.filter.return_value.first.return_value = None  # No existing membership
        mock_db.query.return_value.filter.return_value.count.return_value = 1  # Member count
        
        # Mock role service
        mock_role = MagicMock()
        mock_role.id = "role123"
        mock_role.is_active = True
        existing_assignment = MagicMock()
        existing_assignment.is_active = True
        
        with patch.object(service, 'role_service', new_callable=MagicMock) as mock_role_service:
            mock_role_service.get_role_by_name = AsyncMock(return_value=mock_role)
            mock_role_service.get_user_role_assignment = AsyncMock(return_value=existing_assignment)
            mock_role_service.assign_role_to_user = AsyncMock(return_value=MagicMock())
            
            # Patch get_team_by_id and user lookup
            with patch.object(service, 'get_team_by_id', new_callable=AsyncMock) as mock_get_team:
                mock_get_team.return_value = mock_team
                with patch.object(mock_db, 'query') as mock_query:
                    # Setup user lookup
                    def mock_query_side_effect(model):
                        mock_result = MagicMock()
                        if model == EmailUser:
                            mock_result.filter.return_value.first.return_value = mock_user
                        elif model == EmailTeamMember:
                            mock_result.filter.return_value.first.return_value = None
                            mock_result.filter.return_value.count.return_value = 1
                        return mock_result
                    mock_query.side_effect = mock_query_side_effect
                    
                    # Execute
                    result = await service.add_member_to_team(
                        team_id="team123",
                        user_email="user@example.com",
                        role="member",
                        invited_by="admin@example.com"
                    )
                    
                    # Verify - should NOT assign role again
                    assert result is True
                    mock_role_service.get_role_by_name.assert_called_once()
                    mock_role_service.assign_role_to_user.assert_not_called()
```

**Step 3: Add test for remove_member_from_team with role revocation**

```python
    @pytest.mark.asyncio
    async def test_remove_member_revokes_rbac_role(self, service, mock_db, mock_team):
        """Test that removing a member revokes the RBAC role."""
        # Setup membership mock
        mock_membership = MagicMock(spec=EmailTeamMember)
        mock_membership.role = "member"
        mock_membership.is_active = True
        
        # Mock role service
        mock_role = MagicMock()
        mock_role.id = "role123"
        mock_role.is_active = True
        
        with patch.object(service, 'role_service', new_callable=MagicMock) as mock_role_service:
            mock_role_service.get_role_by_name = AsyncMock(return_value=mock_role)
            mock_role_service.revoke_role_from_user = AsyncMock(return_value=True)
            
            # Patch get_team_by_id
            with patch.object(service, 'get_team_by_id', new_callable=AsyncMock) as mock_get_team:
                mock_get_team.return_value = mock_team
                with patch.object(mock_db, 'query') as mock_query:
                    mock_result = MagicMock()
                    mock_result.filter.return_value.first.return_value = mock_membership
                    mock_query.return_value = mock_result
                    
                    # Execute
                    result = await service.remove_member_from_team(
                        team_id="team123",
                        user_email="user@example.com",
                        removed_by="admin@example.com"
                    )
                    
                    # Verify
                    assert result is True
                    mock_role_service.get_role_by_name.assert_called_once_with("viewer", scope="team")
                    mock_role_service.revoke_role_from_user.assert_called_once_with(
                        user_email="user@example.com",
                        role_id="role123",
                        scope="team",
                        scope_id="team123"
                    )
```

**Step 4: Run new tests**

Run: `pytest tests/unit/mcpgateway/services/test_team_management_service.py -k "rbac_role" -v`
Expected: PASS (all 3 tests)

**Step 5: Commit**

```bash
git add tests/unit/mcpgateway/services/test_team_management_service.py
git commit -m "test: add RBAC role assignment/revocation tests"
```

---

## Task 6: Run Full Test Suite

**Step 1: Run all team management tests**

Run: `pytest tests/unit/mcpgateway/services/test_team_management_service.py -v`
Expected: All tests PASS

**Step 2: Check for regressions**

Run: `pytest tests/unit/mcpgateway/services/ -v --tb=short`
Expected: All tests PASS

**Step 3: Run doctests**

Run: `python -m doctest mcpgateway/services/team_management_service.py -v 2>&1 | tail -5`
Expected: No failures

**Step 4: Final commit**

```bash
git log --oneline -6
```
Expected: 6 commits for this feature

---

## Verification Checklist

- [ ] RoleService lazy initialization works without circular imports
- [ ] `add_member_to_team` assigns RBAC role after adding member
- [ ] `approve_join_request` assigns RBAC role after approving
- [ ] `remove_member_from_team` revokes RBAC role after removing
- [ ] Duplicate role assignments are prevented (checked before assign)
- [ ] Missing role warnings are logged but don't fail operations
- [ ] All existing tests still pass
- [ ] New tests cover role assignment/revocation scenarios
- [ ] Edge case: role already assigned (no duplicate)
- [ ] Edge case: role not found (warning logged, operation continues)

---

## Post-Implementation Notes

After this fix:
1. Setting `DEFAULT_TEAM_MEMBER_ROLE=developer` in `.env` will give new team members the `developer` role
2. Users removed from teams will lose their team-scoped RBAC permissions
3. Existing team members added before this fix will need manual role assignment
4. Personal team creators already get `team_admin` role via user creation flow
