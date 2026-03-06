"""
Redis Server page — summary, performance, replication, clients, slowlog, config, memory, latency.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
from utils.api_client import EngineClient, get_config
from utils.formatting import bytes_to_human, seconds_to_human

st.set_page_config(page_title="Redis Server", page_icon="🔴", layout="wide")
st.title("🔴 Redis Server")


@st.cache_resource
def get_client() -> EngineClient:
    cfg = get_config()
    return EngineClient(cfg["base_url"], cfg.get("api_key"))


c = get_client()

if "last_error" in st.session_state:
    st.error(st.session_state["last_error"])


def _percent_text(value) -> str:
    try:
        if value is None:
            return "—"
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "—"

with st.sidebar:
    if st.button("↻ Refresh"):
        st.rerun()

(
    tab_summary,
    tab_perf,
    tab_repl,
    tab_clients,
    tab_slow,
    tab_config,
    tab_memory,
    tab_latency,
) = st.tabs(["Summary", "Performance", "Replication", "Clients", "Slow Log", "Config", "Memory", "Latency"])

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

with tab_summary:
    summary = c.get_redis_summary()
    if not summary:
        st.warning("Redis summary unavailable.")
    else:
        server = summary.get("server", {}) or {}
        clients_s = summary.get("clients", {}) or {}
        memory = summary.get("memory", {}) or {}
        perf = summary.get("performance", {}) or {}
        keyspace = summary.get("keyspace", {}) or {}
        repl = summary.get("replication", {}) or {}

        st.subheader("Server")
        c1, c2, c3 = st.columns(3)
        c1.metric("Redis Version", server.get("redis_version", "—"))
        c2.metric("Uptime", seconds_to_human(server.get("uptime_in_seconds")))
        c3.metric("Mode", server.get("redis_mode", "—"))

        st.subheader("Clients & Memory")
        c4, c5, c6 = st.columns(3)
        c4.metric("Connected Clients", clients_s.get("connected_clients", 0))
        c5.metric("Memory Used", bytes_to_human(memory.get("used_memory_bytes")))
        c6.metric("Peak Memory", bytes_to_human(memory.get("used_memory_peak_bytes")))

        st.subheader("Performance & Keys")
        c7, c8, c9 = st.columns(3)
        c7.metric("Ops / sec", f"{perf.get('instantaneous_ops_per_sec', 0):,}")
        c8.metric("Hit Rate", _percent_text(perf.get("hit_rate_percent")))
        c9.metric("Total Keys", keyspace.get("total_keys", 0))

        st.subheader("Replication")
        c10, c11 = st.columns(2)
        c10.metric("Role", repl.get("role", "—"))
        c11.metric("Connected Replicas", repl.get("connected_replicas", 0))

# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

with tab_perf:
    perf = c.get_redis_performance()
    if not perf:
        st.warning("Performance data unavailable.")
    else:
        p1, p2 = st.columns(2)
        p1.metric("Ops / sec", f"{perf.get('instantaneous_ops_per_sec', 0):,}")
        p2.metric("Net I/O (in)", bytes_to_human(perf.get("instantaneous_input_kbps")) + "/s" if perf.get("instantaneous_input_kbps") is not None else "—")

        p3, p4 = st.columns(2)
        p3.metric("Hit Rate", _percent_text(perf.get("hit_rate_percent")))
        p4.metric("Evictions", f"{perf.get('evicted_keys', 0):,}")

        p5, p6 = st.columns(2)
        p5.metric("Keyspace Hits", f"{perf.get('keyspace_hits', 0):,}")
        p6.metric("Keyspace Misses", f"{perf.get('keyspace_misses', 0):,}")

        p7, p8 = st.columns(2)
        p7.metric("Total Commands Processed", f"{perf.get('total_commands_processed', 0):,}")
        p8.metric("Expired Keys", f"{perf.get('expired_keys', 0):,}")

# ---------------------------------------------------------------------------
# Replication
# ---------------------------------------------------------------------------

with tab_repl:
    repl = c.get_redis_replication()
    if not repl:
        st.warning("Replication data unavailable.")
    else:
        r1, r2, r3 = st.columns(3)
        r1.metric("Role", repl.get("role", "—"))
        r2.metric("Connected Replicas", repl.get("connected_replicas", 0))
        r3.metric("Replication ID", repl.get("master_replid", "—")[:16] + "…" if repl.get("master_replid") else "—")

        r4, r5 = st.columns(2)
        r4.metric("Master Repl Offset", repl.get("master_repl_offset", "—"))
        r5.metric("Second Repl Offset", repl.get("second_repl_offset", "—"))

        replicas = repl.get("replicas", []) or []
        if replicas:
            st.subheader("Replicas")
            st.dataframe(pd.DataFrame(replicas), width="stretch", hide_index=True)

# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

with tab_clients:
    clients = c.get_redis_clients() or []
    if not clients:
        st.info("No client data.")
    else:
        df = pd.DataFrame(clients)
        st.dataframe(df, width="stretch", hide_index=True)

# ---------------------------------------------------------------------------
# Slow Log
# ---------------------------------------------------------------------------

with tab_slow:
    slowlog = c.get_redis_slowlog() or []

    col_sl, col_reset = st.columns([4, 1])
    with col_reset:
        if st.button("Reset Slow Log"):
            c.reset_redis_slowlog()
            st.rerun()

    if not slowlog:
        st.info("No slow log entries.")
    else:
        rows = []
        for entry in slowlog:
            rows.append({
                "ID": entry.get("id", "?"),
                "Timestamp": entry.get("timestamp", "—"),
                "Duration (µs)": entry.get("duration_us", 0),
                "Command": " ".join(str(a) for a in (entry.get("args") or [])),
                "Client": entry.get("client_addr", "—"),
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

with tab_config:
    col_search, col_save = st.columns([3, 1])
    with col_search:
        config_pattern = st.text_input("Filter config keys (glob)", value="*", key="config_pattern")

    config = c.get_redis_config(pattern=config_pattern)

    if not config:
        st.warning("Config data unavailable.")
    else:
        cfg_items = config if isinstance(config, dict) else {}
        if not cfg_items:
            st.info("No config keys matched.")
        else:
            st.caption(f"{len(cfg_items)} config key(s) shown.")
            for param, val in sorted(cfg_items.items()):
                with st.expander(param, expanded=False):
                    new_val = st.text_input("Value", value=str(val), key=f"cfg_{param}")
                    if st.button("Save", key=f"save_cfg_{param}"):
                        result = c.set_redis_config(param, new_val)
                        if result is not None:
                            st.success(f"Set {param} = {new_val}")
                        elif "last_error" in st.session_state:
                            st.error(st.session_state["last_error"])

    st.divider()
    st.subheader("Persistence")
    col_bg1, col_bg2 = st.columns(2)
    with col_bg1:
        if st.button("BGSAVE"):
            result = c.redis_bgsave()
            if result is not None:
                st.success("BGSAVE triggered.")
    with col_bg2:
        if st.button("BGREWRITEAOF"):
            result = c.redis_bgrewriteaof()
            if result is not None:
                st.success("BGREWRITEAOF triggered.")

    st.divider()
    st.subheader("⚠️ Danger Zone")
    if st.session_state.get("confirm_flushdb"):
        st.error("This will delete ALL keys in the current database. Are you sure?")
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("Yes, FLUSHDB"):
                result = c.redis_flushdb()
                if result is not None:
                    st.success("FLUSHDB complete.")
                st.session_state.pop("confirm_flushdb", None)
                st.rerun()
        with col_no:
            if st.button("Cancel FLUSHDB"):
                st.session_state.pop("confirm_flushdb", None)
                st.rerun()
    else:
        if st.button("FLUSHDB (delete all keys in DB)"):
            st.session_state["confirm_flushdb"] = True
            st.rerun()

# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

with tab_memory:
    mem = c.get_redis_memory_stats()
    if not mem:
        st.warning("Memory stats unavailable.")
    else:
        stats = mem.get("stats", {}) or {}
        doctor = mem.get("doctor", "")

        if doctor:
            st.info(f"MEMORY DOCTOR: {doctor}")

        st.subheader("Memory breakdown")
        key_stats = {
            "used_memory": "Used Memory",
            "used_memory_rss": "RSS",
            "used_memory_peak": "Peak",
            "used_memory_overhead": "Overhead",
            "used_memory_dataset": "Dataset",
            "mem_fragmentation_ratio": "Fragmentation Ratio",
        }
        cols = st.columns(3)
        for i, (k, label) in enumerate(key_stats.items()):
            val = stats.get(k)
            if isinstance(val, (int, float)) and "ratio" not in k:
                display = bytes_to_human(int(val))
            elif val is not None:
                display = str(val)
            else:
                display = "—"
            cols[i % 3].metric(label, display)

        with st.expander("Full MEMORY STATS"):
            st.json(stats)

# ---------------------------------------------------------------------------
# Latency
# ---------------------------------------------------------------------------

with tab_latency:
    latency = c.get_redis_latency_latest() or []

    col_lat, col_reset = st.columns([4, 1])
    with col_reset:
        if st.button("Reset Latency"):
            c.reset_redis_latency()
            st.rerun()

    if not latency:
        st.info("No latency events recorded.")
    else:
        st.dataframe(pd.DataFrame(latency), width="stretch", hide_index=True)
