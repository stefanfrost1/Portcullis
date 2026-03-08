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

import copy
import re
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


# ---------------------------------------------------------------------------
# OpenAPI schema filtering — hide admin-only operations from non-admin users
# ---------------------------------------------------------------------------

# Each rule: (compiled path regex, set of HTTP methods that are admin-only).
# Paths in the OpenAPI schema are full strings like /api/v1/containers/{container_id}.
_ADMIN_RULES: list[tuple[re.Pattern, frozenset[str]]] = [
    # Container: inspect (GET) and remove (DELETE) — admin only
    (re.compile(r"/containers/\{[^/}]+\}$"), frozenset({"get", "delete"})),
    # Container lifecycle: stop, restart, pause, unpause
    (re.compile(r"/containers/\{[^/}]+\}/(stop|restart|pause|unpause)$"), frozenset({"post"})),
    # Images, Networks, Volumes — every method is admin-only
    (re.compile(r"/images(/|$)"), frozenset({"get", "post", "put", "delete", "patch"})),
    (re.compile(r"/networks(/|$)"), frozenset({"get", "post", "put", "delete", "patch"})),
    (re.compile(r"/volumes(/|$)"), frozenset({"get", "post", "put", "delete", "patch"})),
    # Redis — write operations are admin-only; reads remain open
    (re.compile(r"/redis(/|$)"), frozenset({"post", "put", "delete"})),
]

_HTTP_METHODS = frozenset({"get", "post", "put", "delete", "patch", "head", "options"})


def _is_admin_only(path: str, method: str) -> bool:
    m = method.lower()
    for pattern, methods in _ADMIN_RULES:
        if pattern.search(path) and m in methods:
            return True
    return False


def filter_schema_for_role(schema: dict, role: str) -> dict:
    """
    Return a (deep-copied) OpenAPI schema with admin-only operations stripped out
    for non-admin roles.  Admin users receive the full schema unchanged.
    """
    if role == "admin":
        return schema

    schema = copy.deepcopy(schema)
    paths = schema.get("paths", {})
    dead_paths: list[str] = []

    for path, path_item in paths.items():
        for method in list(path_item.keys()):
            if method in _HTTP_METHODS and _is_admin_only(path, method):
                del path_item[method]
        if not any(m in path_item for m in _HTTP_METHODS):
            dead_paths.append(path)

    for path in dead_paths:
        del paths[path]

    return schema
