"""
Containers page — list, inspect, lifecycle controls, and live stats.
"""

import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import plotly.graph_objects as go
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.api_client import EngineClient, get_config
from utils.formatting import state_color, bytes_to_human, seconds_to_human, percent_bar

st.set_page_config(page_title="Containers", page_icon="📦", layout="wide")
st.title("📦 Containers")


@st.cache_resource
def get_client() -> EngineClient:
    cfg = get_config()
    return EngineClient(cfg["base_url"], cfg.get("api_key"))


c = get_client()

# Refresh controls in sidebar
cfg = get_config()
with st.sidebar:
    show_all = st.checkbox("Show stopped containers", value=True)
    name_filter = st.text_input("Filter by name / image", value="")
    auto_refresh = st.checkbox("Auto-refresh (10s)", value=False)
    if st.button("↻ Refresh now"):
        st.rerun()

tab_all, tab_stats, tab_groups = st.tabs(["All Containers", "Live Stats", "By Compose Project"])

# ---------------------------------------------------------------------------
# Tab 1: All Containers
# ---------------------------------------------------------------------------

with tab_all:
    with st.spinner("Loading containers…"):
        containers = c.get_containers(all=show_all)

    if containers is None:
        st.error(c.last_error() or "Could not load containers.")
        containers = []

    if name_filter.strip():
        needle = name_filter.strip().lower()
        containers = [
            ct for ct in containers
            if needle in (ct.get("name") or "").lower()
            or needle in (ct.get("image") or "").lower()
        ]

    if not containers:
        st.info("No containers found.")
    else:
        # Build summary dataframe
        rows = []
        for ct in containers:
            ports = ct.get("ports") or {}
            port_str = ", ".join(
                f"{v}->{k}" for k, v in ports.items() if v
            ) if isinstance(ports, dict) else str(ports)
            rows.append({
                "State": state_color(ct.get("state")),
                "Name": ct.get("name", "—"),
                "Image": ct.get("image", "—"),
                "Status": ct.get("status", "—"),
                "Uptime": seconds_to_human(ct.get("uptime_seconds")),
                "Ports": port_str or "—",
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, width="stretch", hide_index=True)

        st.divider()
        st.subheader("Container detail & controls")

        for ct in containers:
            ct_name = ct.get("name", ct.get("id", "?"))
            ct_id = ct.get("id", "")
            state = ct.get("state", "")

            with st.expander(f"{state_color(state)} {ct_name}  ({ct.get('image', '—')})"):
                col_info, col_actions = st.columns([3, 1])

                with col_info:
                    st.write(f"**ID:** `{ct_id[:12]}`")
                    st.write(f"**Status:** {ct.get('status', '—')}")
                    st.write(f"**Created:** {ct.get('created', '—')}")
                    st.write(f"**Uptime:** {seconds_to_human(ct.get('uptime_seconds'))}")
                    compose = ct.get("compose_project")
                    if compose:
                        st.write(f"**Compose project:** {compose} / {ct.get('compose_service', '—')}")
                    restart = ct.get("restart_policy")
                    if restart:
                        st.write(f"**Restart policy:** {restart}")

                with col_actions:
                    st.write("**Actions**")
                    if state == "running":
                        if st.button("⏹ Stop", key=f"stop_{ct_id}"):
                            result = c.container_action(ct_id, "stop")
                            if result is not None:
                                st.success("Stopped.")
                                st.rerun()
                        if st.button("🔄 Restart", key=f"restart_{ct_id}"):
                            result = c.container_action(ct_id, "restart")
                            if result is not None:
                                st.success("Restarting…")
                                st.rerun()
                        if st.button("⏸ Pause", key=f"pause_{ct_id}"):
                            result = c.container_action(ct_id, "pause")
                            if result is not None:
                                st.success("Paused.")
                                st.rerun()
                    elif state == "paused":
                        if st.button("▶ Unpause", key=f"unpause_{ct_id}"):
                            result = c.container_action(ct_id, "unpause")
                            if result is not None:
                                st.success("Unpaused.")
                                st.rerun()
                    elif state in ("exited", "created", "dead"):
                        if st.button("▶ Start", key=f"start_{ct_id}"):
                            result = c.container_action(ct_id, "start")
                            if result is not None:
                                st.success("Started.")
                                st.rerun()

                    st.write("---")
                    # Removal is disabled server-side (DELETE /containers/{id}
                    # always returns 403), so no button is offered here.
                    st.caption("Removal is disabled by the API.")

                # Fetch and show env/mounts on demand
                if st.toggle("Show full detail", key=f"detail_{ct_id}"):
                    detail = c.get_container(ct_id)
                    if detail is None:
                        st.error(c.last_error() or "Could not load container detail.")
                    else:
                        env = detail.get("env", [])
                        if env:
                            st.write("**Environment variables:**")
                            st.code("\n".join(env))
                        mounts = detail.get("mounts", [])
                        if mounts:
                            st.write("**Mounts:**")
                            st.json(mounts)

# ---------------------------------------------------------------------------
# Tab 2: Live Stats
# ---------------------------------------------------------------------------

with tab_stats:
    with st.spinner("Sampling container stats…"):
        stats_payload = c.get_all_container_stats()

    if stats_payload is None:
        st.error(c.last_error() or "Could not load container stats.")
        stats_list, stats_errors = [], []
    else:
        stats_list = stats_payload.get("containers", []) or []
        stats_errors = stats_payload.get("errors", []) or []

    if stats_errors:
        with st.expander(f"⚠️ {len(stats_errors)} container(s) did not report stats"):
            st.dataframe(pd.DataFrame(stats_errors), width="stretch", hide_index=True)

    if not stats_list:
        st.info("No running containers or stats unavailable.")
    else:
        rows = []
        for s in stats_list:
            rows.append({
                "Name": s.get("name", "—"),
                "CPU %": f"{s.get('cpu_percent', 0):.1f}%",
                "Mem %": f"{s.get('memory_percent', 0):.1f}%",
                "Mem Used": bytes_to_human(s.get("memory_usage_bytes")),
                "Mem Limit": bytes_to_human(s.get("memory_limit_bytes")),
                "Net RX": bytes_to_human(s.get("network_rx_bytes")),
                "Net TX": bytes_to_human(s.get("network_tx_bytes")),
                "Block R": bytes_to_human(s.get("block_read_bytes")),
                "Block W": bytes_to_human(s.get("block_write_bytes")),
                "PIDs": s.get("pids", "—"),
            })

        df_stats = pd.DataFrame(rows)
        st.dataframe(df_stats, width="stretch", hide_index=True)

        # CPU bar chart
        names = [s.get("name", "?") for s in stats_list]
        cpus = [s.get("cpu_percent", 0) or 0 for s in stats_list]
        mems = [s.get("memory_percent", 0) or 0 for s in stats_list]

        fig = go.Figure()
        fig.add_trace(go.Bar(name="CPU %", x=names, y=cpus, marker_color="#4F8EF7"))
        fig.add_trace(go.Bar(name="Mem %", x=names, y=mems, marker_color="#e74c3c"))
        fig.update_layout(
            barmode="group",
            xaxis_title="Container",
            yaxis_title="Percent",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#fafafa"),
            margin=dict(t=20, b=40),
        )
        st.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------------------
# Tab 3: By Compose Project
# ---------------------------------------------------------------------------

with tab_groups:
    with st.spinner("Grouping containers by Compose project…"):
        groups = c.get_container_groups()

    if groups is None:
        st.error(c.last_error() or "Could not load container groups.")
    elif not groups:
        st.info("No Compose projects found.")
    else:
        summary_rows = [
            {
                "Project": g.get("project", "?"),
                "Services": g.get("total", 0),
                "Running": g.get("running", 0),
                "Paused": g.get("paused", 0),
                "Stopped": g.get("stopped", 0),
            }
            for g in groups
        ]
        st.dataframe(pd.DataFrame(summary_rows), width="stretch", hide_index=True)
        st.divider()

        for g in groups:
            project = g.get("project", "?")
            services = g.get("services", []) or []
            running = g.get("running", 0)
            total = g.get("total", len(services))
            health = "🟢" if running == total else ("🟡" if running else "🔴")

            with st.expander(f"{health} 📁 {project} — {running}/{total} running"):
                svc_rows = [
                    {
                        "": state_color(svc.get("state")),
                        "Service": svc.get("name") or "—",
                        "Container": svc.get("container_name", "—"),
                        "State": svc.get("state", "—"),
                        "Uptime": seconds_to_human(svc.get("uptime_seconds")),
                        "Image": svc.get("image", "—"),
                    }
                    for svc in services
                ]
                st.dataframe(pd.DataFrame(svc_rows), width="stretch", hide_index=True)

# ---------------------------------------------------------------------------
# Arm the refresh timer last, so a slow fetch cannot restart the page mid-load.
# ---------------------------------------------------------------------------

if auto_refresh:
    st_autorefresh(interval=10_000, key="containers_refresh")
