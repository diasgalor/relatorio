import pandas as pd
import matplotlib.pyplot as plt
import base64
from io import BytesIO
from pathlib import Path

# Caminho fixo do CSV
CSV_PATH = r"C:\Users\igor.goncalo\OneDrive - Tecsoil Automação e Sistemas S.A\Documentos\GitHub\relatorio\data\dados.csv"
# Caminho de saída do HTML
HTML_OUT = Path(__file__).parent.parent / "output" / "relatorio.html"

def fig_to_base64(fig):
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return f"data:image/png;base64,{b64}"

def gerar_relatorio(csv_path, html_out):
    from pathlib import Path
    csv_path = Path(csv_path)

    # localizar o arquivo (mantém a lógica anterior se desejar)
    candidates = [csv_path, Path(__file__).parent / csv_path, Path.cwd() / csv_path]
    found = next((p for p in candidates if p.exists()), None)
    if found is None:
        repo_root = Path(__file__).parent.parent
        matches = list(repo_root.rglob('dados*.csv')) or list(repo_root.rglob('*.csv'))
        if matches:
            found = matches[0]
        else:
            raise RuntimeError(f"Arquivo CSV não encontrado. Procurados: {candidates} e {repo_root}")
    csv_path = found

    try:
        df = pd.read_csv(csv_path, sep=";", encoding="utf-8")
    except Exception as e:
        raise RuntimeError(f"Erro ao ler o arquivo CSV ({csv_path}): {e}")

    # normalizar nomes de coluna (trim)
    df.columns = [c.strip() for c in df.columns]

    # Nomes esperados
    COL_ESTADO = "cd_estado"
    COL_OPERADOR = "desc_operador"
    COL_CONS_LH = "vl_consumo_instantaneo"
    COL_CONS_LHA = "vl_vazao_litros_ha"
    COL_VEL = "vl_velocidade"
    COL_AREA_H = "vl_hectares_hora"

    # validação mínima
    need = [COL_ESTADO, COL_OPERADOR, COL_CONS_LH, COL_CONS_LHA, COL_VEL, COL_AREA_H]
    faltando = [c for c in need if c not in df.columns]
    if faltando:
        raise ValueError(f"Colunas faltando no CSV: {faltando}")

    # strip em colunas string
    for c in df.select_dtypes(include=["object"]).columns:
        df[c] = df[c].astype(str).str.strip()

    # normalizar coluna de estado: tornar maiúsculo, remover espaços e mapear variantes para "T"
    df[COL_ESTADO] = df[COL_ESTADO].astype(str).str.upper().str.strip()
    df[COL_ESTADO] = df[COL_ESTADO].replace({
        "TRABALHANDO": "T", "TRUE": "T", "SIM": "T", "S": "T", "1": "T",
        "PARADO": "P", "P": "P", "0": "P", "FALSE": "P"
    })

    # função para converter strings numéricas com formatos diferentes para float
    def convert_numeric_series(s: pd.Series) -> pd.Series:
        s = s.fillna("").astype(str).str.strip()
        def fix(x):
            if x == "" or x.lower() in {"nan", "none"}:
                return None
            x = x.replace(" ", "")
            # se tiver tanto '.' quanto ',' -> assume '.' milhar e ',' decimal
            if x.count(".") > 0 and x.count(",") > 0:
                x = x.replace(".", "").replace(",", ".")
            # se tiver só ',' -> substitui por '.'
            elif x.count(",") > 0 and x.count(".") == 0:
                x = x.replace(",", ".")
            # se só tiver '.' assume ponto decimal (mantém)
            # remove outros caracteres indesejados
            # permite sinais e dígitos e ponto
            import re
            m = re.sub(r"[^\d\.\-]", "", x)
            return m if m != "" else None
        return pd.to_numeric(s.map(fix), errors="coerce")

    # converter colunas numéricas
    df[COL_CONS_LH] = convert_numeric_series(df[COL_CONS_LH])
    df[COL_CONS_LHA] = convert_numeric_series(df[COL_CONS_LHA])
    df[COL_VEL] = convert_numeric_series(df[COL_VEL])
    df[COL_AREA_H] = convert_numeric_series(df[COL_AREA_H])

    # --- Gráfico de pizza do estado operacional ---
    estado_counts = df[COL_ESTADO].value_counts()
    fig1 = plt.figure(figsize=(4, 4))
    plt.pie(estado_counts.values, labels=estado_counts.index, autopct='%1.1f%%')
    plt.title("Estado Operacional")
    img_pizza = fig_to_base64(fig1)

    # --- Top 5 Área Operacional por Operador ---
    area_op = (df.groupby(COL_OPERADOR)[COL_AREA_H]
                 .sum()
                 .reset_index()
                 .sort_values(COL_AREA_H, ascending=False)
                 .head(5))
    fig2 = plt.figure(figsize=(6, 4))
    plt.bar(area_op[COL_OPERADOR].astype(str), area_op[COL_AREA_H])
    plt.xticks(rotation=30, ha="right")
    plt.title("Top 5 - Área Operacional por Operador")
    plt.ylabel("ha/h (soma)")
    img_area_op = fig_to_base64(fig2)

    # --- Consumo e Velocidade quando Trabalhando ---
    df_trab = df[df[COL_ESTADO] == "T"]
    consumo_lh = df_trab[COL_CONS_LH].mean()
    consumo_lha = df_trab[COL_CONS_LHA].mean()
    vel_media = df_trab[COL_VEL].mean()

    # garantir números (se NaN -> 0.0)
    consumo_lh = 0.0 if pd.isna(consumo_lh) else consumo_lh
    consumo_lha = 0.0 if pd.isna(consumo_lha) else consumo_lha
    vel_media = 0.0 if pd.isna(vel_media) else vel_media

    cards_html = f"""
    <div style='display:flex; gap:20px; margin-bottom:20px;'>
      <div><b>Consumo (l/h):</b> {consumo_lh:.2f}</div>
      <div><b>Consumo (l/ha):</b> {consumo_lha:.2f}</div>
      <div><b>Velocidade (km/h):</b> {vel_media:.2f}</div>
    </div>
    """

    # --- HTML ---
    html = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <title>Relatório Resumido</title>
    </head>
    <body style="font-family: Arial, sans-serif; padding:20px;">
        <h1>Relatório Resumido - Operações</h1>
        {cards_html}
        <h2>Estado Operacional</h2>
        <img src="{img_pizza}" style="max-width:400px;">
        <h2>Top 5 Área Operacional por Operador</h2>
        <img src="{img_area_op}" style="max-width:600px;">
    </body>
    </html>
    """

    html_out = Path(html_out)
    html_out.parent.mkdir(parents=True, exist_ok=True)
    html_out.write_text(html, encoding="utf-8")
    print(f"✅ Relatório gerado em: {html_out}")

if __name__ == "__main__":
    # Caminho fixo do CSV
    CSV_PATH = r"C:\Users\igor.goncalo\OneDrive - Tecsoil Automação e Sistemas S.A\Documentos\GitHub\relatorio\data\dados.csv"
    # Caminho de saída do HTML
    HTML_OUT = Path(__file__).parent.parent / "output" / "relatorio.html"
    gerar_relatorio(CSV_PATH, HTML_OUT)
