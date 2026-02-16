# -*- coding: utf-8 -*-
"""
Decision Cockpit de Categoría (CatMan) — Streamlit Demo
Flujo: Decidir (ex-ante) -> Gobernar (ejecución) -> Defender (retailer)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import List, Tuple, Dict, Any

import numpy as np
import pandas as pd
import streamlit as st


# =========================
# Utilidades de formato
# =========================
def mxn(x: float) -> str:
    return f"${x:,.0f} MXN"


def pct(x: float) -> str:
    return f"{x * 100:,.1f}%"


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def stable_seed(*parts: str) -> int:
    """Seed determinística por contexto."""
    s = "|".join(parts)
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h *= 16777619
        h &= 0xFFFFFFFF
    return int(h)


def utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# =========================
# Modelo mínimo de datos
# =========================
@dataclass
class ContextoDecision:
    rol: str
    categoria: str
    canal: str
    retailer: str
    objetivo: str  # "Rentabilidad" | "Crecimiento"


@dataclass
class Levers:
    price_pct: float  # ej. +0.02
    sos_pts: float    # ej. +2.0
    top_n: int        # ej. 80


@dataclass
class KPISet:
    sales: float
    cuervo_profit: float
    retailer_profit: float
    risk: float  # 0..1


@dataclass
class DecisionRecord:
    decision_id: str
    timestamp_utc: str
    contexto: ContextoDecision
    chosen_scenario: str  # "A" | "B"
    levers: Levers
    expected: KPISet
    observed: KPISet
    status: str  # "Decidida" | "En seguimiento" | "Con ajuste"


@dataclass
class AdjustmentRecord:
    adj_id: str
    decision_id: str
    timestamp_utc: str
    reason: str
    new_levers: Levers
    new_expected: KPISet


# =========================
# Base data demo (determinística y plausible)
# =========================
N_BASE = 80  # Top-N base para escala


def base_kpis_for_context(ctx: ContextoDecision, demo_mode: bool) -> KPISet:
    """
    Base KPI por contexto. En demo mode, fija un caso “Tequila Core / Moderno / Walmart”
    con números tipo captura; el resto se genera determinísticamente.
    """
    if demo_mode and ctx.categoria == "Tequila Core" and ctx.canal == "Moderno" and ctx.retailer == "Walmart":
        return KPISet(
            sales=66_609_477.0,
            cuervo_profit=24_004_351.0,
            retailer_profit=13_321_895.0,
            risk=0.44,
        )

    seed = stable_seed(ctx.rol, ctx.categoria, ctx.canal, ctx.retailer)
    rng = np.random.default_rng(seed)

    sales = float(rng.uniform(25e6, 120e6))
    cuervo = float(sales * rng.uniform(0.22, 0.38))
    retailer = float(sales * rng.uniform(0.10, 0.22))
    risk = float(rng.uniform(0.25, 0.55))
    return KPISet(sales=sales, cuervo_profit=cuervo, retailer_profit=retailer, risk=risk)


# =========================
# Motor demo (palancas -> KPIs)
# =========================
def compute_kpis(base: KPISet, levers: Levers) -> KPISet:
    """
    Motor demo determinístico y con signos económicos razonables.
    - Precio ↑: sales tiende ↓, cuervo_profit tiende ↑, retailer_profit tiende ↓, riesgo ↑
    - SOS ↑: sales ↑, retailer_profit ↑, riesgo ↑ (ejecución/negociación)
    - Top-N ↓: impactos absolutos ↓, riesgo ↓
    """
    p = levers.price_pct
    s = levers.sos_pts
    n_scale = levers.top_n / N_BASE

    # Parámetros demo
    e_p = 1.25
    e_s = 0.10
    m_p = 2.00
    c_s = 0.015
    r_s = 0.12
    r_p = 0.80

    vol = clamp(1.0 - e_p * p + e_s * (s / 10.0), 0.70, 1.30)

    sales = base.sales * vol * (1.0 + p) * n_scale
    cuervo_profit = base.cuervo_profit * (1.0 + m_p * p) * vol * n_scale - (c_s * (s / 10.0) * base.sales * n_scale)
    retailer_profit = base.retailer_profit * (1.0 + r_s * (s / 10.0) - r_p * p) * vol * n_scale

    risk = base.risk + 0.85 * abs(p) + 0.35 * abs(s / 10.0) + 0.25 * abs(n_scale - 1.0)
    risk = clamp(risk, 0.0, 1.0)

    return KPISet(
        sales=float(sales),
        cuervo_profit=float(cuervo_profit),
        retailer_profit=float(retailer_profit),
        risk=float(risk),
    )


# =========================
# Escenarios A/B (guardrails)
# =========================
@dataclass
class Guardrails:
    risk_max: float = 0.55
    retailer_drop_max: float = 0.02


def is_viable(candidate: KPISet, base: KPISet, gr: Guardrails) -> bool:
    if candidate.risk > gr.risk_max:
        return False
    if (candidate.retailer_profit / base.retailer_profit) < (1.0 - gr.retailer_drop_max):
        return False
    return True


def build_scenarios(
    base_kpis: KPISet,
    current_levers: Levers,
    gr: Guardrails,
) -> Tuple[Tuple[str, Levers, KPISet], Tuple[str, Levers, KPISet]]:
    price_grid = sorted(set([current_levers.price_pct, 0.0, 0.02, -0.03]))
    sos_grid = sorted(set([current_levers.sos_pts, 0.0, 1.0, 2.0]))
    topn_grid = sorted(set([current_levers.top_n, 40, 80, 120]))

    candidates: List[Tuple[Levers, KPISet]] = []
    for p in price_grid:
        for s in sos_grid:
            for n in topn_grid:
                lv = Levers(price_pct=float(p), sos_pts=float(s), top_n=int(max(10, n)))
                k = compute_kpis(base_kpis, lv)
                candidates.append((lv, k))

    viable = [(lv, k) for (lv, k) in candidates if is_viable(k, base_kpis, gr)]
    if not viable:
        # relaja guardrail de retailer para que siempre haya algo que mostrar
        relaxed = Guardrails(risk_max=gr.risk_max, retailer_drop_max=0.10)
        viable = [(lv, k) for (lv, k) in candidates if is_viable(k, base_kpis, relaxed)]
        if not viable:
            viable = candidates

    A_lv, A_k = max(viable, key=lambda t: t[1].cuervo_profit)
    B_lv, B_k = max(viable, key=lambda t: t[1].sales)

    return ("A", A_lv, A_k), ("B", B_lv, B_k)


def observed_from_expected(expected: KPISet, decision_id: str) -> KPISet:
    seed = stable_seed(decision_id)
    rng = np.random.default_rng(seed)

    sales_noise = rng.normal(loc=-0.010, scale=0.012)
    cuervo_noise = rng.normal(loc=-0.008, scale=0.015)
    retailer_noise = rng.normal(loc=-0.006, scale=0.012)

    sales = expected.sales * (1.0 + sales_noise)
    cuervo = expected.cuervo_profit * (1.0 + cuervo_noise)
    retailer = expected.retailer_profit * (1.0 + retailer_noise)
    risk = clamp(expected.risk + abs(sales_noise) * 1.2, 0.0, 1.0)

    return KPISet(sales=float(sales), cuervo_profit=float(cuervo), retailer_profit=float(retailer), risk=float(risk))


# =========================
# UI helpers
# =========================
def kpi_card(title: str, k: KPISet):
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.metric("Ventas (valor)", mxn(k.sales))
        st.metric("Cuervo profit", mxn(k.cuervo_profit))
        st.metric("Retailer profit", mxn(k.retailer_profit))
        st.metric("Riesgo (0–1)", f"{k.risk:.2f}")


def delta_row(label: str, exp: float, obs: float) -> Dict[str, Any]:
    d = obs - exp
    dp = (obs / exp - 1.0) if exp != 0 else np.nan
    return {"KPI": label, "Esperado": exp, "Observado": obs, "Δ (MXN)": d, "Δ (%)": dp}


def init_state():
    if "decisions" not in st.session_state:
        st.session_state.decisions = []
    if "adjustments" not in st.session_state:
        st.session_state.adjustments = []
    if "mode" not in st.session_state:
        st.session_state.mode = "Decidir"
    if "demo_mode" not in st.session_state:
        st.session_state.demo_mode = True


# =========================
# App
# =========================
st.set_page_config(page_title="Decision Cockpit de Categoría", layout="wide")
init_state()

st.title("Decision Cockpit de Categoría")
st.caption("Maqueta: una sola vista, tres momentos de uso — Decidir · Gobernar · Defender")

with st.sidebar:
    st.header("Controles")
    st.session_state.demo_mode = st.toggle("Modo Demo", value=st.session_state.demo_mode)

    rol = st.selectbox("Rol", ["CPS", "CatMan/Trade", "KAM/Comercial", "Viewer"], index=0)
    categoria = st.selectbox("Categoría", ["Tequila Core", "Whisky", "RTDs", "Vodka"], index=0)
    canal_retailer = st.selectbox("Canal / Retailer", ["Moderno / Walmart", "Moderno / Soriana", "Tradicional / Mayoreo"], index=0)

    canal, retailer = [x.strip() for x in canal_retailer.split("/")]
    st.divider()

    if st.session_state.demo_mode:
        st.info("Tip: En Modo Demo hay decisiones precargadas para recorrer el flujo completo.")
    else:
        st.warning("Modo Demo OFF: KPIs base se generan determinísticamente por contexto.")


col_top1, col_top2, col_top3 = st.columns([1, 2, 2])
with col_top1:
    if st.button("Reset Demo"):
        st.session_state.decisions = []
        st.session_state.adjustments = []
        st.session_state.mode = "Decidir"
        st.toast("Estado reiniciado.")
with col_top2:
    st.write("**Modo Demo:**", "ON" if st.session_state.demo_mode else "OFF")
with col_top3:
    st.write("**Demo Runbook (3 pasos):** Step 1: Decidir · Step 2: Gobernar · Step 3: Defender")

st.subheader("Modo")
mode = st.radio("", ["Decidir", "Gobernar", "Defender"], horizontal=True,
                index=["Decidir", "Gobernar", "Defender"].index(st.session_state.mode))
st.session_state.mode = mode

with st.expander("Guardrails (configurables)", expanded=False):
    gr_risk = st.slider("Riesgo máximo permitido", 0.10, 0.95, 0.55, 0.01)
    gr_retailer_drop = st.slider("Caída máxima Retailer profit vs Base (%)", 0.0, 0.20, 0.02, 0.01)

guardrails = Guardrails(risk_max=gr_risk, retailer_drop_max=gr_retailer_drop)

# =========================
# DECIDIR
# =========================
if mode == "Decidir":
    st.markdown("### User Story 1 — Decidir (ex-ante)")

    objetivo = "Rentabilidad"
    ctx = ContextoDecision(
        rol="CPS",
        categoria=categoria,
        canal=canal,
        retailer=retailer,
        objetivo=objetivo,
    )

    base_ctx_kpis = base_kpis_for_context(ctx, demo_mode=st.session_state.demo_mode)

    c1, c2, c3, c4 = st.columns([1.2, 1, 1, 1], gap="large")

    with c1:
        with st.container(border=True):
            st.markdown("**Contexto**")
            st.write(f"**Rol:** {ctx.rol}")
            st.write(f"**Categoría:** {ctx.categoria}")
            st.write(f"**Canal:** {ctx.canal}")
            st.write(f"**Retailer:** {ctx.retailer}")

            objetivo = st.selectbox("Objetivo económico", ["Rentabilidad", "Crecimiento"], index=0)
            ctx.objetivo = objetivo

            st.markdown("**Palancas (demo)**")
            price_pct = st.slider("Ajuste de precio (%)", -10.0, 10.0, 0.0, 0.5) / 100.0
            sos_pts = st.slider("Ajuste de SOS (puntos)", -5.0, 5.0, 0.0, 0.5)
            top_n = st.slider("Top-N SKUs (opcional)", 10, 200, 80, 10)

            current_levers = Levers(price_pct=price_pct, sos_pts=sos_pts, top_n=top_n)

    base_levers = Levers(price_pct=0.0, sos_pts=0.0, top_n=N_BASE)
    base_scn_kpis = compute_kpis(base_ctx_kpis, base_levers)

    (A_code, A_lv, A_k), (B_code, B_lv, B_k) = build_scenarios(base_ctx_kpis, current_levers, guardrails)

    with c2:
        kpi_card("Base", base_scn_kpis)
    with c3:
        kpi_card("A", A_k)
        st.caption("Escenario A (Rentabilidad)")
    with c4:
        kpi_card("B", B_k)
        st.caption("Escenario B (Crecimiento)")

    chart_df = pd.DataFrame(
        {
            "Escenario": ["Base", "Escenario A (Rentabilidad)", "Escenario B (Crecimiento)"],
            "Cuervo profit": [base_scn_kpis.cuervo_profit, A_k.cuervo_profit, B_k.cuervo_profit],
        }
    ).set_index("Escenario")
    st.bar_chart(chart_df)

    st.markdown("#### Elegir escenario y registrar decisión")
    chosen = st.selectbox("Escenario elegido", ["Escenario A (Rentabilidad)", "Escenario B (Crecimiento)"], index=0)
    chosen_code = "A" if chosen.startswith("Escenario A") else "B"
    chosen_levers = A_lv if chosen_code == "A" else B_lv
    chosen_expected = A_k if chosen_code == "A" else B_k

    violates = []
    if chosen_expected.risk > guardrails.risk_max:
        violates.append("Riesgo > límite")
    if (chosen_expected.retailer_profit / base_scn_kpis.retailer_profit) < (1.0 - guardrails.retailer_drop_max):
        violates.append("Retailer profit cae más que guardrail")
    if violates:
        st.warning("Escenario elegido viola guardrails: " + ", ".join(violates))

    if st.button("Registrar decisión"):
        decision_id = str(uuid.uuid4())[:8].upper()
        observed = observed_from_expected(chosen_expected, decision_id)
        rec = DecisionRecord(
            decision_id=decision_id,
            timestamp_utc=utc_now_str(),
            contexto=ctx,
            chosen_scenario=chosen_code,
            levers=chosen_levers,
            expected=chosen_expected,
            observed=observed,
            status="Decidida",
        )
        st.session_state.decisions.append(rec)
        st.toast(f"Decisión registrada: {decision_id}")
        st.session_state.mode = "Gobernar"
        st.rerun()

# =========================
# GOBERNAR
# =========================
elif mode == "Gobernar":
    st.markdown("### User Story 2 — Gobernar")

    if not st.session_state.decisions:
        st.info("No hay decisiones registradas. Ve a **Decidir** y registra una decisión.")
    else:
        ids = [d.decision_id for d in st.session_state.decisions][::-1]
        active_id = st.selectbox("Decisión activa", ids, index=0)
        decision = next(d for d in st.session_state.decisions if d.decision_id == active_id)

        with st.container(border=True):
            st.markdown(f"**Decisión {decision.decision_id}** · {decision.timestamp_utc}")
            st.write(
                f"**Escenario elegido:** {decision.chosen_scenario} | "
                f"**Objetivo:** {decision.contexto.objetivo} | "
                f"**Contexto:** {decision.contexto.categoria} · {decision.contexto.canal}/{decision.contexto.retailer}"
            )
            st.write(
                f"**Parámetros:** precio {pct(decision.levers.price_pct)} · "
                f"SOS {decision.levers.sos_pts:+.1f} pts · Top-N {decision.levers.top_n}"
            )

        exp = decision.expected
        obs = decision.observed

        df = pd.DataFrame([
            delta_row("Ventas", exp.sales, obs.sales),
            delta_row("Cuervo profit", exp.cuervo_profit, obs.cuervo_profit),
            delta_row("Retailer profit", exp.retailer_profit, obs.retailer_profit),
        ])
        df_fmt = df.copy()
        df_fmt["Esperado"] = df_fmt["Esperado"].map(mxn)
        df_fmt["Observado"] = df_fmt["Observado"].map(mxn)
        df_fmt["Δ (MXN)"] = df_fmt["Δ (MXN)"].map(mxn)
        df_fmt["Δ (%)"] = df_fmt["Δ (%)"].map(lambda x: f"{x*100:,.1f}%")
        st.markdown("#### Expected vs Observed")
        st.dataframe(df_fmt[["KPI", "Esperado", "Observado", "Δ (MXN)", "Δ (%)"]], use_container_width=True, hide_index=True)

        sales_dp = (obs.sales / exp.sales - 1.0)
        cuervo_dp = (obs.cuervo_profit / exp.cuervo_profit - 1.0)
        ret_dp = (obs.retailer_profit / exp.retailer_profit - 1.0)

        sales_drop_thr = -0.02
        profit_drop_thr = -0.02
        alerts = []
        if sales_dp < sales_drop_thr:
            alerts.append(("Ventas", "Desviación negativa", f"{sales_dp*100:,.1f}% < {sales_drop_thr*100:,.1f}%"))
        if cuervo_dp < profit_drop_thr:
            alerts.append(("Cuervo profit", "Erosión", f"{cuervo_dp*100:,.1f}% < {profit_drop_thr*100:,.1f}%"))
        if ret_dp < profit_drop_thr:
            alerts.append(("Retailer profit", "Riesgo negociable", f"{ret_dp*100:,.1f}% < {profit_drop_thr*100:,.1f}%"))
        if obs.risk > guardrails.risk_max:
            alerts.append(("Riesgo", "Exposición alta", f"{obs.risk:.2f} > {guardrails.risk_max:.2f}"))

        st.markdown("#### Alertas")
        if not alerts:
            st.success("Sin alertas relevantes bajo los umbrales actuales.")
        else:
            st.dataframe(pd.DataFrame(alerts, columns=["KPI", "Tipo", "Condición"]), use_container_width=True, hide_index=True)

        st.markdown("#### Ajustes (con evidencia)")
        related_adj = [a for a in st.session_state.adjustments if a.decision_id == decision.decision_id]
        if related_adj:
            adj_df = pd.DataFrame([asdict(a) for a in related_adj])
            st.dataframe(adj_df[["adj_id", "timestamp_utc", "reason"]], use_container_width=True, hide_index=True)
        else:
            st.caption("Aún no hay ajustes aprobados para esta decisión.")

        with st.expander("Proponer / aprobar ajuste (demo)", expanded=False):
            reason = st.text_input("Razón del ajuste", value="Corrección por desviación vs plan")
            new_price = st.slider("Nuevo ajuste de precio (%)", -10.0, 10.0, float(decision.levers.price_pct * 100), 0.5) / 100.0
            new_sos = st.slider("Nuevo ajuste SOS (puntos)", -5.0, 5.0, float(decision.levers.sos_pts), 0.5)
            new_topn = st.slider("Nuevo Top-N", 10, 200, int(decision.levers.top_n), 10)
            new_lv = Levers(price_pct=new_price, sos_pts=new_sos, top_n=new_topn)

            base_ctx = decision.contexto
            base_k = base_kpis_for_context(base_ctx, demo_mode=st.session_state.demo_mode)
            new_expected = compute_kpis(base_k, new_lv)

            st.write("**Nuevo Expected (preview):**",
                     mxn(new_expected.sales), mxn(new_expected.cuervo_profit), mxn(new_expected.retailer_profit), f"R={new_expected.risk:.2f}")

            if st.button("Aprobar ajuste"):
                adj = AdjustmentRecord(
                    adj_id=str(uuid.uuid4())[:8].upper(),
                    decision_id=decision.decision_id,
                    timestamp_utc=utc_now_str(),
                    reason=reason,
                    new_levers=new_lv,
                    new_expected=new_expected,
                )
                st.session_state.adjustments.append(adj)

                decision.levers = new_lv
                decision.expected = new_expected
                decision.observed = observed_from_expected(new_expected, decision.decision_id + adj.adj_id)
                decision.status = "Con ajuste"
                st.toast(f"Ajuste aprobado: {adj.adj_id}")
                st.rerun()

# =========================
# DEFENDER
# =========================
else:
    st.markdown("### User Story 3 — Defender")

    if not st.session_state.decisions:
        st.info("No hay decisiones registradas. Ve a **Decidir** y registra una decisión.")
    else:
        ids = [d.decision_id for d in st.session_state.decisions][::-1]
        active_id = st.selectbox("Decisión a defender", ids, index=0)
        decision = next(d for d in st.session_state.decisions if d.decision_id == active_id)

        base_ctx = decision.contexto
        base_k = base_kpis_for_context(base_ctx, demo_mode=st.session_state.demo_mode)
        base_scn = compute_kpis(base_k, Levers(price_pct=0.0, sos_pts=0.0, top_n=N_BASE))
        chosen = decision.expected

        def delta(a: float, b: float):
            d = a - b
            dp = (a / b - 1.0) if b != 0 else np.nan
            return d, dp

        d_sales, dp_sales = delta(chosen.sales, base_scn.sales)
        d_cuervo, dp_cuervo = delta(chosen.cuervo_profit, base_scn.cuervo_profit)
        d_ret, dp_ret = delta(chosen.retailer_profit, base_scn.retailer_profit)

        with st.container(border=True):
            st.markdown(f"## One-pager de defensa — Decisión {decision.decision_id}")
            st.write(f"**Contexto:** {decision.contexto.categoria} · {decision.contexto.canal}/{decision.contexto.retailer}")
            st.write(f"**Objetivo:** {decision.contexto.objetivo}")
            st.write(
                f"**Propuesta (términos):** precio {pct(decision.levers.price_pct)} · "
                f"SOS {decision.levers.sos_pts:+.1f} pts · Top-N {decision.levers.top_n}"
            )

        cL, cM, cR = st.columns(3)
        with cL:
            with st.container(border=True):
                st.markdown("**Valor para el retailer**")
                st.metric("Retailer profit", mxn(chosen.retailer_profit), f"{dp_ret*100:,.1f}% vs Base")
                st.caption(f"Δ: {mxn(d_ret)}")
        with cM:
            with st.container(border=True):
                st.markdown("**Valor para Cuervo**")
                st.metric("Cuervo profit", mxn(chosen.cuervo_profit), f"{dp_cuervo*100:,.1f}% vs Base")
                st.caption(f"Δ: {mxn(d_cuervo)}")
        with cR:
            with st.container(border=True):
                st.markdown("**Ventas (valor)**")
                st.metric("Ventas", mxn(chosen.sales), f"{dp_sales*100:,.1f}% vs Base")
                st.caption(f"Δ: {mxn(d_sales)}")

        st.markdown("#### Riesgo y condiciones operativas")
        with st.container(border=True):
            st.write(f"**Riesgo (0–1):** {chosen.risk:.2f}  (límite actual: {guardrails.risk_max:.2f})")
            conditions = []
            if chosen.risk > guardrails.risk_max:
                conditions.append("Mitigación: piloto con Top-N 40 y escalamiento por tramos.")
            if (chosen.retailer_profit / base_scn.retailer_profit) < (1.0 - guardrails.retailer_drop_max):
                conditions.append("Mitigación: ajustar propuesta para proteger economía del retailer (guardrail).")
            if not conditions:
                conditions.append("Condición: mantener seguimiento semanal y activar alertas por umbral (modo Gobernar).")
            for c in conditions:
                st.write(f"- {c}")

        st.markdown("#### Resumen para llevar al buyer (copiar a PPT)")
        summary = (
            f"Propuesta: precio {pct(decision.levers.price_pct)}, SOS {decision.levers.sos_pts:+.1f} pts, Top-N {decision.levers.top_n}. "
            f"Impacto vs Base — Retailer profit: {mxn(d_ret)} ({dp_ret*100:,.1f}%), "
            f"Cuervo profit: {mxn(d_cuervo)} ({dp_cuervo*100:,.1f}%), "
            f"Ventas: {mxn(d_sales)} ({dp_sales*100:,.1f}%). "
            f"Riesgo: {chosen.risk:.2f}."
        )
        st.code(summary, language="text")
