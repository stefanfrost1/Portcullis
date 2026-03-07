"""
Log Search page — global egrep-style search across all containers with
click-to-expand context windows (single container or global).

UX flow:
  1. Enter a regex pattern in the sidebar → hit Search
  2. Results appear grouped by container, each matched line shown with its timestamp
  3. Click "Context: this container" or "Context: all containers" on any line
     to expand ±N seconds of logs around that exact moment
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
from utils.api_client import EngineClient, get_config

st.set_page_config(page_title="Log Search", page_icon="🔍", layout="wide")
st.title("🔍 Log Search")


@st.cache_resource
def get_client() -> EngineClient:
    cfg = get_config()
    return EngineClient(cfg["base_url"], cfg.get("api_key"))


c = get_client()

# ---------------------------------------------------------------------------
# Sidebar — search controls
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Search")
    pattern = st.text_input(
        "Pattern (regex / egrep)",
        value=st.session_state.get("log_pattern", ""),
        placeholder="e.g.  error|warn|exception",
        help="Python extended regex — same as egrep. Case-sensitive by default.",
    )
    case_insensitive = st.checkbox("Case-insensitive", value=False)
    include_stopped = st.checkbox("Include stopped containers", value=False)

    st.divider()
    st.caption("Limits")
    tail = st.slider("Lines to search per container", 100, 2000, 2000, step=100)
    max_results = st.slider("Max matches per container", 10, 200, 100, step=10)

    st.divider()
    search_clicked = st.button("🔍 Search", type="primary", use_container_width=True)
    if st.button("✕ Clear", use_container_width=True):
        for key in ["log_pattern", "log_results", "log_summary", "ctx_state"]:
            st.session_state.pop(key, None)
        st.rerun()

    st.divider()
    st.header("Context window")
    window_seconds = st.slider("Window ± seconds", 10, 300, 60, step=10)
    st.caption(f"Clicking a context button shows ±{window_seconds}s ({window_seconds * 2}s total) around the matched line.")

# ---------------------------------------------------------------------------
# Run search
# ---------------------------------------------------------------------------

if search_clicked:
    if not pattern.strip():
        st.warning("Enter a search pattern first.")
        st.stop()
    with st.spinner("Searching all containers…"):
        result = c.global_search_logs(
            pattern=pattern.strip(),
            tail=tail,
            max_results_per_container=max_results,
            case_insensitive=case_insensitive,
            running_only=not include_stopped,
            timestamps=False,   # display lines are stripped; timestamps come via matches[]
        )
    if result is None:
        st.error(st.session_state.get("last_error", "Search failed."))
        st.stop()
    st.session_state["log_pattern"] = pattern.strip()
    st.session_state["log_results"] = result
    st.session_state.pop("ctx_state", None)   # clear any open context panel
    st.rerun()

result = st.session_state.get("log_results")

# ---------------------------------------------------------------------------
# No results yet — show hints
# ---------------------------------------------------------------------------

if result is None:
    st.markdown(
        """
        **How to use:**
        1. Type a regex pattern in the sidebar (egrep syntax — `error|warn`, `timeout`, `5[0-9]{2}`, etc.)
        2. Hit **Search** — the API searches the last N log lines of every running container in parallel
        3. Matches are returned grouped by container; click any line to open a ±context window

        **Tips:**
        - Use `|` for OR: `error|exception|fatal`
        - Prefix with `(?i)` for inline case-insensitive: `(?i)warning`
        - Use `since` / `until` filters via the API directly if you need a time-bounded search
        """
    )
    st.stop()

# ---------------------------------------------------------------------------
# Summary bar
# ---------------------------------------------------------------------------

searched = result.get("containers_searched", 0)
with_matches = result.get("containers_with_matches", 0)
total = result.get("total_matched", 0)
errors = result.get("errors", [])
pat = result.get("pattern", "")

col_a, col_b, col_c, col_d = st.columns(4)
col_a.metric("Containers searched", searched)
col_b.metric("Containers with matches", with_matches)
col_c.metric("Total matches", total)
col_d.metric("Errors", len(errors))

if not result.get("results"):
    st.info(f'No matches found for pattern **`{pat}`** across {searched} container(s).')
    if errors:
        with st.expander(f"⚠️ {len(errors)} container(s) had errors"):
            for e in errors:
                st.warning(f"`{e.get('container_name', e.get('container_id', '?'))}` — {e.get('error', '?')}")
    st.stop()

# ---------------------------------------------------------------------------
# Context state management
# ---------------------------------------------------------------------------
# ctx_state = {"pivot": "...", "container_id": "...", "container_name": "...", "scope": "single"|"global"}

def _set_ctx(pivot: str, container_id: str, container_name: str, scope: str):
    st.session_state["ctx_state"] = {
        "pivot": pivot,
        "container_id": container_id,
        "container_name": container_name,
        "scope": scope,
    }

def _clear_ctx():
    st.session_state.pop("ctx_state", None)

ctx = st.session_state.get("ctx_state")

# ---------------------------------------------------------------------------
# Context panel (shown above results when active)
# ---------------------------------------------------------------------------

if ctx:
    pivot = ctx["pivot"]
    scope = ctx["scope"]
    cid = ctx["container_id"]
    cname = ctx["container_name"]

    scope_label = f"🐳 {cname}" if scope == "single" else "🌐 All containers"
    st.subheader(f"Context window — {scope_label}")
    st.caption(f"Pivot: `{pivot}`  ·  Window: ±{window_seconds}s")

    with st.spinner("Fetching context…"):
        if scope == "single":
            ctx_data = c.get_logs_context(cid, pivot=pivot, window_seconds=window_seconds, timestamps=True)
        else:
            ctx_data = c.global_logs_context(pivot=pivot, window_seconds=window_seconds,
                                              running_only=not include_stopped, timestamps=True)

    if ctx_data is None:
        st.error(st.session_state.get("last_error", "Context fetch failed."))
    elif scope == "single":
        lines = ctx_data.get("lines", [])
        since = ctx_data.get("since", "")[:19].replace("T", " ")
        until = ctx_data.get("until", "")[:19].replace("T", " ")
        st.caption(f"{since}  →  {until}  ·  {len(lines)} lines")
        if lines:
            # Highlight the pivot line
            pivot_ts = pivot[:19]   # compare truncated
            rendered = []
            for ln in lines:
                rendered.append(ln)
            st.code("\n".join(rendered), language=None)
        else:
            st.info("No log lines in this time window.")
    else:
        ctx_results = ctx_data.get("results", [])
        ctx_errors = ctx_data.get("errors", [])
        since = ctx_data.get("since", "")[:19].replace("T", " ")
        until = ctx_data.get("until", "")[:19].replace("T", " ")
        st.caption(
            f"{since}  →  {until}  ·  "
            f"{ctx_data.get('containers_with_logs', 0)} / {ctx_data.get('containers_searched', 0)} containers had output"
        )
        if not ctx_results:
            st.info("No log lines found in this time window across any container.")
        for cr in ctx_results:
            cr_name = cr.get("container_name", cr.get("container_id", "?"))
            cr_lines = cr.get("lines", [])
            with st.expander(f"🐳 {cr_name}  ({len(cr_lines)} lines)", expanded=True):
                if cr_lines:
                    st.code("\n".join(cr_lines), language=None)
                else:
                    st.write("No lines.")
        if ctx_errors:
            with st.expander(f"⚠️ {len(ctx_errors)} error(s)"):
                for e in ctx_errors:
                    st.warning(f"`{e.get('container_name', '?')}` — {e.get('error', '?')}")

    if st.button("✕ Close context", key="close_ctx"):
        _clear_ctx()
        st.rerun()

    st.divider()

# ---------------------------------------------------------------------------
# Results — grouped by container
# ---------------------------------------------------------------------------

st.subheader(f"Matches for `{pat}`")

if errors:
    with st.expander(f"⚠️ {len(errors)} container(s) had errors — click to expand"):
        for e in errors:
            st.warning(f"`{e.get('container_name', e.get('container_id', '?'))}` — {e.get('error', '?')}")

for container_result in result.get("results", []):
    cid = container_result.get("container_id", "")
    cname = container_result.get("container_name", cid[:12])
    matches = container_result.get("matches", [])
    match_count = container_result.get("match_count", len(matches))
    truncated = container_result.get("truncated", False)

    header = f"🐳 **{cname}** — {match_count} match{'es' if match_count != 1 else ''}"
    if truncated:
        header += f"  _(showing first {len(matches)}, truncated)_"

    with st.expander(header, expanded=True):
        if not matches:
            st.write("No structured match data.")
            continue

        for i, m in enumerate(matches):
            ts = m.get("timestamp")       # ISO 8601 or None
            line = m.get("line", "")

            # Row: timestamp chip | log line | context buttons
            col_ts, col_line, col_btn = st.columns([2, 7, 3])

            with col_ts:
                if ts:
                    # Show HH:MM:SS.mmm for compactness
                    short_ts = ts[11:23] if len(ts) > 11 else ts
                    st.code(short_ts, language=None)
                else:
                    st.caption("no timestamp")

            with col_line:
                st.code(line, language=None)

            with col_btn:
                if ts:
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("🐳 Context", key=f"ctx_single_{cid}_{i}",
                                     help=f"Show ±{window_seconds}s from this line in {cname}"):
                            _set_ctx(ts, cid, cname, "single")
                            st.rerun()
                    with b2:
                        if st.button("🌐 Global", key=f"ctx_global_{cid}_{i}",
                                     help=f"Show ±{window_seconds}s from this line across all containers"):
                            _set_ctx(ts, cid, cname, "global")
                            st.rerun()
                else:
                    st.caption("No pivot — enable timestamps in API call")
