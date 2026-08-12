"""
Redis Queues — click-to-drill queue browser.

Workflow-first: see the queues and their depths, click one to drill in, browse
or free-text search its contents, view/edit/delete a specific entry, and bulk
push to the front or back. No dropdown-select-click — click a queue to open it.
"""

import fnmatch
import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh
from utils.api_client import EngineClient, get_config, is_admin
from utils.formatting import seconds_to_human

st.set_page_config(page_title="Redis Queues", page_icon="📬", layout="wide")


@st.cache_resource
def get_client() -> EngineClient:
    cfg = get_config()
    return EngineClient(cfg["base_url"], cfg.get("api_key"))


c = get_client()
admin = is_admin()

SEL = "queue_selected_key"
_TYPE_ICON = {"list": "📋", "stream": "🌊"}


def _icon(qtype: str) -> str:
    return _TYPE_ICON.get(qtype, "•")


def _render_value(raw) -> None:
    """Show a payload as pretty JSON when it parses, otherwise as raw text."""
    if isinstance(raw, (dict, list)):
        st.json(raw)
        return
    text = "" if raw is None else str(raw)
    try:
        st.json(json.loads(text))
    except (ValueError, TypeError):
        st.code(text or "(empty)", language="text")


def _select_queue(key: str) -> None:
    """Drill into a queue and reset any per-queue view state."""
    st.session_state[SEL] = key
    for k in list(st.session_state.keys()):
        if k.startswith("qi_"):
            st.session_state.pop(k, None)


# ---------------------------------------------------------------------------
# Sidebar — scan + sort controls
# ---------------------------------------------------------------------------

with st.sidebar:
    st.subheader("Queues")
    pattern = st.text_input("Key pattern", value="*", help="Glob over key names, e.g. queue:*")
    max_keys = st.slider("Max keys to scan", 100, 5000, 500, 100)
    sort_choice = st.selectbox(
        "Sort by",
        ["Depth (high → low)", "Depth (low → high)", "Name (A → Z)", "Name (Z → A)"],
        index=0,
    )
    name_filter = st.text_input("Filter by name", value="", placeholder="substring…")
    st.divider()
    auto_refresh = st.checkbox("Auto-refresh (10s)", value=False)
    if st.button("↻ Refresh now", use_container_width=True):
        st.rerun()

st.title("📬 Redis Queues")
if not admin:
    st.caption("🔒 Read-only — sign in as admin to edit, delete, or push.")

# ---------------------------------------------------------------------------
# Fetch + sort + filter
# ---------------------------------------------------------------------------

with st.spinner("Scanning for queues…"):
    queues = c.get_redis_queues(pattern=pattern or "*", max_keys=max_keys) or []

if c.last_error():
    st.error(c.last_error())

if sort_choice.startswith("Depth"):
    queues.sort(key=lambda q: q.get("depth") or 0, reverse=sort_choice.endswith("(high → low)"))
else:
    queues.sort(key=lambda q: (q.get("key") or "").lower(), reverse=sort_choice.endswith("(Z → A)"))

nf = name_filter.strip().lower()
visible = [q for q in queues if not nf or nf in (q.get("key") or "").lower()]

total_depth = sum(q.get("depth") or 0 for q in queues)
m1, m2, m3 = st.columns(3)
m1.metric("Queues", len(queues))
m2.metric("Total depth", f"{total_depth:,}")
m3.metric("Shown", len(visible))

with st.expander("📊 Depth chart (top 20)", expanded=False):
    top = sorted(queues, key=lambda q: q.get("depth") or 0, reverse=True)[:20]
    if top:
        fig = go.Figure(
            go.Bar(
                x=[q.get("depth") or 0 for q in top],
                y=[q.get("key") for q in top],
                orientation="h",
                marker_color="#4F8EF7",
                text=[f"{q.get('depth') or 0:,}" for q in top],
                textposition="auto",
            )
        )
        fig.update_layout(
            yaxis=dict(autorange="reversed"),
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#fafafa"),
            margin=dict(t=10, b=20, l=10, r=10),
            height=max(240, min(len(top) * 26, 700)),
        )
        st.plotly_chart(fig, width="stretch")
    else:
        st.caption("No queues to chart.")

st.divider()

# ---------------------------------------------------------------------------
# Master (click list) + detail (inspector)
# ---------------------------------------------------------------------------

list_col, insp_col = st.columns([1, 2], gap="large")

MAX_ROWS = 200
with list_col:
    st.markdown("#### Click a queue")
    if not visible:
        st.info("No queues match the pattern/filter.")
    for q in visible[:MAX_ROWS]:
        key = q.get("key", "?")
        depth = q.get("depth") or 0
        qtype = q.get("type", "?")
        is_sel = st.session_state.get(SEL) == key
        label = f"{'▶ ' if is_sel else ''}{_icon(qtype)} {key}  ·  {depth:,}"
        if st.button(
            label,
            key=f"q_{key}",
            use_container_width=True,
            type="primary" if is_sel else "secondary",
        ):
            _select_queue(key)
            st.rerun()
    if len(visible) > MAX_ROWS:
        st.caption(f"Showing first {MAX_ROWS} of {len(visible)} — narrow with the name filter.")


# ---------------------------------------------------------------------------
# Inspector renderers
# ---------------------------------------------------------------------------

def _entry_actions(key: str, index: int, value, uid: str) -> None:
    """View + (admin) edit/delete controls for a single list entry."""
    _render_value(value)
    if not admin:
        return
    new_val = st.text_area("Edit value", value=str(value), key=f"qi_ev_{uid}")
    if st.button("💾 Save", key=f"qi_save_{uid}"):
        # Safeguard: the index may have shifted since load (the queue drained).
        # Only LSET in place if the index still holds the value we loaded;
        # otherwise remove the original and append the edit to the back so we
        # never overwrite a different entry that moved into this slot.
        current = c.get_redis_list(key, index, index)
        cur_items = (current or {}).get("items", []) if current is not None else []
        cur_val = cur_items[0] if cur_items else None
        if cur_val is not None and str(cur_val) == str(value):
            res = c.set_redis_list_index(key, index, new_val)
            if res is not None:
                st.success(f"Updated index {index} in place.")
                st.rerun()
            else:
                st.error(c.last_error() or "Could not update.")
        else:
            rem = c.remove_redis_list_value(key, str(value), count=1)
            push = c.push_redis_list(key, [new_val], direction="right")
            if push is not None:
                removed = (rem or {}).get("removed", 0) if rem is not None else 0
                st.success(
                    f"Index moved since load — removed {removed} original and "
                    f"appended the edit to the back (new length {push.get('length'):,})."
                )
                st.rerun()
            else:
                st.error(c.last_error() or "Could not apply edit.")
    if st.button("🗑 Delete this entry", key=f"qi_del_{uid}"):
        res = c.remove_redis_list_value(key, str(value), count=1)
        if res is not None:
            st.success(f"Removed {res.get('removed', 0)} entry.")
            st.rerun()
        else:
            st.error(c.last_error() or "Could not delete.")


def _render_list_inspector(key: str, depth: int) -> None:
    tab_browse, tab_search, tab_modify = st.tabs(["🔎 Browse", "🔍 Search", "✏️ Modify"])

    # -- Browse --------------------------------------------------------
    with tab_browse:
        size = st.selectbox("Page size", [10, 25, 50, 100], index=0, key=f"qi_size_{key}")
        start = st.number_input(
            "From index (0 = head / front)",
            min_value=0, value=0, step=int(size), key=f"qi_start_{key}",
        )
        start = int(start)
        page = c.get_redis_list(key, start=start, stop=start + int(size) - 1)
        if page is None:
            st.error(c.last_error() or "Could not read entries.")
        else:
            items = page.get("items", []) or []
            if not items:
                st.info("No entries in this range.")
            for i, item in enumerate(items):
                idx = start + i
                with st.expander(f"#{idx}"):
                    _entry_actions(key, idx, item, uid=f"{key}_b_{idx}")
            if items:
                st.download_button(
                    "⬇ Export shown",
                    data=json.dumps(items, indent=2, default=str),
                    file_name=f"{key.replace(':', '_')}_{start}.json",
                    mime="application/json",
                    key=f"qi_dl_{key}",
                )

    # -- Search --------------------------------------------------------
    with tab_search:
        term = st.text_input(
            "Find text in entries", key=f"qi_find_{key}",
            placeholder="substring — or use * and ? wildcards",
            help="Plain text matches any entry that contains it. Add * (any run) "
                 "or ? (one char) to switch to whole-value wildcard matching, "
                 "e.g. `*CostCenter*` or `lock:*`. Case-insensitive.",
        )
        window = st.slider("Scan the first N entries", 100, 5000, 1000, 100, key=f"qi_win_{key}")
        if term:
            scanned = c.get_redis_list(key, start=0, stop=int(window) - 1)
            items = (scanned or {}).get("items", []) or []
            tl = term.lower()
            if any(ch in term for ch in "*?"):
                # Wildcard: match the whole value (glob-anchored), case-insensitive.
                matches = [(i, v) for i, v in enumerate(items)
                           if fnmatch.fnmatchcase(str(v).lower(), tl)]
            else:
                # Plain text: contains match, case-insensitive.
                matches = [(i, v) for i, v in enumerate(items) if tl in str(v).lower()]
            st.caption(
                f"{len(matches)} match(es) in the first {min(int(window), depth):,} of "
                f"{depth:,} entries."
            )
            if admin and matches:
                confirm = st.checkbox(
                    f"Yes, delete all {len(matches)} matching entries", key=f"qi_delall_ok_{key}"
                )
                if st.button("🗑 Delete all matches", key=f"qi_delall_{key}", disabled=not confirm):
                    removed = 0
                    for val in {str(v) for _, v in matches}:
                        res = c.remove_redis_list_value(key, val, count=0)
                        if res is not None:
                            removed += res.get("removed", 0) or 0
                    st.success(f"Removed {removed} entr{'y' if removed == 1 else 'ies'}.")
                    st.rerun()
            for idx, val in matches[:200]:
                with st.expander(f"#{idx}"):
                    _entry_actions(key, idx, val, uid=f"{key}_s_{idx}")
            if len(matches) > 200:
                st.caption("Showing first 200 matches.")

    # -- Modify --------------------------------------------------------
    with tab_modify:
        if not admin:
            st.info("Sign in as admin to push or pop.")
        else:
            st.markdown("**Bulk push** — one value per line")
            vals = st.text_area("Values", key=f"qi_push_{key}", height=120,
                                label_visibility="collapsed")
            where = st.radio("Push to", ["Back (tail)", "Front (head)"],
                             horizontal=True, key=f"qi_dir_{key}")
            if st.button("⬆ Push", key=f"qi_pushbtn_{key}"):
                values = [ln for ln in vals.splitlines() if ln.strip() != ""]
                if not values:
                    st.warning("Nothing to push.")
                else:
                    direction = "left" if where.startswith("Front") else "right"
                    res = c.push_redis_list(key, values, direction=direction)
                    if res is not None:
                        st.success(f"Pushed {len(values)} — new length {res.get('length'):,}.")
                        st.rerun()
                    else:
                        st.error(c.last_error() or "Could not push.")
            st.divider()
            st.markdown("**Pop one entry**")
            if st.button("⤺ Pop from front", key=f"qi_popf_{key}"):
                res = c.pop_redis_list(key, direction="left")
                if res is not None:
                    st.success(f"Popped: {res.get('value')!r}")
                    st.rerun()
                else:
                    st.error(c.last_error() or "Could not pop.")
            if st.button("Pop from back ⤻", key=f"qi_popb_{key}"):
                res = c.pop_redis_list(key, direction="right")
                if res is not None:
                    st.success(f"Popped: {res.get('value')!r}")
                    st.rerun()
                else:
                    st.error(c.last_error() or "Could not pop.")


def _render_stream_inspector(key: str, detail: dict) -> None:
    groups = detail.get("consumer_groups") or []
    if groups:
        st.markdown("**Consumer groups**")
        for g in groups:
            st.write(
                f"- **{g.get('name')}** — {g.get('consumers', 0)} consumer(s), "
                f"{g.get('pending', 0)} pending, last {g.get('last_delivered_id', '—')}"
            )
    sample = detail.get("sample_oldest") or []
    st.markdown("**Newest entries**" if not sample else "**Oldest entries (sample)**")
    entries = c.get_redis_stream(key, start="-", end="+", count=20)
    rows = (entries or {}).get("items", []) or sample
    if not rows:
        st.info("No entries.")
    for entry in rows:
        label = entry.get("id", "?") if isinstance(entry, dict) else "entry"
        with st.expander(f"📨 {label}"):
            _render_value(entry.get("fields") if isinstance(entry, dict) else entry)


with insp_col:
    target = st.session_state.get(SEL)
    if not target:
        st.info("← Click a queue on the left to open it.")
    else:
        detail = c.get_redis_queue(target, sample_count=10)
        if detail is None:
            st.error(c.last_error() or f"Could not inspect '{target}'.")
        else:
            qtype = detail.get("type", "?")
            depth = detail.get("depth", 0) or 0

            st.markdown(f"### {_icon(qtype)} `{target}`")
            d1, d2, d3 = st.columns(3)
            d1.metric("Type", qtype)
            d2.metric("Depth", f"{depth:,}")
            oldest = detail.get("oldest_pending_age_seconds")
            d3.metric("Oldest pending", seconds_to_human(oldest) if oldest is not None else "—")

            if qtype == "list":
                _render_list_inspector(target, depth)
            elif qtype == "stream":
                _render_stream_inspector(target, detail)
            else:
                st.info("Unsupported queue type for the inspector.")
                for i, item in enumerate(detail.get("sample_oldest") or []):
                    with st.expander(f"message {i}"):
                        _render_value(item)

# ---------------------------------------------------------------------------
# Arm the refresh timer last, so a slow scan cannot restart the page mid-load.
# ---------------------------------------------------------------------------

if auto_refresh:
    st_autorefresh(interval=10_000, key="queues_refresh")
