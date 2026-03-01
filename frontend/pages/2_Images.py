"""
Images page — list, pull, and remove Docker images.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
from utils.api_client import EngineClient, get_config
from utils.formatting import bytes_to_human

st.set_page_config(page_title="Images", page_icon="🖼️", layout="wide")
st.title("🖼️ Images")


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
# Pull image form
# ---------------------------------------------------------------------------

with st.expander("Pull a new image", expanded=False):
    with st.form("pull_form"):
        pull_name = st.text_input("Image name (e.g. nginx:latest)", placeholder="nginx:latest")
        submitted = st.form_submit_button("Pull")
    if submitted and pull_name.strip():
        with st.spinner(f"Pulling {pull_name}…"):
            result = c.pull_image(pull_name.strip())
        if result is not None:
            st.success(f"Pulled {pull_name} successfully.")
            st.rerun()
        elif "last_error" in st.session_state:
            st.error(st.session_state["last_error"])

st.divider()

# ---------------------------------------------------------------------------
# Image list
# ---------------------------------------------------------------------------

images = c.get_images() or []

if not images:
    st.info("No images found.")
else:
    rows = []
    for img in images:
        tags = img.get("tags") or ["<none>"]
        rows.append({
            "Tags": ", ".join(tags),
            "ID": img.get("short_id", img.get("id", "?")[:12]),
            "Created": img.get("created", "—"),
            "Size": bytes_to_human(img.get("size_bytes")),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Image detail & removal")

    for img in images:
        img_id = img.get("id", "")
        tags = img.get("tags") or ["<none>"]
        label = tags[0] if tags else img_id[:12]

        with st.expander(f"🖼️ {label}"):
            col_info, col_action = st.columns([3, 1])

            with col_info:
                st.write(f"**ID:** `{img_id[:12]}`")
                st.write(f"**All tags:** {', '.join(tags)}")
                st.write(f"**Created:** {img.get('created', '—')}")
                st.write(f"**Size:** {bytes_to_human(img.get('size_bytes'))}")
                if img.get("labels"):
                    st.write("**Labels:**")
                    st.json(img["labels"])

                if st.toggle("Show full inspect", key=f"inspect_{img_id}"):
                    detail = c.get_image(img_id)
                    if detail:
                        for field in ("architecture", "os", "author", "cmd", "entrypoint"):
                            val = detail.get(field)
                            if val:
                                st.write(f"**{field.capitalize()}:** {val}")
                        env = detail.get("env", [])
                        if env:
                            st.write("**Env:**")
                            st.code("\n".join(env))

            with col_action:
                confirm_key = f"confirm_remove_img_{img_id}"
                if st.session_state.get(confirm_key):
                    st.warning("Remove this image?")
                    if st.button("Yes, remove", key=f"yes_img_{img_id}"):
                        result = c.remove_image(img_id, force=True)
                        if result is not None:
                            st.success("Removed.")
                        st.session_state.pop(confirm_key, None)
                        st.rerun()
                    if st.button("Cancel", key=f"no_img_{img_id}"):
                        st.session_state.pop(confirm_key, None)
                        st.rerun()
                else:
                    if st.button("🗑 Remove", key=f"remove_img_{img_id}"):
                        st.session_state[confirm_key] = True
                        st.rerun()
