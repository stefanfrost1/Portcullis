"""
Redis Keys page — browse, view, create, edit, and delete keys.
Supports all Redis data types: string, hash, list, set, zset.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
from utils.api_client import EngineClient, get_config
from utils.formatting import seconds_to_human

st.set_page_config(page_title="Redis Keys", page_icon="🗝️", layout="wide")
st.title("🗝️ Redis Keys")


@st.cache_resource
def get_client() -> EngineClient:
    cfg = get_config()
    return EngineClient(cfg["base_url"], cfg.get("api_key"))


c = get_client()

if "last_error" in st.session_state:
    st.error(st.session_state["last_error"])

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------

with st.sidebar:
    pattern = st.text_input("Key pattern", value="*")
    key_type = st.selectbox("Type filter", ["all", "string", "hash", "list", "set", "zset", "stream"])
    page_size = st.selectbox("Keys per page", [25, 50, 100, 200], index=1)
    if st.button("↻ Refresh"):
        st.session_state["redis_cursor"] = 0
        st.rerun()
    st.divider()
    total = c.get_redis_key_count()
    if total is not None:
        st.metric("Total keys (DBSIZE)", total)

# ---------------------------------------------------------------------------
# Key creation form
# ---------------------------------------------------------------------------

with st.expander("Create / overwrite a key", expanded=False):
    with st.form("create_key_form"):
        new_key = st.text_input("Key name")
        new_type = st.selectbox("Type", ["string", "hash", "list", "set", "zset"])
        new_value = st.text_area("Value (JSON for hash/list/set/zset)", height=80)
        new_ttl = st.number_input("TTL (seconds, 0 = no expiry)", min_value=0, value=0)
        submitted = st.form_submit_button("Save")
    if submitted and new_key.strip():
        import json as _json
        val = new_value.strip()
        if new_type != "string":
            try:
                val = _json.loads(val)
            except Exception:
                st.error("Value must be valid JSON for this type.")
                val = None
        if val is not None:
            result = c.set_redis_key(
                new_key.strip(),
                key_type=new_type,
                value=val,
                ttl=new_ttl if new_ttl > 0 else None,
            )
            if result is not None:
                st.success(f"Key '{new_key}' saved.")
                st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Pagination state
# ---------------------------------------------------------------------------

if "redis_cursor" not in st.session_state:
    st.session_state["redis_cursor"] = 0
if "redis_cursor_history" not in st.session_state:
    st.session_state["redis_cursor_history"] = [0]

# ---------------------------------------------------------------------------
# Key browser
# ---------------------------------------------------------------------------

result = c.get_redis_keys(
    pattern=pattern,
    cursor=st.session_state["redis_cursor"],
    count=page_size,
    key_type=key_type if key_type != "all" else None,
)

keys = []
next_cursor = 0
if result:
    keys = result.get("keys", [])
    next_cursor = result.get("next_cursor", 0)

if not keys and st.session_state["redis_cursor"] == 0:
    st.info("No keys found matching the filter.")
else:
    st.write(f"Showing {len(keys)} key(s).")

    # Pagination controls
    col_prev, col_info, col_next = st.columns([1, 3, 1])
    history: list = st.session_state["redis_cursor_history"]

    with col_prev:
        if len(history) > 1:
            if st.button("◀ Prev"):
                history.pop()
                st.session_state["redis_cursor"] = history[-1]
                st.rerun()

    with col_next:
        if next_cursor and next_cursor != 0:
            if st.button("Next ▶"):
                history.append(next_cursor)
                st.session_state["redis_cursor"] = next_cursor
                st.rerun()

    with col_info:
        st.caption(f"Cursor: {st.session_state['redis_cursor']}")

    # Bulk delete
    selected = st.multiselect(
        "Select keys for bulk delete",
        options=keys,
        default=[],
        key="bulk_select",
    )
    if selected:
        if st.session_state.get("confirm_bulk_delete"):
            st.warning(f"Delete {len(selected)} key(s)?")
            col_yes, col_no = st.columns(2)
            with col_yes:
                if st.button("Yes, delete all"):
                    res = c.bulk_delete_redis_keys(selected)
                    if res is not None:
                        st.success(f"Deleted {len(selected)} key(s).")
                    st.session_state.pop("confirm_bulk_delete", None)
                    st.rerun()
            with col_no:
                if st.button("Cancel bulk"):
                    st.session_state.pop("confirm_bulk_delete", None)
                    st.rerun()
        else:
            if st.button(f"🗑 Delete selected ({len(selected)})"):
                st.session_state["confirm_bulk_delete"] = True
                st.rerun()

    st.divider()

    # Per-key expanders
    for key in keys:
        with st.expander(f"🗝️ {key}"):
            col_val, col_actions = st.columns([3, 1])

            key_data = c.get_redis_key(key)

            with col_val:
                if key_data:
                    ktype = key_data.get("type", "?")
                    ttl_val = key_data.get("ttl", -1)
                    value = key_data.get("value")

                    st.write(f"**Type:** {ktype}")
                    st.write(f"**TTL:** {seconds_to_human(ttl_val) if ttl_val > 0 else ('No expiry' if ttl_val == -1 else 'Expired/missing')}")

                    if ktype == "string":
                        st.text_area("Value", value=str(value or ""), key=f"val_{key}", disabled=True)
                    elif ktype == "hash" and isinstance(value, dict):
                        st.dataframe(
                            pd.DataFrame(
                                [{"Field": k, "Value": v} for k, v in value.items()]
                            ),
                            width="stretch",
                            hide_index=True,
                        )
                    elif ktype in ("list", "set") and isinstance(value, list):
                        st.write(f"Items ({len(value)}):")
                        for item in value[:50]:
                            st.write(f"  • {item}")
                        if len(value) > 50:
                            st.caption(f"… and {len(value) - 50} more")
                    elif ktype == "zset" and isinstance(value, list):
                        st.dataframe(
                            pd.DataFrame(value[:50]),
                            width="stretch",
                            hide_index=True,
                        )
                    else:
                        st.json(value if value is not None else {})

            with col_actions:
                # TTL management
                with st.form(f"ttl_form_{key}"):
                    new_ttl = st.number_input("Set TTL (s)", min_value=0, value=0, key=f"ttl_input_{key}")
                    if st.form_submit_button("Set TTL"):
                        if new_ttl > 0:
                            c.set_redis_key_expire(key, int(new_ttl))
                        else:
                            c.persist_redis_key(key)
                        st.rerun()

                # Delete
                confirm_key = f"confirm_del_{key}"
                if st.session_state.get(confirm_key):
                    st.warning("Delete?")
                    if st.button("Yes", key=f"yes_del_{key}"):
                        c.delete_redis_key(key)
                        st.session_state.pop(confirm_key, None)
                        st.rerun()
                    if st.button("No", key=f"no_del_{key}"):
                        st.session_state.pop(confirm_key, None)
                        st.rerun()
                else:
                    if st.button("🗑 Delete", key=f"del_{key}"):
                        st.session_state[confirm_key] = True
                        st.rerun()
