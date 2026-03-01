"""
System page — Docker daemon info and disk usage breakdown.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import plotly.graph_objects as go
from utils.api_client import EngineClient, get_config
from utils.formatting import bytes_to_human

st.set_page_config(page_title="System", page_icon="⚙️", layout="wide")
st.title("⚙️ System Info")


@st.cache_resource
def get_client() -> EngineClient:
    cfg = get_config()
    return EngineClient(cfg["base_url"], cfg.get("api_key"))


c = get_client()

if "last_error" in st.session_state:
    st.error(st.session_state["last_error"])

with st.sidebar:
    if st.button("↻ Refresh"):
        st.rerun()

# ---------------------------------------------------------------------------
# System info
# ---------------------------------------------------------------------------

info = c.get_system_info()

if info:
    st.subheader("Docker Daemon")
    cols = st.columns(3)
    cols[0].metric("Docker Version", info.get("docker_version", "—"))
    cols[1].metric("API Version", info.get("api_version", "—"))
    cols[2].metric("Kernel", info.get("kernel_version", "—"))

    cols2 = st.columns(3)
    cols2[0].metric("OS", info.get("os", "—"))
    cols2[1].metric("Architecture", info.get("architecture", "—"))
    cols2[2].metric("CPUs", info.get("ncpu", "—"))

    cols3 = st.columns(3)
    cols3[0].metric("Total Memory", bytes_to_human(info.get("total_memory_bytes")))
    cols3[1].metric("Containers Running", info.get("containers_running", 0))
    cols3[2].metric("Images", info.get("images_count", 0))
else:
    st.warning("Could not load system info — Docker may be unreachable.")

st.divider()

# ---------------------------------------------------------------------------
# Disk usage
# ---------------------------------------------------------------------------

st.subheader("Disk Usage")

df_data = c.get_disk_usage()

if df_data:
    # Summarise by category
    def sum_size(items: list, size_key: str = "size_bytes") -> int:
        return sum((item.get(size_key) or 0) for item in (items or []))

    images_size = sum_size(df_data.get("images", []))
    containers_size = sum_size(df_data.get("containers", []))
    volumes_size = sum_size(df_data.get("volumes", []))
    cache_size = sum_size(df_data.get("build_cache", []))

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Images", bytes_to_human(images_size))
    col2.metric("Containers", bytes_to_human(containers_size))
    col3.metric("Volumes", bytes_to_human(volumes_size))
    col4.metric("Build Cache", bytes_to_human(cache_size))

    # Stacked bar chart
    categories = ["Images", "Containers", "Volumes", "Build Cache"]
    sizes = [images_size, containers_size, volumes_size, cache_size]
    colors = ["#4F8EF7", "#e74c3c", "#2ecc71", "#f39c12"]

    fig = go.Figure()
    for cat, size, color in zip(categories, sizes, colors):
        fig.add_trace(
            go.Bar(
                name=cat,
                x=[cat],
                y=[size],
                marker_color=color,
                text=[bytes_to_human(size)],
                textposition="auto",
            )
        )
    fig.update_layout(
        yaxis_title="Bytes",
        showlegend=True,
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#fafafa"),
        margin=dict(t=20, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Raw image list
    with st.expander("Images"):
        imgs = df_data.get("images", [])
        for img in imgs:
            tags = img.get("tags") or ["<none>"]
            st.write(f"  • {', '.join(tags)} — {bytes_to_human(img.get('size_bytes'))}")

    # Raw container list
    with st.expander("Containers"):
        cts = df_data.get("containers", [])
        for ct in cts:
            st.write(f"  • {ct.get('name', '?')} — {bytes_to_human(ct.get('size_bytes'))}")

else:
    st.warning("Could not load disk usage.")
