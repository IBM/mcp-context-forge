#!/usr/bin/env python3
"""
Script to fix Alembic multiple heads issue.
This script will create a merge revision to resolve the multiple heads.
"""

import subprocess
import sys
from pathlib import Path


def run_command(cmd, cwd=None):
    """Run a shell command and return the result."""
    try:
        result = subprocess.run(
            cmd, 
            shell=True, 
            cwd=cwd,
            capture_output=True, 
            text=True, 
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error running command '{cmd}': {e}")
        print(f"stderr: {e.stderr}")
        return None


def check_multiple_heads():
    """Check if there are multiple heads in the Alembic migration."""
    project_dir = Path(__file__).parent
    try:
        heads_output = run_command("alembic -c mcpgateway/alembic.ini heads", cwd=project_dir)
        if heads_output:
            # Count non-empty lines in heads output
            head_lines = [line.strip() for line in heads_output.split('\n') if line.strip()]
            return len(head_lines) > 1, head_lines
    except Exception as e:
        print(f"Error checking heads: {e}")
        # Fallback: try to detect from error messages
        try:
            # Try current command which might reveal multiple heads error
            run_command("alembic -c mcpgateway/alembic.ini current", cwd=project_dir)
            return False, []
        except Exception:
            # If current fails, likely multiple heads
            return True, ["f1822fcc2ca2", "f3a3a3d901b8"]  # Known heads from error
    return False, []


def get_revision_heads():
    """Get all revision heads from the migration directory."""
    project_dir = Path(__file__).parent
    try:
        # Get all heads including unmerged ones
        result = run_command("alembic -c mcpgateway/alembic.ini heads", cwd=project_dir)
        if result:
            heads = []
            for line in result.split('\n'):
                line = line.strip()
                if line and not line.startswith('INFO'):
                    # Extract revision ID (first part before space or parentheses)
                    rev_id = line.split(' ')[0].split('(')[0]
                    if rev_id:
                        heads.append(rev_id)
            return heads
    except Exception as e:
        print(f"Error getting revision heads: {e}")
    return []


def main():
    """Fix the Alembic multiple heads issue."""
    # Change to the project directory
    project_dir = Path(__file__).parent
    
    print("🔍 Checking Alembic status...")
    
    # Check if we actually have multiple heads
    has_multiple_heads, heads = check_multiple_heads()
    
    if not has_multiple_heads:
        print("✅ Only one head found, no action needed")
        return True
    
    print(f"⚠️  Multiple heads detected: {len(heads)} heads")
    for head in heads:
        print(f"  - {head}")
    
    # Get more detailed head information
    all_heads = get_revision_heads()
    if all_heads:
        print(f"All revision heads: {all_heads}")
    
    # Check current heads with more verbose output
    heads_output = run_command("alembic -c mcpgateway/alembic.ini heads --verbose", cwd=project_dir)
    if heads_output:
        print("Current heads (verbose):")
        print(heads_output)
    
    # Check history
    history_output = run_command("alembic -c mcpgateway/alembic.ini history", cwd=project_dir)
    if history_output:
        print("\nMigration history (last 10 lines):")
        print('\n'.join(history_output.split('\n')[-10:]))
    
    print("\n🔧 Creating merge revision to fix multiple heads...")
    
    # Create a merge revision - specify the heads explicitly if we know them
    merge_cmd = "alembic -c mcpgateway/alembic.ini merge"
    if all_heads and len(all_heads) >= 2:
        # Explicitly specify heads to merge
        merge_cmd += f" {' '.join(all_heads[:2])}"  # Merge first two heads
    merge_cmd += " -m 'merge multiple heads'"
    
    merge_result = run_command(merge_cmd, cwd=project_dir)
    
    if merge_result is not None:
        print("✅ Merge revision created successfully")
        print(f"Output: {merge_result}")
        
        print("\n🔄 Upgrading to the new merged head...")
        upgrade_result = run_command("alembic -c mcpgateway/alembic.ini upgrade head", cwd=project_dir)
        
        if upgrade_result is not None:
            print("✅ Database upgraded successfully")
            print("🎉 Alembic heads issue resolved!")
            
            # Verify the fix
            print("\n🔍 Verifying fix...")
            final_has_multiple_heads, final_heads = check_multiple_heads()
            
            if not final_has_multiple_heads:
                print("✅ Successfully resolved to single head!")
                print(f"Final head: {final_heads[0] if final_heads else 'Unknown'}")
                return True
            else:
                print("⚠️  Still have multiple heads, manual intervention may be needed")
                return False
        else:
            print("❌ Failed to upgrade database")
            return False
    else:
        print("❌ Failed to create merge revision")
        
        # Try alternative approach: reset to a specific head and then upgrade
        print("\n🔄 Trying alternative approach: reset and upgrade...")
        
        # Try to reset to one of the known heads first
        known_heads = ["f1822fcc2ca2", "f3a3a3d901b8"]
        for head in known_heads:
            print(f"Trying to stamp to head {head}...")
            stamp_result = run_command(f"alembic -c mcpgateway/alembic.ini stamp {head}", cwd=project_dir)
            if stamp_result is not None:
                print(f"✅ Successfully stamped to {head}")
                
                # Now try to upgrade to head
                upgrade_result = run_command("alembic -c mcpgateway/alembic.ini upgrade head", cwd=project_dir)
                if upgrade_result is not None:
                    print("✅ Successfully upgraded to head")
                    return True
                break
        
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
