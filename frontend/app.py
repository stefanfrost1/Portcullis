"""
Streamlit entrypoint using the modern navigation API.

This replaces legacy automatic pages discovery with explicit st.Page routing.
"""

import streamlit as st

from utils.api_client import get_config


# Overview page name is deployment-configurable (DASHBOARD_TITLE / PROJECT_NAME).
_dashboard_title = get_config()["dashboard_title"]

dashboard = st.Page("app_pages/Dashboard.py", title=_dashboard_title, icon="🐳", default=True)
system = st.Page("app_pages/5_System.py", title="System", icon="⚙️")
log_search = st.Page("app_pages/10_Log_Search.py", title="Logs", icon="📋")
containers = st.Page("app_pages/1_Containers.py", title="Containers", icon="📦")

redis_server = st.Page("app_pages/7_Redis_Server.py", title="Redis Server", icon="🔴")
redis_queues = st.Page("app_pages/9_Redis_Queues.py", title="Redis Queues", icon="📬")
redis_keys = st.Page("app_pages/6_Redis_Keys.py", title="Redis Keys", icon="🗝️")
redis_analysis = st.Page("app_pages/8_Redis_Analysis.py", title="Redis Analysis", icon="📊")

# Volumes, networks, and images are host/resource views, kept in a section at
# the bottom below the day-to-day operational pages.
volumes = st.Page("app_pages/4_Volumes.py", title="Volumes", icon="💾")
networks = st.Page("app_pages/3_Networks.py", title="Networks", icon="🌐")
images = st.Page("app_pages/2_Images.py", title="Images", icon="🖼️")

pg = st.navigation(
    {
        "Overview": [dashboard],
        "Docker": [system, log_search, containers],
        "Redis": [redis_server, redis_queues, redis_keys, redis_analysis],
        "Resources": [volumes, networks, images],
    }
)

pg.run()
