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

with st.sidebar:
    if st.button("↻ Refresh"):
        st.rerun()
    scan_pattern = st.text_input("Key pattern", value="*")

tab_keyspace, tab_memory_top, tab_expiring = st.tabs(["Keyspace", "Memory Top", "Expiring Soon"])

# ---------------------------------------------------------------------------
# Keyspace
# ---------------------------------------------------------------------------

with tab_keyspace:
    with st.spinner("Sampling keyspace…"):
        ks = c.get_redis_analysis_keyspace(pattern=scan_pattern or "*")

    if ks is None:
        st.error(c.last_error() or "Keyspace analysis unavailable.")
    elif not ks:
        st.warning("Keyspace analysis unavailable.")
    else:
        st.caption(f"Sampled {ks.get('total_scanned', 0):,} key(s) from db {ks.get('db', 0)}.")
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
                st.plotly_chart(fig, width="stretch")
            else:
                st.info("No type data.")

        # Top prefixes bar — the API returns [{"prefix": ..., "count": ...}, …]
        prefixes = ks.get("top_prefixes") or []
        if isinstance(prefixes, dict):   # tolerate the older map shape
            prefixes = [{"prefix": p, "count": n} for p, n in prefixes.items()]

        with col2:
            st.subheader("Top key prefixes")
            if prefixes:
                top = prefixes[:20]
                prefix_names = [p.get("prefix", "?") for p in top]
                prefix_counts = [p.get("count", 0) for p in top]
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
                st.plotly_chart(fig2, width="stretch")
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
            st.plotly_chart(fig3, width="stretch")

# ---------------------------------------------------------------------------
# Memory Top
# ---------------------------------------------------------------------------

with tab_memory_top:
    n = st.slider("Number of keys to show", min_value=10, max_value=100, value=20, step=10)
    with st.spinner("Measuring key memory…"):
        top_keys = c.get_redis_analysis_memory_top(count=n)

    if top_keys is None:
        st.error(c.last_error() or "Could not measure key memory.")
        top_keys = []

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
        st.dataframe(df[["Key", "Type", "Memory"]], width="stretch", hide_index=True)

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
            st.plotly_chart(fig, width="stretch")

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

    with st.spinner("Scanning for expiring keys…"):
        expiring = c.get_redis_analysis_expiring_soon(seconds=int(window_secs))

    if expiring is None:
        st.error(c.last_error() or "Could not scan for expiring keys.")
        expiring = []

    if not expiring:
        st.info(f"No keys expiring within {seconds_to_human(window_secs)}.")
    else:
        rows = []
        for entry in expiring:
            ttl = entry.get("ttl", entry.get("ttl_seconds", 0))
            rows.append({
                "Key": entry.get("key", "?"),
                "Type": entry.get("type", "?"),
                "TTL": seconds_to_human(ttl),
                "TTL (s)": ttl,
            })
        df = pd.DataFrame(rows).sort_values("TTL (s)")
        st.write(f"**{len(expiring)} key(s)** expiring within {seconds_to_human(window_secs)}")
        st.dataframe(df[["Key", "Type", "TTL"]], width="stretch", hide_index=True)
