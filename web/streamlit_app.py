from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from speech_service import SpeechSession

HERE = Path(__file__).parent
st.set_page_config(page_title="YapBook", page_icon=str(HERE / "frontend/public/favicon.ico"), layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
    [data-testid="stAppViewContainer"] { background:#f6f5f1; }
    [data-testid="stHeader"] { display:none; }
    .block-container { padding:0 !important; max-width:none !important; }
    [data-testid="stVerticalBlock"] { gap:0; }
    iframe { border:0; }
    </style>""", unsafe_allow_html=True)

reader = components.declare_component("yapbook_reader", path=str(HERE / "frontend/dist"))
if "speech_session" not in st.session_state:
    st.session_state.speech_session = SpeechSession()


@st.fragment(run_every=0.5)
def reader_fragment():
    session = st.session_state.speech_session
    command = reader(reply=session.snapshot(), key="reader", default=None)
    if command:
        session.submit(command)


reader_fragment()
