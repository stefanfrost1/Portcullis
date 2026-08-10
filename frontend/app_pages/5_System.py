"""
System page — Docker daemon info and disk usage breakdown.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
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

with st.sidebar:
    if st.button("↻ Refresh"):
        st.rerun()
    force_df = st.checkbox(
        "Recalculate disk usage",
        value=False,
        help="Bypasses the API's disk-usage cache. Slow on hosts with many images.",
    )

# ---------------------------------------------------------------------------
# System info
# ---------------------------------------------------------------------------

info = c.get_system_info()

if info is None:
    st.error(c.last_error() or "Could not load system info — Docker may be unreachable.")
else:
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

st.divider()

# ---------------------------------------------------------------------------
# Disk usage
# ---------------------------------------------------------------------------

st.subheader("Disk Usage")

with st.spinner("Reading Docker disk usage…"):
    df_data = c.get_disk_usage(refresh=force_df)

if df_data is None:
    st.error(c.last_error() or "Could not load disk usage.")
else:
    summary = df_data.get("summary") or {}

    images_size = summary.get("images_bytes", 0)
    containers_size = summary.get("containers_bytes", 0)
    volumes_size = summary.get("volumes_bytes", 0)
    cache_size = summary.get("build_cache_bytes", 0)

    st.caption(f"Total reclaimable footprint: {bytes_to_human(summary.get('total_bytes', 0))}")

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
    st.plotly_chart(fig, width="stretch")

    # Largest images first — the list runs to hundreds on a busy host.
    imgs = sorted(
        df_data.get("images", []),
        key=lambda i: i.get("size_bytes", 0),
        reverse=True,
    )
    with st.expander(f"Images ({len(imgs)})"):
        st.dataframe(
            pd.DataFrame([
                {
                    "Tags": ", ".join(img.get("tags") or ["<none>"]),
                    "Size": bytes_to_human(img.get("size_bytes")),
                    "Shared": bytes_to_human(img.get("shared_size_bytes")),
                    "In use by": img.get("containers", 0),
                }
                for img in imgs
            ]),
            width="stretch",
            hide_index=True,
        )

    cts = sorted(
        df_data.get("containers", []),
        key=lambda ct: ct.get("size_bytes", 0),
        reverse=True,
    )
    with st.expander(f"Containers ({len(cts)})"):
        st.dataframe(
            pd.DataFrame([
                {
                    "Name": ct.get("name", "?"),
                    "Image": ct.get("image", "—"),
                    "State": ct.get("state", "—"),
                    "Writable layer": bytes_to_human(ct.get("size_bytes")),
                }
                for ct in cts
            ]),
            width="stretch",
            hide_index=True,
        )

    vols = sorted(
        df_data.get("volumes", []),
        key=lambda v: v.get("size_bytes", 0),
        reverse=True,
    )
    with st.expander(f"Volumes ({len(vols)})"):
        st.dataframe(
            pd.DataFrame([
                {
                    "Name": vol.get("name", "?"),
                    "Driver": vol.get("driver", "—"),
                    "Size": bytes_to_human(vol.get("size_bytes")),
                    "Used by": vol.get("ref_count", 0),
                }
                for vol in vols
            ]),
            width="stretch",
            hide_index=True,
        )
