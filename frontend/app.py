"""
Streamlit entrypoint using the modern navigation API.

This replaces legacy automatic pages discovery with explicit st.Page routing.
"""

import streamlit as st


dashboard = st.Page("app_pages/Dashboard.py", title="Dashboard", icon="🐳", default=True)
containers = st.Page("app_pages/1_Containers.py", title="Containers", icon="📦")
images = st.Page("app_pages/2_Images.py", title="Images", icon="🖼️")
networks = st.Page("app_pages/3_Networks.py", title="Networks", icon="🌐")
volumes = st.Page("app_pages/4_Volumes.py", title="Volumes", icon="💾")
system = st.Page("app_pages/5_System.py", title="System", icon="⚙️")
log_search = st.Page("app_pages/10_Log_Search.py", title="Logs", icon="📋")
redis_keys = st.Page("app_pages/6_Redis_Keys.py", title="Redis Keys", icon="🗝️")
redis_server = st.Page("app_pages/7_Redis_Server.py", title="Redis Server", icon="🔴")
redis_analysis = st.Page("app_pages/8_Redis_Analysis.py", title="Redis Analysis", icon="📊")
redis_queues = st.Page("app_pages/9_Redis_Queues.py", title="Redis Queues", icon="📬")

pg = st.navigation(
    {
        "Overview": [dashboard],
        "Docker": [containers, images, networks, volumes, system, log_search],
        "Redis": [redis_keys, redis_server, redis_analysis, redis_queues],
    }
)

pg.run()
