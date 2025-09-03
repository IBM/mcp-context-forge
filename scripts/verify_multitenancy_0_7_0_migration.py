#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP Gateway v0.7.0 Multitenancy Migration Verification

This script verifies that the v0.6.0 → v0.7.0 multitenancy migration 
completed successfully and that old servers/resources are visible in 
the new team-based system.

Checks:
- Platform admin user creation
- Personal team setup
- Resource team assignments (servers, tools, resources)
- Visibility settings
- Team membership

Usage:
    python3 scripts/verify_multitenancy_0_7_0_migration.py
"""

import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from mcpgateway.db import (
        SessionLocal, EmailUser, EmailTeam, EmailTeamMember, 
        Server, Tool, Resource, Role, UserRole
    )
    from mcpgateway.config import settings
    from sqlalchemy import text
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're running this from the project root directory")
    sys.exit(1)


def verify_migration():
    """Verify the multitenancy migration was successful."""
    
    print("🔍 MCP Gateway v0.7.0 Multitenancy Migration Verification")
    print("📅 Migration: v0.6.0 → v0.7.0")  
    print("=" * 65)
    
    success = True
    
    try:
        with SessionLocal() as db:
            
            # 1. Check admin user exists
            print("\n📋 1. ADMIN USER CHECK")
            admin_email = settings.platform_admin_email
            admin_user = db.query(EmailUser).filter(
                EmailUser.email == admin_email,
                EmailUser.is_admin == True
            ).first()
            
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
                personal_team = db.query(EmailTeam).filter(
                    EmailTeam.created_by == admin_user.email,
                    EmailTeam.is_personal == True,
                    EmailTeam.is_active == True
                ).first()
                
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
            resource_types = [
                ("Servers", Server),
                ("Tools", Tool),
                ("Resources", Resource)
            ]
            
            for resource_name, resource_model in resource_types:
                total_count = db.query(resource_model).count()
                assigned_count = db.query(resource_model).filter(
                    resource_model.team_id != None,
                    resource_model.owner_email != None,
                    resource_model.visibility != None
                ).count()
                unassigned_count = total_count - assigned_count
                
                print(f"   {resource_name}:")
                print(f"      Total: {total_count}")
                print(f"      Assigned to teams: {assigned_count}")
                print(f"      Unassigned: {unassigned_count}")
                
                if unassigned_count > 0:
                    print(f"      ❌ {unassigned_count} {resource_name.lower()} lack team assignment!")
                    success = False
                    
                    # Show details of unassigned resources
                    unassigned = db.query(resource_model).filter(
                        (resource_model.team_id == None) |
                        (resource_model.owner_email == None) |
                        (resource_model.visibility == None)
                    ).limit(3).all()
                    
                    for resource in unassigned:
                        name = getattr(resource, 'name', 'Unknown')
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
                    if hasattr(resource_model, 'visibility'):
                        visibility_counts = {}
                        resources = db.query(resource_model).all()
                        
                        for resource in resources:
                            vis = getattr(resource, 'visibility', 'unknown')
                            visibility_counts[vis] = visibility_counts.get(vis, 0) + 1
                        
                        print(f"   {resource_name}:")
                        for visibility, count in visibility_counts.items():
                            print(f"      {visibility}: {count}")
            
            # 5. Database schema validation  
            print("\n🗄️  5. DATABASE SCHEMA VALIDATION")
            
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
            
            # Verify resource models have team attributes
            resource_models = [
                ("Server", Server),
                ("Tool", Tool), 
                ("Resource", Resource)
            ]
            
            for model_name, model_class in resource_models:
                try:
                    # Check if model has team attributes
                    sample = db.query(model_class).first()
                    if sample:
                        has_team_id = hasattr(sample, 'team_id')
                        has_owner_email = hasattr(sample, 'owner_email') 
                        has_visibility = hasattr(sample, 'visibility')
                        
                        if has_team_id and has_owner_email and has_visibility:
                            print(f"   ✅ {model_name}: has multitenancy attributes")
                        else:
                            missing_attrs = []
                            if not has_team_id: missing_attrs.append('team_id')
                            if not has_owner_email: missing_attrs.append('owner_email')
                            if not has_visibility: missing_attrs.append('visibility')
                            print(f"   ❌ {model_name}: missing {missing_attrs}")
                            success = False
                    else:
                        print(f"   ⚠️  {model_name}: no records to check")
                except Exception as e:
                    print(f"   ❌ {model_name}: model access failed - {e}")
                    success = False
            
            if "core_auth" in schema_checks and "rbac" in schema_checks:
                print("   ✅ Multitenancy schema fully operational")
            
            # 6. Team membership check  
            print("\n👥 6. TEAM MEMBERSHIP CHECK")
            if admin_user and personal_team:
                membership = db.query(EmailTeamMember).filter(
                    EmailTeamMember.team_id == personal_team.id,
                    EmailTeamMember.user_email == admin_user.email,
                    EmailTeamMember.is_active == True
                ).first()
                
                if membership:
                    print(f"   ✅ Admin is member of personal team")
                    print(f"      Role: {membership.role}")
                    print(f"      Joined: {membership.joined_at}")
                else:
                    print(f"   ❌ Admin is not a member of personal team")
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
        print(f"\n🚀 You can now access the admin UI at: /admin")
        print(f"📧 Login with admin email: {settings.platform_admin_email}")
        return True
    else:
        print("❌ MIGRATION VERIFICATION: FAILED!")
        print("\n⚠️  Some issues were detected. Please check the details above.")
        print("💡 You may need to re-run the migration or check your configuration.")
        print(f"\n📋 To re-run migration: python3 -m mcpgateway.bootstrap_db")
        print(f"🔧 Make sure PLATFORM_ADMIN_EMAIL is set in your .env file")
        return False


if __name__ == "__main__":
    verify_migration()