"""
Redis Queues page — monitor queue depths for List and Stream keys.
Auto-refreshes every 10 seconds.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
from utils.api_client import EngineClient, get_config

st.set_page_config(page_title="Redis Queues", page_icon="📬", layout="wide")
st.title("📬 Redis Queues")


@st.cache_resource
def get_client() -> EngineClient:
    cfg = get_config()
    return EngineClient(cfg["base_url"], cfg.get("api_key"))


c = get_client()

if "last_error" in st.session_state:
    st.error(st.session_state["last_error"])

with st.sidebar:
    auto_refresh = st.checkbox("Auto-refresh (10s)", value=True)
    if auto_refresh:
        st_autorefresh(interval=10_000, key="queues_refresh")
    if st.button("↻ Refresh now"):
        st.rerun()
    top_n = st.slider("Chart: top N queues", min_value=5, max_value=50, value=20)

# ---------------------------------------------------------------------------
# Queue data
# ---------------------------------------------------------------------------

queues = c.get_redis_queues() or []

if not queues:
    st.info("No queues found. List or Stream keys will appear here when they exist.")
else:
    # Sort by depth descending
    queues_sorted = sorted(queues, key=lambda q: q.get("depth", 0) or 0, reverse=True)

    # Summary metrics
    total_depth = sum(q.get("depth", 0) or 0 for q in queues_sorted)
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Queues", len(queues_sorted))
    col2.metric("Total Depth", f"{total_depth:,}")
    col3.metric("Deepest Queue", queues_sorted[0].get("key", "?") if queues_sorted else "—")

    # Bar chart
    chart_queues = queues_sorted[:top_n]
    fig = go.Figure(
        go.Bar(
            x=[q.get("depth", 0) for q in chart_queues],
            y=[q.get("key", "?") for q in chart_queues],
            orientation="h",
            marker_color="#4F8EF7",
            text=[str(q.get("depth", 0)) for q in chart_queues],
            textposition="auto",
        )
    )
    fig.update_layout(
        xaxis_title="Depth",
        yaxis=dict(autorange="reversed"),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#fafafa"),
        margin=dict(t=20, b=40, l=20, r=20),
        height=max(300, min(top_n * 28, 800)),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Table
    rows = []
    for q in queues_sorted:
        rows.append({
            "Queue": q.get("key", "?"),
            "Type": q.get("type", "?"),
            "Depth": q.get("depth", 0),
            "Consumer Groups": q.get("group_count", "—") if q.get("type") == "stream" else "—",
            "Pending": q.get("pending_count", "—") if q.get("type") == "stream" else "—",
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Queue detail")

    for q in queues_sorted[:20]:
        q_key = q.get("key", "?")
        q_type = q.get("type", "?")
        depth = q.get("depth", 0)

        with st.expander(f"📬 {q_key}  (depth: {depth:,})"):
            st.write(f"**Type:** {q_type}")
            st.write(f"**Depth:** {depth:,}")

            if q_type == "stream":
                groups = q.get("groups", []) or []
                if groups:
                    st.write(f"**Consumer groups ({len(groups)}):**")
                    gdf = pd.DataFrame(groups)
                    st.dataframe(gdf, use_container_width=True, hide_index=True)
                else:
                    st.write("No consumer groups.")
