"""
Redis Keys page — click-to-drill keyspace browser + editor.

  1. Browser  — cursor-paginated SCAN; click a key row to open it. Named sort
                and a name filter narrow the current page.
  2. Inspector — full value view for the selected key (any type), with
                pagination for large collections and type-appropriate editing,
                plus a guarded delete (flush) of the whole key.

Any key can also be opened by name, so keys beyond the scan window are reachable.
"""

import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
from utils.api_client import EngineClient, get_config, current_role
from utils.formatting import bytes_to_human, seconds_to_human

st.set_page_config(page_title="Redis Keys", page_icon="🗝️", layout="wide")
st.title("🗝️ Redis Keys")


@st.cache_resource
def get_client() -> EngineClient:
    cfg = get_config()
    return EngineClient(cfg["base_url"], cfg.get("api_key"))


c = get_client()

SELECTED = "redis_selected_key"
_TYPE_ICON = {
    "string": "🔤", "hash": "🧩", "list": "📋",
    "set": "🎯", "zset": "📊", "stream": "🌊",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _type_icon(t: str) -> str:
    return _TYPE_ICON.get(t, "•")


def _ttl_text(ttl) -> str:
    """Render a Redis TTL: -1 means no expiry, -2 means the key is gone."""
    if ttl is None:
        return "—"
    if ttl == -1:
        return "No expiry"
    if ttl == -2:
        return "Expired / missing"
    return seconds_to_human(ttl)


def _ttl_sort_key(ttl) -> float:
    """Sort soonest-expiring first; no-expiry / missing sink to the bottom."""
    if isinstance(ttl, int) and ttl >= 0:
        return ttl
    return float("inf")


def _pretty(value: str):
    """Render a scalar as JSON when it parses as JSON, otherwise as raw text."""
    text = "" if value is None else str(value)
    try:
        st.json(json.loads(text))
    except (ValueError, TypeError):
        st.code(text or "(empty)", language="text")


def _select(key: str) -> None:
    st.session_state[SELECTED] = key


def _export_button(key: str, payload) -> None:
    st.download_button(
        "⬇ Export JSON",
        data=json.dumps(payload, indent=2, default=str),
        file_name=f"{key.replace(':', '_').replace('/', '_')}.json",
        mime="application/json",
        key=f"export_{key}",
    )


# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------

with st.sidebar:
    st.caption(f"Signed in as: **{current_role()}**")
    pattern = st.text_input("Key pattern", value="*", help="Glob over key names, e.g. user:*")
    key_type = st.selectbox("Type filter", ["all", "string", "hash", "list", "set", "zset", "stream"])
    sort_choice = st.selectbox(
        "Sort by", ["Key (A → Z)", "Key (Z → A)", "Type", "TTL (soonest)"], index=0
    )
    name_filter = st.text_input("Filter by name", value="", placeholder="substring…")
    page_size = st.selectbox("Keys per page", [25, 50, 100, 200], index=1)
    if st.button("↻ Refresh"):
        st.session_state["redis_cursor"] = 0
        st.session_state["redis_cursor_history"] = [0]
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
        val = new_value.strip()
        if new_type != "string":
            try:
                val = json.loads(val)
            except ValueError:
                st.error("Value must be valid JSON for this type.")
                val = None
        if val is not None:
            result = c.set_redis_key(
                new_key.strip(),
                key_type=new_type,
                value=val,
                ttl=new_ttl if new_ttl > 0 else None,
            )
            if result is None:
                st.error(c.last_error() or "Could not save key.")
            else:
                st.success(f"Key '{new_key}' saved.")
                _select(new_key.strip())
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
# Key browser — click a row to drill in
# ---------------------------------------------------------------------------

st.subheader("Browser")

result = c.get_redis_keys(
    pattern=pattern,
    cursor=st.session_state["redis_cursor"],
    count=page_size,
    key_type=key_type if key_type != "all" else None,
)

if result is None:
    st.error(c.last_error() or "Could not scan the keyspace.")
    result = {}

# The API returns enriched entries: [{"key": ..., "type": ..., "ttl": ...}]
entries = [e for e in (result.get("keys", []) or []) if isinstance(e, dict)]
next_cursor = result.get("cursor", 0)

# Named sort + name filter (applied to the current SCAN page).
nf = name_filter.strip().lower()
shown = [e for e in entries if not nf or nf in e.get("key", "").lower()]
if sort_choice == "Key (A → Z)":
    shown.sort(key=lambda e: e.get("key", "").lower())
elif sort_choice == "Key (Z → A)":
    shown.sort(key=lambda e: e.get("key", "").lower(), reverse=True)
elif sort_choice == "Type":
    shown.sort(key=lambda e: (e.get("type", ""), e.get("key", "").lower()))
elif sort_choice == "TTL (soonest)":
    shown.sort(key=lambda e: _ttl_sort_key(e.get("ttl")))

if not entries and st.session_state["redis_cursor"] == 0:
    st.info("No keys found matching the filter.")
else:
    st.caption(
        f"Showing {len(shown)} of {len(entries)} key(s) on this page. SCAN returns "
        "approximate page sizes; an empty page does not mean the scan is finished."
    )

    # Pagination controls
    col_prev, col_info, col_next = st.columns([1, 3, 1])
    history: list = st.session_state["redis_cursor_history"]
    with col_prev:
        if len(history) > 1 and st.button("◀ Prev"):
            history.pop()
            st.session_state["redis_cursor"] = history[-1]
            st.rerun()
    with col_next:
        if next_cursor and st.button("Next ▶"):
            history.append(next_cursor)
            st.session_state["redis_cursor"] = next_cursor
            st.rerun()
    with col_info:
        st.caption(
            f"Cursor: {st.session_state['redis_cursor']}"
            + ("" if next_cursor else " · scan complete")
        )

    # Clickable rows — inside a fixed-height scrollable box so the inspector
    # below stays reachable even with a full page of keys.
    st.markdown("**Click a key to open it**")
    box = st.container(height=360)
    with box:
        if not shown:
            st.caption("No keys on this page match the filter.")
        for e in shown:
            k = e.get("key", "?")
            t = e.get("type", "?")
            sel = st.session_state.get(SELECTED) == k
            label = f"{'▶ ' if sel else ''}{_type_icon(t)} {k}  ·  {_ttl_text(e.get('ttl'))}"
            if st.button(
                label, key=f"krow_{k}", use_container_width=True,
                type="primary" if sel else "secondary",
            ):
                _select(k)
                st.rerun()

    # Bulk delete (secondary, guarded)
    with st.expander("🗑 Bulk delete keys from this page"):
        picked = st.multiselect("Select keys", options=[e.get("key") for e in shown], key="bulk_select")
        if picked:
            ok = st.checkbox(f"Yes, delete {len(picked)} key(s)", key="bulk_ok")
            if st.button("Delete selected", disabled=not ok):
                res = c.bulk_delete_redis_keys(picked)
                if res is None:
                    st.error(c.last_error() or "Bulk delete failed.")
                else:
                    st.success(f"Deleted {res.get('deleted', 0)} key(s).")
                    st.session_state.pop("bulk_select", None)
                    st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Key inspector
# ---------------------------------------------------------------------------

st.subheader("Inspector")

oc1, oc2 = st.columns([4, 1])
with oc1:
    open_name = st.text_input(
        "Open any key by name",
        value="",
        placeholder="reach keys beyond the current page",
        key="open_by_name",
    )
with oc2:
    st.write("")
    if st.button("Open", width="stretch") and open_name.strip():
        _select(open_name.strip())
        st.rerun()

target = (st.session_state.get(SELECTED) or "").strip()

if not target:
    st.info("Click a key above, or open one by name.")
else:
    st.markdown(f"### `{target}`")
    col_off, col_cnt = st.columns(2)
    with col_off:
        offset = st.number_input("Offset (collections)", min_value=0, value=0, step=50)
    with col_cnt:
        count = st.number_input("Items per page", min_value=1, max_value=5000, value=200, step=50)

    data = c.get_redis_key(target, offset=int(offset), count=int(count))

    if data is None:
        st.error(c.last_error() or f"Could not read '{target}'.")
    else:
        ktype = data.get("type", "?")
        value = data.get("value")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Type", ktype)
        m2.metric("TTL", _ttl_text(data.get("ttl")))
        m3.metric("Length", data.get("length") if data.get("length") is not None else "—")
        m4.metric("Memory", bytes_to_human(data.get("memory_bytes")))
        st.caption(f"Encoding: `{data.get('encoding') or '—'}` · db {data.get('db', 0)}")

        if data.get("truncated"):
            st.warning("Value is truncated — page through it with the offset above.")

        # -- Value view + type-specific editing -------------------------

        if ktype == "string":
            _pretty(value)
            with st.form(f"edit_string_{target}"):
                edited = st.text_area("Edit value", value=str(value or ""), height=160)
                if st.form_submit_button("Save value"):
                    if c.set_redis_key(target, "string", edited) is None:
                        st.error(c.last_error() or "Save failed.")
                    else:
                        st.success("Saved.")
                        st.rerun()

        elif ktype == "hash" and isinstance(value, dict):
            st.dataframe(
                pd.DataFrame([{"Field": k, "Value": v} for k, v in value.items()]),
                width="stretch",
                hide_index=True,
            )
            field_names = list(value.keys())
            if field_names:
                inspect_field = st.selectbox("Show field value", field_names, key=f"hf_{target}")
                _pretty(value.get(inspect_field))

            col_set, col_del = st.columns(2)
            with col_set:
                with st.form(f"hset_{target}"):
                    st.write("**Set field**")
                    f_name = st.text_input("Field", key=f"hset_name_{target}")
                    f_val = st.text_area("Value", key=f"hset_val_{target}", height=80)
                    if st.form_submit_button("HSET") and f_name.strip():
                        if c.set_redis_hash_field(target, f_name.strip(), f_val) is None:
                            st.error(c.last_error() or "HSET failed.")
                        else:
                            st.success("Field set.")
                            st.rerun()
            with col_del:
                with st.form(f"hdel_{target}"):
                    st.write("**Delete field**")
                    d_field = st.selectbox("Field", field_names or ["—"], key=f"hdel_{target}")
                    if st.form_submit_button("HDEL") and field_names:
                        if c.delete_redis_hash_field(target, d_field) is None:
                            st.error(c.last_error() or "HDEL failed.")
                        else:
                            st.success("Field deleted.")
                            st.rerun()

        elif ktype == "list" and isinstance(value, list):
            st.dataframe(
                pd.DataFrame([
                    {"Index": int(offset) + i, "Value": v} for i, v in enumerate(value)
                ]),
                width="stretch",
                hide_index=True,
            )
            if value:
                idx_options = [int(offset) + i for i in range(len(value))]
                show_idx = st.selectbox("Show item", idx_options, key=f"li_{target}")
                _pretty(value[show_idx - int(offset)])

            col_push, col_edit, col_rem = st.columns(3)
            with col_push:
                with st.form(f"lpush_{target}"):
                    st.write("**Push item**")
                    p_val = st.text_area("Value", key=f"lpush_val_{target}", height=80)
                    p_dir = st.radio("Direction", ["right", "left"], horizontal=True, key=f"lpush_dir_{target}")
                    if st.form_submit_button("Push"):
                        if c.push_redis_list(target, [p_val], direction=p_dir) is None:
                            st.error(c.last_error() or "Push failed.")
                        else:
                            st.success("Pushed.")
                            st.rerun()
            with col_edit:
                with st.form(f"lset_{target}"):
                    st.write("**Replace at index**")
                    e_idx = st.number_input("Index", min_value=0, value=int(offset), key=f"lset_idx_{target}")
                    e_val = st.text_area("New value", key=f"lset_val_{target}", height=80)
                    if st.form_submit_button("LSET"):
                        if c.set_redis_list_index(target, int(e_idx), e_val) is None:
                            st.error(c.last_error() or "LSET failed.")
                        else:
                            st.success("Item replaced.")
                            st.rerun()
            with col_rem:
                with st.form(f"lrem_{target}"):
                    st.write("**Remove / pop**")
                    r_val = st.text_area("Remove by value", key=f"lrem_val_{target}", height=80)
                    do_rem = st.form_submit_button("LREM")
                    do_pop = st.form_submit_button("Pop right")
                    if do_rem and r_val:
                        if c.remove_redis_list_value(target, r_val) is None:
                            st.error(c.last_error() or "LREM failed.")
                        else:
                            st.success("Removed.")
                            st.rerun()
                    if do_pop:
                        popped = c.pop_redis_list(target, direction="right")
                        if popped is None:
                            st.error(c.last_error() or "Pop failed.")
                        else:
                            st.success(f"Popped: {popped.get('value')}")
                            st.rerun()

        elif ktype == "set" and isinstance(value, list):
            st.dataframe(
                pd.DataFrame([{"Member": m} for m in value]),
                width="stretch",
                hide_index=True,
            )
            col_add, col_rem = st.columns(2)
            with col_add:
                with st.form(f"sadd_{target}"):
                    st.write("**Add member**")
                    s_val = st.text_input("Member", key=f"sadd_val_{target}")
                    if st.form_submit_button("SADD") and s_val:
                        if c.add_redis_set_members(target, [s_val]) is None:
                            st.error(c.last_error() or "SADD failed.")
                        else:
                            st.success("Member added.")
                            st.rerun()
            with col_rem:
                with st.form(f"srem_{target}"):
                    st.write("**Remove member**")
                    s_del = st.selectbox("Member", value or ["—"], key=f"srem_{target}")
                    if st.form_submit_button("SREM") and value:
                        if c.remove_redis_set_member(target, s_del) is None:
                            st.error(c.last_error() or "SREM failed.")
                        else:
                            st.success("Member removed.")
                            st.rerun()

        elif ktype == "zset" and isinstance(value, list):
            st.dataframe(
                pd.DataFrame([
                    {"Member": m.get("member"), "Score": m.get("score")}
                    for m in value if isinstance(m, dict)
                ]),
                width="stretch",
                hide_index=True,
            )
            members = [m.get("member") for m in value if isinstance(m, dict)]
            col_add, col_rem = st.columns(2)
            with col_add:
                with st.form(f"zadd_{target}"):
                    st.write("**Add / update member**")
                    z_member = st.text_input("Member", key=f"zadd_m_{target}")
                    z_score = st.number_input("Score", value=0.0, key=f"zadd_s_{target}")
                    if st.form_submit_button("ZADD") and z_member:
                        if c.add_redis_zset_member(target, z_member, float(z_score)) is None:
                            st.error(c.last_error() or "ZADD failed.")
                        else:
                            st.success("Member stored.")
                            st.rerun()
            with col_rem:
                with st.form(f"zrem_{target}"):
                    st.write("**Remove member**")
                    z_del = st.selectbox("Member", members or ["—"], key=f"zrem_{target}")
                    if st.form_submit_button("ZREM") and members:
                        if c.remove_redis_zset_member(target, z_del) is None:
                            st.error(c.last_error() or "ZREM failed.")
                        else:
                            st.success("Member removed.")
                            st.rerun()

        elif ktype == "stream":
            st.caption(
                "Showing the oldest entries in range. Narrow the window with entry "
                "IDs to reach newer ones (`1700000000000-0`)."
            )
            col_s, col_e, col_n = st.columns(3)
            with col_s:
                s_start = st.text_input("From ID", value="-", key=f"xs_{target}")
            with col_e:
                s_end = st.text_input("To ID", value="+", key=f"xe_{target}")
            with col_n:
                s_count = st.number_input("Entries", min_value=1, max_value=1000, value=50, key=f"xc_{target}")

            stream = c.get_redis_stream(target, start=s_start, end=s_end, count=int(s_count))
            if stream is None:
                st.error(c.last_error() or "Could not read stream entries.")
            else:
                stream_entries = stream.get("entries", stream.get("items", [])) or []
                if not stream_entries:
                    st.info("No entries in this range.")
                for entry in stream_entries:
                    entry_id = entry.get("id", "?")
                    with st.expander(f"📨 {entry_id}"):
                        st.json(entry.get("fields", {}))
                        if st.button("🗑 XDEL", key=f"xdel_{target}_{entry_id}"):
                            if c.delete_redis_stream_entry(target, entry_id) is None:
                                st.error(c.last_error() or "XDEL failed.")
                            else:
                                st.success("Entry deleted.")
                                st.rerun()

        else:
            st.json(value if value is not None else {})

        # -- Key-level operations ---------------------------------------

        st.divider()
        st.write("**Key operations**")
        op1, op2, op3, op4 = st.columns(4)

        with op1:
            with st.form(f"ttl_form_{target}"):
                st.write("TTL")
                ttl_secs = st.number_input("Seconds (0 = persist)", min_value=0, value=0)
                if st.form_submit_button("Apply"):
                    res = (
                        c.set_redis_key_expire(target, int(ttl_secs))
                        if ttl_secs > 0 else c.persist_redis_key(target)
                    )
                    if res is None:
                        st.error(c.last_error() or "TTL change failed.")
                    else:
                        st.success("TTL updated.")
                        st.rerun()

        with op2:
            with st.form(f"rename_form_{target}"):
                st.write("Rename")
                rename_to = st.text_input("New name")
                if st.form_submit_button("Rename") and rename_to.strip():
                    if c.rename_redis_key(target, rename_to.strip()) is None:
                        st.error(c.last_error() or "Rename failed.")
                    else:
                        st.success("Renamed.")
                        _select(rename_to.strip())
                        st.rerun()

        with op3:
            with st.form(f"copy_form_{target}"):
                st.write("Copy")
                copy_to = st.text_input("Destination")
                replace = st.checkbox("Replace if exists")
                if st.form_submit_button("Copy") and copy_to.strip():
                    if c.copy_redis_key(target, copy_to.strip(), replace=replace) is None:
                        st.error(c.last_error() or "Copy failed.")
                    else:
                        st.success("Copied.")
                        st.rerun()

        with op4:
            st.write("Danger")
            _export_button(target, data)
            confirm_key = f"confirm_del_{target}"
            if st.session_state.get(confirm_key):
                st.warning("Empty / delete this whole key?")
                if st.button("Yes, delete", key=f"yes_del_{target}"):
                    res = c.delete_redis_key(target)
                    st.session_state.pop(confirm_key, None)
                    if res is None:
                        st.error(c.last_error() or "Delete failed.")
                    else:
                        st.session_state.pop(SELECTED, None)
                        st.success("Key deleted.")
                        st.rerun()
                if st.button("Cancel", key=f"no_del_{target}"):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
            else:
                if st.button("🗑 Empty / delete key", key=f"del_{target}"):
                    st.session_state[confirm_key] = True
                    st.rerun()
