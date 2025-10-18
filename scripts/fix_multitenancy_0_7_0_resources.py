#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP Gateway v0.7.0 Multitenancy Resource Fix

This script finds and fixes resources that lack proper team assignments
after the v0.7.0 → v0.7.0 multitenancy migration. This can happen if:
- Resources were created after the initial migration
- Migration was incomplete for some resources
- Database had edge cases not handled by the main migration

Fixes: servers, tools, resources, prompts, gateways, a2a_agents

Usage:
    python3 scripts/fix_multitenancy_0_7_0_resources.py
"""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from mcpgateway.db import SessionLocal, EmailUser, EmailTeam, Server, Tool, Resource, Prompt, Gateway, A2AAgent
    from mcpgateway.config import settings
    from sqlalchemy import text
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're running this from the project root directory")
    sys.exit(1)


def fix_unassigned_resources():
    """Fix resources that lack proper team assignments."""

    print("🔧 MCP Gateway - Fix Unassigned Resources")
    print("=" * 50)

    try:
        with SessionLocal() as db:
            # 1. Find admin user and personal team
            print("🔍 Finding admin user and personal team...")
            admin_email = settings.platform_admin_email
            admin_user = db.query(EmailUser).filter(EmailUser.email == admin_email, EmailUser.is_admin == True).first()

            if not admin_user:
                print(f"❌ Admin user not found: {admin_email}")
                print("Make sure the migration has run and admin user exists")
                return False

            personal_team = db.query(EmailTeam).filter(EmailTeam.created_by == admin_user.email, EmailTeam.is_personal == True, EmailTeam.is_active == True).first()

            if not personal_team:
                print(f"❌ Personal team not found for admin: {admin_user.email}")
                return False

            print(f"✅ Found admin: {admin_user.email}")
            print(f"✅ Found personal team: {personal_team.name} ({personal_team.id})")

            # 2. Fix each resource type
            resource_types = [("servers", Server), ("tools", Tool), ("resources", Resource), ("prompts", Prompt), ("gateways", Gateway), ("a2a_agents", A2AAgent)]

            total_fixed = 0

            for table_name, resource_model in resource_types:
                print(f"\n📋 Processing {table_name}...")

                # Find unassigned resources
                unassigned = db.query(resource_model).filter((resource_model.team_id == None) | (resource_model.owner_email == None) | (resource_model.visibility == None)).all()

                if not unassigned:
                    print(f"   ✅ No unassigned {table_name} found")
                    continue

                print(f"   🔧 Fixing {len(unassigned)} unassigned {table_name}...")

                for resource in unassigned:
                    resource_name = getattr(resource, "name", "Unknown")
                    print(f"      - Assigning: {resource_name}")

                    # Assign to admin's personal team
                    resource.team_id = personal_team.id
                    resource.owner_email = admin_user.email

                    # Set visibility to public if not already set
                    if not hasattr(resource, "visibility") or resource.visibility is None:
                        resource.visibility = "public"

                    total_fixed += 1

                # Commit changes for this resource type
                db.commit()
                print(f"   ✅ Fixed {len(unassigned)} {table_name}")

            print(f"\n🎉 Successfully fixed {total_fixed} resources!")
            print(f"   All resources now assigned to: {personal_team.name}")
            print(f"   Owner email: {admin_user.email}")
            print("   Default visibility: public")

            return True

    except Exception as e:
        print(f"\n❌ Fix operation failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    """Main function with user confirmation."""

    print("This script will assign unassigned resources to the platform admin's personal team.")
    print("This is safe and will make resources visible in the team-based UI.\n")

    response = input("Continue? (y/N): ").lower().strip()
    if response not in ("y", "yes"):
        print("Operation cancelled.")
        return

    if fix_unassigned_resources():
        print("\n✅ Fix completed successfully!")
        print("🔍 Run verification script to confirm: python3 scripts/verify_multitenancy_0_7_0_migration.py")
    else:
        print("\n❌ Fix operation failed. Check the errors above.")


if __name__ == "__main__":
    main()
