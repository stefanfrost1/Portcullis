"""
Redis Analysis page — keyspace distribution, memory top-N, expiring-soon keys.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from utils.api_client import EngineClient, get_config
from utils.formatting import bytes_to_human, seconds_to_human

st.set_page_config(page_title="Redis Analysis", page_icon="📊", layout="wide")
st.title("📊 Redis Analysis")


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

tab_keyspace, tab_memory_top, tab_expiring = st.tabs(["Keyspace", "Memory Top", "Expiring Soon"])

# ---------------------------------------------------------------------------
# Keyspace
# ---------------------------------------------------------------------------

with tab_keyspace:
    ks = c.get_redis_analysis_keyspace()
    if not ks:
        st.warning("Keyspace analysis unavailable.")
    else:
        col1, col2 = st.columns(2)

        # Type distribution pie
        type_dist = ks.get("type_distribution", {}) or {}
        with col1:
            st.subheader("Key type distribution")
            if type_dist:
                fig = go.Figure(
                    go.Pie(
                        labels=list(type_dist.keys()),
                        values=list(type_dist.values()),
                        hole=0.4,
                        textinfo="label+percent+value",
                    )
                )
                fig.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#fafafa"),
                    margin=dict(t=20, b=20, l=20, r=20),
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No type data.")

        # Top prefixes bar
        prefixes = ks.get("top_prefixes", {}) or {}
        with col2:
            st.subheader("Top key prefixes")
            if prefixes:
                prefix_names = list(prefixes.keys())[:20]
                prefix_counts = [prefixes[p] for p in prefix_names]
                fig2 = go.Figure(
                    go.Bar(
                        x=prefix_counts,
                        y=prefix_names,
                        orientation="h",
                        marker_color="#4F8EF7",
                    )
                )
                fig2.update_layout(
                    xaxis_title="Count",
                    yaxis=dict(autorange="reversed"),
                    paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#fafafa"),
                    margin=dict(t=20, b=40, l=20, r=20),
                )
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("No prefix data.")

        # TTL buckets
        ttl_dist = ks.get("ttl_distribution", {}) or {}
        if ttl_dist:
            st.subheader("TTL distribution")
            fig3 = go.Figure(
                go.Bar(
                    x=list(ttl_dist.keys()),
                    y=list(ttl_dist.values()),
                    marker_color="#2ecc71",
                )
            )
            fig3.update_layout(
                xaxis_title="TTL bucket",
                yaxis_title="Count",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#fafafa"),
                margin=dict(t=20, b=40),
            )
            st.plotly_chart(fig3, use_container_width=True)

# ---------------------------------------------------------------------------
# Memory Top
# ---------------------------------------------------------------------------

with tab_memory_top:
    n = st.slider("Number of keys to sample", min_value=10, max_value=100, value=20, step=10)
    top_keys = c.get_redis_analysis_memory_top(count=n) or []

    if not top_keys:
        st.info("No data. Keys may be too small to sample or Redis unavailable.")
    else:
        rows = []
        for entry in top_keys:
            rows.append({
                "Key": entry.get("key", "?"),
                "Type": entry.get("type", "?"),
                "Memory": bytes_to_human(entry.get("memory_bytes")),
                "Memory (bytes)": entry.get("memory_bytes", 0),
            })
        df = pd.DataFrame(rows)
        st.dataframe(df[["Key", "Type", "Memory"]], use_container_width=True, hide_index=True)

        # Bar chart
        if rows:
            fig = go.Figure(
                go.Bar(
                    x=[r["Memory (bytes)"] for r in rows],
                    y=[r["Key"] for r in rows],
                    orientation="h",
                    marker_color="#e74c3c",
                    text=[r["Memory"] for r in rows],
                    textposition="auto",
                )
            )
            fig.update_layout(
                xaxis_title="Memory (bytes)",
                yaxis=dict(autorange="reversed"),
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#fafafa"),
                margin=dict(t=20, b=40, l=20, r=20),
            )
            st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Expiring Soon
# ---------------------------------------------------------------------------

with tab_expiring:
    window_opts = {"1 minute": 60, "5 minutes": 300, "1 hour": 3600, "Custom": None}
    window_label = st.selectbox("Expiry window", list(window_opts.keys()))
    if window_opts[window_label] is None:
        window_secs = st.number_input("Custom (seconds)", min_value=1, value=300)
    else:
        window_secs = window_opts[window_label]

    expiring = c.get_redis_analysis_expiring_soon(seconds=window_secs) or []

    if not expiring:
        st.info(f"No keys expiring within {seconds_to_human(window_secs)}.")
    else:
        rows = []
        for entry in expiring:
            rows.append({
                "Key": entry.get("key", "?"),
                "Type": entry.get("type", "?"),
                "TTL": seconds_to_human(entry.get("ttl_seconds")),
                "TTL (s)": entry.get("ttl_seconds", 0),
            })
        df = pd.DataFrame(rows).sort_values("TTL (s)")
        st.write(f"**{len(expiring)} key(s)** expiring within {seconds_to_human(window_secs)}")
        st.dataframe(df[["Key", "Type", "TTL"]], use_container_width=True, hide_index=True)
