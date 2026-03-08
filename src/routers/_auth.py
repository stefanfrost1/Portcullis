"""
Role-based access control via Caddy reverse-proxy headers.

Caddy sets `X-User-Groups` on every authenticated request.  The header value
contains the user's group memberships, e.g. "[authp/user, authp/admin]".

Roles returned by get_role():
  "admin"     — authp/admin group present
  "developer" — authp/user group present (no admin)
  "reader"    — no recognised group header (fallback)

Usage in route handlers:

    from fastapi import Depends
    from src.routers._auth import require_admin

    @router.post("/sensitive")
    def sensitive_op(_: None = Depends(require_admin)):
        ...
"""

from typing import Optional

from fastapi import Header, HTTPException, status


def get_role(x_user_groups: Optional[str] = Header(None)) -> str:
    """Extract role from the Caddy-injected X-User-Groups header."""
    if x_user_groups:
        if "authp/admin" in x_user_groups:
            return "admin"
        if "authp/user" in x_user_groups:
            return "developer"
    return "reader"


def require_admin(x_user_groups: Optional[str] = Header(None)) -> None:
    """Dependency that raises 403 unless the request carries admin credentials."""
    if get_role(x_user_groups) != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required.",
        )
