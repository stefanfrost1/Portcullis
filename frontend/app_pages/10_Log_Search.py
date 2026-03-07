"""
Logs page — browse container logs, search, and drill into context windows.

Primary flow:
  1. Click a container in the sidebar → its last N lines appear in the main area
  2. Use the search bar at the top to filter within that container or globally
  3. Click "🐳 Context" / "🌐 Global" on any search result line to open a
     ±N second context window around that exact log timestamp
  4. For the raw log view, copy a timestamp and paste it into the drill-down
     bar at the bottom to open the same context window
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
from utils.api_client import EngineClient, get_config

st.set_page_config(page_title="Logs", page_icon="📋", layout="wide")


@st.cache_resource
def get_client() -> EngineClient:
    cfg = get_config()
    return EngineClient(cfg["base_url"], cfg.get("api_key"))


c = get_client()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state_icon(state: str) -> str:
    return {"running": "🟢", "paused": "⏸️", "exited": "⭕", "dead": "💀"}.get(state, "⚫")


def _set_ctx(pivot: str, container_id: str, container_name: str, scope: str):
    st.session_state["ctx_state"] = {
        "pivot": pivot, "container_id": container_id,
        "container_name": container_name, "scope": scope,
    }


# ---------------------------------------------------------------------------
# Sidebar — container list + options
# ---------------------------------------------------------------------------

with st.sidebar:
    include_stopped = st.checkbox("Show stopped containers", value=False)

    all_containers = c.get_containers(all=True) or []
    visible = all_containers if include_stopped else [
        ct for ct in all_containers if ct.get("state") == "running"
    ]
    visible.sort(key=lambda ct: (0 if ct.get("state") == "running" else 1, ct.get("name", "")))

    selected_id = st.session_state.get("selected_id", "")

    st.caption(f"{len(visible)} container(s)")
    for ct in visible:
        cid = ct.get("id", "")
        cname = ct.get("name", cid[:12])
        state = ct.get("state", "")
        label = f"{_state_icon(state)} {cname}"
        is_selected = cid == selected_id
        if st.button(label, key=f"sel_{cid}", use_container_width=True,
                     type="primary" if is_selected else "secondary"):
            if not is_selected:
                st.session_state["selected_id"] = cid
                st.session_state["selected_name"] = cname
                # Clear stale state when switching containers
                for k in ("logs_cache", "logs_cache_key", "search_results", "ctx_state"):
                    st.session_state.pop(k, None)
                st.rerun()

    if not visible:
        st.info("No running containers." if not include_stopped else "No containers.")

    st.divider()
    st.caption("**Log options**")
    tail = st.slider("Lines to load", 100, 2000, 500, step=100)
    show_ts = st.checkbox("Show timestamps", value=True)
    max_results = st.slider("Max search results", 20, 200, 100, step=10)

    if st.button("↻ Refresh logs", use_container_width=True):
        st.session_state.pop("logs_cache", None)
        st.session_state.pop("logs_cache_key", None)
        st.rerun()

    st.divider()
    st.caption("**Context window**")
    window_seconds = st.slider("± seconds", 10, 300, 60, step=10)
    st.caption(f"±{window_seconds}s = {window_seconds * 2}s total")

# ---------------------------------------------------------------------------
# No container selected
# ---------------------------------------------------------------------------

selected_id = st.session_state.get("selected_id", "")
selected_name = st.session_state.get("selected_name", "")

if not selected_id:
    st.title("📋 Logs")
    st.info("← Select a container from the sidebar to view its logs.")
    st.stop()

ct_info = next((ct for ct in all_containers if ct.get("id") == selected_id), None)

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

h1, h2 = st.columns([8, 1])
with h1:
    state = (ct_info or {}).get("state", "")
    image = (ct_info or {}).get("image", "—")
    st.title(f"📋 {selected_name}")
    st.caption(f"{_state_icon(state)} {state}  ·  `{image}`")
with h2:
    if st.button("↻", help="Refresh logs"):
        st.session_state.pop("logs_cache", None)
        st.session_state.pop("logs_cache_key", None)
        st.rerun()

# ---------------------------------------------------------------------------
# SEARCH BAR — top of main area, secondary but always accessible
# ---------------------------------------------------------------------------

with st.container(border=True):
    sc1, sc2, sc3, sc4, sc5 = st.columns([5, 1, 1, 1, 1])
    with sc1:
        search_pattern = st.text_input(
            "Search pattern",
            value=st.session_state.get("search_pattern", ""),
            placeholder="regex pattern, e.g.  error|warn|timeout",
            label_visibility="collapsed",
            key="search_input",
        )
    with sc2:
        case_i = st.checkbox("i", value=False, help="Case-insensitive")
    with sc3:
        search_this = st.button("🐳 This", use_container_width=True,
                                help=f"Search within {selected_name}")
    with sc4:
        search_all = st.button("🌐 All", use_container_width=True,
                               help="Search across all containers")
    with sc5:
        if st.session_state.get("search_results") and st.button("✕", use_container_width=True,
                                                                   help="Clear search results"):
            st.session_state.pop("search_results", None)
            st.session_state.pop("search_pattern", None)
            st.rerun()

if search_this and search_pattern.strip():
    with st.spinner(f"Searching {selected_name}…"):
        res = c.search_container_logs(
            selected_id, search_pattern.strip(),
            tail=tail, max_results=max_results, case_insensitive=case_i,
        )
    if res is not None:
        st.session_state["search_results"] = {"scope": "single", "data": res}
        st.session_state["search_pattern"] = search_pattern.strip()
        st.session_state.pop("ctx_state", None)
        st.rerun()
    else:
        st.error(st.session_state.get("last_error", "Search failed."))

if search_all and search_pattern.strip():
    with st.spinner("Searching all containers…"):
        res = c.global_search_logs(
            search_pattern.strip(),
            tail=tail, max_results_per_container=max_results,
            case_insensitive=case_i, running_only=not include_stopped,
        )
    if res is not None:
        st.session_state["search_results"] = {"scope": "global", "data": res}
        st.session_state["search_pattern"] = search_pattern.strip()
        st.session_state.pop("ctx_state", None)
        st.rerun()
    else:
        st.error(st.session_state.get("last_error", "Search failed."))

# ---------------------------------------------------------------------------
# CONTEXT PANEL — shown when a drill-down is active
# ---------------------------------------------------------------------------

ctx = st.session_state.get("ctx_state")
if ctx:
    pivot = ctx["pivot"]
    scope = ctx["scope"]
    cid = ctx["container_id"]
    cname = ctx["container_name"]

    with st.container(border=True):
        hcol, bcol = st.columns([9, 1])
        with hcol:
            scope_label = f"🐳 {cname}" if scope == "single" else "🌐 All containers"
            st.subheader(f"Context — {scope_label}")
            st.caption(f"Pivot `{pivot}`  ·  ±{window_seconds}s")
        with bcol:
            if st.button("✕ Close", key="close_ctx"):
                st.session_state.pop("ctx_state", None)
                st.rerun()

        with st.spinner("Fetching context…"):
            if scope == "single":
                ctx_data = c.get_logs_context(cid, pivot=pivot,
                                              window_seconds=window_seconds, timestamps=True)
            else:
                ctx_data = c.global_logs_context(pivot=pivot, window_seconds=window_seconds,
                                                  running_only=not include_stopped, timestamps=True)

        if ctx_data is None:
            st.error(st.session_state.get("last_error", "Failed to fetch context."))
        elif scope == "single":
            lines = ctx_data.get("lines", [])
            since = ctx_data.get("since", "")[:19].replace("T", " ")
            until = ctx_data.get("until", "")[:19].replace("T", " ")
            st.caption(f"{since}  →  {until}  ·  {len(lines)} lines")
            st.code("\n".join(lines) if lines else "(no lines in window)", language=None)
        else:
            cr_list = ctx_data.get("results", [])
            cr_errors = ctx_data.get("errors", [])
            since = ctx_data.get("since", "")[:19].replace("T", " ")
            until = ctx_data.get("until", "")[:19].replace("T", " ")
            st.caption(
                f"{since}  →  {until}  ·  "
                f"{ctx_data.get('containers_with_logs', 0)} / {ctx_data.get('containers_searched', 0)} containers"
            )
            if not cr_list:
                st.info("No log output in this time window across any container.")
            for cr in cr_list:
                cr_name = cr.get("container_name", cr.get("container_id", "?"))
                cr_lines = cr.get("lines", [])
                # Expand the originating container by default, collapse others
                expand = cr.get("container_id") == cid
                with st.expander(f"🐳 {cr_name}  ({len(cr_lines)} lines)", expanded=expand):
                    st.code("\n".join(cr_lines) if cr_lines else "(no lines)", language=None)
            if cr_errors:
                with st.expander(f"⚠️ {len(cr_errors)} error(s)"):
                    for e in cr_errors:
                        st.warning(f"`{e.get('container_name', '?')}` — {e.get('error', '?')}")

# ---------------------------------------------------------------------------
# SEARCH RESULTS — shown when a search was run
# ---------------------------------------------------------------------------

search_state = st.session_state.get("search_results")
if search_state:
    scope = search_state["scope"]
    data = search_state["data"]
    pat = st.session_state.get("search_pattern", "")

    st.divider()

    if scope == "single":
        matches = data.get("matches", [])
        total = data.get("total_matched", len(matches))
        truncated = data.get("truncated", False)
        trunc_note = f"  _(showing {len(matches)} of {total})_" if truncated else ""

        st.subheader(f"Search results — `{pat}` in {selected_name}{trunc_note}")

        if not matches:
            st.info("No matches.")
        else:
            for i, m in enumerate(matches):
                ts = m.get("timestamp")
                line = m.get("line", "")
                short_ts = ts[11:23] if ts and len(ts) > 11 else (ts or "")

                rc1, rc2, rc3 = st.columns([2, 7, 3])
                with rc1:
                    st.code(short_ts or "—", language=None)
                with rc2:
                    st.code(line, language=None)
                with rc3:
                    if ts:
                        b1, b2 = st.columns(2)
                        with b1:
                            if st.button("🐳", key=f"cs_{i}",
                                         help=f"±{window_seconds}s in {selected_name}"):
                                _set_ctx(ts, selected_id, selected_name, "single")
                                st.rerun()
                        with b2:
                            if st.button("🌐", key=f"cg_{i}",
                                         help=f"±{window_seconds}s across all containers"):
                                _set_ctx(ts, selected_id, selected_name, "global")
                                st.rerun()
                    else:
                        st.caption("no ts")

    else:  # global
        total = data.get("total_matched", 0)
        searched = data.get("containers_searched", 0)
        with_matches = data.get("containers_with_matches", 0)
        errors = data.get("errors", [])

        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("Searched", searched)
        mc2.metric("With matches", with_matches)
        mc3.metric("Total matches", total)
        mc4.metric("Errors", len(errors))

        st.subheader(f"Global search — `{pat}`")

        if errors:
            with st.expander(f"⚠️ {len(errors)} error(s)"):
                for e in errors:
                    st.warning(f"`{e.get('container_name', '?')}` — {e.get('error', '?')}")

        if not data.get("results"):
            st.info(f"No matches found for `{pat}`.")
        else:
            for cr in data.get("results", []):
                cid = cr.get("container_id", "")
                cname = cr.get("container_name", cid[:12])
                matches = cr.get("matches", [])
                match_count = cr.get("match_count", len(matches))
                truncated = cr.get("truncated", False)
                trunc_note = f"  _(showing {len(matches)} of {match_count})_" if truncated else ""

                # Auto-expand the currently viewed container's results
                with st.expander(
                    f"🐳 **{cname}** — {match_count} match{'es' if match_count != 1 else ''}{trunc_note}",
                    expanded=(cid == selected_id),
                ):
                    for i, m in enumerate(matches):
                        ts = m.get("timestamp")
                        line = m.get("line", "")
                        short_ts = ts[11:23] if ts and len(ts) > 11 else (ts or "")

                        rc1, rc2, rc3 = st.columns([2, 7, 3])
                        with rc1:
                            st.code(short_ts or "—", language=None)
                        with rc2:
                            st.code(line, language=None)
                        with rc3:
                            if ts:
                                b1, b2 = st.columns(2)
                                with b1:
                                    if st.button("🐳", key=f"gcs_{cid}_{i}",
                                                 help=f"±{window_seconds}s in {cname}"):
                                        _set_ctx(ts, cid, cname, "single")
                                        st.rerun()
                                with b2:
                                    if st.button("🌐", key=f"gcg_{cid}_{i}",
                                                 help=f"±{window_seconds}s globally"):
                                        _set_ctx(ts, cid, cname, "global")
                                        st.rerun()

# ---------------------------------------------------------------------------
# LOG VIEWER — primary content
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Logs")

# Cache logs per container+tail+timestamps combo to avoid re-fetching on every widget touch
cache_key = f"{selected_id}_{tail}_{show_ts}"
if st.session_state.get("logs_cache_key") != cache_key:
    with st.spinner("Loading logs…"):
        raw = c.get_container_logs(selected_id, tail=tail, timestamps=show_ts)
    if raw is None:
        st.error(st.session_state.get("last_error", "Failed to load logs."))
        st.stop()
    lines = raw.get("lines", []) if isinstance(raw, dict) else (raw or [])
    st.session_state["logs_cache"] = lines
    st.session_state["logs_cache_key"] = cache_key

lines = st.session_state.get("logs_cache", [])
st.caption(f"{len(lines)} lines  ·  last {tail} loaded")

if lines:
    st.code("\n".join(lines), language=None)
else:
    st.info("No log output.")

# ---------------------------------------------------------------------------
# DRILL-DOWN BAR — paste a timestamp from the log above to open context
# ---------------------------------------------------------------------------

st.divider()
st.caption("**Drill-down:** copy a timestamp from the log above, paste it here, then choose the context scope.")

dc1, dc2, dc3 = st.columns([5, 1, 1])
with dc1:
    pivot_input = st.text_input(
        "Timestamp",
        placeholder="2024-01-15T10:23:45.123456789Z",
        label_visibility="collapsed",
        key="drill_pivot",
    )
with dc2:
    if st.button("🐳 Container", use_container_width=True, disabled=not pivot_input.strip(),
                 help=f"Open ±{window_seconds}s context for {selected_name}"):
        _set_ctx(pivot_input.strip(), selected_id, selected_name, "single")
        st.rerun()
with dc3:
    if st.button("🌐 Global", use_container_width=True, disabled=not pivot_input.strip(),
                 help=f"Open ±{window_seconds}s context across all containers"):
        _set_ctx(pivot_input.strip(), selected_id, selected_name, "global")
        st.rerun()
