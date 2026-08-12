"""
Redis Keys — master/detail keyspace browser and editor.

Left  (master):  cursor-paginated SCAN, click a key row to open it. Named sort
                 and a name filter narrow the current page.
Right (detail):  a tabbed inspector for the selected key —
                   • Value   view contents; filter + click an item to drill in,
                             with inline edit/delete per item
                   • Add     type-appropriate insert (push / HSET / SADD / ZADD)
                   • Manage  TTL, rename, copy, export, and a guarded delete

Any key can also be opened by name, so keys beyond the scan window are reachable.
"""

import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
from utils.api_client import EngineClient, get_config, current_role, is_admin
from utils.formatting import bytes_to_human, seconds_to_human

st.set_page_config(page_title="Redis Keys", page_icon="🗝️", layout="wide")

SELECTED = "redis_selected_key"
_TYPE_ICON = {
    "string": "🔤", "hash": "🧩", "list": "📋",
    "set": "🎯", "zset": "📊", "stream": "🌊",
}
_ITEM_CAP = 300  # per-page render cap for big collections


@st.cache_resource
def get_client() -> EngineClient:
    cfg = get_config()
    return EngineClient(cfg["base_url"], cfg.get("api_key"))


c = get_client()
admin = is_admin()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _type_icon(t: str) -> str:
    return _TYPE_ICON.get(t, "•")


def _ttl_text(ttl) -> str:
    if ttl is None:
        return "—"
    if ttl == -1:
        return "No expiry"
    if ttl == -2:
        return "Expired / missing"
    return seconds_to_human(ttl)


def _ttl_sort_key(ttl) -> float:
    if isinstance(ttl, int) and ttl >= 0:
        return ttl
    return float("inf")


def _pretty(value) -> None:
    """Render as pretty JSON when it parses, otherwise as raw text."""
    if isinstance(value, (dict, list)):
        st.json(value)
        return
    text = "" if value is None else str(value)
    try:
        st.json(json.loads(text))
    except (ValueError, TypeError):
        st.code(text or "(empty)", language="text")


def _select(key: str) -> None:
    st.session_state[SELECTED] = key


def _matches(needle: str, *fields) -> bool:
    if not needle:
        return True
    n = needle.lower()
    return any(n in str(f).lower() for f in fields)


# ---------------------------------------------------------------------------
# Sidebar — scan + sort controls
# ---------------------------------------------------------------------------

with st.sidebar:
    st.subheader("Keyspace")
    st.caption(f"Signed in as **{current_role()}**")
    pattern = st.text_input("Key pattern", value="*", help="Glob over key names, e.g. user:*")
    key_type = st.selectbox("Type filter", ["all", "string", "hash", "list", "set", "zset", "stream"])
    sort_choice = st.selectbox(
        "Sort by", ["Key (A → Z)", "Key (Z → A)", "Type", "TTL (soonest)"], index=0
    )
    name_filter = st.text_input("Filter by name", value="", placeholder="substring…")
    page_size = st.selectbox("Keys per page", [25, 50, 100, 200], index=1)
    if st.button("↻ Refresh", use_container_width=True):
        st.session_state["redis_cursor"] = 0
        st.session_state["redis_cursor_history"] = [0]
        st.rerun()
    total = c.get_redis_key_count()
    if total is not None:
        st.metric("Total keys (DBSIZE)", f"{total:,}")

st.title("🗝️ Redis Keys")
if not admin:
    st.caption("🔒 Read-only — sign in as admin to create, edit, or delete keys.")

# ---------------------------------------------------------------------------
# Fetch + sort + filter the current SCAN page
# ---------------------------------------------------------------------------

if "redis_cursor" not in st.session_state:
    st.session_state["redis_cursor"] = 0
if "redis_cursor_history" not in st.session_state:
    st.session_state["redis_cursor_history"] = [0]

result = c.get_redis_keys(
    pattern=pattern,
    cursor=st.session_state["redis_cursor"],
    count=page_size,
    key_type=key_type if key_type != "all" else None,
)
if result is None:
    st.error(c.last_error() or "Could not scan the keyspace.")
    result = {}

entries = [e for e in (result.get("keys", []) or []) if isinstance(e, dict)]
next_cursor = result.get("cursor", 0)

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

master, detail = st.columns([1, 2], gap="large")

# ---------------------------------------------------------------------------
# Master — click a key
# ---------------------------------------------------------------------------

with master:
    if admin:
        with st.expander("➕ Create / overwrite a key"):
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
                    res = c.set_redis_key(new_key.strip(), key_type=new_type, value=val,
                                          ttl=new_ttl if new_ttl > 0 else None)
                    if res is None:
                        st.error(c.last_error() or "Could not save key.")
                    else:
                        st.success(f"Key '{new_key}' saved.")
                        _select(new_key.strip())
                        st.rerun()

    st.caption(f"{len(shown)} of {len(entries)} on this page · cursor {st.session_state['redis_cursor']}"
               + ("" if next_cursor else " · scan complete"))

    pc = st.columns(2)
    history: list = st.session_state["redis_cursor_history"]
    with pc[0]:
        if len(history) > 1 and st.button("◀ Prev", use_container_width=True):
            history.pop()
            st.session_state["redis_cursor"] = history[-1]
            st.rerun()
    with pc[1]:
        if next_cursor and st.button("Next ▶", use_container_width=True):
            history.append(next_cursor)
            st.session_state["redis_cursor"] = next_cursor
            st.rerun()

    box = st.container(height=520)
    with box:
        if not shown:
            st.caption("No keys on this page match the filter.")
        for e in shown:
            k = e.get("key", "?")
            sel = st.session_state.get(SELECTED) == k
            label = f"{'▶ ' if sel else ''}{_type_icon(e.get('type','?'))} {k}  ·  {_ttl_text(e.get('ttl'))}"
            if st.button(label, key=f"krow_{k}", use_container_width=True,
                         type="primary" if sel else "secondary"):
                _select(k)
                st.rerun()

    if admin:
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


# ---------------------------------------------------------------------------
# Detail — inspector tabs
# ---------------------------------------------------------------------------

def _value_tab(target: str, ktype: str, value, offset: int) -> None:
    """View + click-to-drill items with inline edit/delete."""
    if ktype == "string":
        _pretty(value)
        if admin:
            new = st.text_area("Edit value", value=str(value or ""), height=180, key=f"sv_{target}")
            if st.button("💾 Save value", key=f"ss_{target}"):
                if c.set_redis_key(target, "string", new) is None:
                    st.error(c.last_error() or "Save failed.")
                else:
                    st.success("Saved.")
                    st.rerun()
        return

    if ktype == "stream":
        st.caption("Oldest entries in range. Narrow with entry IDs to reach newer ones.")
        s_start = st.text_input("From ID", value="-", key=f"xs_{target}")
        s_end = st.text_input("To ID", value="+", key=f"xe_{target}")
        s_count = st.number_input("Entries", min_value=1, max_value=1000, value=50, key=f"xc_{target}")
        stream = c.get_redis_stream(target, start=s_start, end=s_end, count=int(s_count))
        rows = (stream or {}).get("entries", (stream or {}).get("items", [])) or []
        if not rows:
            st.info("No entries in this range.")
        for entry in rows:
            eid = entry.get("id", "?")
            with st.expander(f"📨 {eid}"):
                st.json(entry.get("fields", {}))
                if admin and st.button("🗑 XDEL", key=f"xdel_{target}_{eid}"):
                    if c.delete_redis_stream_entry(target, eid) is None:
                        st.error(c.last_error() or "XDEL failed.")
                    else:
                        st.success("Entry deleted.")
                        st.rerun()
        return

    # Collections: hash / list / set / zset — filter + per-item drill-in.
    filt = st.text_input("Filter items", key=f"cf_{target}", placeholder="substring…")

    if ktype == "hash" and isinstance(value, dict):
        items = [(f, v) for f, v in value.items() if _matches(filt, f, v)]
        st.caption(f"{len(items)} field(s)")
        for f, v in items[:_ITEM_CAP]:
            with st.expander(f"🔑 {f}"):
                _pretty(v)
                if admin:
                    nv = st.text_area("Value", value=str(v), key=f"hv_{target}_{f}", height=80)
                    if st.button("💾 Save", key=f"hs_{target}_{f}"):
                        if c.set_redis_hash_field(target, f, nv) is None:
                            st.error(c.last_error() or "HSET failed.")
                        else:
                            st.success("Saved.")
                            st.rerun()
                    if st.button("🗑 Delete field", key=f"hd_{target}_{f}"):
                        if c.delete_redis_hash_field(target, f) is None:
                            st.error(c.last_error() or "HDEL failed.")
                        else:
                            st.success("Deleted.")
                            st.rerun()

    elif ktype == "list" and isinstance(value, list):
        rows = [(offset + i, v) for i, v in enumerate(value) if _matches(filt, v)]
        st.caption(f"{len(rows)} item(s) on this page")
        for idx, v in rows[:_ITEM_CAP]:
            with st.expander(f"#{idx}"):
                _pretty(v)
                if admin:
                    nv = st.text_area("Value", value=str(v), key=f"lv_{target}_{idx}", height=80)
                    if st.button("💾 Save at index", key=f"ls_{target}_{idx}"):
                        if c.set_redis_list_index(target, idx, nv) is None:
                            st.error(c.last_error() or "LSET failed.")
                        else:
                            st.success("Saved.")
                            st.rerun()
                    if st.button("🗑 Delete (by value)", key=f"ld_{target}_{idx}"):
                        if c.remove_redis_list_value(target, str(v), count=1) is None:
                            st.error(c.last_error() or "LREM failed.")
                        else:
                            st.success("Removed.")
                            st.rerun()

    elif ktype == "set" and isinstance(value, list):
        members = [m for m in value if _matches(filt, m)]
        st.caption(f"{len(members)} member(s) on this page")
        for m in members[:_ITEM_CAP]:
            with st.expander(f"• {m}"):
                if admin and st.button("🗑 Remove", key=f"sr_{target}_{m}"):
                    if c.remove_redis_set_member(target, m) is None:
                        st.error(c.last_error() or "SREM failed.")
                    else:
                        st.success("Removed.")
                        st.rerun()

    elif ktype == "zset" and isinstance(value, list):
        rows = [it for it in value if isinstance(it, dict) and _matches(filt, it.get("member"))]
        st.caption(f"{len(rows)} member(s) on this page")
        for it in rows[:_ITEM_CAP]:
            m, sc = it.get("member"), it.get("score")
            with st.expander(f"{m}  ·  score {sc}"):
                if admin:
                    ns = st.number_input("Score", value=float(sc or 0), key=f"zs_{target}_{m}")
                    if st.button("💾 Update score", key=f"zu_{target}_{m}"):
                        if c.add_redis_zset_member(target, m, float(ns)) is None:
                            st.error(c.last_error() or "ZADD failed.")
                        else:
                            st.success("Updated.")
                            st.rerun()
                    if st.button("🗑 Remove", key=f"zr_{target}_{m}"):
                        if c.remove_redis_zset_member(target, m) is None:
                            st.error(c.last_error() or "ZREM failed.")
                        else:
                            st.success("Removed.")
                            st.rerun()
    else:
        _pretty(value)


def _add_tab(target: str, ktype: str) -> None:
    if not admin:
        st.info("Sign in as admin to add items.")
        return
    if ktype == "hash":
        with st.form(f"add_h_{target}"):
            f = st.text_input("Field")
            v = st.text_area("Value", height=80)
            if st.form_submit_button("HSET") and f.strip():
                if c.set_redis_hash_field(target, f.strip(), v) is None:
                    st.error(c.last_error() or "HSET failed.")
                else:
                    st.success("Field set.")
                    st.rerun()
    elif ktype == "list":
        with st.form(f"add_l_{target}"):
            st.caption("One value per line pushes several at once.")
            body = st.text_area("Value(s)", height=100)
            where = st.radio("Push to", ["Back (tail)", "Front (head)"], horizontal=True)
            if st.form_submit_button("Push"):
                vals = [ln for ln in body.splitlines() if ln.strip() != ""] or ([body] if body else [])
                if vals:
                    d = "left" if where.startswith("Front") else "right"
                    if c.push_redis_list(target, vals, direction=d) is None:
                        st.error(c.last_error() or "Push failed.")
                    else:
                        st.success(f"Pushed {len(vals)}.")
                        st.rerun()
    elif ktype == "set":
        with st.form(f"add_s_{target}"):
            m = st.text_input("Member")
            if st.form_submit_button("SADD") and m.strip():
                if c.add_redis_set_members(target, [m.strip()]) is None:
                    st.error(c.last_error() or "SADD failed.")
                else:
                    st.success("Member added.")
                    st.rerun()
    elif ktype == "zset":
        with st.form(f"add_z_{target}"):
            m = st.text_input("Member")
            sc = st.number_input("Score", value=0.0)
            if st.form_submit_button("ZADD") and m.strip():
                if c.add_redis_zset_member(target, m.strip(), float(sc)) is None:
                    st.error(c.last_error() or "ZADD failed.")
                else:
                    st.success("Member stored.")
                    st.rerun()
    elif ktype == "string":
        st.info("Edit the value directly in the Value tab.")
    else:
        st.info("Adding entries to this type is not supported here.")


def _manage_tab(target: str, data: dict) -> None:
    st.download_button(
        "⬇ Export JSON",
        data=json.dumps(data, indent=2, default=str),
        file_name=f"{target.replace(':', '_').replace('/', '_')}.json",
        mime="application/json",
        key=f"export_{target}",
    )
    if not admin:
        st.info("Sign in as admin to change or delete this key.")
        return

    with st.form(f"ttl_{target}"):
        st.markdown("**TTL**")
        secs = st.number_input("Seconds (0 = persist / no expiry)", min_value=0, value=0)
        if st.form_submit_button("Apply TTL"):
            res = c.set_redis_key_expire(target, int(secs)) if secs > 0 else c.persist_redis_key(target)
            if res is None:
                st.error(c.last_error() or "TTL change failed.")
            else:
                st.success("TTL updated.")
                st.rerun()

    with st.form(f"rename_{target}"):
        st.markdown("**Rename**")
        to = st.text_input("New name")
        if st.form_submit_button("Rename") and to.strip():
            if c.rename_redis_key(target, to.strip()) is None:
                st.error(c.last_error() or "Rename failed.")
            else:
                st.success("Renamed.")
                _select(to.strip())
                st.rerun()

    with st.form(f"copy_{target}"):
        st.markdown("**Copy**")
        to = st.text_input("Destination")
        replace = st.checkbox("Replace if exists")
        if st.form_submit_button("Copy") and to.strip():
            if c.copy_redis_key(target, to.strip(), replace=replace) is None:
                st.error(c.last_error() or "Copy failed.")
            else:
                st.success("Copied.")
                st.rerun()

    st.divider()
    st.markdown("**Danger zone**")
    st.caption("Deletes the entire key. This cannot be undone.")
    ok = st.checkbox(f"Yes, empty and delete '{target}'", key=f"del_ok_{target}")
    if st.button("🗑 Empty / delete key", disabled=not ok, key=f"del_{target}"):
        res = c.delete_redis_key(target)
        if res is None:
            st.error(c.last_error() or "Delete failed.")
        else:
            st.session_state.pop(SELECTED, None)
            st.success("Key deleted.")
            st.rerun()


with detail:
    with st.form("open_by_name", clear_on_submit=False):
        nm = st.text_input("Open a key by name", placeholder="reach keys beyond the current page")
        if st.form_submit_button("Open") and nm.strip():
            _select(nm.strip())
            st.rerun()

    target = (st.session_state.get(SELECTED) or "").strip()
    if not target:
        st.info("← Click a key on the left, or open one by name above.")
    else:
        with st.expander("⚙ Paging for large collections"):
            offset = st.number_input("Offset", min_value=0, value=0, step=50, key=f"off_{target}")
            count = st.number_input("Items per page", min_value=1, max_value=5000, value=200, step=50,
                                    key=f"cnt_{target}")

        data = c.get_redis_key(target, offset=int(offset), count=int(count))
        if data is None:
            st.error(c.last_error() or f"Could not read '{target}'.")
        else:
            ktype = data.get("type", "?")
            value = data.get("value")

            st.markdown(f"### {_type_icon(ktype)} `{target}`")
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Type", ktype)
            k2.metric("TTL", _ttl_text(data.get("ttl")))
            k3.metric("Length", data.get("length") if data.get("length") is not None else "—")
            k4.metric("Memory", bytes_to_human(data.get("memory_bytes")))
            st.caption(f"Encoding: `{data.get('encoding') or '—'}` · db {data.get('db', 0)}")
            if data.get("truncated"):
                st.warning("Value is truncated — page through it with the offset above.")

            tab_value, tab_add, tab_manage = st.tabs(["📄 Value", "➕ Add", "⚙️ Manage"])
            with tab_value:
                _value_tab(target, ktype, value, int(offset))
            with tab_add:
                _add_tab(target, ktype)
            with tab_manage:
                _manage_tab(target, data)
