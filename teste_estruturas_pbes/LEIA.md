# teste_estruturas_pbes — o Mini extrai as tabelas das pranchas estruturais?

Teste de 10/10/2026 sobre o acervo `3. PBES/DE` do Drive (projeto estrutural da ETA Vila C, Foz do Iguaçu, SANEPAR): 47 pranchas
em 8 estruturas e o `Resumo de Materiais.pdf`, que serve de gabarito. **Resultado e achados: `RELATORIO.md`.** Propostas para o Mini:
`propostas.md`.

## Estrutura (a rastreabilidade do Caio: estrutura → prancha → tabela → quantidade)

```
resultados/<estrutura>/<codigo_arquivo>/        estrutura = nome da pasta do Drive; codigo_arquivo = nome do PDF sem extensão
    prancha.json                  as caixas achadas (tipo, posição em pt), tempo, erro
    resumo_materiais.csv          DIVISÃO · ÁREA DE FORMAS (m²) · VOLUME DE CONCRETO (m³), TOTAL, LASTRO, ENCHIMENTO
    resumo_aco.csv                AÇO · BIT · COMPR (m) · PESO (kg) e o 'Peso Total'
    tabela_armadura.csv           AÇO · POS · BIT · QUANT · COMPR UNIT/TOTAL (cm), por elemento (PAR1, V3, LAJES…)
    resumo_material_metalico.csv  (só a ETL01: estrutura metálica)
resultados/consolidado/
    quantitativos_por_estrutura.csv   uma linha por estrutura × prancha × quantidade: valor, tabela e caixa de origem, valor do resumo, confere
    conferencia_por_prancha.csv       tudo de cada prancha: forma, concreto, aço por 3 fontes, consenso, reparos
    totais_por_estrutura.csv          totais por estrutura × o que o resumo geral soma para as mesmas pranchas
    divergencias.csv                  só onde não confere, com a origem
    cobertura_resumo_x_pasta.csv      104 linhas do resumo × os 47 PDFs
    mini_localizacao.csv              as tabelas-alvo × as que o malhas() do Mini achou
    resultado_codigo_do_mini.json     o que o código atual do Mini devolveu (0 itens)
    tabela_armadura.csv, resumo_aco.csv, resumo_materiais.csv, resumo_material_metalico.csv   o detalhe empilhado
gabarito/gabarito_resumo.json      o Resumo de Materiais + Relação de Desenhos lidos pelo código (104 linhas × 13 colunas, folha, unidade), fecha com a linha TOTAIS
jsonld/                            a SAÍDA de entrega: obra.jsonld, <estrutura>/<UNIDADE>.jsonld, <estrutura>/<prancha>.jsonld, quantitativos.jsonl, contexto.jsonld
codigo/                            extrator de referência, lote, conferência, teste do Mini, testes
```

Toda linha de todo CSV leva `estrutura`, `codigo_arquivo` e `pagina`. O CSV é a fonte; nada aqui é planilha.

## Como reproduzir

```bash
pip install pdfplumber pypdfium2 pandas numpy opencv-python-headless rapidocr_onnxruntime polars   # + tesseract (apt install tesseract-ocr)
export PBES_BRUTO=~/pbes_bruto                       # os PDFs (nunca vão ao git); estrutura = uma pasta por estrutura
python3 codigo/baixar.py                             # baixa os 47 do Drive pelo link compartilhado (manifesto_drive.py)
python3 codigo/resumo_gabarito.py "<Resumo de Materiais.pdf>" gabarito/gabarito_resumo.json
OMP_THREAD_LIMIT=1 python3 codigo/rodar.py           # as 47 pranchas, 4 processos (~20 min)
python3 codigo/conferir.py                           # consolida e confere
OMP_THREAD_LIMIT=1 python3 codigo/teste_mini_lote.py # o código atual do Mini em 12 pranchas
python3 codigo/testes_pbes.py                        # testes das funções determinísticas
```

O `extrator_pbes.py` importa as funções de geometria do `codigo/tabela.py` do próprio Mini **sem alterá-lo**; só muda a configuração em
memória (`malha_min_linhas = 2`, zona do carimbo liberada), e isso está dito no código.

## O que o teste não cobre

Vision e glm-ocr (só existem no Mac mini); gabarito por linha de armadura (só uma prancha, a ACT01-009, foi conferida por inteiro a olho);
os 58 desenhos que o resumo lista e a pasta não tem. Detalhes em `RELATORIO.md` §7.
