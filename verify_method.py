import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from mcpgateway.services.permission_service import PermissionService

print(f"PermissionService file: {sys.modules['mcpgateway.services.permission_service'].__file__}")
print(f"Has check_admin_permission: {hasattr(PermissionService, 'check_admin_permission')}")
print(f"Dir: {dir(PermissionService)}")
