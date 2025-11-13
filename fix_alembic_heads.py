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

def main():
    """Fix the Alembic multiple heads issue."""
    # Change to the project directory
    project_dir = Path(__file__).parent
    
    print("🔍 Checking Alembic status...")
    
    # Check current heads
    heads_output = run_command("alembic -c mcpgateway/alembic.ini heads", cwd=project_dir)
    if heads_output:
        print("Current heads:")
        print(heads_output)
    
    # Check history
    history_output = run_command("alembic -c mcpgateway/alembic.ini history", cwd=project_dir)
    if history_output:
        print("\nMigration history (last 10 lines):")
        print('\n'.join(history_output.split('\n')[-10:]))
    
    print("\n🔧 Creating merge revision to fix multiple heads...")
    
    # Create a merge revision
    merge_result = run_command(
        "alembic -c mcpgateway/alembic.ini merge -m 'merge multiple heads'",
        cwd=project_dir
    )
    
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
            final_heads = run_command("alembic -c mcpgateway/alembic.ini heads", cwd=project_dir)
            if final_heads:
                print("Current heads after fix:")
                print(final_heads)
                
                # Check if we now have a single head
                head_lines = [line for line in final_heads.split('\n') if line.strip()]
                if len(head_lines) == 1:
                    print("✅ Successfully resolved to single head!")
                    return True
                else:
                    print("⚠️  Still have multiple heads, manual intervention may be needed")
                    return False
            else:
                print("❌ Could not verify heads status")
                return False
        else:
            print("❌ Failed to upgrade database")
            return False
    else:
        print("❌ Failed to create merge revision")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
