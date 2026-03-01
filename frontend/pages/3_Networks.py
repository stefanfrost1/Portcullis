"""
Networks page — list, inspect, create, and remove Docker networks.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
from utils.api_client import EngineClient, get_config

st.set_page_config(page_title="Networks", page_icon="🌐", layout="wide")
st.title("🌐 Networks")

BUILTIN_NETWORKS = {"bridge", "host", "none"}


@st.cache_resource
def get_client() -> EngineClient:
    cfg = get_config()
    return EngineClient(cfg["base_url"], cfg.get("api_key"))


c = get_client()

if "last_error" in st.session_state:
    st.error(st.session_state["last_error"])

with st.sidebar:
    if st.button("↻ Refresh"):
        st.rerun()

# ---------------------------------------------------------------------------
# Create network form
# ---------------------------------------------------------------------------

with st.expander("Create a new network", expanded=False):
    with st.form("create_net_form"):
        net_name = st.text_input("Network name")
        net_driver = st.selectbox("Driver", ["bridge", "overlay", "host", "none", "macvlan"])
        net_internal = st.checkbox("Internal (no external connectivity)")
        submitted = st.form_submit_button("Create")
    if submitted and net_name.strip():
        result = c.create_network(net_name.strip(), driver=net_driver, internal=net_internal)
        if result is not None:
            st.success(f"Network '{net_name}' created.")
            st.rerun()
        elif "last_error" in st.session_state:
            st.error(st.session_state["last_error"])

st.divider()

# ---------------------------------------------------------------------------
# Network list
# ---------------------------------------------------------------------------

networks = c.get_networks() or []

if not networks:
    st.info("No networks found.")
else:
    rows = []
    for net in networks:
        containers = net.get("containers") or {}
        rows.append({
            "Name": net.get("name", "—"),
            "Driver": net.get("driver", "—"),
            "Scope": net.get("scope", "—"),
            "Internal": "✓" if net.get("internal") else "",
            "Containers": len(containers) if isinstance(containers, dict) else 0,
            "Created": net.get("created", "—"),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Network detail")

    for net in networks:
        net_id = net.get("id", "")
        net_name = net.get("name", "?")
        is_builtin = net_name in BUILTIN_NETWORKS

        with st.expander(f"🌐 {net_name}  ({net.get('driver', '—')})"):
            col_info, col_action = st.columns([3, 1])

            with col_info:
                st.write(f"**ID:** `{net_id[:12]}`")
                st.write(f"**Driver:** {net.get('driver', '—')}")
                st.write(f"**Scope:** {net.get('scope', '—')}")
                st.write(f"**Internal:** {'Yes' if net.get('internal') else 'No'}")

                containers = net.get("containers") or {}
                if containers:
                    st.write(f"**Attached containers ({len(containers)}):**")
                    for cid, info in containers.items():
                        name = info.get("name", cid[:12]) if isinstance(info, dict) else cid[:12]
                        ip = info.get("ip", "") if isinstance(info, dict) else ""
                        st.write(f"  • {name}" + (f" ({ip})" if ip else ""))
                else:
                    st.write("No containers attached.")

            with col_action:
                if is_builtin:
                    st.caption("Built-in network — cannot remove.")
                else:
                    confirm_key = f"confirm_remove_net_{net_id}"
                    if st.session_state.get(confirm_key):
                        st.warning("Remove this network?")
                        if st.button("Yes, remove", key=f"yes_net_{net_id}"):
                            result = c.remove_network(net_id)
                            if result is not None:
                                st.success("Removed.")
                            st.session_state.pop(confirm_key, None)
                            st.rerun()
                        if st.button("Cancel", key=f"no_net_{net_id}"):
                            st.session_state.pop(confirm_key, None)
                            st.rerun()
                    else:
                        if st.button("🗑 Remove", key=f"remove_net_{net_id}"):
                            st.session_state[confirm_key] = True
                            st.rerun()
