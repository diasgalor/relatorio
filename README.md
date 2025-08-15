# Relatório Operacional Diário

Este projeto gera um relatório HTML diário a partir de um arquivo CSV com dados operacionais.

## Estrutura de pastas

```
relatorio_operacional/
│
├── data/                # CSVs diários
├── output/              # Relatórios HTML gerados
├── src/
│   ├── gerar_relatorio.py   # Script Python principal
│   ├── templates/
│   │   └── base.html        # Estrutura HTML com placeholders
│   └── static/
│       └── style.css        # CSS separado
├── README.md
└── requirements.txt
```

## Uso

1. Instale as dependências:
```bash
pip install -r requirements.txt
```

2. Coloque seu CSV (separado por ponto e vírgula) na pasta `data/`.

3. Execute o script:
```bash
python src/gerar_relatorio.py --csv data/SEU_ARQUIVO.csv --out output/relatorio.html
```

O relatório HTML será salvo na pasta `output/`.

## Ajustes

- Edite o arquivo `static/style.css` para personalizar o design.
- Edite `templates/base.html` para modificar a estrutura do HTML.
