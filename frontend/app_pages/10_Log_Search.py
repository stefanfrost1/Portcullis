"""
Logs page — global merged log view by default; click a container for focused view.

UX:
  - Default: merged timeline of all running containers, newest at bottom
  - Sidebar: compact container list with filter for 60+ containers;
    running containers shown directly, stopped in a collapsible section
  - Search bar at the top of the main area (secondary, always accessible)
  - Any search result line has 🐳 / 🌐 drill-down buttons
  - Raw log view has a timestamp paste bar at the bottom for drill-down
  - Context panel floats above the log view when active
"""

import re
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
from utils.api_client import EngineClient, get_config

st.set_page_config(page_title="Logs", page_icon="📋", layout="wide")

_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s*(.*)")
_STATE_ICON = {"running": "🟢", "paused": "⏸️", "exited": "⭕", "dead": "💀"}


@st.cache_resource
def get_client() -> EngineClient:
    cfg = get_config()
    return EngineClient(cfg["base_url"], cfg.get("api_key"))


c = get_client()


def _icon(state: str) -> str:
    return _STATE_ICON.get(state, "⚫")


def _split(line: str) -> tuple[str, str]:
    """Split 'TIMESTAMP content' → (timestamp, content). Returns ("", line) if no ts."""
    m = _TS_RE.match(line)
    return (m.group(1), m.group(2)) if m else ("", line)


def _set_ctx(pivot: str, container_id: str, container_name: str, scope: str):
    st.session_state["ctx_state"] = {
        "pivot": pivot, "container_id": container_id,
        "container_name": container_name, "scope": scope,
    }


def _clear_state(*keys):
    for k in keys:
        st.session_state.pop(k, None)


# ---------------------------------------------------------------------------
# Sidebar — compact container selector
# ---------------------------------------------------------------------------

with st.sidebar:
    # Fetch once; cached per Streamlit run
    all_containers = c.get_containers(all=True) or []
    running = sorted(
        [ct for ct in all_containers if ct.get("state") == "running"],
        key=lambda ct: ct.get("name", ""),
    )
    stopped = sorted(
        [ct for ct in all_containers if ct.get("state") != "running"],
        key=lambda ct: ct.get("name", ""),
    )

    selected_id = st.session_state.get("selected_id", "")  # "" = All

    # "All" button — always at the top
    if st.button(
        f"🌐  All containers  ({len(running)} running)",
        use_container_width=True,
        type="primary" if selected_id == "" else "secondary",
    ):
        if selected_id != "":
            st.session_state["selected_id"] = ""
            _clear_state("selected_name", "logs_cache", "logs_cache_key",
                         "search_results", "ctx_state")
            st.rerun()

    st.divider()

    # Filter input — handles 60+ containers without scrolling forever
    filt = st.text_input(
        "Filter", placeholder="filter containers…",
        label_visibility="collapsed", key="ct_filter",
    )

    def _matches(ct):
        return not filt or filt.lower() in ct.get("name", "").lower()

    # Running containers
    visible_running = [ct for ct in running if _matches(ct)]
    for ct in visible_running:
        cid = ct.get("id", "")
        cname = ct.get("name", cid[:12])
        is_sel = cid == selected_id
        if st.button(
            f"🟢 {cname}", key=f"sel_{cid}",
            use_container_width=True,
            type="primary" if is_sel else "secondary",
        ):
            if not is_sel:
                st.session_state["selected_id"] = cid
                st.session_state["selected_name"] = cname
                _clear_state("logs_cache", "logs_cache_key", "search_results", "ctx_state")
                st.rerun()

    if not visible_running and not filt:
        st.caption("No running containers.")

    # Stopped containers — collapsed so they don't dominate the sidebar
    visible_stopped = [ct for ct in stopped if _matches(ct)]
    if visible_stopped:
        label = f"Stopped ({len(visible_stopped)})" + (f" — {len(stopped)} total" if filt else "")
        with st.expander(label, expanded=bool(filt)):
            for ct in visible_stopped:
                cid = ct.get("id", "")
                cname = ct.get("name", cid[:12])
                state = ct.get("state", "")
                is_sel = cid == selected_id
                if st.button(
                    f"{_icon(state)} {cname}", key=f"sel_{cid}",
                    use_container_width=True,
                    type="primary" if is_sel else "secondary",
                ):
                    if not is_sel:
                        st.session_state["selected_id"] = cid
                        st.session_state["selected_name"] = cname
                        _clear_state("logs_cache", "logs_cache_key", "search_results", "ctx_state")
                        st.rerun()

    st.divider()
    st.caption("**Log options**")

    # Smaller tail default for global view (N containers × tail = total lines)
    if selected_id == "":
        tail = st.slider("Lines per container", 50, 500, 100, step=50)
        merge_view = st.checkbox("Merge into timeline", value=True,
                                 help="Interleave all container logs sorted by timestamp")
        include_stopped_global = st.checkbox("Include stopped containers", value=False)
    else:
        tail = st.slider("Lines to load", 100, 2000, 500, step=100)

    show_ts = st.checkbox("Show timestamps", value=True)
    max_results = st.slider("Max search results", 20, 200, 100, step=10)

    if st.button("↻ Refresh", use_container_width=True):
        _clear_state("logs_cache", "logs_cache_key")
        st.rerun()

    st.divider()
    st.caption("**Context window**")
    window_seconds = st.slider("± seconds", 10, 300, 60, step=10)
    st.caption(f"±{window_seconds}s = {window_seconds * 2}s total")


# ---------------------------------------------------------------------------
# Re-read selected state (may have changed in sidebar above)
# ---------------------------------------------------------------------------

selected_id = st.session_state.get("selected_id", "")
selected_name = st.session_state.get("selected_name", "")
is_global = selected_id == ""

# ---------------------------------------------------------------------------
# Shared helpers rendered in main area
# ---------------------------------------------------------------------------

def _render_context_panel():
    """Render the active context panel (shown when ctx_state is set)."""
    ctx = st.session_state.get("ctx_state")
    if not ctx:
        return

    pivot = ctx["pivot"]
    scope = ctx["scope"]
    cid = ctx["container_id"]
    cname = ctx["container_name"]
    running_only = not st.session_state.get("include_stopped_global_val", False)

    with st.container(border=True):
        hcol, bcol = st.columns([9, 1])
        with hcol:
            scope_label = f"🐳 {cname}" if scope == "single" else "🌐 All containers"
            st.subheader(f"Context — {scope_label}")
            st.caption(f"Pivot `{pivot}`  ·  ±{window_seconds}s")
        with bcol:
            if st.button("✕ Close", key="close_ctx"):
                _clear_state("ctx_state")
                st.rerun()

        with st.spinner("Fetching context…"):
            if scope == "single":
                ctx_data = c.get_logs_context(
                    cid, pivot=pivot, window_seconds=window_seconds, timestamps=True,
                )
            else:
                ctx_data = c.global_logs_context(
                    pivot=pivot, window_seconds=window_seconds,
                    running_only=running_only, timestamps=True,
                )

        if ctx_data is None:
            st.error(st.session_state.get("last_error", "Failed to fetch context."))
            return

        if scope == "single":
            lines = ctx_data.get("lines", [])
            since = ctx_data.get("since", "")[:19].replace("T", " ")
            until = ctx_data.get("until", "")[:19].replace("T", " ")
            st.caption(f"{since}  →  {until}  ·  {len(lines)} lines")
            st.code("\n".join(lines) if lines else "(no lines in window)", language=None)
        else:
            cr_list = ctx_data.get("results", [])
            since = ctx_data.get("since", "")[:19].replace("T", " ")
            until = ctx_data.get("until", "")[:19].replace("T", " ")
            st.caption(
                f"{since}  →  {until}  ·  "
                f"{ctx_data.get('containers_with_logs', 0)} / "
                f"{ctx_data.get('containers_searched', 0)} containers"
            )
            if not cr_list:
                st.info("No log output in this time window.")
            for cr in cr_list:
                cr_name = cr.get("container_name", "?")
                cr_lines = cr.get("lines", [])
                with st.expander(
                    f"🐳 {cr_name}  ({len(cr_lines)} lines)",
                    expanded=(cr.get("container_id") == cid),
                ):
                    st.code("\n".join(cr_lines) if cr_lines else "(no lines)", language=None)
            ctx_errs = ctx_data.get("errors", [])
            if ctx_errs:
                with st.expander(f"⚠️ {len(ctx_errs)} error(s)"):
                    for e in ctx_errs:
                        st.warning(f"`{e.get('container_name', '?')}` — {e.get('error', '?')}")


def _render_search_bar(scope_label: str):
    """Render the compact search bar and handle button clicks."""
    with st.container(border=True):
        sc1, sc2, sc3, sc4, sc5 = st.columns([5, 1, 1, 1, 1])
        with sc1:
            pat = st.text_input(
                "Search pattern",
                value=st.session_state.get("search_pattern", ""),
                placeholder="regex  e.g.  error|warn|timeout",
                label_visibility="collapsed", key="search_input",
            )
        with sc2:
            case_i = st.checkbox("i", value=False, help="Case-insensitive")
        with sc3:
            search_this = st.button(
                f"🐳 {scope_label}", use_container_width=True,
                help="Search within selected container" if not is_global else "Search all running",
            )
        with sc4:
            search_all = st.button("🌐 All", use_container_width=True,
                                   help="Search across all containers")
        with sc5:
            if st.session_state.get("search_results"):
                if st.button("✕", use_container_width=True, help="Clear results"):
                    _clear_state("search_results", "search_pattern")
                    st.rerun()

    return pat, case_i, search_this, search_all


def _render_match_rows(matches: list, cid: str, cname: str, key_prefix: str):
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
                    if st.button("🐳", key=f"{key_prefix}_s_{i}",
                                 help=f"±{window_seconds}s in {cname}"):
                        _set_ctx(ts, cid, cname, "single")
                        st.rerun()
                with b2:
                    if st.button("🌐", key=f"{key_prefix}_g_{i}",
                                 help=f"±{window_seconds}s globally"):
                        _set_ctx(ts, cid, cname, "global")
                        st.rerun()
            else:
                st.caption("no ts")


# ============================================================================
# GLOBAL VIEW  (selected_id == "")
# ============================================================================

if is_global:
    running_only_global = not st.session_state.get("include_stopped_global_val", False)
    # Keep the checkbox value accessible for context panel
    if "include_stopped_global" in st.session_state:
        st.session_state["include_stopped_global_val"] = include_stopped_global

    h1, h2 = st.columns([9, 1])
    with h1:
        st.title("📋 All containers")
        st.caption(f"🟢 {len(running)} running  ·  ⭕ {len(stopped)} stopped")
    with h2:
        if st.button("↻", key="ref_global", help="Refresh logs"):
            _clear_state("logs_cache", "logs_cache_key")
            st.rerun()

    # Search bar
    pat, case_i, search_this, search_all = _render_search_bar("All running")

    if (search_this or search_all) and pat.strip():
        with st.spinner("Searching all containers…"):
            running_only = not include_stopped_global
            res = c.global_search_logs(
                pat.strip(), tail=tail, max_results_per_container=max_results,
                case_insensitive=case_i, running_only=running_only,
            )
        if res is not None:
            st.session_state["search_results"] = {"scope": "global", "data": res}
            st.session_state["search_pattern"] = pat.strip()
            _clear_state("ctx_state")
            st.rerun()
        else:
            st.error(st.session_state.get("last_error", "Search failed."))

    # Context panel
    _render_context_panel()

    # Search results
    search_state = st.session_state.get("search_results")
    if search_state:
        data = search_state["data"]
        pattern_used = st.session_state.get("search_pattern", "")
        total = data.get("total_matched", 0)
        searched = data.get("containers_searched", 0)
        with_matches = data.get("containers_with_matches", 0)
        errors = data.get("errors", [])

        st.divider()
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("Searched", searched)
        mc2.metric("With matches", with_matches)
        mc3.metric("Total matches", total)
        mc4.metric("Errors", len(errors))
        st.subheader(f"Global search — `{pattern_used}`")

        if errors:
            with st.expander(f"⚠️ {len(errors)} error(s)"):
                for e in errors:
                    st.warning(f"`{e.get('container_name', '?')}` — {e.get('error', '?')}")

        if not data.get("results"):
            st.info(f"No matches for `{pattern_used}`.")
        else:
            for cr in data.get("results", []):
                cid = cr.get("container_id", "")
                cname = cr.get("container_name", cid[:12])
                matches = cr.get("matches", [])
                mc = cr.get("match_count", len(matches))
                trunc = f" _(showing {len(matches)} of {mc})_" if cr.get("truncated") else ""
                with st.expander(
                    f"🐳 **{cname}** — {mc} match{'es' if mc != 1 else ''}{trunc}",
                    expanded=True,
                ):
                    _render_match_rows(matches, cid, cname, f"g_{cid}")

    # -----------------------------------------------------------------------
    # Global log viewer (primary)
    # -----------------------------------------------------------------------

    st.divider()
    cache_key = f"global_{tail}_{show_ts}_{include_stopped_global}"
    if st.session_state.get("logs_cache_key") != cache_key:
        with st.spinner(f"Loading logs from {len(running)} containers…"):
            raw = c.get_all_logs(
                tail=tail, timestamps=True,
                running_only=not include_stopped_global,
            )
        if raw is None:
            st.error(st.session_state.get("last_error", "Failed to load logs."))
            st.stop()
        st.session_state["logs_cache"] = raw
        st.session_state["logs_cache_key"] = cache_key

    raw = st.session_state.get("logs_cache", {})
    containers_data = raw.get("containers", [])
    fetched = raw.get("containers_fetched", 0)
    fetch_errors = raw.get("errors", [])

    total_lines = sum(cr.get("count", 0) for cr in containers_data)
    st.caption(f"{total_lines} lines from {fetched} containers  ·  {tail} per container")

    if fetch_errors:
        with st.expander(f"⚠️ {len(fetch_errors)} fetch error(s)"):
            for e in fetch_errors:
                st.warning(f"`{e.get('container_name', '?')}` — {e.get('error', '?')}")

    if not containers_data:
        st.info("No log output.")
    elif merge_view:
        # Merged timeline: interleave all lines sorted by timestamp
        merged = []
        max_name = max((len(cr.get("container_name", "")) for cr in containers_data), default=8)
        max_name = min(max_name, 20)
        for cr in containers_data:
            cname = cr.get("container_name", "?")
            padded = cname[:max_name].ljust(max_name)
            for line in cr.get("lines", []):
                ts, content = _split(line)
                display = f"[{padded}] {line if show_ts else content}"
                merged.append((ts, display))
        merged.sort(key=lambda x: x[0])
        rendered = [d for _, d in merged]
        st.subheader("Merged timeline")
        st.code("\n".join(rendered) if rendered else "(no lines)", language=None)
    else:
        # Per-container sections
        st.subheader("Per-container logs")
        for cr in containers_data:
            cname = cr.get("container_name", "?")
            lines = cr.get("lines", [])
            display = [(_split(ln)[1] if not show_ts else ln) for ln in lines]
            with st.expander(f"🐳 {cname}  ({len(lines)} lines)", expanded=False):
                st.code("\n".join(display) if display else "(no lines)", language=None)

    # Drill-down bar (global view uses timestamp paste → global context)
    st.divider()
    st.caption("**Drill-down:** paste a timestamp from the log above to open a context window.")
    dc1, dc2 = st.columns([6, 2])
    with dc1:
        pivot_input = st.text_input(
            "Timestamp", placeholder="2024-01-15T10:23:45.123456789Z",
            label_visibility="collapsed", key="drill_pivot_global",
        )
    with dc2:
        if st.button("🌐 Global context", use_container_width=True,
                     disabled=not pivot_input.strip()):
            _set_ctx(pivot_input.strip(), "", "All containers", "global")
            st.rerun()

    st.stop()


# ============================================================================
# SINGLE-CONTAINER VIEW  (selected_id != "")
# ============================================================================

ct_info = next((ct for ct in all_containers if ct.get("id") == selected_id), None)
state = (ct_info or {}).get("state", "")
image = (ct_info or {}).get("image", "—")

h1, h2 = st.columns([9, 1])
with h1:
    st.title(f"📋 {selected_name}")
    st.caption(f"{_icon(state)} {state}  ·  `{image}`")
with h2:
    if st.button("↻", key="ref_single", help="Refresh logs"):
        _clear_state("logs_cache", "logs_cache_key")
        st.rerun()

# Search bar
pat, case_i, search_this, search_all = _render_search_bar("This container")

if search_this and pat.strip():
    with st.spinner(f"Searching {selected_name}…"):
        res = c.search_container_logs(
            selected_id, pat.strip(),
            tail=tail, max_results=max_results, case_insensitive=case_i,
        )
    if res is not None:
        st.session_state["search_results"] = {"scope": "single", "data": res}
        st.session_state["search_pattern"] = pat.strip()
        _clear_state("ctx_state")
        st.rerun()
    else:
        st.error(st.session_state.get("last_error", "Search failed."))

if search_all and pat.strip():
    with st.spinner("Searching all containers…"):
        res = c.global_search_logs(
            pat.strip(), tail=tail, max_results_per_container=max_results,
            case_insensitive=case_i, running_only=True,
        )
    if res is not None:
        st.session_state["search_results"] = {"scope": "global", "data": res}
        st.session_state["search_pattern"] = pat.strip()
        _clear_state("ctx_state")
        st.rerun()
    else:
        st.error(st.session_state.get("last_error", "Search failed."))

# Context panel
_render_context_panel()

# Search results
search_state = st.session_state.get("search_results")
if search_state:
    scope = search_state["scope"]
    data = search_state["data"]
    pattern_used = st.session_state.get("search_pattern", "")
    st.divider()

    if scope == "single":
        matches = data.get("matches", [])
        total = data.get("total_matched", len(matches))
        trunc = f"  _(showing {len(matches)} of {total})_" if data.get("truncated") else ""
        st.subheader(f"Search — `{pattern_used}` in {selected_name}{trunc}")
        if not matches:
            st.info("No matches.")
        else:
            _render_match_rows(matches, selected_id, selected_name, "s")
    else:
        total = data.get("total_matched", 0)
        searched = data.get("containers_searched", 0)
        with_matches = data.get("containers_with_matches", 0)
        errors = data.get("errors", [])
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("Searched", searched)
        mc2.metric("With matches", with_matches)
        mc3.metric("Total matches", total)
        mc4.metric("Errors", len(errors))
        st.subheader(f"Global search — `{pattern_used}`")
        if errors:
            with st.expander(f"⚠️ {len(errors)} error(s)"):
                for e in errors:
                    st.warning(f"`{e.get('container_name', '?')}` — {e.get('error', '?')}")
        if not data.get("results"):
            st.info(f"No matches for `{pattern_used}`.")
        else:
            for cr in data.get("results", []):
                cid = cr.get("container_id", "")
                cname = cr.get("container_name", cid[:12])
                matches = cr.get("matches", [])
                mc = cr.get("match_count", len(matches))
                trunc = f" _(showing {len(matches)} of {mc})_" if cr.get("truncated") else ""
                with st.expander(
                    f"🐳 **{cname}** — {mc} match{'es' if mc != 1 else ''}{trunc}",
                    expanded=(cid == selected_id),
                ):
                    _render_match_rows(matches, cid, cname, f"g_{cid}")

# ---------------------------------------------------------------------------
# Log viewer
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Logs")

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
st.code("\n".join(lines) if lines else "(no log output)", language=None)

# ---------------------------------------------------------------------------
# Drill-down bar
# ---------------------------------------------------------------------------

st.divider()
st.caption("**Drill-down:** copy a timestamp from the log above, paste it here.")
dc1, dc2, dc3 = st.columns([5, 1, 1])
with dc1:
    pivot_input = st.text_input(
        "Timestamp", placeholder="2024-01-15T10:23:45.123456789Z",
        label_visibility="collapsed", key="drill_pivot",
    )
with dc2:
    if st.button("🐳 Container", use_container_width=True, disabled=not pivot_input.strip(),
                 help=f"±{window_seconds}s in {selected_name}"):
        _set_ctx(pivot_input.strip(), selected_id, selected_name, "single")
        st.rerun()
with dc3:
    if st.button("🌐 Global", use_container_width=True, disabled=not pivot_input.strip(),
                 help=f"±{window_seconds}s across all containers"):
        _set_ctx(pivot_input.strip(), selected_id, selected_name, "global")
        st.rerun()
