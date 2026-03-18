# Dashboard de Satisfacao do Cliente

Aplicacao em `Streamlit` para leitura executiva e operacional da carteira, usando como fonte principal o CSV exportado na pasta `data`.

## Origem do projeto

Na analise inicial foram encontrados:

- `data/dashboard_v2.8.html`: prototipo visual/manual com matriz de risco, dashboard operacional, plano de acao, GIMB e historico.
- `data/teste2.8.txt`: duplicata do mesmo HTML.
- um CSV operacional real da carteira, com linhas de instrucao antes do cabecalho efetivo.

A versao atual em Python substitui o fluxo baseado em HTML/localStorage por uma dashboard conectada diretamente ao CSV operacional.

## Estrutura da aplicacao

A dashboard esta organizada nas abas:

- `Visao Executiva`
- `Matriz de Satisfacao`
- `Operacao`
- `Plano de Acao`
- `GIMB`
- `Base`

## O que existe na home hoje

A aba `Visao Executiva` foi desenhada como a pagina principal de acompanhamento.

Ela contem:

- `Resumo executivo` no topo, com leitura rapida da carteira.
- `Panorama da carteira` com cards executivos e um `donut executivo` mostrando a composicao entre:
  - `Alto Risco`
  - `Atencao`
  - `Seguro`
- `Sinais que merecem monitoramento continuo` em `expanders`, cada um com:
  - descricao do sinal;
  - impacto gerencial;
  - exemplos de clientes afetados no recorte atual;
  - nivel de prioridade.
- `Clientes que precisam de atencao` em `expanders`, cada um com:
  - resumo da conta;
  - gestor;
  - analista;
  - distancia media;
  - status do plano;
  - metricas de andamento;
  - tabela com o plano de acao daquele cliente.

## Plano de acao e acompanhamento

O `Plano de Acao` funciona como base de acompanhamento da home.

Campos usados:

- `Cliente`
- `Ponto de atencao`
- `Acao`
- `Responsavel`
- `Prazo`
- `Status`
- `Atualizacao`
- `Proximo passo`

A home usa esses dados para mostrar, por cliente:

- se ha acao em andamento;
- se ha acao concluida;
- se ha acao atrasada;
- se ha item sem atualizacao;
- qual foi a ultima atualizacao registrada.

Os clientes com maior urgencia tendem a abrir automaticamente quando possuem acao atrasada ou em andamento.

## Como a satisfacao e inferida

Como o CSV nao possui uma coluna explicita de satisfacao do cliente, a aplicacao infere essa leitura a partir de criterios operacionais e comerciais.

Criterios usados:

- `Relacionamento`: piora com distancia media e dispersao geografica.
- `Satisfacao`: piora com distrato, alta distancia e ausencia de equipamentos.
- `Financeiro`: piora com distrato, area zerada e baixo volume de equipamentos.
- `Operacional`: piora com distancia, quantidade de fazendas e cidades atendidas.
- `Engajamento`: piora quando a conta tem pouca recorrencia ou baixo volume operacional.
- `Concorrencia`: piora com distrato e sinais de baixa densidade operacional.

## Escala de pontuacao

- Cada criterio vai de `0` a `5`.
- `0` representa pior situacao e menor satisfacao percebida.
- `5` representa melhor situacao e maior satisfacao percebida.
- Internamente a aplicacao estima sinais de risco e depois inverte essa leitura para entregar uma escala final de satisfacao.
- A pontuacao final e a soma dos 6 criterios.

Classificacao atual:

- `0 a 10`: `Alto Risco`
- `11 a 18`: `Atencao`
- `19 ou mais`: `Seguro`

## Sinais usados na home

Os sinais principais monitorados na home sao:

- `Distrato em carteira`
- `Distancia operacional alta`
- `Baixa densidade operacional`
- `Contas sem equipamentos`
- `Atendimento disperso`

Exemplos de sinais textuais gerados por cliente:

- `Distrato na carteira`
- `Alta distancia media`
- `Sem equipamentos ativos`
- `Baixo volume de equipamentos`
- `Pouca capilaridade`
- `Atendimento disperso`

## Estrutura do CSV

O parser trata automaticamente:

- linhas iniciais de instrucao da planilha exportada;
- numeros com virgula decimal;
- cabecalho real encontrado a partir da linha que contem `Gestor`;
- renomeacao das colunas para uso interno.

Campos principais esperados:

- `Gestor`
- `Analista`
- `Cliente`
- `Fazenda`
- `Cidade`
- `Area (ha)`
- `Quantidade de equipamentos (Cb's)`
- `Quantidade de equipamentos (Clima)`
- `Distrato`
- `Distancia (km)`

## Como executar

1. Crie ou ative um ambiente virtual.
2. Instale as dependencias:

```bash
pip install -r requirements.txt
```

3. Rode a aplicacao:

```bash
streamlit run app.py
```

## Observacoes importantes

- O arquivo `.txt` em `data` nao e usado porque repete o HTML.
- `Plano de Acao` e `GIMB` sao mantidos em sessao (`st.session_state`), entao o acompanhamento atual nao persiste entre reinicios da aplicacao.
- Se surgirem colunas reais de `NPS`, `CSAT`, `chamados`, `renovacao` ou `reclamacoes`, vale substituir os criterios inferidos por indicadores diretos de satisfacao.
