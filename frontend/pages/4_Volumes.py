"""
Volumes page — list, inspect, create, and remove Docker volumes.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
from utils.api_client import EngineClient, get_config

st.set_page_config(page_title="Volumes", page_icon="💾", layout="wide")
st.title("💾 Volumes")


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
# Create volume form
# ---------------------------------------------------------------------------

with st.expander("Create a new volume", expanded=False):
    with st.form("create_vol_form"):
        vol_name = st.text_input("Volume name")
        vol_driver = st.text_input("Driver", value="local")
        submitted = st.form_submit_button("Create")
    if submitted and vol_name.strip():
        result = c.create_volume(vol_name.strip(), driver=vol_driver.strip() or "local")
        if result is not None:
            st.success(f"Volume '{vol_name}' created.")
            st.rerun()
        elif "last_error" in st.session_state:
            st.error(st.session_state["last_error"])

st.divider()

# ---------------------------------------------------------------------------
# Volume list
# ---------------------------------------------------------------------------

volumes = c.get_volumes() or []

if not volumes:
    st.info("No volumes found.")
else:
    rows = []
    for vol in volumes:
        rows.append({
            "Name": vol.get("name", "—"),
            "Driver": vol.get("driver", "—"),
            "Scope": vol.get("scope", "—"),
            "Mountpoint": vol.get("mountpoint", "—"),
            "Created": vol.get("created", "—"),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Volume detail")

    for vol in volumes:
        vol_name = vol.get("name", "?")

        with st.expander(f"💾 {vol_name}"):
            col_info, col_action = st.columns([3, 1])

            with col_info:
                st.write(f"**Driver:** {vol.get('driver', '—')}")
                st.write(f"**Scope:** {vol.get('scope', '—')}")
                st.write(f"**Mountpoint:** `{vol.get('mountpoint', '—')}`")
                st.write(f"**Created:** {vol.get('created', '—')}")
                if vol.get("labels"):
                    st.write("**Labels:**")
                    st.json(vol["labels"])

            with col_action:
                confirm_key = f"confirm_remove_vol_{vol_name}"
                if st.session_state.get(confirm_key):
                    st.warning("Remove this volume?")
                    if st.button("Yes, remove", key=f"yes_vol_{vol_name}"):
                        result = c.remove_volume(vol_name)
                        if result is not None:
                            st.success("Removed.")
                        st.session_state.pop(confirm_key, None)
                        st.rerun()
                    if st.button("Cancel", key=f"no_vol_{vol_name}"):
                        st.session_state.pop(confirm_key, None)
                        st.rerun()
                else:
                    if st.button("🗑 Remove", key=f"remove_vol_{vol_name}"):
                        st.session_state[confirm_key] = True
                        st.rerun()
