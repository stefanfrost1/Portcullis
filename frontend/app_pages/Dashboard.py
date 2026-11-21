"""
MyEngine Dashboard — Overview page.

Shows Redis top-level metrics and queue depths from GET /api/v1/overview.
Auto-refreshes every REFRESH_INTERVAL seconds (default 10).
"""

import streamlit as st
from streamlit_autorefresh import st_autorefresh
import plotly.graph_objects as go

from utils.api_client import EngineClient, get_config
from utils.formatting import bytes_to_human, health_badge


st.set_page_config(
    page_title="MyEngine Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Shared client (singleton across reruns via cache_resource)
# ---------------------------------------------------------------------------

@st.cache_resource
def get_client() -> EngineClient:
    cfg = get_config()
    return EngineClient(cfg["base_url"], cfg.get("api_key"))


def client() -> EngineClient:
    return get_client()


# ---------------------------------------------------------------------------
# Auto-refresh
# ---------------------------------------------------------------------------

cfg = get_config()
refresh_ms = cfg["refresh_interval"] * 1000
st_autorefresh(interval=refresh_ms, key="dashboard_refresh")

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

st.title("📊 MyEngine Dashboard")

c = client()

# Health check (fast, small call)
redis_health = c.get_redis_health()
redis_ok = redis_health is not None

col_h1, col_h2 = st.columns([2, 6])
with col_h1:
    st.markdown(f"**Redis** {health_badge(redis_ok)}")
with col_h2:
    import datetime
    st.caption(f"Last updated: {datetime.datetime.now().strftime('%H:%M:%S')} · auto-refresh every {cfg['refresh_interval']}s")

st.divider()

# ---------------------------------------------------------------------------
# Overview data
# ---------------------------------------------------------------------------

overview = c.get_overview()

if "last_error" in st.session_state:
    st.error(st.session_state["last_error"])

# Safe accessors
redis_data = (overview or {}).get("redis", {}) or {}
redis_status = redis_data.get("status")

# ---------------------------------------------------------------------------
# Redis metrics row
# ---------------------------------------------------------------------------

st.subheader("Redis")

r_clients = redis_data.get("connected_clients", 0) or 0
r_memory = redis_data.get("used_memory_bytes", None)
r_keys = redis_data.get("total_keys", 0) or 0
r_ops = redis_data.get("ops_per_sec", 0) or 0
r_hit_rate = redis_data.get("hit_rate_percent", redis_data.get("hit_rate", None))

rcols = st.columns(5)
rcols[0].metric("Connected Clients", r_clients)
rcols[1].metric("Memory Used", bytes_to_human(r_memory))
rcols[2].metric("Total Keys", r_keys)
rcols[3].metric("Ops / sec", f"{r_ops:,}")
rcols[4].metric("Hit Rate", f"{r_hit_rate:.1f}%" if r_hit_rate is not None else "—")

if redis_status == "error":
    st.warning("Redis data unavailable — check Redis connection.")

st.divider()

# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

# Top queues bar chart
st.subheader("Top Queues by Depth")
top_queues = redis_data.get("top_queues", []) or []

if not top_queues:
    st.info("No queues found or Redis unavailable.")
else:
    q_names = [q.get("key", "?") for q in top_queues[:10]]
    q_depths = [q.get("depth", 0) or 0 for q in top_queues[:10]]

    fig2 = go.Figure(
        data=[
            go.Bar(
                x=q_depths,
                y=q_names,
                orientation="h",
                marker=dict(color="#4F8EF7"),
            )
        ]
    )
    fig2.update_layout(
        xaxis_title="Depth",
        yaxis=dict(autorange="reversed"),
        margin=dict(t=20, b=40, l=20, r=20),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#fafafa"),
    )
    st.plotly_chart(fig2, width="stretch")
