"""
Streamlit entrypoint using the modern navigation API.

This replaces legacy automatic pages discovery with explicit st.Page routing.
"""

import streamlit as st


dashboard = st.Page("app_pages/Dashboard.py", title="Dashboard", icon="📊", default=True)
redis_keys = st.Page("app_pages/6_Redis_Keys.py", title="Redis Keys", icon="🗝️")
redis_server = st.Page("app_pages/7_Redis_Server.py", title="Redis Server", icon="🔴")
redis_analysis = st.Page("app_pages/8_Redis_Analysis.py", title="Redis Analysis", icon="📊")
redis_queues = st.Page("app_pages/9_Redis_Queues.py", title="Redis Queues", icon="📬")

pg = st.navigation(
    {
        "Overview": [dashboard],
        "Redis": [redis_keys, redis_server, redis_analysis, redis_queues],
    }
)

pg.run()
