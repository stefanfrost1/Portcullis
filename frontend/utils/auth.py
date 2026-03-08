"""
Role detection via Caddy forward-auth headers.

Caddy injects X-User-Groups after authenticating via Authelia/Authcrunch.
Roles:
  admin     — authp/admin group  → full access
  developer — authp/user group   → no Images / Networks / Volumes
  reader    — no matching group  → Dashboard, Containers, System only
"""

import streamlit as st


def get_current_role() -> str:
    """
    Retrieve the current user's role from Caddy headers.
    Returns: 'admin', 'developer', or 'reader'.
    """
    headers = {}
    if hasattr(st, "context") and hasattr(st.context, "headers"):
        headers = st.context.headers

    groups_header = headers.get("X-User-Groups") or headers.get("x-user-groups")

    if groups_header:
        if "authp/admin" in groups_header:
            return "admin"
        elif "authp/user" in groups_header:
            return "developer"

    return "reader"
