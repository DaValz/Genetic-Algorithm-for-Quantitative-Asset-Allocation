"""GoalGA: percorso guidato verso la strategia d'investimento giusta per i tuoi obiettivi.

Avvio: ``streamlit run app.py``
"""
import streamlit as st

from goalga import snapshot
from goalga.i18n import t
from ui import lang, state

state.init_state()
lang.activate()

st.set_page_config(
    page_title=t("app.title"),
    page_icon=":material/auto_awesome:",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={"About": t("app.about")},
)

from ui import account, flow  # noqa: E402


def main() -> None:
    account.refresh_badge()
    if not snapshot.available():
        st.error(t("mkt.no_snapshot_help"), icon=":material/error_outline:")
        st.stop()
    flow.render()


main()
