"""
Streamlit entrypoint using the modern navigation API.

This replaces legacy automatic pages discovery with explicit st.Page routing.
Navigation is gated by the user's role, derived from the X-User-Groups header
injected by Caddy after forward-auth.

Roles:
  admin     — full access (all pages)
  developer — Containers + Redis, but no Images / Networks / Volumes
  reader    — Dashboard, Containers, System only
"""

import streamlit as st

from utils.auth import get_current_role


role = get_current_role()

# ---------------------------------------------------------------------------
# Page definitions
# ---------------------------------------------------------------------------

dashboard = st.Page("app_pages/Dashboard.py", title="Dashboard", icon="🐳", default=True)
containers = st.Page("app_pages/1_Containers.py", title="Containers", icon="📦")
images = st.Page("app_pages/2_Images.py", title="Images", icon="🖼️")
networks = st.Page("app_pages/3_Networks.py", title="Networks", icon="🌐")
volumes = st.Page("app_pages/4_Volumes.py", title="Volumes", icon="💾")
system = st.Page("app_pages/5_System.py", title="System", icon="⚙️")
redis_keys = st.Page("app_pages/6_Redis_Keys.py", title="Redis Keys", icon="🗝️")
redis_server = st.Page("app_pages/7_Redis_Server.py", title="Redis Server", icon="🔴")
redis_analysis = st.Page("app_pages/8_Redis_Analysis.py", title="Redis Analysis", icon="📊")
redis_queues = st.Page("app_pages/9_Redis_Queues.py", title="Redis Queues", icon="📬")

# ---------------------------------------------------------------------------
# Role-based navigation
# ---------------------------------------------------------------------------

if role == "admin":
    docker_pages = [containers, images, networks, volumes, system]
    redis_pages = [redis_keys, redis_server, redis_analysis, redis_queues]
elif role == "developer":
    docker_pages = [containers, system]
    redis_pages = [redis_keys, redis_server, redis_analysis, redis_queues]
else:  # reader
    docker_pages = [containers, system]
    redis_pages = []

nav: dict = {"Overview": [dashboard], "Docker": docker_pages}
if redis_pages:
    nav["Redis"] = redis_pages

pg = st.navigation(nav)
pg.run()
