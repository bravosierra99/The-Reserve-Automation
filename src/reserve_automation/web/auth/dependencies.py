"""FastAPI dependencies for auth."""

from fastapi import Depends, HTTPException, Request

from .models import AuthenticatedUser


def get_current_user(request: Request) -> AuthenticatedUser:
    """Get the authenticated user from request state.

    This is set by AuthMiddleware on every request.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require(permission: str):
    """Create a FastAPI dependency that checks a permission.

    Usage:
        @router.get("/foo", dependencies=[Depends(require("foo.view"))])
        async def foo(): ...

    Or to get the user:
        @router.get("/foo")
        async def foo(user: AuthenticatedUser = Depends(require("foo.view"))):
            ...
    """
    def _check_permission(request: Request) -> AuthenticatedUser:
        user = get_current_user(request)

        # Load auth config from app state
        auth_config = getattr(request.app.state, "auth_config", None)
        if auth_config is None:
            # No auth config = no permission enforcement (backwards compat)
            return user

        if not auth_config.has_permission(user.role, permission):
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied: {permission} requires one of "
                       f"{auth_config.permissions.get(permission, [])}, "
                       f"you are '{user.role}'"
            )

        return user

    return _check_permission
