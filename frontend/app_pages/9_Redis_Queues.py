"""
Redis Queues page — monitor and audit List / Stream queues.

Top half:  depth overview across every queue key (chart + table).
Bottom half: inspector for one queue — consumer groups, pending summary, and
the actual messages, paged and JSON-decoded.

Editing a queue's contents happens in the Redis Keys inspector; the "Edit in
Key Inspector" button hands the selected key over to that page.
"""

import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
from utils.api_client import EngineClient, get_config
from utils.formatting import seconds_to_human

st.set_page_config(page_title="Redis Queues", page_icon="📬", layout="wide")
st.title("📬 Redis Queues")


@st.cache_resource
def get_client() -> EngineClient:
    cfg = get_config()
    return EngineClient(cfg["base_url"], cfg.get("api_key"))


c = get_client()

SELECTED = "queue_selected_key"


def _render_message(raw) -> None:
    """Show a queue payload as JSON when it parses, otherwise as raw text."""
    if isinstance(raw, (dict, list)):
        st.json(raw)
        return
    text = "" if raw is None else str(raw)
    try:
        st.json(json.loads(text))
    except (ValueError, TypeError):
        st.code(text or "(empty)", language="text")


with st.sidebar:
    pattern = st.text_input("Queue key pattern", value="*")
    max_keys = st.slider("Max keys to scan", min_value=100, max_value=5000, value=500, step=100)
    auto_refresh = st.checkbox("Auto-refresh (10s)", value=False)
    if st.button("↻ Refresh now"):
        st.rerun()
    top_n = st.slider("Chart: top N queues", min_value=5, max_value=50, value=20)

# ---------------------------------------------------------------------------
# Queue overview
# ---------------------------------------------------------------------------

with st.spinner("Scanning for queue keys…"):
    queues = c.get_redis_queues(pattern=pattern or "*", max_keys=max_keys)

if queues is None:
    st.error(c.last_error() or "Could not scan for queues.")
    queues = []

if not queues:
    st.info("No queues found. List or Stream keys will appear here when they exist.")
    queues_sorted = []
else:
    queues_sorted = sorted(queues, key=lambda q: q.get("depth", 0) or 0, reverse=True)

    total_depth = sum(q.get("depth", 0) or 0 for q in queues_sorted)
    total_pending = sum(
        sum(g.get("pending", 0) or 0 for g in (q.get("consumer_groups") or []))
        for q in queues_sorted
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Queues", len(queues_sorted))
    col2.metric("Total Depth", f"{total_depth:,}")
    col3.metric("Pending (streams)", f"{total_pending:,}")
    col4.metric("Deepest Queue", queues_sorted[0].get("key", "?"))

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
    st.plotly_chart(fig, width="stretch")

    # Table — consumer group data only exists for streams. The stream/list
    # columns must stay a single dtype or Arrow refuses to serialise them.
    rows = []
    for q in queues_sorted:
        groups = q.get("consumer_groups") or []
        is_stream = q.get("type") == "stream"
        rows.append({
            "Queue": q.get("key", "?"),
            "Type": q.get("type", "?"),
            "Depth": q.get("depth", 0),
            "Consumer Groups": str(len(groups)) if is_stream else "—",
            "Pending": (
                str(sum(g.get("pending", 0) or 0 for g in groups)) if is_stream else "—"
            ),
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

st.divider()

# ---------------------------------------------------------------------------
# Queue inspector
# ---------------------------------------------------------------------------

st.subheader("Queue inspector")

queue_names = [q.get("key", "?") for q in queues_sorted]

col_pick, col_count = st.columns([3, 1])
with col_pick:
    if queue_names:
        default_idx = (
            queue_names.index(st.session_state[SELECTED])
            if st.session_state.get(SELECTED) in queue_names else 0
        )
        target = st.selectbox("Queue", queue_names, index=default_idx, key="queue_picker")
    else:
        target = st.text_input("Queue key", value=st.session_state.get(SELECTED, ""))
with col_count:
    sample_count = st.number_input("Messages to show", min_value=1, max_value=100, value=10)

target = (target or "").strip()

if not target:
    st.info("Select a queue to inspect its contents.")
else:
    st.session_state[SELECTED] = target
    detail = c.get_redis_queue(target, sample_count=int(sample_count))

    if detail is None:
        st.error(c.last_error() or f"Could not inspect '{target}'.")
    else:
        qtype = detail.get("type", "?")
        depth = detail.get("depth", 0) or 0

        d1, d2, d3 = st.columns(3)
        d1.metric("Type", qtype)
        d2.metric("Depth", f"{depth:,}")
        oldest_age = detail.get("oldest_pending_age_seconds")
        d3.metric("Oldest pending", seconds_to_human(oldest_age) if oldest_age is not None else "—")

        if st.button("✏️ Edit in Key Inspector"):
            st.session_state["redis_selected_key"] = target
            st.switch_page("app_pages/6_Redis_Keys.py")

        # -- Consumer groups (streams) ---------------------------------

        groups = detail.get("consumer_groups") or []
        if groups:
            st.write("**Consumer groups**")
            st.dataframe(
                pd.DataFrame([
                    {
                        "Group": g.get("name"),
                        "Consumers": g.get("consumers", 0),
                        "Pending": g.get("pending", 0),
                        "Last delivered": g.get("last_delivered_id"),
                        # Lag is None before Redis 7.0 — keep the column one dtype.
                        "Lag": "—" if g.get("lag") is None else str(g.get("lag")),
                    }
                    for g in groups
                ]),
                width="stretch",
                hide_index=True,
            )

        pending_summary = detail.get("pending_summary") or []
        if pending_summary:
            st.write("**Pending messages by group**")
            for entry in pending_summary:
                with st.expander(
                    f"⏳ {entry.get('group')} — {entry.get('total_pending', 0)} pending"
                ):
                    st.caption(
                        f"IDs {entry.get('min_pending_id', '—')} → {entry.get('max_pending_id', '—')}"
                    )
                    consumers = entry.get("consumers") or []
                    if consumers:
                        st.dataframe(
                            pd.DataFrame([
                                {"Consumer": cons.get("name"), "Pending": cons.get("pending_count", 0)}
                                for cons in consumers
                            ]),
                            width="stretch",
                            hide_index=True,
                        )

        # -- Message contents ------------------------------------------

        st.write("**Messages**")

        if qtype == "list":
            start = st.number_input("From index", min_value=0, value=0, step=10, key=f"lstart_{target}")
            page = c.get_redis_list(target, start=int(start), stop=int(start) + int(sample_count) - 1)
            if page is None:
                st.error(c.last_error() or "Could not read queue items.")
            else:
                items = page.get("items", []) or []
                if not items:
                    st.info("No messages in this range.")
                for i, item in enumerate(items):
                    with st.expander(f"📨 index {int(start) + i}"):
                        _render_message(item)
                if items:
                    st.download_button(
                        "⬇ Export shown messages",
                        data=json.dumps(items, indent=2, default=str),
                        file_name=f"{target.replace(':', '_')}_messages.json",
                        mime="application/json",
                    )

        elif qtype == "stream":
            col_s, col_e = st.columns(2)
            with col_s:
                s_start = st.text_input("From ID", value="-", key=f"qxs_{target}")
            with col_e:
                s_end = st.text_input("To ID", value="+", key=f"qxe_{target}")

            page = c.get_redis_stream(target, start=s_start, end=s_end, count=int(sample_count))
            if page is None:
                st.error(c.last_error() or "Could not read stream entries.")
            else:
                entries = page.get("items", []) or []
                if not entries:
                    st.info("No entries in this range.")
                for entry in entries:
                    with st.expander(f"📨 {entry.get('id', '?')}"):
                        _render_message(entry.get("fields"))
                if entries:
                    st.download_button(
                        "⬇ Export shown entries",
                        data=json.dumps(entries, indent=2, default=str),
                        file_name=f"{target.replace(':', '_')}_entries.json",
                        mime="application/json",
                    )

        else:
            # Fall back to the sample the queue endpoint already returned.
            sample = detail.get("sample_oldest") or []
            if not sample:
                st.info("No message sample available for this key type.")
            for i, item in enumerate(sample):
                with st.expander(f"📨 message {i}"):
                    _render_message(item)

# ---------------------------------------------------------------------------
# Arm the refresh timer last, so a slow scan cannot restart the page mid-load.
# ---------------------------------------------------------------------------

if auto_refresh:
    st_autorefresh(interval=10_000, key="queues_refresh")
