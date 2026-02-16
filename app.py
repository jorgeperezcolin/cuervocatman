# Decision Cockpit de Categoría (CatMan) — Streamlit Demo

Este repositorio contiene una maqueta funcional en **Streamlit** del **Decision Cockpit de Categoría**, diseñada para demostrar un flujo completo de Category Management orientado a decisiones:

**Decidir (ex-ante) → Gobernar (ejecución) → Defender (retailer)**

La maqueta **no busca “precisión analítica”** con datos reales. Busca demostrar **consistencia decisional**, trazabilidad y un paquete cuantificado para negociación.

---

## ¿Qué demuestra la maqueta?

### 1) Decidir (ex-ante)
- Comparación simultánea de **Base vs Escenario A vs Escenario B**
- Palancas de demo:
  - **Ajuste de precio (%)**
  - **Ajuste de SOS (puntos)**
  - **Top-N SKUs (scope operable)**
- KPIs core (inmutables):
  - **Ventas (MXN)**
  - **Cuervo profit (MXN)**
  - **Retailer profit (MXN)**
  - **Riesgo (0–1)**
- Selección y **registro de decisión** (DecisionRecord)

### 2) Gobernar (ejecución)
- Expected vs Observed (demo) con **Δ MXN / Δ %**
- **Alertas por umbral** (no por opinión)
- Historial y **ajustes** (demo) con evidencia y trazabilidad

### 3) Defender (retailer)
- One-pager con:
  - Propuesta (términos): precio / SOS / Top-N
  - Impacto para retailer (delta vs Base)
  - Impacto para Cuervo (delta vs Base)
  - Riesgo y condiciones operativas (guardrails)
- Bloque “listo para PPT” para conversación con buyer

---

## Arquitectura (alto nivel)
- **Front-end**: Streamlit (single-page app con selector de modo)
- **Motor demo**: funciones determinísticas de simulación (palancas → KPIs)
- **Persistencia demo**: `st.session_state` (decisiones y ajustes durante la sesión)

> Nota: la persistencia está limitada a la sesión del navegador; no hay base de datos en esta maqueta.

---

## Requisitos
- Python 3.10+
- Dependencias:
  - streamlit
  - pandas
  - numpy

Instalación:
```bash
pip install -r requirements.txt
