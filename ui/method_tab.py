"""Scheda Metodo: descrizione del modello, convenzioni, parametri e limiti."""
from __future__ import annotations

import streamlit as st

from goalga.i18n import t

PARAMS = ("scenarios", "population", "crossover", "mutation", "step", "stop", "threshold", "tail", "portfolios")
PARAM_VALUES = {"scenarios": "1.000", "population": "100", "crossover": "0,55", "mutation": "0,30", "step": "±2",
                "stop": "200", "threshold": "90%", "tail": "5%", "portfolios": "9"}


def _value(key: str) -> str:
    """Valore nella notazione della lingua attiva (cifre decimali e migliaia)."""
    raw = PARAM_VALUES[key]
    from . import format as fmt

    numeric = {"scenarios": fmt.number(1000), "crossover": fmt.number(0.55, 2), "mutation": fmt.number(0.30, 2),
               "threshold": fmt.pct(0.90, 0), "tail": fmt.pct(0.05, 0)}
    return numeric.get(key, raw)


def render() -> None:
    left, right = st.columns([1.35, 1], gap="large")
    with left:
        st.markdown(f"#### {t('method.problem.title')}")
        st.markdown(t("method.problem.body"))
        st.markdown(f"#### {t('method.objective.title')}")
        st.latex(r"\max S,\quad S=\begin{cases}\Pr_{Goal} & \Pr_{Goal}<\Pr^*_{Goal}\\[2pt]"
                 r"2+IRR_{ES} & \Pr_{Goal}\ge \Pr^*_{Goal}\end{cases}")
        st.latex(r"I_1\ge I_2\ge\dots\ge I_T,\qquad I_t\in\{1,\dots,9\}")
        st.markdown(t("method.objective.body"))

        st.markdown(f"#### {t('method.how.title')}")
        st.markdown(t("method.how.body"))

        st.markdown(f"#### {t('method.risk.title')}")
        st.markdown(t("method.risk.body"))

        st.markdown(f"#### {t('method.conv.title')}")
        st.markdown(t("method.conv.body"))

    with right:
        st.markdown(f"#### {t('method.params.title')}")
        st.table({t("method.params.col_param"): [t(f"method.param.{k}") for k in PARAMS],
                  t("method.params.col_value"): [_value(k) if k != "stop" else t("method.param.stop_value")
                                                 for k in PARAMS]})
        st.caption(t("method.params.caption"))

        st.markdown(f"#### {t('method.impl.title')}")
        st.markdown(t("method.impl.body"))

        st.markdown(f"#### {t('method.limits.title')}")
        st.markdown(t("method.limits.body"))

        st.markdown(f"#### {t('method.ref.title')}")
        st.markdown(t("method.ref.body"))
