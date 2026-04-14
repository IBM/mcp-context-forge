#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ContextForge v0.7.0 Multitenancy Migration Verification

This script verifies that the v0.6.0 → v0.7.0 multitenancy migration
completed successfully and that old servers/resources are visible in
the new team-based system.

Checks:
- Platform admin user creation
- Personal team setup
- Resource team assignments (servers, tools, resources, prompts, gateways, a2a_agents)
- Visibility settings
- Team membership

Usage:
    python3 scripts/verify_multitenancy_0_7_0_migration.py
"""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from mcpgateway.db import (
        SessionLocal,
        EmailUser,
        EmailTeam,
        EmailTeamMember,
        Server,
        Tool,
        Resource,
        Prompt,
        Gateway,
        A2AAgent,
        Role,
        UserRole,
        EmailApiToken,
        TokenUsageLog,
        TokenRevocation,
        SSOProvider,
        SSOAuthSession,
        PendingUserApproval,
    )
    from mcpgateway.config import settings
    from sqlalchemy import text, inspect
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're running this from the project root directory")
    sys.exit(1)


def verify_migration():
    """Verify the multitenancy migration was successful."""

    print("🔍 ContextForge v0.7.0 Multitenancy Migration Verification")
    print("📅 Migration: v0.6.0 → v0.7.0")
    print("=" * 65)

    success = True

    try:
        with SessionLocal() as db:
            # 1. Check admin user exists
            print("\n📋 1. ADMIN USER CHECK")
            admin_email = settings.platform_admin_email
            admin_user = db.query(EmailUser).filter(EmailUser.email == admin_email, EmailUser.is_admin == True).first()

            if admin_user:
                print(f"   ✅ Admin user found: {admin_user.email}")
                print(f"      Full name: {admin_user.full_name}")
                print(f"      Is admin: {admin_user.is_admin}")
                print(f"      Is active: {admin_user.is_active}")
            else:
                print(f"   ❌ Admin user not found: {admin_email}")
                success = False

            # 2. Check personal team exists
            print("\n🏢 2. PERSONAL TEAM CHECK")
            if admin_user:
                personal_team = db.query(EmailTeam).filter(EmailTeam.created_by == admin_user.email, EmailTeam.is_personal == True, EmailTeam.is_active == True).first()

                if personal_team:
                    print(f"   ✅ Personal team found: {personal_team.name}")
                    print(f"      Team ID: {personal_team.id}")
                    print(f"      Slug: {personal_team.slug}")
                    print(f"      Visibility: {personal_team.visibility}")
                else:
                    print(f"   ❌ Personal team not found for admin: {admin_user.email}")
                    success = False
            else:
                personal_team = None
                print("   ⚠️  Cannot check personal team (admin user missing)")

            # 3. Check resource assignments
            print("\n📦 3. RESOURCE ASSIGNMENT CHECK")
            resource_types = [("Servers", Server), ("Tools", Tool), ("Resources", Resource), ("Prompts", Prompt), ("Gateways", Gateway), ("A2A Agents", A2AAgent)]

            for resource_name, resource_model in resource_types:
                total_count = db.query(resource_model).count()
                assigned_count = db.query(resource_model).filter(resource_model.team_id is not None, resource_model.owner_email is not None, resource_model.visibility is not None).count()
                unassigned_count = total_count - assigned_count

                print(f"   {resource_name}:")
                print(f"      Total: {total_count}")
                print(f"      Assigned to teams: {assigned_count}")
                print(f"      Unassigned: {unassigned_count}")

                if unassigned_count > 0:
                    print(f"      ❌ {unassigned_count} {resource_name.lower()} lack team assignment!")
                    success = False

                    # Show details of unassigned resources
                    unassigned = db.query(resource_model).filter((resource_model.team_id is None) | (resource_model.owner_email is None) | (resource_model.visibility is None)).limit(3).all()

                    for resource in unassigned:
                        name = getattr(resource, "name", "Unknown")
                        print(f"         - {name} (ID: {resource.id})")
                        print(f"           team_id: {getattr(resource, 'team_id', 'N/A')}")
                        print(f"           owner_email: {getattr(resource, 'owner_email', 'N/A')}")
                        print(f"           visibility: {getattr(resource, 'visibility', 'N/A')}")
                else:
                    print(f"      ✅ All {resource_name.lower()} properly assigned")

            # 4. Check visibility distribution
            if personal_team:
                print("\n👁️  4. VISIBILITY DISTRIBUTION")

                for resource_name, resource_model in resource_types:
                    if hasattr(resource_model, "visibility"):
                        visibility_counts = {}
                        resources = db.query(resource_model).all()

                        for resource in resources:
                            vis = getattr(resource, "visibility", "unknown")
                            visibility_counts[vis] = visibility_counts.get(vis, 0) + 1

                        print(f"   {resource_name}:")
                        for visibility, count in visibility_counts.items():
                            print(f"      {visibility}: {count}")

            # 5. Database schema validation
            print("\n🗄️  5. DATABASE SCHEMA VALIDATION")

            # Check database tables exist
            inspector = inspect(db.bind)
            existing_tables = set(inspector.get_table_names())

            # Expected multitenancy tables from migration
            expected_auth_tables = {
                "email_users",
                "email_auth_events",
                "email_teams",
                "email_team_members",
                "email_team_invitations",
                "email_team_join_requests",
                "pending_user_approvals",
                "email_api_tokens",
                "token_usage_logs",
                "token_revocations",
                "sso_providers",
                "sso_auth_sessions",
                "roles",
                "user_roles",
                "permission_audit_log",
            }

            missing_tables = expected_auth_tables - existing_tables
            if missing_tables:
                print(f"   ❌ Missing tables: {sorted(missing_tables)}")
                success = False
            else:
                print(f"   ✅ All {len(expected_auth_tables)} multitenancy tables exist")

            # Check if we can access multitenancy models (proves schema exists)
            schema_checks = []
            try:
                user_count = db.query(EmailUser).count()
                team_count = db.query(EmailTeam).count()
                member_count = db.query(EmailTeamMember).count()
                print(f"   ✅ EmailUser model: {user_count} records")
                print(f"   ✅ EmailTeam model: {team_count} records")
                print(f"   ✅ EmailTeamMember model: {member_count} records")
                schema_checks.append("core_auth")
            except Exception as e:
                print(f"   ❌ Core auth models inaccessible: {e}")
                success = False

            try:
                role_count = db.query(Role).count()
                user_role_count = db.query(UserRole).count()
                print(f"   ✅ Role model: {role_count} records")
                print(f"   ✅ UserRole model: {user_role_count} records")
                schema_checks.append("rbac")
            except Exception as e:
                print(f"   ❌ RBAC models inaccessible: {e}")
                success = False

            # Check token management tables
            try:
                token_count = db.query(EmailApiToken).count()
                usage_count = db.query(TokenUsageLog).count()
                revocation_count = db.query(TokenRevocation).count()
                print(f"   ✅ EmailApiToken model: {token_count} records")
                print(f"   ✅ TokenUsageLog model: {usage_count} records")
                print(f"   ✅ TokenRevocation model: {revocation_count} records")
                schema_checks.append("token_management")
            except Exception as e:
                print(f"   ❌ Token management models inaccessible: {e}")
                success = False

            # Check SSO tables
            try:
                sso_provider_count = db.query(SSOProvider).count()
                sso_session_count = db.query(SSOAuthSession).count()
                pending_count = db.query(PendingUserApproval).count()
                print(f"   ✅ SSOProvider model: {sso_provider_count} records")
                print(f"   ✅ SSOAuthSession model: {sso_session_count} records")
                print(f"   ✅ PendingUserApproval model: {pending_count} records")
                schema_checks.append("sso")
            except Exception as e:
                print(f"   ❌ SSO models inaccessible: {e}")
                success = False

            # Verify resource models have team attributes
            resource_models = [("Server", Server), ("Tool", Tool), ("Resource", Resource), ("Prompt", Prompt), ("Gateway", Gateway), ("A2AAgent", A2AAgent)]

            for model_name, model_class in resource_models:
                try:
                    # Check if model has team attributes
                    sample = db.query(model_class).first()
                    if sample:
                        has_team_id = hasattr(sample, "team_id")
                        has_owner_email = hasattr(sample, "owner_email")
                        has_visibility = hasattr(sample, "visibility")

                        if has_team_id and has_owner_email and has_visibility:
                            print(f"   ✅ {model_name}: has multitenancy attributes")
                        else:
                            missing_attrs = []
                            if not has_team_id:
                                missing_attrs.append("team_id")
                            if not has_owner_email:
                                missing_attrs.append("owner_email")
                            if not has_visibility:
                                missing_attrs.append("visibility")
                            print(f"   ❌ {model_name}: missing {missing_attrs}")
                            success = False
                    else:
                        print(f"   ⚠️  {model_name}: no records to check")
                except Exception as e:
                    print(f"   ❌ {model_name}: model access failed - {e}")
                    success = False

            if len(schema_checks) >= 4 and "core_auth" in schema_checks and "rbac" in schema_checks and "token_management" in schema_checks and "sso" in schema_checks:
                print("   ✅ Multitenancy schema fully operational")
            elif len(schema_checks) >= 2:
                print(f"   ⚠️  Partial schema operational ({len(schema_checks)}/4 components working)")
            else:
                print("   ❌ Schema validation failed")

            # 6. Team membership check
            print("\n👥 6. TEAM MEMBERSHIP CHECK")
            if admin_user and personal_team:
                membership = db.query(EmailTeamMember).filter(EmailTeamMember.team_id == personal_team.id, EmailTeamMember.user_email == admin_user.email, EmailTeamMember.is_active == True).first()

                if membership:
                    print("   ✅ Admin is member of personal team")
                    print(f"      Role: {membership.role}")
                    print(f"      Joined: {membership.joined_at}")
                else:
                    print("   ❌ Admin is not a member of personal team")
                    success = False

    except Exception as e:
        print(f"\n❌ Verification failed with error: {e}")
        import traceback

        traceback.print_exc()
        return False

    print("\n" + "=" * 65)
    if success:
        print("🎉 MIGRATION VERIFICATION: SUCCESS!")
        print("\n✅ All checks passed. Your migration completed successfully.")
        print("✅ Old servers should now be visible in the Virtual Servers list.")
        print("✅ Resources are properly assigned to teams with appropriate visibility.")
        print("\n🚀 You can now access the admin UI at: /admin")
        print(f"📧 Login with admin email: {settings.platform_admin_email}")
        return True
    else:
        print("❌ MIGRATION VERIFICATION: FAILED!")
        print("\n⚠️  Some issues were detected. Please check the details above.")
        print("💡 You may need to re-run the migration or check your configuration.")
        print("\n📋 To re-run migration: python3 -m mcpgateway.bootstrap_db")
        print("🔧 Make sure PLATFORM_ADMIN_EMAIL is set in your .env file")
        return False


if __name__ == "__main__":
    verify_migration()
