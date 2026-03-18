from __future__ import annotations

from dataclasses import dataclass
import html
import math
from pathlib import Path
import re
import textwrap
import unicodedata

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


DATA_DIR = Path("data")
CSV_GLOB = "*.csv"

RISK_COLUMNS = [
    "relacionamento",
    "satisfacao",
    "financeiro",
    "operacional",
    "engajamento",
    "concorrencia",
]

RISK_LABELS = {
    "relacionamento": "Relacionamento",
    "satisfacao": "Satisfacao",
    "financeiro": "Financeiro",
    "operacional": "Operacional",
    "engajamento": "Engajamento",
    "concorrencia": "Concorrencia",
}

SILENT_SIGNALS = [
    "Cliente com distrato marcado",
    "Carteira com longa distancia operacional",
    "Baixo volume de equipamentos ativos",
    "Concentracao em poucas fazendas",
    "Analistas com alta dispersao geografica",
    "Contas sem Cb e Clima cadastrados",
]


@dataclass(frozen=True)
class DatasetSummary:
    raw_rows: int
    clients: int
    analysts: int
    managers: int


STATUS_COLORS = {
    "Seguro": "#2F6B55",
    "Atencao": "#C38A2D",
    "Alto Risco": "#B64545",
}

ACTION_PLAN_COLUMNS = [
    "Cliente",
    "Ponto de atencao",
    "Acao",
    "Responsavel",
    "Prazo",
    "Status",
    "Atualizacao",
    "Proximo passo",
]

ACTION_STATUS_GROUPS = {
    "nao_iniciado": {"Nao iniciado", "Pendente", "Backlog"},
    "em_andamento": {"Em andamento", "Em execucao", "Em execução", "Acompanhando"},
    "concluido": {"Concluido", "Concluído", "Finalizado", "Resolvido"},
}

CHART_PALETTE = {
    "teal": "#1F5F5B",
    "teal_soft": "#DCEBE3",
    "sand": "#ECE4D6",
    "amber": "#C38A2D",
    "amber_soft": "#F5EAD2",
    "red": "#B64545",
    "red_soft": "#F5DDDD",
    "green": "#2F6B55",
    "green_soft": "#DCEBE3",
    "ink": "#1D3431",
    "muted": "#62706C",
    "grid": "#E6E0D4",
}


def find_csv_file() -> Path:
    files = sorted(DATA_DIR.glob(CSV_GLOB))
    if not files:
        raise FileNotFoundError("Nenhum CSV encontrado na pasta data.")
    return files[0]


def normalize_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_")


def to_number(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
        .replace({"": None, "nan": None, "None": None})
        .pipe(pd.to_numeric, errors="coerce")
        .fillna(0)
    )


def first_non_empty(series: pd.Series) -> str:
    valid = series.replace("", pd.NA).dropna()
    return valid.iloc[0] if not valid.empty else ""


def clamp_score(series: pd.Series) -> pd.Series:
    return series.round().clip(lower=0, upper=5).astype(int)


def invert_score(series: pd.Series) -> pd.Series:
    return 5 - clamp_score(series)


def build_signal_text(row: pd.Series) -> str:
    signals: list[str] = []
    if row["distrato_count"] > 0:
        signals.append("Distrato na carteira")
    if row["distancia_media_km"] >= 250:
        signals.append("Alta distancia media")
    if row["equip_cb"] + row["equip_clima"] == 0:
        signals.append("Sem equipamentos ativos")
    elif row["equip_cb"] + row["equip_clima"] < 8:
        signals.append("Baixo volume de equipamentos")
    if row["fazendas"] <= 1:
        signals.append("Pouca capilaridade")
    if row["cidades"] > 1:
        signals.append("Atendimento disperso")
    return ", ".join(signals) if signals else "Sem sinal critico"


@st.cache_data(show_spinner=False)
def load_operational_data() -> tuple[pd.DataFrame, DatasetSummary, Path]:
    csv_path = find_csv_file()
    raw = pd.read_csv(csv_path, sep=";", header=None, encoding="utf-8-sig")

    header_idx = raw.index[raw.iloc[:, 1].astype(str).str.strip().eq("Gestor")]
    if header_idx.empty:
        raise ValueError("Nao foi possivel localizar o cabecalho real do CSV.")

    header_row = header_idx[0]
    columns = raw.iloc[header_row, 1:].tolist()
    data = raw.iloc[header_row + 1 :, 1:].copy()
    data.columns = columns
    data = data.dropna(how="all")
    data = data.apply(lambda col: col.astype(str).str.strip())
    data = data.replace({"nan": "", "None": ""})
    data = data.rename(columns={col: normalize_label(col) for col in data.columns})

    required_map = {
        "gestor": "gestor",
        "analista": "analista",
        "cliente": "cliente",
        "fazenda": "fazenda",
        "cidade": "cidade",
        "area_ha": "area_ha",
        "quantidade_de_equipamentos_cb_s": "equip_cb",
        "quantidade_de_equipamentos_clima": "equip_clima",
        "distrato_sim_nao": "distrato",
        "distancia_km_obs_da_base_do_analista_a_fazenda_ida_volta": "distancia_km",
    }
    missing = [column for column in required_map if column not in data.columns]
    if missing:
        raise ValueError(f"Colunas esperadas nao encontradas no CSV: {', '.join(missing)}")

    data = data.rename(columns=required_map)

    for numeric_col in ["area_ha", "equip_cb", "equip_clima", "distancia_km"]:
        data[numeric_col] = to_number(data[numeric_col])

    for text_col in ["gestor", "analista", "cliente", "fazenda", "cidade", "distrato"]:
        data[text_col] = data[text_col].astype(str).str.strip()

    data = data[data["cliente"].ne("")].copy()

    summary = DatasetSummary(
        raw_rows=len(data),
        clients=data["cliente"].replace("", pd.NA).dropna().nunique(),
        analysts=data["analista"].replace("", pd.NA).dropna().nunique(),
        managers=data["gestor"].replace("", pd.NA).dropna().nunique(),
    )
    return data, summary, csv_path


@st.cache_data(show_spinner=False)
def build_client_matrix(df: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        df.groupby("cliente", dropna=False)
        .agg(
            gestor=("gestor", first_non_empty),
            analista=("analista", first_non_empty),
            fazendas=("fazenda", lambda s: s.replace("", pd.NA).dropna().nunique()),
            cidades=("cidade", lambda s: s.replace("", pd.NA).dropna().nunique()),
            area_ha=("area_ha", "sum"),
            equip_cb=("equip_cb", "sum"),
            equip_clima=("equip_clima", "sum"),
            distancia_media_km=("distancia_km", "mean"),
            distancia_max_km=("distancia_km", "max"),
            ocorrencias=("cliente", "size"),
            distrato_count=("distrato", lambda s: s.str.upper().eq("SIM").sum()),
            distrato_flag=("distrato", lambda s: "SIM" if s.str.upper().eq("SIM").any() else "NAO"),
        )
        .reset_index()
    )

    total_equip = grouped["equip_cb"] + grouped["equip_clima"]
    grouped["relacionamento"] = invert_score(
        grouped["distancia_media_km"].div(120).fillna(0) + grouped["cidades"].sub(1).clip(lower=0)
    )
    grouped["satisfacao"] = invert_score(
        grouped["distrato_count"].mul(3)
        + grouped["distancia_max_km"].div(180).fillna(0)
        + total_equip.eq(0).mul(2)
    )
    grouped["financeiro"] = invert_score(
        grouped["distrato_count"].mul(4)
        + grouped["area_ha"].eq(0).mul(1)
        + total_equip.lt(5).mul(1)
    )
    grouped["operacional"] = invert_score(
        grouped["distancia_media_km"].div(140).fillna(0)
        + grouped["fazendas"].sub(1).clip(lower=0).div(2)
        + grouped["cidades"].sub(1).clip(lower=0).div(2)
    )
    grouped["engajamento"] = invert_score(
        grouped["ocorrencias"].eq(1).mul(2)
        + total_equip.lt(8).mul(2)
        + grouped["fazendas"].eq(1).mul(1)
    )
    grouped["concorrencia"] = invert_score(
        grouped["distrato_count"].mul(3)
        + grouped["distancia_max_km"].gt(250).mul(1)
        + total_equip.lt(10).mul(1)
    )

    grouped["pontuacao"] = grouped[RISK_COLUMNS].sum(axis=1)
    grouped["classificacao"] = pd.cut(
        grouped["pontuacao"],
        bins=[-1, 10, 18, float("inf")],
        labels=["Alto Risco", "Atencao", "Seguro"],
    ).astype(str)
    grouped["sinais"] = grouped.apply(build_signal_text, axis=1)

    return grouped.sort_values(["pontuacao", "cliente"], ascending=[True, True]).reset_index(drop=True)


def seed_action_plan(client_df: pd.DataFrame) -> pd.DataFrame:
    attention_clients = client_df[client_df["classificacao"].isin(["Alto Risco", "Atencao"])].copy()
    if attention_clients.empty:
        return pd.DataFrame(columns=ACTION_PLAN_COLUMNS)

    rows = []
    for _, row in attention_clients.sort_values(["pontuacao", "cliente"], ascending=[True, True]).iterrows():
        rows.append(
            {
                "Cliente": row["cliente"],
                "Ponto de atencao": row["classificacao"],
                "Acao": "Validar percepcao do cliente e plano de retencao com gestor e analista.",
                "Responsavel": row["gestor"] or row["analista"] or "Definir",
                "Prazo": "",
                "Status": "Nao iniciado",
                "Atualizacao": "",
                "Proximo passo": "Agendar alinhamento com coordenador e analista.",
            }
        )
    return pd.DataFrame(rows, columns=ACTION_PLAN_COLUMNS)


def seed_gimb_checklist() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Item": "Ritual de acompanhamento da carteira", "Status": "OK", "Observacoes": ""},
            {"Item": "Plano de acao para clientes em risco", "Status": "Pendente", "Observacoes": ""},
            {"Item": "Revisao de contas com distrato", "Status": "Pendente", "Observacoes": ""},
            {"Item": "Cobertura regional dos analistas", "Status": "Em andamento", "Observacoes": ""},
        ]
    )


def normalize_action_plan_df(action_plan: pd.DataFrame) -> pd.DataFrame:
    normalized = action_plan.copy() if action_plan is not None else pd.DataFrame()
    for column in ACTION_PLAN_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = ""

    normalized = normalized[ACTION_PLAN_COLUMNS].fillna("")
    for column in ACTION_PLAN_COLUMNS:
        normalized[column] = normalized[column].astype(str).str.strip()
    return normalized


def sync_action_plan_with_clients(action_plan: pd.DataFrame, client_df: pd.DataFrame) -> pd.DataFrame:
    normalized = normalize_action_plan_df(action_plan)
    attention_clients = client_df[client_df["classificacao"].isin(["Alto Risco", "Atencao"])].copy()
    if attention_clients.empty:
        return normalized

    existing_clients = set(normalized["Cliente"].astype(str).str.strip())
    rows_to_add: list[dict[str, str]] = []
    for _, row in attention_clients.sort_values(["pontuacao", "cliente"], ascending=[True, True]).iterrows():
        client_name = str(row["cliente"]).strip()
        if client_name in existing_clients:
            continue
        rows_to_add.append(
            {
                "Cliente": client_name,
                "Ponto de atencao": str(row["classificacao"]).strip(),
                "Acao": "Validar percepcao do cliente e plano de retencao com gestor e analista.",
                "Responsavel": row["gestor"] or row["analista"] or "Definir",
                "Prazo": "",
                "Status": "Nao iniciado",
                "Atualizacao": "",
                "Proximo passo": "Agendar alinhamento com coordenador e analista.",
            }
        )

    if not rows_to_add:
        return normalized

    merged = pd.concat([normalized, pd.DataFrame(rows_to_add, columns=ACTION_PLAN_COLUMNS)], ignore_index=True)
    return normalize_action_plan_df(merged)


def ensure_action_plan_state(client_df: pd.DataFrame) -> pd.DataFrame:
    if "action_plan" not in st.session_state:
        st.session_state["action_plan"] = seed_action_plan(client_df)
    st.session_state["action_plan"] = sync_action_plan_with_clients(st.session_state["action_plan"], client_df)
    return st.session_state["action_plan"]


def action_status_bucket(value: str) -> str:
    status = str(value).strip()
    if status in ACTION_STATUS_GROUPS["concluido"]:
        return "concluido"
    if status in ACTION_STATUS_GROUPS["em_andamento"]:
        return "em_andamento"
    return "nao_iniciado"


def parse_action_deadlines(action_plan: pd.DataFrame) -> pd.Series:
    prazo = action_plan["Prazo"].astype(str).str.strip()
    parsed = pd.to_datetime(prazo, dayfirst=True, errors="coerce")
    parsed = parsed.fillna(pd.to_datetime(prazo, format="%Y-%m-%d", errors="coerce"))
    return parsed


def build_action_plan_monitor(action_plan: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    normalized = normalize_action_plan_df(action_plan)
    if normalized.empty:
        return normalized, {
            "total": 0,
            "em_andamento": 0,
            "concluido": 0,
            "atrasado": 0,
            "sem_responsavel": 0,
            "vence_semana": 0,
        }

    monitor = normalized.copy()
    monitor["bucket"] = monitor["Status"].apply(action_status_bucket)
    monitor["prazo_dt"] = parse_action_deadlines(monitor)
    today = pd.Timestamp.today().normalize()
    monitor["atrasado"] = monitor["prazo_dt"].lt(today) & monitor["bucket"].ne("concluido")
    monitor["vence_semana"] = (
        monitor["prazo_dt"].ge(today) & monitor["prazo_dt"].le(today + pd.Timedelta(days=7))
    ) & monitor["bucket"].ne("concluido")
    monitor["sem_responsavel"] = monitor["Responsavel"].eq("")
    monitor["sem_atualizacao"] = monitor["Atualizacao"].eq("")

    summary = {
        "total": int(len(monitor)),
        "em_andamento": int(monitor["bucket"].eq("em_andamento").sum()),
        "concluido": int(monitor["bucket"].eq("concluido").sum()),
        "atrasado": int(monitor["atrasado"].sum()),
        "sem_responsavel": int(monitor["sem_responsavel"].sum()),
        "vence_semana": int(monitor["vence_semana"].sum()),
    }
    return monitor, summary


def summarize_client_action_state(client_actions: pd.DataFrame) -> dict[str, str | int | bool]:
    if client_actions.empty:
        return {
            "total_acoes": 0,
            "andamento": 0,
            "concluidas": 0,
            "atrasadas": 0,
            "sem_atualizacao": 0,
            "progresso_pct": 0.0,
            "ultima_atualizacao": "Sem atualizacao",
            "status_label": "Sem plano",
            "expanded": False,
            "priority_rank": 3,
        }

    total_acoes = int(len(client_actions))
    andamento = int(client_actions["bucket"].eq("em_andamento").sum())
    concluidas = int(client_actions["bucket"].eq("concluido").sum())
    atrasadas = int(client_actions["atrasado"].sum())
    sem_atualizacao = int(client_actions["sem_atualizacao"].sum())
    progresso_pct = (concluidas / total_acoes) * 100 if total_acoes else 0.0
    latest_updates = [
        value.strip()
        for value in client_actions["Atualizacao"].astype(str).tolist()
        if value.strip()
    ]
    ultima_atualizacao = latest_updates[0] if latest_updates else "Sem atualizacao"

    if atrasadas > 0:
        status_label = "Atrasado"
        expanded = True
        priority_rank = 0
    elif andamento > 0:
        status_label = "Em andamento"
        expanded = True
        priority_rank = 1
    elif concluidas == len(client_actions):
        status_label = "Concluido"
        expanded = False
        priority_rank = 3
    else:
        status_label = "Sem avancos"
        expanded = False
        priority_rank = 2

    return {
        "total_acoes": total_acoes,
        "andamento": andamento,
        "concluidas": concluidas,
        "atrasadas": atrasadas,
        "sem_atualizacao": sem_atualizacao,
        "progresso_pct": progresso_pct,
        "ultima_atualizacao": ultima_atualizacao,
        "status_label": status_label,
        "expanded": expanded,
        "priority_rank": priority_rank,
    }


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.header("Filtros")
    gestores = sorted(v for v in df["gestor"].dropna().unique() if v)
    analistas = sorted(v for v in df["analista"].dropna().unique() if v)
    cidades = sorted(v for v in df["cidade"].dropna().unique() if v)

    selected_gestores = st.sidebar.multiselect("Gestor", gestores)
    selected_analistas = st.sidebar.multiselect("Analista", analistas)
    selected_cidades = st.sidebar.multiselect("Cidade", cidades)
    only_distrato = st.sidebar.checkbox("Mostrar apenas contas com distrato")

    filtered = df.copy()
    if selected_gestores:
        filtered = filtered[filtered["gestor"].isin(selected_gestores)]
    if selected_analistas:
        filtered = filtered[filtered["analista"].isin(selected_analistas)]
    if selected_cidades:
        filtered = filtered[filtered["cidade"].isin(selected_cidades)]
    if only_distrato:
        filtered = filtered[filtered["distrato"].str.upper().eq("SIM")]
    return filtered


def format_int(value: float | int) -> str:
    return f"{int(value):,}".replace(",", ".")


def format_float(value: float, digits: int = 1) -> str:
    formatted = f"{value:,.{digits}f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def render_html_block(content: str) -> None:
    st.markdown(textwrap.dedent(content).strip(), unsafe_allow_html=True)


def _polar_to_cartesian(cx: float, cy: float, radius: float, angle_deg: float) -> tuple[float, float]:
    angle_rad = math.radians(angle_deg - 90)
    return cx + radius * math.cos(angle_rad), cy + radius * math.sin(angle_rad)


def _build_donut_arc_path(
    cx: float,
    cy: float,
    radius: float,
    start_angle: float,
    end_angle: float,
) -> str:
    start_x, start_y = _polar_to_cartesian(cx, cy, radius, start_angle)
    end_x, end_y = _polar_to_cartesian(cx, cy, radius, end_angle)
    large_arc = 1 if end_angle - start_angle > 180 else 0
    return f"M {start_x:.2f} {start_y:.2f} A {radius:.2f} {radius:.2f} 0 {large_arc} 1 {end_x:.2f} {end_y:.2f}"


def render_portfolio_donut(total: int, risk: int, attention: int, safe: int) -> None:
    values = [
        ("Alto Risco", risk, STATUS_COLORS["Alto Risco"]),
        ("Atencao", attention, STATUS_COLORS["Atencao"]),
        ("Seguro", safe, STATUS_COLORS["Seguro"]),
    ]
    total_base = max(total, 1)
    angle = 0.0
    gap = 6.0
    paths: list[str] = []
    for _, value, color in values:
        if value <= 0:
            continue
        sweep = 360 * (value / total_base)
        start_angle = angle + gap / 2
        end_angle = angle + sweep - gap / 2
        if end_angle > start_angle:
            path = _build_donut_arc_path(130, 130, 78, start_angle, end_angle)
            paths.append(
                f'<path d="{path}" stroke="{color}" stroke-width="30" fill="none" stroke-linecap="round"></path>'
            )
        angle += sweep

    legend_html = "".join(
        f"""
        <span class="panorama-legend-item">
            <span class="panorama-legend-dot" style="background:{color};"></span>
            {html.escape(label)} ({value})
        </span>
        """
        for label, value, color in values
    )
    donut_html = f"""
    <div class="portfolio-donut-shell">
        <svg viewBox="0 0 260 260" class="portfolio-donut-svg" aria-hidden="true">
            {''.join(paths)}
            <text x="130" y="126" text-anchor="middle" class="portfolio-donut-value">{total}</text>
            <text x="130" y="151" text-anchor="middle" class="portfolio-donut-label">clientes</text>
        </svg>
        <div class="panorama-legend">
            {legend_html}
        </div>
    </div>
    <style>
        :root {{
            --text: #1d3431;
            --muted: #62706c;
        }}
        body {{
            margin: 0;
            background: transparent;
            font-family: "Segoe UI", sans-serif;
        }}
        .portfolio-donut-shell {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 10px;
            padding-top: 8px;
        }}
        .portfolio-donut-svg {{
            width: 250px;
            height: 250px;
            overflow: visible;
            display: block;
            margin: 0 auto;
        }}
        .portfolio-donut-value {{
            fill: var(--text);
            font-size: 24px;
            font-weight: 700;
        }}
        .portfolio-donut-label {{
            fill: var(--muted);
            font-size: 14px;
            font-weight: 500;
        }}
        .panorama-legend {{
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 14px;
            width: 100%;
            padding-top: 8px;
            border-top: 1px solid rgba(29, 52, 49, 0.08);
            color: var(--muted);
            font-size: 14px;
        }}
        .panorama-legend-item {{
            display: inline-flex;
            align-items: center;
            gap: 7px;
            white-space: nowrap;
        }}
        .panorama-legend-dot {{
            width: 11px;
            height: 11px;
            border-radius: 999px;
            display: inline-block;
        }}
    </style>
    """
    components.html(donut_html, height=330, scrolling=False)


def style_chart(chart: alt.Chart | alt.LayerChart | alt.FacetChart) -> alt.Chart | alt.LayerChart | alt.FacetChart:
    return (
        chart.configure_view(strokeOpacity=0)
        .configure_axis(
            gridColor=CHART_PALETTE["grid"],
            domainColor=CHART_PALETTE["grid"],
            tickColor=CHART_PALETTE["grid"],
            labelColor=CHART_PALETTE["muted"],
            titleColor=CHART_PALETTE["muted"],
            labelFontSize=12,
            titleFontSize=12,
            labelPadding=8,
            titlePadding=10,
        )
        .configure_header(
            titleColor=CHART_PALETTE["ink"],
            labelColor=CHART_PALETTE["muted"],
            titleFontSize=13,
            labelFontSize=12,
        )
        .configure_legend(
            titleColor=CHART_PALETTE["muted"],
            labelColor=CHART_PALETTE["muted"],
            symbolType="circle",
            padding=6,
        )
    )


def inject_theme() -> None:
    st.markdown(
        """
        <style>
        :root {
            --bg: #f4f1ea;
            --surface: rgba(255, 255, 255, 0.80);
            --surface-strong: #ffffff;
            --line: rgba(29, 52, 49, 0.10);
            --text: #1d3431;
            --muted: #62706c;
            --teal: #1f5f5b;
            --teal-soft: #dbe9e5;
            --sand: #ece4d6;
            --amber: #c38a2d;
            --amber-soft: #f5ead2;
            --red: #b64545;
            --red-soft: #f5dddd;
            --green: #2f6b55;
            --green-soft: #dcebe3;
            --shadow: 0 18px 48px rgba(23, 35, 33, 0.08);
            --radius-xl: 28px;
            --radius-lg: 22px;
            --radius-md: 16px;
        }
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(222, 232, 227, 0.95), transparent 28%),
                radial-gradient(circle at top right, rgba(245, 234, 210, 0.75), transparent 24%),
                linear-gradient(180deg, #f7f4ee 0%, #f2eee6 100%);
            color: var(--text);
        }
        [data-testid="stHeader"] {
            background: rgba(255, 255, 255, 0);
        }
        [data-testid="stSidebar"] {
            background: rgba(255, 255, 255, 0.72);
            border-right: 1px solid var(--line);
        }
        [data-testid="stSidebar"] > div:first-child {
            padding-top: 1.25rem;
        }
        .block-container {
            padding-top: 1.6rem;
            padding-bottom: 2.5rem;
            max-width: 1380px;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border: 0;
            box-shadow: none;
            background: transparent;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.hero-card),
        [data-testid="stTabs"] [data-baseweb="tab-panel"] {
            border: 0 !important;
            box-shadow: none !important;
            background: transparent !important;
        }
        h1, h2, h3 {
            color: var(--text);
            letter-spacing: -0.02em;
        }
        p, li, div, label {
            color: var(--text);
        }
        .dashboard-shell {
            display: grid;
            gap: 1rem;
        }
        .panel-card, .metric-card, .attention-card, .signal-card {
            background: var(--surface);
            backdrop-filter: blur(14px);
            border: 1px solid var(--line);
            box-shadow: var(--shadow);
        }
        .hero-card {
            padding: 1.4rem 1.5rem;
            border-radius: var(--radius-xl);
            background:
                linear-gradient(135deg, rgba(31, 95, 91, 0.96), rgba(24, 50, 47, 0.96)),
                linear-gradient(120deg, rgba(255, 255, 255, 0.1), transparent);
            color: #f5f7f4;
            border: none;
            box-shadow: 0 18px 42px rgba(23, 35, 33, 0.10);
        }
        .hero-grid {
            display: grid;
            grid-template-columns: minmax(0, 1.7fr) minmax(260px, 0.9fr);
            gap: 1rem;
            align-items: end;
        }
        .hero-kicker {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            padding: 0.35rem 0.7rem;
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.12);
            color: #e9f0ed;
            font-size: 0.8rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        .hero-title {
            margin: 0.9rem 0 0.35rem 0;
            font-size: 2rem;
            line-height: 1.05;
            color: #ffffff;
        }
        .hero-subtitle {
            margin: 0;
            max-width: 700px;
            color: rgba(255, 255, 255, 0.82);
            font-size: 0.98rem;
            line-height: 1.45;
        }
        .hero-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 0.65rem;
            margin-top: 1rem;
        }
        .hero-chip {
            padding: 0.48rem 0.78rem;
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.10);
            color: #f7f9f7;
            font-size: 0.88rem;
        }
        .hero-side {
            background: rgba(255, 255, 255, 0.08);
            border-radius: 22px;
            padding: 1rem 1.05rem;
            border: none;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.10);
        }
        .hero-side-label {
            color: rgba(255, 255, 255, 0.68);
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        .hero-side-value {
            margin-top: 0.35rem;
            color: #ffffff;
            font-size: 2rem;
            font-weight: 700;
            line-height: 1;
        }
        .hero-side-text {
            margin-top: 0.55rem;
            color: rgba(255, 255, 255, 0.76);
            font-size: 0.92rem;
            line-height: 1.4;
        }
        .section-label {
            margin: 0.25rem 0 0.75rem 0;
            color: var(--muted);
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        .section-title {
            margin: 0 0 0.35rem 0;
            font-size: 1.22rem;
            font-weight: 700;
            line-height: 1.15;
            color: var(--text);
        }
        .section-subtitle {
            margin: 0 0 1rem 0;
            color: var(--muted);
            font-size: 0.92rem;
            line-height: 1.45;
        }
        .section-shell {
            margin-top: 1.25rem;
        }
        .section-shell:first-of-type {
            margin-top: 0.9rem;
        }
        .panorama-shell {
            margin-top: 0;
        }
        .panorama-header {
            padding: 0 0.15rem 0.9rem 0.15rem;
            margin-bottom: 0.9rem;
        }
        .panorama-metrics {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.95rem;
        }
        .panorama-metric {
            min-height: 156px;
            padding: 1rem 1rem 0.95rem 1rem;
            border-radius: 22px;
            border: 1px solid rgba(29, 52, 49, 0.08);
            border-left: 4px solid rgba(29, 52, 49, 0.16);
            background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 244, 237, 0.9));
            box-shadow:
                0 10px 24px rgba(23, 35, 33, 0.05),
                inset 0 1px 0 rgba(255, 255, 255, 0.7);
            height: 100%;
            display: flex;
            flex-direction: column;
        }
        .panorama-metric.critical { border-left-color: var(--red); }
        .panorama-metric.warning { border-left-color: var(--amber); }
        .panorama-metric.safe { border-left-color: var(--green); }
        .panorama-metric.neutral { border-left-color: rgba(29, 52, 49, 0.18); }
        [data-testid="stVegaLiteChart"] {
            display: flex;
            justify-content: center;
        }
        .panorama-chart-card {
            width: 100%;
            min-height: 318px;
            padding: 1.15rem 1.15rem 1rem 1.15rem;
            border-radius: 26px;
            border: 1px solid rgba(29, 52, 49, 0.08);
            background: linear-gradient(180deg, rgba(255, 255, 255, 0.97), rgba(247, 243, 236, 0.92));
            box-shadow:
                0 12px 28px rgba(23, 35, 33, 0.055),
                inset 0 1px 0 rgba(255, 255, 255, 0.74);
            display: flex;
            flex-direction: column;
        }
        .panorama-chart-wrap {
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 0.5rem 0 0.25rem 0;
        }
        .panorama-donut {
            width: 230px;
            height: 230px;
            border-radius: 50%;
            position: relative;
            box-shadow: inset 0 0 0 1px rgba(29, 52, 49, 0.05);
        }
        .panorama-donut::before {
            content: "";
            position: absolute;
            inset: 34px;
            border-radius: 50%;
            background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(247, 243, 236, 0.98));
            box-shadow: inset 0 0 0 1px rgba(29, 52, 49, 0.05);
        }
        .panorama-donut-center {
            position: absolute;
            inset: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-direction: column;
            text-align: center;
            z-index: 1;
        }
        .panorama-donut-value {
            font-size: 2rem;
            font-weight: 700;
            line-height: 1;
            color: var(--text);
        }
        .panorama-donut-label {
            margin-top: 0.2rem;
            font-size: 0.9rem;
            color: var(--muted);
        }
        .panorama-legend {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 0.85rem;
            margin-top: 0.45rem;
            padding-top: 0.7rem;
            border-top: 1px solid rgba(29, 52, 49, 0.07);
        }
        .panorama-legend-item {
            display: inline-flex;
            align-items: center;
            gap: 0.42rem;
            font-size: 0.88rem;
            color: var(--muted);
        }
        .panorama-legend-dot {
            width: 10px;
            height: 10px;
            border-radius: 999px;
        }
        @media (max-width: 1180px) {
            .panorama-chart-card {
                min-height: auto;
            }
        }
        @media (max-width: 920px) {
            .panorama-metrics {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        @media (max-width: 640px) {
            .panorama-shell {
                padding: 1rem;
                border-radius: 26px;
            }
            .panorama-metrics {
                grid-template-columns: 1fr;
            }
            .panorama-donut {
                width: 200px;
                height: 200px;
            }
            .panorama-donut::before {
                inset: 30px;
            }
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.panorama-shell) {
            position: relative;
            margin: 1.1rem 0 1.45rem 0;
            padding: 1.55rem 1.35rem 1.35rem 1.35rem;
            border-radius: 36px;
            border: 1px solid rgba(29, 52, 49, 0.10);
            background: linear-gradient(180deg, rgba(255, 255, 255, 0.82), rgba(247, 242, 234, 0.94));
            box-shadow: 0 18px 44px rgba(23, 35, 33, 0.05);
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.panorama-shell) .section-shell {
            margin-top: 0;
            padding: 0 0.2rem 0.5rem 0.2rem;
            margin-bottom: 1rem;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.panorama-shell) .stColumn {
            position: relative;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.panorama-shell) [data-testid="column"] {
            display: flex;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.panorama-shell) [data-testid="column"] > div {
            width: 100%;
            height: 100%;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.panorama-shell) [data-testid="stHorizontalBlock"] {
            align-items: stretch;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.signals-shell),
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.attention-shell) {
            position: relative;
            margin: 1.1rem 0 1.45rem 0;
            padding: 1.35rem 1.25rem 1.25rem 1.25rem;
            border-radius: 32px;
            border: 1px solid rgba(29, 52, 49, 0.09);
            background: linear-gradient(180deg, rgba(255, 255, 255, 0.8), rgba(247, 242, 234, 0.92));
            box-shadow: 0 16px 38px rgba(23, 35, 33, 0.045);
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.signals-shell) .section-shell,
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.attention-shell) .section-shell {
            margin-top: 0;
            padding: 0 0.15rem 0.45rem 0.15rem;
            margin-bottom: 0.85rem;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.metric-card) {
            height: 100%;
        }
        .metric-card {
            padding: 1.02rem 1rem 0.98rem 1rem;
            border-radius: var(--radius-lg);
            min-height: 178px;
            height: 178px;
            box-shadow:
                0 12px 26px rgba(23, 35, 33, 0.05),
                0 1px 0 rgba(255, 255, 255, 0.72) inset;
            backdrop-filter: none;
            background: linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(248, 244, 237, 0.88));
            border: 1px solid rgba(29, 52, 49, 0.08);
            border-left: 4px solid transparent;
            height: 100%;
            display: flex;
            flex-direction: column;
            justify-content: flex-start;
        }
        .metric-label {
            color: var(--muted);
            font-size: 0.82rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            line-height: 1.45;
            min-height: 2.9em;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
        .metric-value {
            margin-top: 0.65rem;
            font-size: 1.85rem;
            font-weight: 700;
            line-height: 1;
            min-height: 1.2em;
        }
        .metric-note {
            margin-top: auto;
            padding-top: 0.65rem;
            color: var(--muted);
            font-size: 0.9rem;
            line-height: 1.35;
            min-height: 4.05em;
            display: -webkit-box;
            -webkit-line-clamp: 3;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
        .metric-critical {
            border-left-color: var(--red);
        }
        .metric-warning {
            border-left-color: var(--amber);
        }
        .metric-safe {
            border-left-color: var(--green);
        }
        .metric-neutral {
            border-left-color: rgba(29, 52, 49, 0.18);
        }
        .metric-grid-gap {
            height: 0.35rem;
        }
        .panel-card {
            padding: 1.2rem 1.2rem 1rem 1.2rem;
            border-radius: var(--radius-xl);
        }
        .panel-card.soft {
            background: rgba(255, 255, 255, 0.88);
            box-shadow: 0 12px 28px rgba(23, 35, 33, 0.05);
        }
        .stack-panel {
            display: flex;
            flex-direction: column;
            gap: 0.8rem;
            height: 100%;
        }
        .panel-head {
            min-height: 108px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .panel-title {
            margin: 0;
            font-size: 0.98rem;
            font-weight: 700;
            line-height: 1.2;
        }
        .panel-subtitle {
            margin: 0.55rem 0 0 0;
            color: var(--muted);
            font-size: 0.88rem;
            line-height: 1.4;
        }
        .attention-card {
            padding: 0.95rem 1rem 0.9rem 1rem;
            border-radius: var(--radius-lg);
            background: rgba(255, 255, 255, 0.92);
            box-shadow: none;
        }
        .attention-card.alert {
            border-left: 5px solid var(--red);
        }
        .attention-card.warning {
            border-left: 5px solid var(--amber);
        }
        .attention-card.safe {
            border-left: 5px solid var(--green);
        }
        .attention-header {
            display: flex;
            justify-content: space-between;
            gap: 0.75rem;
            align-items: flex-start;
        }
        .attention-client {
            font-size: 1rem;
            font-weight: 700;
        }
        .attention-score {
            white-space: nowrap;
            font-size: 0.9rem;
            padding: 0.35rem 0.6rem;
            border-radius: 999px;
            background: rgba(29, 52, 49, 0.06);
        }
        .attention-meta, .attention-signals {
            margin-top: 0.55rem;
            color: var(--muted);
            font-size: 0.88rem;
            line-height: 1.45;
        }
        .signal-card {
            padding: 0.9rem 0.95rem 0.85rem 0.95rem;
            border-radius: var(--radius-md);
            background: rgba(255, 255, 255, 0.92);
            box-shadow: none;
        }
        .signal-title {
            margin: 0;
            font-weight: 700;
            font-size: 0.95rem;
        }
        .signal-count {
            margin-top: 0.3rem;
            color: var(--muted);
            font-size: 0.84rem;
        }
        .signal-high { border-left: 4px solid var(--red); }
        .signal-warn { border-left: 4px solid var(--amber); }
        .signal-safe { border-left: 4px solid var(--green); }
        .clean-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 0.55rem;
            font-size: 0.88rem;
            overflow: hidden;
            border-radius: 14px;
            border: 1px solid var(--line);
            background: rgba(255, 255, 255, 0.92);
        }
        .clean-table th,
        .clean-table td {
            padding: 0.72rem 0.78rem;
            border-bottom: 1px solid rgba(29, 52, 49, 0.08);
            text-align: left;
            vertical-align: top;
        }
        .clean-table th {
            color: var(--muted);
            font-size: 0.76rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            background: rgba(244, 241, 234, 0.75);
        }
        .clean-table tr:last-child td {
            border-bottom: none;
        }
        .compact-list {
            margin: 0.8rem 0 0 0;
            padding-left: 1.1rem;
        }
        .compact-list li {
            margin-bottom: 0.8rem;
            color: var(--text);
            line-height: 1.45;
            padding-left: 0.2rem;
        }
        .compact-list li::marker {
            color: var(--teal);
        }
        .pill {
            display: inline-flex;
            align-items: center;
            padding: 0.24rem 0.5rem;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 600;
            white-space: nowrap;
        }
        .pill.safe {
            background: var(--green-soft);
            color: var(--green);
        }
        .pill.warn {
            background: var(--amber-soft);
            color: #8b6217;
        }
        .pill.high {
            background: var(--red-soft);
            color: var(--red);
        }
        .grid-card {
            background: linear-gradient(180deg, rgba(255, 255, 255, 0.95), rgba(247, 243, 236, 0.9));
            border: 1px solid rgba(29, 52, 49, 0.08);
            border-radius: var(--radius-xl);
            padding: 1rem 1rem 0.75rem 1rem;
            box-shadow:
                0 14px 34px rgba(23, 35, 33, 0.055),
                0 1px 0 rgba(255, 255, 255, 0.72) inset;
            height: 100%;
        }
        .grid-card.tight {
            padding: 1.05rem 1.05rem 1rem 1.05rem;
        }
        .exec-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 1.25rem;
            align-items: stretch;
        }
        .exec-column {
            display: flex;
            flex-direction: column;
            gap: 0.8rem;
        }
        .exec-panel {
            background: rgba(255, 255, 255, 0.9);
            border: 1px solid var(--line);
            border-radius: 26px;
            padding: 1.2rem;
            box-shadow: 0 12px 28px rgba(23, 35, 33, 0.05);
        }
        .exec-header {
            min-height: 122px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .exec-title {
            margin: 0;
            font-size: 1.1rem;
            font-weight: 700;
            line-height: 1.2;
            color: var(--text);
        }
        .exec-subtitle {
            margin: 0.7rem 0 0 0;
            font-size: 0.9rem;
            line-height: 1.45;
            color: var(--muted);
        }
        .exec-item {
            background: rgba(255, 255, 255, 0.96);
            border: 1px solid rgba(29, 52, 49, 0.08);
            border-left: 4px solid transparent;
            border-radius: 18px;
            padding: 0.95rem 1rem;
        }
        .exec-item.alert { border-left-color: var(--red); }
        .exec-item.warning { border-left-color: var(--amber); }
        .exec-item.safe { border-left-color: var(--green); }
        .exec-row {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 0.8rem;
        }
        .exec-item-title {
            margin: 0;
            font-size: 0.95rem;
            font-weight: 700;
            line-height: 1.3;
            color: var(--text);
        }
        .exec-item-meta {
            margin-top: 0.55rem;
            font-size: 0.86rem;
            line-height: 1.5;
            color: var(--muted);
        }
        .exec-item-text {
            margin-top: 0.55rem;
            font-size: 0.86rem;
            line-height: 1.45;
            color: var(--muted);
        }
        .exec-badge {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            white-space: nowrap;
            border-radius: 999px;
            background: rgba(29, 52, 49, 0.06);
            color: var(--text);
            font-size: 0.78rem;
            font-weight: 600;
            padding: 0.35rem 0.6rem;
        }
        .section-spacer {
            height: 0.35rem;
        }
        [data-testid="stTabs"] [role="tablist"] {
            gap: 0.45rem;
        }
        [data-testid="stTabs"] [role="tab"] {
            background: rgba(255, 255, 255, 0.58);
            border: 1px solid var(--line);
            border-radius: 999px;
            padding: 0.55rem 0.95rem;
            color: var(--muted);
        }
        [data-testid="stTabs"] [aria-selected="true"] {
            background: var(--teal);
            color: #ffffff;
            border-color: rgba(31, 95, 91, 0.28);
        }
        [data-testid="stMetric"] {
            background: transparent;
            border: 0;
        }
        [data-testid="stDataFrame"], [data-testid="stMarkdownContainer"] table {
            border-radius: 18px;
            overflow: hidden;
        }
        [data-testid="stDataFrame"], [data-testid="stDataEditor"] {
            border: 1px solid var(--line);
            border-radius: 22px;
            background: rgba(255, 255, 255, 0.84);
            box-shadow: 0 12px 28px rgba(23, 35, 33, 0.05);
            overflow: hidden;
        }
        [data-testid="stDataFrame"] [data-testid="stTable"],
        [data-testid="stDataEditor"] [data-testid="stDataFrame"] {
            background: rgba(255, 255, 255, 0.9);
        }
        [data-testid="stDataFrame"] thead tr th,
        [data-testid="stDataEditor"] thead tr th {
            background: linear-gradient(180deg, rgba(219, 233, 229, 0.95), rgba(236, 228, 214, 0.88));
            color: var(--text);
            font-size: 0.78rem;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            border-bottom: 1px solid rgba(29, 52, 49, 0.08);
        }
        [data-testid="stDataFrame"] tbody tr:nth-child(even),
        [data-testid="stDataEditor"] tbody tr:nth-child(even) {
            background: rgba(244, 241, 234, 0.58);
        }
        [data-testid="stDataFrame"] tbody tr:hover,
        [data-testid="stDataEditor"] tbody tr:hover {
            background: rgba(219, 233, 229, 0.52);
        }
        [data-testid="stDataFrame"] tbody td,
        [data-testid="stDataEditor"] tbody td {
            color: var(--text);
            border-bottom: 1px solid rgba(29, 52, 49, 0.06);
        }
        [data-testid="stDataEditor"] [role="textbox"],
        [data-testid="stDataEditor"] input,
        [data-testid="stDataEditor"] textarea {
            background: rgba(255, 255, 255, 0.92) !important;
            color: var(--text) !important;
        }
        [data-testid="stExpander"] {
            border: 0 !important;
            box-shadow: none !important;
            background: transparent !important;
        }
        [data-testid="stExpander"] > details {
            border: 0 !important;
            outline: 0 !important;
            box-shadow: none !important;
            background: rgba(255, 255, 255, 0.55) !important;
        }
        [data-testid="stExpander"] details {
            border: 0 !important;
            border-radius: 22px;
            background: rgba(255, 255, 255, 0.55) !important;
            box-shadow: none !important;
            overflow: hidden;
            margin-bottom: 0.85rem;
        }
        [data-testid="stExpander"] details summary {
            padding: 1rem 1.1rem;
            font-weight: 600;
            color: var(--text);
            font-size: 0.95rem;
            line-height: 1.45;
            background: rgba(255,255,255,0.72) !important;
            border: 0 !important;
            box-shadow: none !important;
        }
        [data-testid="stExpander"] details > div {
            padding: 0.45rem 0.2rem 0.2rem 0.2rem;
        }
        .client-banner {
            background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(244,241,234,0.88));
            border: 1px solid rgba(29, 52, 49, 0.08);
            border-radius: 20px;
            padding: 0.95rem 1rem;
            margin-bottom: 0.9rem;
        }
        .client-banner-top {
            display: flex;
            justify-content: space-between;
            gap: 0.9rem;
            align-items: flex-start;
        }
        .client-banner-title {
            margin: 0;
            font-size: 1rem;
            font-weight: 700;
            line-height: 1.25;
        }
        .client-banner-subtitle {
            margin: 0.35rem 0 0 0;
            font-size: 0.87rem;
            line-height: 1.45;
            color: var(--muted);
        }
        .status-pill {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 0.34rem 0.62rem;
            font-size: 0.76rem;
            font-weight: 700;
            letter-spacing: 0.02em;
            white-space: nowrap;
        }
        .status-pill.critical {
            background: var(--red-soft);
            color: var(--red);
        }
        .status-pill.warning {
            background: var(--amber-soft);
            color: #8b6217;
        }
        .status-pill.safe {
            background: var(--green-soft);
            color: var(--green);
        }
        .status-pill.neutral {
            background: rgba(29, 52, 49, 0.08);
            color: var(--text);
        }
        .info-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.65rem;
            margin-top: 0.8rem;
        }
        .info-chip {
            background: rgba(255,255,255,0.78);
            border: 1px solid rgba(29, 52, 49, 0.08);
            border-radius: 14px;
            padding: 0.75rem 0.8rem;
        }
        .info-chip-label {
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--muted);
        }
        .info-chip-value {
            margin-top: 0.3rem;
            font-size: 0.92rem;
            font-weight: 600;
            line-height: 1.35;
            color: var(--text);
        }
        .mini-metric-grid {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 0.7rem;
            margin-bottom: 0.9rem;
        }
        .mini-metric {
            background: rgba(255,255,255,0.94);
            border: 1px solid rgba(29, 52, 49, 0.08);
            border-top: 3px solid transparent;
            border-radius: 16px;
            padding: 0.85rem 0.85rem 0.8rem 0.85rem;
        }
        .mini-metric.critical { border-top-color: var(--red); }
        .mini-metric.warning { border-top-color: var(--amber); }
        .mini-metric.safe { border-top-color: var(--green); }
        .mini-metric.neutral { border-top-color: rgba(29, 52, 49, 0.18); }
        .mini-metric-label {
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--muted);
        }
        .mini-metric-value {
            margin-top: 0.4rem;
            font-size: 1.55rem;
            font-weight: 700;
            line-height: 1;
            color: var(--text);
        }
        .mini-metric-note {
            margin-top: 0.4rem;
            font-size: 0.83rem;
            line-height: 1.35;
            color: var(--muted);
        }
        .table-caption {
            margin: 0 0 0.8rem 0;
            color: var(--muted);
            font-size: 0.92rem;
            line-height: 1.45;
        }
        @media (max-width: 980px) {
            .hero-grid {
                grid-template-columns: 1fr;
            }
            .exec-grid {
                grid-template-columns: 1fr;
            }
            .hero-title {
                font-size: 1.75rem;
            }
            .panel-head {
                min-height: auto;
            }
            .info-grid,
            .mini-metric-grid {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_hero(base_df: pd.DataFrame, csv_path: Path, client_df: pd.DataFrame) -> None:
    criticos = int(client_df["classificacao"].eq("Alto Risco").sum())
    atencao = int(client_df["classificacao"].eq("Atencao").sum())
    media_risco = float(client_df["pontuacao"].mean()) if not client_df.empty else 0.0
    total_clientes = int(client_df["cliente"].nunique()) if "cliente" in client_df.columns else 0
    total_analistas = int(base_df["analista"].replace("", pd.NA).dropna().nunique()) if not base_df.empty else 0
    html_block = f"""
    <section class="hero-card">
        <div class="hero-grid">
            <div>
                <span class="hero-kicker">Resumo executivo</span>
                <h1 class="hero-title">Comece pelo que pede resposta agora.</h1>
                <p class="hero-subtitle">
                    A home passa a funcionar como triagem da carteira: um resumo curto para entender o quadro
                    e apontar rapidamente quais contas merecem atencao imediata.
                </p>
                <div class="hero-chips">
                    <span class="hero-chip">{total_clientes} clientes</span>
                    <span class="hero-chip">{total_analistas} analistas ativos</span>
                    <span class="hero-chip">{atencao} em atencao</span>
                    <span class="hero-chip">Fonte: {html.escape(csv_path.name)}</span>
                </div>
            </div>
            <aside class="hero-side">
                <div class="hero-side-label">Prioridade da leitura</div>
                <div class="hero-side-value">{criticos} contas criticas</div>
                <div class="hero-side-text">
                    Pontuacao media da carteira: {format_float(media_risco)}. Se esse bloco subir,
                    a agenda da semana precisa migrar para retencao e cobertura.
                </div>
            </aside>
        </div>
    </section>
    """
    render_html_block(html_block)


def render_metric_card(label: str, value: str, note: str, tone: str = "safe") -> None:
    render_html_block(
        f"""
        <article class="metric-card metric-{tone}">
            <div class="metric-label">{html.escape(label)}</div>
            <div class="metric-value">{html.escape(value)}</div>
            <div class="metric-note">{html.escape(note)}</div>
        </article>
        """
    )


def render_panorama_metrics(metrics: list[tuple[str, str, str, str]]) -> None:
    cards_html = "".join(
        f"""
        <div class="panorama-metric {tone}">
            <div class="metric-label">{html.escape(label)}</div>
            <div class="metric-value">{html.escape(value)}</div>
            <div class="metric-note">{html.escape(note)}</div>
        </div>
        """
        for label, value, note, tone in metrics
    )

    html_block = f"""
    <html>
        <head>
            <style>
                html, body {{
                    margin: 0;
                    padding: 0;
                    background: transparent;
                    font-family: "Segoe UI", sans-serif;
                }}
                .panorama-metrics {{
                    display: grid;
                    grid-template-columns: repeat(4, minmax(0, 1fr));
                    gap: 0.95rem;
                    padding: 0.05rem;
                }}
                .panorama-metric {{
                    box-sizing: border-box;
                    height: 178px;
                    padding: 1.02rem 1rem 0.98rem 1rem;
                    border-radius: 22px;
                    border: 1px solid rgba(29, 52, 49, 0.08);
                    border-left: 4px solid rgba(29, 52, 49, 0.18);
                    background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 244, 237, 0.9));
                    box-shadow:
                        0 12px 26px rgba(23, 35, 33, 0.05),
                        inset 0 1px 0 rgba(255, 255, 255, 0.72);
                    display: flex;
                    flex-direction: column;
                }}
                .panorama-metric.critical {{ border-left-color: #B64545; }}
                .panorama-metric.warning {{ border-left-color: #C38A2D; }}
                .panorama-metric.safe {{ border-left-color: #2F6B55; }}
                .panorama-metric.neutral {{ border-left-color: rgba(29, 52, 49, 0.18); }}
                .metric-label {{
                    color: #62706C;
                    font-size: 0.82rem;
                    text-transform: uppercase;
                    letter-spacing: 0.08em;
                    line-height: 1.45;
                    min-height: 2.9em;
                    display: -webkit-box;
                    -webkit-line-clamp: 2;
                    -webkit-box-orient: vertical;
                    overflow: hidden;
                }}
                .metric-value {{
                    margin-top: 0.65rem;
                    min-height: 1.2em;
                    color: #143746;
                    font-size: 1.85rem;
                    font-weight: 700;
                    line-height: 1;
                }}
                .metric-note {{
                    margin-top: auto;
                    padding-top: 0.65rem;
                    min-height: 4.05em;
                    color: #62706C;
                    font-size: 0.9rem;
                    line-height: 1.35;
                    display: -webkit-box;
                    -webkit-line-clamp: 3;
                    -webkit-box-orient: vertical;
                    overflow: hidden;
                }}
            </style>
        </head>
        <body>
            <div class="panorama-metrics">{cards_html}</div>
        </body>
    </html>
    """
    components.html(textwrap.dedent(html_block).strip(), height=390, scrolling=False)


def render_summary_cards(client_df: pd.DataFrame, base_df: pd.DataFrame) -> None:
    total_equip = int(client_df["equip_cb"].sum() + client_df["equip_clima"].sum())
    total_clientes = int(len(client_df))
    clientes_risco = int(client_df["classificacao"].eq("Alto Risco").sum())
    clientes_atencao = int(client_df["classificacao"].eq("Atencao").sum())
    clientes_seguro = int(client_df["classificacao"].eq("Seguro").sum())
    distratos = int(client_df["distrato_count"].sum())
    media_risco = float(client_df["pontuacao"].mean()) if not client_df.empty else 0.0
    distancia_media = float(base_df["distancia_km"].mean()) if not base_df.empty else 0.0
    metrics = [
        ("Clientes na carteira", format_int(total_clientes), "Base filtrada para esta leitura", "neutral"),
        ("Alto risco", format_int(clientes_risco), "Contas que devem abrir a agenda", "critical"),
        ("Em atencao", format_int(clientes_atencao), "Contas com sinais intermediarios", "warning"),
        ("Distratos sinalizados", format_int(distratos), "Indicador mais sensivel de desgaste", "critical"),
        ("Pontuacao media", format_float(media_risco), "Leitura sintetica de risco da carteira", "warning"),
        ("Equipamentos ativos", format_int(total_equip), "Cb + Clima nas contas visiveis", "neutral"),
        ("Distancia media", f"{format_float(distancia_media, 0)} km", "Quanto maior, maior friccao de cobertura", "warning"),
        ("Area total (ha)", format_int(base_df["area_ha"].sum()), "Escala operacional da carteira", "neutral"),
    ]

    left, right = st.columns([0.98, 1.92], gap="large")
    with left:
        st.markdown("#### Composicao da carteira")
        st.caption("Distribuicao executiva entre alto risco, atencao e clientes seguros.")
        render_portfolio_donut(total_clientes, clientes_risco, clientes_atencao, clientes_seguro)
    with right:
        render_panorama_metrics(metrics)


def build_signal_summary(client_df: pd.DataFrame) -> list[dict[str, str | int]]:
    total_equip = client_df["equip_cb"] + client_df["equip_clima"]
    return [
        {
            "title": "Distrato em carteira",
            "count": int(client_df["distrato_count"].gt(0).sum()),
            "detail": "Clientes com distrato marcado exigem leitura executiva imediata.",
            "tone": "high",
        },
        {
            "title": "Distancia operacional alta",
            "count": int(client_df["distancia_media_km"].ge(250).sum()),
            "detail": "Operacoes distantes tendem a elevar atrito e tempo de resposta.",
            "tone": "warn",
        },
        {
            "title": "Baixa densidade operacional",
            "count": int(total_equip.lt(8).sum()),
            "detail": "Baixo volume costuma indicar vinculo fragil ou baixa relevancia.",
            "tone": "warn",
        },
        {
            "title": "Contas sem equipamentos",
            "count": int(total_equip.eq(0).sum()),
            "detail": "Sem atividade instalada, a relacao fica muito vulneravel.",
            "tone": "high",
        },
        {
            "title": "Atendimento disperso",
            "count": int(client_df["cidades"].gt(1).sum()),
            "detail": "Dispersao geografica aumenta complexidade operacional.",
            "tone": "safe",
        },
    ]


def build_signal_monitoring_details(client_df: pd.DataFrame) -> list[dict[str, object]]:
    total_equip = client_df["equip_cb"] + client_df["equip_clima"]
    definitions = [
        {
            "title": "Distrato em carteira",
            "tone": "high",
            "detail": "Clientes com distrato marcado exigem leitura executiva imediata.",
            "impact": "Indica risco comercial aberto e necessidade de acao coordenada entre gestao e operacao.",
            "mask": client_df["distrato_count"].gt(0),
        },
        {
            "title": "Distancia operacional alta",
            "tone": "warn",
            "detail": "Operacoes distantes tendem a elevar atrito e tempo de resposta.",
            "impact": "Pode gerar percepcao de lentidao, menor frequencia de acompanhamento e desgaste de cobertura.",
            "mask": client_df["distancia_media_km"].ge(250),
        },
        {
            "title": "Baixa densidade operacional",
            "tone": "warn",
            "detail": "Baixo volume costuma indicar vinculo fragil ou baixa relevancia.",
            "impact": "Contas com pouca densidade tendem a ter menor dependencia da solucao e menor barreira de saida.",
            "mask": total_equip.lt(8),
        },
        {
            "title": "Contas sem equipamentos",
            "tone": "high",
            "detail": "Sem atividade instalada, a relacao fica muito vulneravel.",
            "impact": "Sem operacao viva, o cliente pode perder percepcao de valor rapidamente.",
            "mask": total_equip.eq(0),
        },
    ]

    details: list[dict[str, object]] = []
    for item in definitions:
        sample = client_df.loc[item["mask"], "cliente"].head(4).tolist()
        details.append(
            {
                "title": item["title"],
                "tone": item["tone"],
                "detail": item["detail"],
                "impact": item["impact"],
                "count": int(item["mask"].sum()),
                "examples": sample,
            }
        )
    return details


def render_clean_table(dataframe: pd.DataFrame) -> None:
    if dataframe.empty:
        st.info("Nenhum dado disponivel.")
        return

    headers = "".join(f"<th>{html.escape(str(col))}</th>" for col in dataframe.columns)
    rows: list[str] = []
    for _, row in dataframe.iterrows():
        cells = "".join(f"<td>{html.escape(str(value))}</td>" for value in row.tolist())
        rows.append(f"<tr>{cells}</tr>")

    render_html_block(
        f"""
        <table class="clean-table">
            <thead><tr>{headers}</tr></thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
        """
    )


def render_styled_dataframe(dataframe: pd.DataFrame, height: int | None = None) -> None:
    if dataframe.empty:
        st.info("Nenhum dado disponivel.")
        return

    styled = (
        dataframe.style.hide(axis="index")
        .format(
            {
                col: "{:,.2f}"
                for col in dataframe.select_dtypes(include=["number"]).columns
            }
        )
        .set_properties(**{"background-color": "rgba(255,255,255,0.0)", "color": "#1d3431"})
    )
    st.dataframe(styled, use_container_width=True, height=height)


def render_attention_board(client_df: pd.DataFrame) -> None:
    if client_df.empty:
        st.info("Nenhum cliente disponivel para priorizacao.")
        return

    top_clients = client_df.head(3)
    priority_items: list[str] = []
    for _, row in top_clients.iterrows():
        tone = "safe"
        if row["classificacao"] == "Alto Risco":
            tone = "alert"
        elif row["classificacao"] == "Atencao":
            tone = "warning"
        priority_items.append(
            textwrap.dedent(
                f"""
                <article class="exec-item {tone}">
                    <div class="exec-row">
                        <h4 class="exec-item-title">{html.escape(row["cliente"])}</h4>
                        <span class="exec-badge">{html.escape(row["classificacao"])} | {int(row["pontuacao"])} pts</span>
                    </div>
                    <div class="exec-item-meta">
                        Gestor: {html.escape(row["gestor"] or "Nao definido")}<br>
                        Analista: {html.escape(row["analista"] or "Nao definido")}<br>
                        Distancia media: {format_float(float(row["distancia_media_km"]), 0)} km
                    </div>
                    <div class="exec-item-text">{html.escape(row["sinais"])}</div>
                </article>
                """
            ).strip()
        )

    signal_items: list[str] = []
    tone_map = {"high": "alert", "warn": "warning", "safe": "safe"}
    for signal in build_signal_summary(client_df)[:4]:
        signal_items.append(
            textwrap.dedent(
                f"""
                <article class="exec-item {tone_map.get(str(signal["tone"]), "safe")}">
                    <div class="exec-row">
                        <h4 class="exec-item-title">{html.escape(str(signal["title"]))}</h4>
                        <span class="exec-badge">{int(signal["count"])} clientes</span>
                    </div>
                    <div class="exec-item-text">{html.escape(str(signal["detail"]))}</div>
                </article>
                """
            ).strip()
        )

    render_html_block(
        f"""
        <section class="exec-grid">
            <div class="exec-column">
                <div class="exec-panel">
                    <div class="exec-header">
                        <div>
                            <h3 class="exec-title">Clientes que merecem contato prioritario</h3>
                            <p class="exec-subtitle">Uma selecao curta para direcionar a agenda executiva e operacional da semana.</p>
                        </div>
                    </div>
                </div>
                {''.join(priority_items)}
            </div>
            <div class="exec-column">
                <div class="exec-panel">
                    <div class="exec-header">
                        <div>
                            <h3 class="exec-title">Sinais que merecem monitoramento continuo</h3>
                            <p class="exec-subtitle">Leituras simples para identificar desgaste antes de virar perda.</p>
                        </div>
                    </div>
                </div>
                {''.join(signal_items)}
            </div>
        </section>
        """
    )


def render_signal_monitoring_block(client_df: pd.DataFrame) -> None:
    with st.container():
        render_html_block(
            """
            <section class="section-shell signals-shell">
                <h2 class="section-title">Sinais que merecem monitoramento continuo</h2>
                <p class="section-subtitle">Indicadores de desgaste para acompanhar de forma recorrente, antes que virem perda ou escalada de risco.</p>
            </section>
            """
        )
        tone_map = {"high": "alert", "warn": "warning", "safe": "safe"}
        for signal in build_signal_monitoring_details(client_df):
            header = f'{signal["title"]} | {signal["count"]} clientes'
            with st.expander(header, expanded=False):
                render_html_block(
                    f"""
                    <section class="client-banner">
                        <div class="client-banner-top">
                            <div>
                                <h3 class="client-banner-title">{html.escape(str(signal["title"]))}</h3>
                                <p class="client-banner-subtitle">{html.escape(str(signal["detail"]))}</p>
                            </div>
                            <span class="status-pill {tone_map.get(str(signal["tone"]), "neutral")}">{int(signal["count"])} clientes</span>
                        </div>
                        <div class="info-grid">
                            <div class="info-chip">
                                <div class="info-chip-label">Leitura</div>
                                <div class="info-chip-value">{html.escape(str(signal["impact"]))}</div>
                            </div>
                            <div class="info-chip">
                                <div class="info-chip-label">Clientes exemplo</div>
                                <div class="info-chip-value">{html.escape(", ".join(signal["examples"]) if signal["examples"] else "Nenhum cliente no recorte atual")}</div>
                            </div>
                            <div class="info-chip">
                                <div class="info-chip-label">Prioridade</div>
                                <div class="info-chip-value">{'Alta' if str(signal["tone"]) == 'high' else 'Media' if str(signal["tone"]) == 'warn' else 'Controle'}</div>
                            </div>
                        </div>
                    </section>
                    """
                )


def _legacy_render_attention_clients(client_df: pd.DataFrame) -> None:
    action_plan = ensure_action_plan_state(client_df)
    monitor, _ = build_action_plan_monitor(action_plan)

    render_html_block(
        """
        <section class="section-shell">
            <h2 class="section-title">Clientes que precisam de atencao</h2>
            <p class="section-subtitle">Abra cada cliente para acompanhar o plano de acao, o andamento e os proximos passos da equipe.</p>
        </section>
        """
    )

    focus_clients = client_df.head(6).copy()
    if focus_clients.empty:
        st.info("Nenhum cliente em foco com os filtros atuais.")
        return

    focus_clients["priority_rank"] = focus_clients["cliente"].apply(
        lambda name: summarize_client_action_state(monitor[monitor["Cliente"].eq(name)]).get("priority_rank", 3)
    )
    focus_clients = focus_clients.sort_values(["priority_rank", "pontuacao"], ascending=[True, False])

    for _, row in focus_clients.iterrows():
        client_actions = monitor[monitor["Cliente"].eq(row["cliente"])].copy()
        client_state = summarize_client_action_state(client_actions)
        header = (
            f'{row["cliente"]} · {row["classificacao"]} · {int(row["pontuacao"])} pts'
            f' · {client_state["status_label"]}'
            f' · Ultima atualizacao: {client_state["ultima_atualizacao"]}'
        )
        with st.expander(header, expanded=bool(client_state["expanded"])):
            meta_1, meta_2 = st.columns([1.1, 1], gap="large")
            with meta_1:
                render_html_block(
                    f"""
                    <section class="grid-card tight">
                        <h3 class="panel-title">Resumo da conta</h3>
                        <p class="panel-subtitle">Gestor: {html.escape(row["gestor"] or "Nao definido")}<br>
                        Analista: {html.escape(row["analista"] or "Nao definido")}<br>
                        Distancia media: {format_float(float(row["distancia_media_km"]), 0)} km</p>
                        <p class="table-caption">{html.escape(row["sinais"])}</p>
                    </section>
                    """
                )
            with meta_2:
                cards = st.columns(3)
                with cards[0]:
                    render_metric_card(
                        "Em andamento",
                        format_int(int(client_state["andamento"])),
                        "Acoes ativas para este cliente",
                        "warning",
                    )
                with cards[1]:
                    render_metric_card(
                        "Concluidas",
                        format_int(int(client_state["concluidas"])),
                        "Acoes ja finalizadas",
                        "safe",
                    )
                with cards[2]:
                    render_metric_card(
                        "Atrasadas",
                        format_int(int(client_state["atrasadas"])),
                        "Prazos vencidos sem conclusao",
                        "critical",
                    )

                cards = st.columns(2)
                with cards[0]:
                    render_metric_card(
                        "Sem atualizacao",
                        format_int(int(client_state["sem_atualizacao"])),
                        "Itens sem retorno registrado",
                        "neutral",
                    )
                with cards[1]:
                    render_metric_card(
                        "Total de acoes",
                        format_int(len(client_actions)),
                        "Frentes abertas para o cliente",
                        "neutral",
                    )

            if client_actions.empty:
                st.info("Esse cliente ainda nao possui acao cadastrada no Plano de Acao.")
            else:
                view = client_actions[
                    ["Acao", "Responsavel", "Prazo", "Status", "Atualizacao", "Proximo passo"]
                ].rename(
                    columns={
                        "Acao": "Acao",
                        "Responsavel": "Responsavel",
                        "Prazo": "Prazo",
                        "Status": "Status",
                        "Atualizacao": "Atualizacao",
                        "Proximo passo": "Proximo passo",
                    }
                )
                render_clean_table(view)


def render_attention_clients(client_df: pd.DataFrame) -> None:
    action_plan = ensure_action_plan_state(client_df)
    monitor, _ = build_action_plan_monitor(action_plan)

    with st.container():
        render_html_block(
            """
            <section class="section-shell attention-shell">
                <h2 class="section-title">Clientes que precisam de atencao</h2>
                <p class="section-subtitle">Quando um cliente entra em atencao ou alto risco, ele ja passa a exigir acao e acompanhamento de execucao neste mesmo bloco.</p>
            </section>
            """
        )

        focus_clients = client_df[client_df["classificacao"].isin(["Alto Risco", "Atencao"])].copy()
        if focus_clients.empty:
            st.info("Nenhum cliente em foco com os filtros atuais.")
            return

        focus_clients["priority_rank"] = focus_clients["cliente"].apply(
            lambda name: summarize_client_action_state(monitor[monitor["Cliente"].eq(name)]).get("priority_rank", 3)
        )
        focus_clients = focus_clients.sort_values(["priority_rank", "pontuacao", "cliente"], ascending=[True, True, True])

        client_options = ["Todos os clientes"] + focus_clients["cliente"].tolist()
        selected_client = st.selectbox(
            "Filtrar cliente dentro do bloco",
            client_options,
            key="attention_client_filter",
        )
        visible_clients = (
            focus_clients if selected_client == "Todos os clientes" else focus_clients[focus_clients["cliente"].eq(selected_client)].copy()
        )

        monitored_clients = int(visible_clients["cliente"].isin(monitor["Cliente"]).sum()) if not monitor.empty else 0
        total_actions = int(monitor["Cliente"].isin(visible_clients["cliente"]).sum()) if not monitor.empty else 0
        overdue_actions = (
            int(monitor.loc[monitor["Cliente"].isin(visible_clients["cliente"]), "atrasado"].sum())
            if not monitor.empty
            else 0
        )
        in_progress_actions = (
            int(monitor.loc[monitor["Cliente"].isin(visible_clients["cliente"]), "bucket"].eq("em_andamento").sum())
            if not monitor.empty
            else 0
        )
        completed_actions = (
            int(monitor.loc[monitor["Cliente"].isin(visible_clients["cliente"]), "bucket"].eq("concluido").sum())
            if not monitor.empty
            else 0
        )
        progress_pct = (completed_actions / total_actions) * 100 if total_actions else 0.0

        cards = st.columns(6)
        with cards[0]:
            render_metric_card(
                "Clientes em foco",
                format_int(len(visible_clients)),
                "Clientes em atencao e alto risco",
                "critical",
            )
        with cards[1]:
            render_metric_card(
                "Com plano",
                format_int(monitored_clients),
                "Clientes ja acompanhados",
                "warning",
            )
        with cards[2]:
            render_metric_card(
                "Acoes abertas",
                format_int(total_actions),
                "Frentes cadastradas no plano",
                "neutral",
            )
        with cards[3]:
            render_metric_card(
                "Progresso",
                f"{progress_pct:.0f}%",
                "Percentual de acoes concluidas",
                "safe" if progress_pct >= 70 else "warning",
            )
        with cards[4]:
            render_metric_card(
                "Em andamento",
                format_int(in_progress_actions),
                "Execucao em curso",
                "warning",
            )
        with cards[5]:
            render_metric_card(
                "Atrasadas",
                format_int(overdue_actions),
                "Prazo vencido sem conclusao",
                "critical",
            )

        details_label = (
            f"Mostrar clientes listados ({len(visible_clients)})"
            if selected_client == "Todos os clientes"
            else f"Mostrar detalhes de {selected_client}"
        )
        show_client_list = st.toggle(details_label, value=False, key="attention_show_client_list")
        if show_client_list:
            for _, row in visible_clients.iterrows():
                client_actions = monitor[monitor["Cliente"].eq(row["cliente"])].copy()
                client_state = summarize_client_action_state(client_actions)

                if client_state["status_label"] == "Atrasado":
                    pill_tone = "critical"
                elif client_state["status_label"] == "Em andamento":
                    pill_tone = "warning"
                elif client_state["status_label"] == "Concluido":
                    pill_tone = "safe"
                else:
                    pill_tone = "neutral"

                header = (
                    f'{row["cliente"]} | {row["classificacao"]} | {int(row["pontuacao"])} pts'
                    f' | {client_state["status_label"]}'
                    f' | Ultima atualizacao: {client_state["ultima_atualizacao"]}'
                )

                with st.expander(header, expanded=False):
                    render_html_block(
                        f"""
                        <section class="client-banner">
                            <div class="client-banner-top">
                                <div>
                                    <h3 class="client-banner-title">{html.escape(row["cliente"])}</h3>
                                    <p class="client-banner-subtitle">Acompanhamento de execucao para cliente priorizado na visao executiva.</p>
                                </div>
                                <span class="status-pill {pill_tone}">{html.escape(str(client_state["status_label"]))}</span>
                            </div>
                            <div class="info-grid">
                                <div class="info-chip">
                                    <div class="info-chip-label">Gestor</div>
                                    <div class="info-chip-value">{html.escape(row["gestor"] or "Nao definido")}</div>
                                </div>
                                <div class="info-chip">
                                    <div class="info-chip-label">Analista</div>
                                    <div class="info-chip-value">{html.escape(row["analista"] or "Nao definido")}</div>
                                </div>
                                <div class="info-chip">
                                    <div class="info-chip-label">Distancia media</div>
                                    <div class="info-chip-value">{format_float(float(row["distancia_media_km"]), 0)} km</div>
                                </div>
                            </div>
                        </section>
                        <section class="mini-metric-grid">
                            <article class="mini-metric warning">
                                <div class="mini-metric-label">Em andamento</div>
                                <div class="mini-metric-value">{format_int(int(client_state["andamento"]))}</div>
                                <div class="mini-metric-note">Acoes ativas</div>
                            </article>
                            <article class="mini-metric neutral">
                                <div class="mini-metric-label">Progresso</div>
                                <div class="mini-metric-value">{float(client_state["progresso_pct"]):.0f}%</div>
                                <div class="mini-metric-note">Percentual concluido</div>
                            </article>
                            <article class="mini-metric safe">
                                <div class="mini-metric-label">Concluidas</div>
                                <div class="mini-metric-value">{format_int(int(client_state["concluidas"]))}</div>
                                <div class="mini-metric-note">Ja finalizadas</div>
                            </article>
                            <article class="mini-metric critical">
                                <div class="mini-metric-label">Atrasadas</div>
                                <div class="mini-metric-value">{format_int(int(client_state["atrasadas"]))}</div>
                                <div class="mini-metric-note">Prazo vencido</div>
                            </article>
                            <article class="mini-metric neutral">
                                <div class="mini-metric-label">Sem atualizacao</div>
                                <div class="mini-metric-value">{format_int(int(client_state["sem_atualizacao"]))}</div>
                                <div class="mini-metric-note">Sem retorno</div>
                            </article>
                            <article class="mini-metric neutral">
                                <div class="mini-metric-label">Total de acoes</div>
                                <div class="mini-metric-value">{format_int(len(client_actions))}</div>
                                <div class="mini-metric-note">Frentes abertas</div>
                            </article>
                        </section>
                        """
                    )

                    if client_actions.empty:
                        st.info("Esse cliente ainda nao possui acao cadastrada no Plano de Acao.")
                    else:
                        render_html_block(
                            """
                            <p class="table-caption">
                                Plano de acao e andamento registrado pela equipe para esta conta.
                            </p>
                            """
                        )
                        view = client_actions[
                            ["Acao", "Responsavel", "Prazo", "Status", "Atualizacao", "Proximo passo"]
                        ]
                        render_clean_table(view)


def render_overview_tab(
    base_df: pd.DataFrame,
    client_df: pd.DataFrame,
    summary: DatasetSummary,
    csv_path: Path,
) -> None:
    render_hero(base_df, csv_path, client_df)
    with st.container():
        render_html_block(
            """
            <section class="panorama-shell">
                <div class="panorama-header">
                    <h2 class="section-title">Panorama da carteira</h2>
                    <p class="section-subtitle">Resumo objetivo para entender o tamanho, o risco e a pressao operacional da carteira filtrada.</p>
                </div>
            </section>
            """
        )
        render_summary_cards(client_df, base_df)
    render_attention_clients(client_df)


def render_risk_tab(client_df: pd.DataFrame) -> None:
    st.caption(
        "A matriz abaixo reaproveita a estrutura do HTML, mas agora calcula a pontuacao a partir da base operacional. "
        "Como o CSV nao possui uma coluna explicita de satisfacao, os criterios sao inferidos e servem como ponto inicial. "
        "Na escala atual, 0 representa pior situacao e 5 representa melhor situacao."
    )

    show_cols = [
        "cliente",
        "gestor",
        "analista",
        *RISK_COLUMNS,
        "pontuacao",
        "classificacao",
        "equip_cb",
        "equip_clima",
        "area_ha",
        "distancia_media_km",
        "sinais",
    ]
    renamed = client_df[show_cols].rename(
        columns={
            "cliente": "Cliente",
            "gestor": "Gestor",
            "analista": "Analista",
            "pontuacao": "Pontuacao",
            "classificacao": "Classificacao",
            "equip_cb": "Cb's",
            "equip_clima": "Clima",
            "area_ha": "Area (ha)",
            "distancia_media_km": "Distancia media (km)",
            "sinais": "Sinais/Acoes",
            **RISK_LABELS,
        }
    )
    render_html_block(
        """
        <p class="table-caption">
            Leitura detalhada por cliente. Scores mais altos representam melhor satisfacao percebida,
            enquanto pontuacoes baixas concentram os casos de maior risco.
        </p>
        """
    )
    render_styled_dataframe(renamed, height=520)

    st.markdown("### Peso dos criterios")
    melted = client_df.melt(
        id_vars=["cliente"],
        value_vars=RISK_COLUMNS,
        var_name="criterio",
        value_name="valor",
    )
    mean_scores = (
        melted.groupby("criterio", as_index=False)["valor"]
        .mean()
        .rename(columns={"valor": "media"})
    )
    score_chart = (
        alt.Chart(melted)
        .mark_boxplot(
            extent="min-max",
            size=28,
            median={"color": CHART_PALETTE["ink"], "strokeWidth": 2},
            ticks={"color": CHART_PALETTE["muted"]},
        )
        .encode(
            x=alt.X("criterio:N", title="Criterio"),
            y=alt.Y("valor:Q", title="Score", scale=alt.Scale(domain=[0, 5])),
            color=alt.Color(
                "criterio:N",
                legend=None,
                scale=alt.Scale(
                    range=[
                        CHART_PALETTE["teal"],
                        CHART_PALETTE["amber"],
                        CHART_PALETTE["green"],
                        "#7A8B5A",
                        "#B86B52",
                        "#4F6D7A",
                    ]
                ),
            ),
            tooltip=["criterio", alt.Tooltip("valor:Q", title="Score", format=".1f")],
        )
        .properties(height=320)
    )
    score_means = (
        alt.Chart(mean_scores)
        .mark_point(
            shape="diamond",
            filled=True,
            size=180,
            color=CHART_PALETTE["ink"],
            stroke="#FFFFFF",
        )
        .encode(
            x=alt.X("criterio:N", title="Criterio"),
            y=alt.Y("media:Q", title="Score"),
            tooltip=[alt.Tooltip("criterio:N", title="Criterio"), alt.Tooltip("media:Q", title="Media", format=".2f")],
        )
    )
    st.altair_chart(style_chart(score_chart + score_means), use_container_width=True)


def render_operational_tab(base_df: pd.DataFrame, client_df: pd.DataFrame) -> None:
    st.markdown("### Distribuicao operacional por cliente")
    top_clients = client_df.nsmallest(12, "pontuacao").copy()
    top_clients["cliente_curto"] = top_clients["cliente"].apply(
        lambda value: value if len(value) <= 28 else value[:25] + "..."
    )
    chart_data = top_clients.melt(
        id_vars=["cliente", "cliente_curto"],
        value_vars=["equip_cb", "equip_clima", "area_ha"],
        var_name="indicador",
        value_name="valor",
    )
    indicator_labels = {
        "equip_cb": "Equipamentos Cb",
        "equip_clima": "Equipamentos Clima",
        "area_ha": "Area (ha)",
    }
    chart_data["indicador_label"] = chart_data["indicador"].map(indicator_labels)
    operational_chart = (
        alt.Chart(chart_data)
        .mark_bar(cornerRadiusEnd=8, size=18)
        .encode(
            x=alt.X("valor:Q", title=None, axis=alt.Axis(grid=True, domain=False)),
            y=alt.Y(
                "cliente_curto:N",
                sort=alt.SortField(field="valor", order="descending"),
                title=None,
                axis=alt.Axis(labelLimit=220),
            ),
            color=alt.Color(
                "indicador_label:N",
                scale=alt.Scale(
                    domain=["Area (ha)", "Equipamentos Cb", "Equipamentos Clima"],
                    range=[
                        CHART_PALETTE["teal"],
                        CHART_PALETTE["amber"],
                        CHART_PALETTE["green"],
                    ],
                ),
                legend=None,
            ),
            tooltip=[
                "cliente",
                alt.Tooltip("indicador_label:N", title="Indicador"),
                alt.Tooltip("valor:Q", title="Valor", format=",.2f"),
            ],
        )
        .properties(height=155)
        .facet(
            row=alt.Row(
                "indicador_label:N",
                title=None,
                header=alt.Header(labelOrient="left", labelPadding=10),
                sort=["Area (ha)", "Equipamentos Cb", "Equipamentos Clima"],
            )
        )
        .resolve_scale(x="independent")
        .properties(spacing=14)
    )
    st.altair_chart(style_chart(operational_chart), use_container_width=True)

    st.markdown("### Carga por analista")
    analyst_load = (
        base_df.groupby("analista", as_index=False)
        .agg(
            clientes=("cliente", "nunique"),
            fazendas=("fazenda", "nunique"),
            area_ha=("area_ha", "sum"),
            distancia_media_km=("distancia_km", "mean"),
        )
        .sort_values("clientes", ascending=False)
    )
    render_html_block(
        """
        <p class="table-caption">
            Distribuicao de carteira por analista para apoiar conversa de cobertura, capacidade e deslocamento.
        </p>
        """
    )
    render_styled_dataframe(analyst_load, height=420)


def render_action_plan_tab(client_df: pd.DataFrame) -> None:
    st.markdown("### Plano de acao")
    ensure_action_plan_state(client_df)

    render_html_block(
        """
        <p class="table-caption">
            Edite o plano diretamente na tabela. A ideia aqui e transformar os alertas da home em
            encaminhamentos concretos com responsavel, prazo, atualizacao e proximo passo.
        </p>
        """
    )
    action_plan = st.data_editor(
        st.session_state["action_plan"],
        use_container_width=True,
        height=320,
        num_rows="dynamic",
        hide_index=True,
        key="action_plan_editor",
    )
    st.session_state["action_plan"] = normalize_action_plan_df(action_plan)
    action_plan = st.session_state["action_plan"]

    if not action_plan.empty and "Status" in action_plan.columns:
        monitor, summary = build_action_plan_monitor(action_plan)
        cards = st.columns(4)
        with cards[0]:
            render_metric_card("Total de acoes", format_int(summary["total"]), "Itens cadastrados no plano", "neutral")
        with cards[1]:
            render_metric_card("Em andamento", format_int(summary["em_andamento"]), "Frentes em execucao", "warning")
        with cards[2]:
            render_metric_card("Concluidas", format_int(summary["concluido"]), "Acoes encerradas", "safe")
        with cards[3]:
            render_metric_card("Atrasadas", format_int(summary["atrasado"]), "Prazo vencido sem conclusao", "critical")

        status_counts = (
            action_plan["Status"]
            .fillna("Sem status")
            .value_counts()
            .rename_axis("status")
            .reset_index(name="total")
        )
        total_actions = int(status_counts["total"].sum())
        status_chart = (
            alt.Chart(status_counts)
            .mark_arc(innerRadius=52, outerRadius=86, cornerRadius=8)
            .encode(
                theta="total:Q",
                color=alt.Color(
                    "status:N",
                    title="Status",
                    scale=alt.Scale(
                        range=[
                            CHART_PALETTE["teal"],
                            CHART_PALETTE["amber"],
                            CHART_PALETTE["red"],
                            CHART_PALETTE["sand"],
                        ]
                    ),
                ),
                tooltip=["status", "total"],
            )
            .properties(height=280)
        )
        status_text = pd.DataFrame(
            [{"label": "Acoes", "total": total_actions}]
        )
        status_center = (
            alt.Chart(status_text)
            .mark_text(
                align="center",
                baseline="middle",
                color=CHART_PALETTE["ink"],
                fontSize=16,
                fontWeight=700,
                lineBreak="\n",
            )
            .encode(
                x=alt.value(145),
                y=alt.value(140),
                text=alt.value(f"{total_actions}\nacoes"),
            )
        )
        st.altair_chart(style_chart(status_chart + status_center), use_container_width=True)


def render_gimb_tab() -> None:
    st.markdown("### Checklist GIMB")
    if "gimb" not in st.session_state:
        st.session_state["gimb"] = seed_gimb_checklist()

    render_html_block(
        """
        <p class="table-caption">
            Checklist operacional para acompanhar rituais, cobertura e disciplina de acompanhamento da carteira.
        </p>
        """
    )
    gimb_df = st.data_editor(
        st.session_state["gimb"],
        use_container_width=True,
        height=280,
        num_rows="dynamic",
        hide_index=True,
        key="gimb_editor",
    )
    st.session_state["gimb"] = gimb_df


def render_data_tab(base_df: pd.DataFrame, csv_path: Path, summary: DatasetSummary) -> None:
    st.markdown("### Fonte de dados")
    st.write(f"Arquivo analisado: `{csv_path}`")
    st.write(
        f"{summary.raw_rows} linhas operacionais, {summary.clients} clientes, "
        f"{summary.analysts} analistas e {summary.managers} gestores."
    )
    render_html_block(
        """
        <p class="table-caption">
            Base tratada apos limpeza do CSV exportado da planilha original. Esta visao ajuda a validar
            colunas, filtros e consistencia da fonte.
        </p>
        """
    )
    render_styled_dataframe(base_df, height=520)
    st.download_button(
        "Baixar base tratada em CSV",
        data=base_df.to_csv(index=False).encode("utf-8"),
        file_name="base_tratada_clientes.csv",
        mime="text/csv",
    )


def main() -> None:
    st.set_page_config(
        page_title="Dashboard de Satisfacao do Cliente",
        layout="wide",
    )
    inject_theme()

    st.title("Dashboard de Satisfacao do Cliente")
    st.write(
        "Visao executiva da carteira com leitura orientada a prioridade, risco e capacidade operacional."
    )

    try:
        base_df, summary, csv_path = load_operational_data()
    except Exception as exc:
        st.error(f"Falha ao carregar os dados: {exc}")
        st.stop()

    filtered_df = apply_filters(base_df)
    client_df = build_client_matrix(filtered_df)

    if filtered_df.empty or client_df.empty:
        st.warning("Nenhum registro encontrado com os filtros atuais.")
        st.stop()

    tabs = st.tabs(
        [
            "Visao Executiva",
            "Matriz de Satisfacao",
            "Operacao",
            "Plano de Acao",
            "GIMB",
            "Base",
        ]
    )

    with tabs[0]:
        render_overview_tab(filtered_df, client_df, summary, csv_path)
    with tabs[1]:
        render_risk_tab(client_df)
    with tabs[2]:
        render_operational_tab(filtered_df, client_df)
    with tabs[3]:
        render_action_plan_tab(client_df)
    with tabs[4]:
        render_gimb_tab()
    with tabs[5]:
        render_data_tab(filtered_df, csv_path, summary)


if __name__ == "__main__":
    main()
