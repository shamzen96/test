"""Domain and HTTP exceptions for multi-tenant handling."""

from fastapi import HTTPException, status


class TenantException(HTTPException):
    """Base exception for tenant-related errors."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(status_code=status_code, detail=detail)


class TenantNotFoundError(TenantException):
    """Raised when the specified tenant does not exist."""

    def __init__(self, detail: str = "Tenant not found"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class TenantInactiveError(TenantException):
    """Raised when attempting to access a deactivated or suspended tenant."""

    def __init__(self, detail: str = "Tenant is inactive"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class InvalidTenantSlugError(TenantException):
    """Raised when tenant slug fails validation or contains reserved keywords."""

    def __init__(self, detail: str = "Invalid tenant identifier"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class AuthenticationRequiredError(TenantException):
    """Raised when authentication credentials are missing or invalid."""

    def __init__(self, detail: str = "Authentication required"):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


class CrossTenantAccessError(TenantException):
    """Raised when a user attempts cross-tenant access."""

    def __init__(self, detail: str = "Access denied"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class PermissionDeniedError(TenantException):
    """Raised when a user lacks required permissions."""

    def __init__(self, detail: str = "Permission denied"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class ResourceNotFoundError(TenantException):
    """Raised when a requested resource is not found."""

    def __init__(self, detail: str = "Resource not found"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class ConflictError(TenantException):
    """Raised when a resource conflict occurs (e.g. duplicate slug or email)."""

    def __init__(self, detail: str = "Conflict with existing resource"):
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)

