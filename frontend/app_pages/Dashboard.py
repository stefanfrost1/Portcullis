"""
Portcullis Dashboard — Overview page.

Shows combined Docker + Redis top-level metrics from GET /api/v1/overview.
Auto-refreshes every REFRESH_INTERVAL seconds (default 10).
"""

import streamlit as st
from streamlit_autorefresh import st_autorefresh
import plotly.graph_objects as go

from utils.api_client import EngineClient, get_config
from utils.formatting import bytes_to_human, health_badge


st.set_page_config(
    page_title="Portcullis Dashboard",
    page_icon="🐳",
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

st.title("🐳 Portcullis Dashboard")

c = client()

# Health checks (fast, small calls)
docker_health = c.get_health()
redis_health = c.get_redis_health()

docker_ok = docker_health is not None
redis_ok = redis_health is not None

col_h1, col_h2, col_h3 = st.columns([2, 2, 4])
with col_h1:
    st.markdown(f"**Docker** {health_badge(docker_ok)}")
with col_h2:
    st.markdown(f"**Redis** {health_badge(redis_ok)}")
with col_h3:
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
docker_data = (overview or {}).get("docker", {}) or {}
redis_data = (overview or {}).get("redis", {}) or {}

docker_status = docker_data.get("status")
redis_status = redis_data.get("status")


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _count_from(value, default: int = 0) -> int:
    if isinstance(value, dict):
        return _safe_int(value.get("count"), default)
    return _safe_int(value, default)


def _bytes_from(value):
    if isinstance(value, dict):
        raw = value.get("total_bytes")
    else:
        raw = value
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None

# ---------------------------------------------------------------------------
# Docker metrics row
# ---------------------------------------------------------------------------

st.subheader("Docker")

d_running = docker_data.get("containers_running", 0) or 0
d_paused = docker_data.get("containers_paused", 0) or 0
d_stopped = docker_data.get("containers_stopped", 0) or 0
containers_block = docker_data.get("containers", {}) if isinstance(docker_data.get("containers"), dict) else {}
images_block = docker_data.get("images", 0)
volumes_block = docker_data.get("volumes", 0)

d_running = _safe_int(containers_block.get("running", d_running), 0)
d_paused = _safe_int(containers_block.get("paused", d_paused), 0)
d_stopped = _safe_int(containers_block.get("stopped", d_stopped), 0)
d_images = _count_from(images_block, 0)
d_volumes = _count_from(volumes_block, 0)
d_projects = _safe_int(
    docker_data.get("compose_project_count", len(docker_data.get("compose_projects", []) or [])),
    0,
)

d_disk_bytes = docker_data.get("disk_usage_bytes", None)
if d_disk_bytes is None:
    img_bytes = _bytes_from(images_block)
    vol_bytes = _bytes_from(volumes_block)
    if img_bytes is not None or vol_bytes is not None:
        d_disk_bytes = (img_bytes or 0) + (vol_bytes or 0)

cols = st.columns(6)
cols[0].metric("Running", d_running)
cols[1].metric("Paused", d_paused)
cols[2].metric("Stopped", d_stopped)
cols[3].metric("Images", d_images)
cols[4].metric("Volumes", d_volumes)
cols[5].metric("Compose Projects", d_projects)

if d_disk_bytes is not None:
    st.caption(f"Docker disk usage: {bytes_to_human(d_disk_bytes)}")

if docker_status == "error":
    st.warning("Docker data unavailable — check API connection.")

st.divider()

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

chart_col1, chart_col2 = st.columns(2)

# Container state pie chart
with chart_col1:
    st.subheader("Container States")
    labels = ["Running", "Paused", "Stopped"]
    values = [d_running, d_paused, d_stopped]
    colors = ["#2ecc71", "#f39c12", "#e74c3c"]

    if sum(values) == 0:
        st.info("No containers found.")
    else:
        fig = go.Figure(
            data=[
                go.Pie(
                    labels=labels,
                    values=values,
                    marker=dict(colors=colors),
                    hole=0.4,
                    textinfo="label+value",
                )
            ]
        )
        fig.update_layout(
            showlegend=True,
            margin=dict(t=20, b=20, l=20, r=20),
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#fafafa"),
        )
        st.plotly_chart(fig, width="stretch")

# Top queues bar chart
with chart_col2:
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
