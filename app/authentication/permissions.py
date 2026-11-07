"""Role-based and permission-based authorization checks."""

from app.core.exceptions import PermissionDeniedError
from app.database.models import TenantUser


class PermissionChecker:
    """Dependency for verifying that an authenticated user possesses the required permission."""

    def __init__(self, required_permission: str):
        self.required_permission = required_permission

    def __call__(
        self,
        tenant_user: TenantUser,
    ) -> TenantUser:
        # If user is admin in this tenant or superuser, grant full access
        if tenant_user.user.is_superuser or (tenant_user.role and tenant_user.role.name == "admin"):
            return tenant_user

        # Check explicit role permissions
        if tenant_user.role and tenant_user.role.permissions:
            user_permissions = {rp.permission.code for rp in tenant_user.role.permissions}
            if self.required_permission in user_permissions:
                return tenant_user

        raise PermissionDeniedError(f"Missing required permission: '{self.required_permission}'")


def require_role(allowed_roles: list[str]):
    """Helper dependency that checks if the user's role is in the allowed roles list."""
    def role_dependency(tenant_user: TenantUser) -> TenantUser:
        if tenant_user.user.is_superuser:
            return tenant_user
        if not tenant_user.role or tenant_user.role.name not in allowed_roles:
            raise PermissionDeniedError(f"Role must be one of: {', '.join(allowed_roles)}")
        return tenant_user
    return role_dependency
