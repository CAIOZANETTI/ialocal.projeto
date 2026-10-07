# Inventário, roteamento e extração especializada — evolução da arquitetura

**Estado: plano, antes do código** (07/10/2026). Pedido do Caio: separar a leitura de projetos em três etapas —
**(1) leitura inicial → inventário**, **(2) classificação e roteamento → escolha do processo e do modelo**,
**(3) extração especializada → dados estruturados** — com a página/prancha como unidade, o inventário independente da
extração e o roteador aprendendo com o histórico. Este documento analisa o que o repositório faz hoje (0v24), diz o
que se aproveita e propõe a arquitetura, os contratos de dados e a ordem de implementação. Nada aqui muda código.

> Premissa: **LER → INVENTARIAR → CLASSIFICAR → ROTEAR → EXTRAIR → NORMALIZAR → ARMAZENAR**, e não
> `PDF → IA grande → texto`.

Índice (os 24 pontos pedidos): [1](#1-arquitetura-atual) arquitetura atual · [2](#2-fluxo-atual) fluxo atual ·
[3](#3-o-que-se-reaproveita) reaproveitamento · [4](#4-onde-entra-a-leitura-inicial) onde entra o inventário ·
[5](#5-implementação-do-inventário) implementação · [6](#6-schema-do-inventariocsv) schema do CSV ·
[7](#7-o-que-sai-do-pdf-sem-ia) sem IA · [8](#8-o-que-exige-visão) com visão · [9](#9-o-que-uma-ia-pequena-classifica) IA pequena ·
[10](#10-regiões-e-bounding-boxes) regiões · [11](#11-arquitetura-do-roteador) roteador ·
[12](#12-catálogo-das-ias) catálogo · [13](#13-seleção-automática-do-executor) seleção ·
[14](#14-estrutura-de-dados-da-extração) dados da extração · [15](#15-tubos-dispositivos-e-estruturas) geometria ·
[16](#16-georreferenciamento) georreferência · [17](#17-formatos-espaciais) formatos ·
[18](#18-estrutura-de-arquivos) arquivos · [19](#19-rastreabilidade) rastreabilidade ·
[20](#20-confiança-e-revisão) confiança · [21](#21-métricas-de-cada-ia) métricas ·
[22](#22-impacto-no-código-atual) impacto · [23](#23-plano-incremental) plano · [24](#24-testes) testes

---

## 1. Arquitetura atual

O repositório é a etapa "projeto" do ecossistema `ialocal.*`: roda no Mac mini, lê o que o `ialocal.extrator`
entrega, extrai e publica CSVs no Drive. Princípios que **já** estão no código e que a nova arquitetura preserva:
código antes de IA; número só é fato com dois leitores de natureza diferente; nenhuma invenção (presença,
concordância, conferência, rastro — `plano_projeto.md` §11.1); regras em JSON (`conceitos/`), não no código;
congelamento das respostas de modelo; refazer automático por versão (`versoes.jsonl → muda`).

| camada | módulo | papel |
|---|---|---|
| entrada | `codigo/entrega.py` | lê `~/dados/extracao/projeto_entrega/parte_*.parquet` (só PDFs cuja **primeira página** é A3 ou maior, `entrega.py:30`) e o mapa de obras; soma os anexos das demandas (`respostas.py`) |
| orquestração | `codigo/ciclo.py` | a rodada: `situacao()` → `proxima_tarefa()` (`ciclo.py:101`) decide **por `if`** entre `ler_prancha`, `ler_sondagem`, `ler_sondagem_ia`, `ler_prancha_ia`; código em tudo, depois IA na vez da GPU do maestro (`cliente_gpu.py`, prioridade 7) |
| leitura de prancha | `codigo/prancha.py` | `perfilar` (formato, classe, OCG, sinais — **só a página 0**, `prancha.py:82`), `ler_carimbo` (região fixa `[0.7, 0.62, 1, 1]`), `familia` (regex), `eixo` (faixa colorida ou traços das camadas de tubo), `ler_prancha_ia` (fatias de 1.100 px × glm-ocr e Vision, imagens coladas como tabela, conferência eixo × relação) |
| leitura de boletim | `codigo/sondagem.py` | reconhece o boletim (sinais no texto ou nome), lê por página: texto real pelo código, digitalizada por glm-ocr × Vision |
| modelos | `codigo/ia.py` | porta única: Ollama (glm-ocr, gemma3, qwen3), Vision (processo à parte, com prazo, devolve palavras com caixa normalizada), Apple FM, NVIDIA (exceção §5.6 até 03/11); congelamento por chave |
| agentes externos | `codigo/agentes.py` | Kimi K3 e reservas (GLM-5.3 Flash, Muse Glimmer, DeepSeek V4.1 Flash); Parse descontinuado; paralelo com ritmo por provedor |
| decisão entre leitores | `codigo/curadoria.py` | `confirmada` (testemunha + leitor), `confirmada_ia`, `divergente`, `so_<leitor>` |
| leitor só de código | `codigo/grade.py` | tabela pelas caixas das palavras do Vision, sem modelo |
| medição | `codigo/bancada.py` | todos os leitores contra gabarito (tabelas de Cambé, controle negativo, boletins): qualidade, tempo útil, taxa de erro, tempo perdido, **veredito** (continua / troca / descontinua) |
| persistência | `codigo/comum.py` | uma `dados/<familia>.parquet` por família, troca por chave `id × extrator × arquivo` (`comum.py:21`), JSONL com trava, CSV `;` com BOM para o Drive |
| conceitos | `conceitos/*.json` | `prancha.json` (reconhecer, famílias, carimbo, eixo, fatias, padrões, conferência, classe), `sondagem.json`, `ia.json`, `agentes.json`, `bancada.json`, `operacao.json`, `demandas.json`, prompts versionados |
| protótipos | `notas/prototipo_prancha/` | separação por camada OCG (pikepdf), malha → UTM, perfil pela geometria — validados na AAT-06, **fora** do pipeline |

**Diagnóstico em uma frase:** o repositório já tem as peças boas (perfil barato pelo pdfium, camada de leitura,
curadoria, bancada com veredito, catálogo de modelos em JSON), mas elas estão **acopladas por documento** e a
decisão de "quem lê" está **escrita em `if`**, não em dados.

## 2. Fluxo atual

```
extrator (2v94/2v96): PDF com 1ª página ≥ A3 (+ boletim A4) → projeto_entrega
        │
ciclo.rodada()
        │  1ª passada (código, sem GPU)
        ├─ ler_prancha(documento)            prancha.py:402
        │     perfilar(página 0) → formato, classe (raster | vetorial_texto | vetorial_curva), OCG, sinais
        │     e_boletim?  ── sim → marca boletim_sondagem, e_prancha = False
        │     e_prancha?  ── sim → carimbo (região fixa), família (regex), eixo, nº de fatias
        │     grava prancha.parquet (+ carimbo.parquet se o carimbo tem texto real)
        │  2ª passada
        ├─ ler_sondagem(documento)           páginas com texto, pelo código
        │
        │  IA (vez da GPU, um documento por vez, prioridade 7)
        ├─ ler_sondagem_ia                   páginas digitalizadas: glm-ocr × Vision
        └─ ler_prancha_ia                    carimbo desenhado (glm-ocr × Vision), fatias da página 0,
                                             imagens coladas em faixas, conferência eixo × tubo, desempate da família
        │
publicar(): pranchas.csv, prancha_leituras.csv, prancha_tabelas.csv, carimbos.csv, sondagens*.csv → Drive
status.json → maestro
```

**Limites do fluxo atual, em relação ao pedido:**

1. **A unidade é o arquivo e só a página 0 é prancha.** `perfilar`, `ler_carimbo`, `eixo` e `ler_fatias` olham
   `documento[0]`; `fatias.paginas_com_ia = 1`. Um `ADUTORA_REV03.pdf` de 6 páginas vira uma linha, e as páginas 2–6
   (planta e perfil, detalhes, quantitativos, sondagem) não existem para o sistema.
2. **O filtro de entrada é pela primeira página.** O extrator entrega o PDF se a página 1 é A3+; um jogo com capa A4
   e pranchas A1 não chega. O A4 só chega se for boletim (2v96).
3. **Perfil e extração estão misturados** em `ler_prancha`: o que é inventário (formato, classe, camadas) e o que já
   é extração (campos do carimbo, eixo em mm) saem na mesma linha e na mesma tarefa.
4. **O roteamento é fixo.** `proxima_tarefa` conhece quatro caminhos; o carimbo vai ao glm-ocr × Vision porque está
   escrito, não porque a bancada mostrou que é o melhor para aquele tipo de recorte.
5. **Localização por fração fixa.** O carimbo é sempre `[0.7, 0.62, 1.0, 1.0]`; o próprio `plano_projeto.md` §4-A e a
   skill dizem que fração fixa não generaliza (0,8° de giro desloca uma estaca).
6. **A bancada mede, mas não decide.** O veredito sai em `saidas/bancada_agentes.csv` para o Caio ler; nenhum código
   consome o placar para escolher executor.
7. **Confiança é categórica** (`confirmado`, `so_glm`…), sem número calibrado e sem fila de revisão.
8. **Não há geometria no mundo.** O eixo sai em mm de papel (e metros pela escala confirmada); malha, georreferência,
   perfil e DXF existem só nos protótipos.

## 3. O que se reaproveita

| peça existente | onde | vira | observação |
|---|---|---|---|
| `formato()` | `prancha.py:30` | inventário: formato | acrescentar formato estendido (A1×2, A0+) e orientação |
| `perfilar()` (pdfium: caracteres, caminhos, imagens, fração de imagem, OCG) | `prancha.py:77` | **núcleo da Etapa 1** | passar a rodar **por página**; tirar o retorno antecipado de formato pequeno (`:87`) |
| `classe()` (raster / vetorial_texto / vetorial_curva) | `prancha.py:55` | `tipo_pdf` + `texto_pdf` | acrescentar `hibrido` e `raster_com_ocr` |
| `camadas()` (OCG do catálogo) e `camada_da_marca()` (OC por objeto) | `prancha.py:40`, `:284` | inventário: camadas por página e **caixa por camada** | a caixa da camada `MALHA`, `Grade_perfil`, `TUBO…` já é uma região |
| `sinais()`, `familias.padroes`, `familias.desenhos`, `codigo_desenho` | `prancha.py:63`, `prancha.json` | classificação preliminar por regra | viram `conceitos/taxonomia.json` + `inventario.json` |
| `e_boletim()` | `sondagem.py:23` | `tipo_documento = sondagem` | já funciona em A4 e digitalizado |
| `ler_carimbo()` + `campos_do_carimbo()` | `prancha.py:151`, `:131` | título, nº do desenho e revisão "fáceis" no inventário; o carimbo completo fica na Etapa 3 | a região passa a vir de `regioes.parquet` |
| `limites()` das imagens + `get_px_size()` | `prancha.py:72`, `:594` | DPI efetivo de cada imagem → qualidade de OCR | — |
| `ia.ler_com_vision()` com `palavras` (caixa normalizada, origem em cima) | `ia.py:341`, `:442` | âncoras de região na página raster (Etapa 1, nível 1b) | mesma convenção de bbox do pedido |
| `grade.py` | — | processo `tabela_por_palavras` (Etapa 3) | sem mudança |
| `curadoria.py` | — | resolução de alegações (Etapa 3) | entra a confiança numérica derivada do status |
| `ia.congelado()` | `ia.py:53` | rastro de toda chamada de modelo | a assinatura vira a chave da evidência |
| `bancada.py` (`resumo_das_chamadas`, `resumir`, `veredito`) | `:490`, `:540`, `:560` | **alimenta o desempenho que o roteador consome** | estratificar por tipo de região × natureza × formato |
| `agentes.json`, `ia.json`, `bancada.json → locais` | `conceitos/` | **catálogo unificado** `modelos.json` | — |
| `comum.gravar/ler/publicar`, `versoes.jsonl` | `comum.py` | persistência de todas as etapas | `gravar` aceita a chave da família (a página entra na chave) |
| `cliente_gpu`, quarentena, limite por prancha | `ciclo.py`, `operacao.json` | execução da Etapa 3 | — |
| protótipos `camadas.py`, `georef.py`, `perfil.py` | `notas/prototipo_prancha/` | processos `isolar_camada`, `georreferenciar`, `ler_perfil` | validados na AAT-06 (eixo 540,02 × 540 m; perfil ≤ 3 mm) |
| `testes.py` (`pdf_prancha`, `pdf_com_camadas`, `pdf_em_branco`, servidor NVIDIA falso) | — | fixtures dos testes novos | — |

## 4. Onde entra a leitura inicial

**Entre a entrega e tudo o mais**, como tarefa de código própria, `inventariar`, que roda antes de `ler_prancha` e
substitui a parte de perfil dele:

```
entrega.documentos()  ──►  inventariar(documento)          ETAPA 1 (código; visão leve só na raster)
                               │  documentos.parquet, paginas.parquet, regioes.parquet → inventario.csv
                               ▼
                          rotear(paginas, regioes, catálogo, desempenho)      ETAPA 2 (código puro)
                               │  tarefas.parquet (uma por página/região × processo)
                               ▼
                          ciclo: executa as tarefas (código já; IA na vez da GPU)     ETAPA 3
                               │  alegacoes/*.parquet (+ evidências)
                               ▼
                          normalizar → metadados, engenharia, espacial → exportadores
```

Três regras de fronteira:

- **O inventário não extrai.** Ele pode ler o título e a revisão quando estão em texto real (custo zero), mas não lê
  o carimbo desenhado, não transcreve tabela, não mede eixo. Se precisa de OCR para responder, a resposta é
  `incerto` e o roteador decide.
- **O inventário é refeito sozinho** quando o hash do arquivo ou a versão de `inventariar` mudam (o mesmo `muda` de
  `versoes.jsonl`), sem refazer a extração — e a extração de uma página só é refeita se a **decisão** do roteador
  para ela mudou.
- **Entrada independente do extrator.** Além da entrega, `inventario.py pasta <dir>` inventaria qualquer pasta de
  PDFs (o caso "pasta de projetos" do pedido) gravando só em `dados/`. Para o acervo de produção, o extrator precisa
  entregar **todo PDF** (ou todo PDF com alguma página ≥ A3 ou boletim), não só o de primeira página A3+: mudança no
  `ialocal.extrator`, fora deste repositório — fica como pedido ao Caio (§22).

## 5. Implementação do inventário

Módulo novo `codigo/inventario.py`, regras em `conceitos/inventario.json`. Só pypdfium2 (Apache/BSD) e pdfminer via
pdfplumber para o catálogo; **sem PyMuPDF** (AGPL, decisão D2 do `plano_projeto.md`). pikepdf (MPL-2.0, já usado no
protótipo) entra só para o que o pdfium não expõe (dicionário `/Measure /GEO`, filtros de imagem).

**Três níveis, do mais barato ao mais caro; cada página para no primeiro que responde:**

| nível | o que faz | custo alvo (premissa, a medir) | quando |
|---|---|---|---|
| **N0 — metadados** | hash, nº de páginas, Producer/Creator, versão, criptografia, OCG do catálogo, GeoPDF; por página: tamanho, `/Rotate`, formato | < 50 ms por arquivo | sempre |
| **N1 — conteúdo nativo** | contagem de caracteres, palavras com posição, caminhos, segmentos retos, imagens (caixa, px, DPI efetivo, filtro), OC por objeto e caixa por camada, regiões vetoriais (§10), regras de tipo (§9) | < 1 s por página na folha de 78 mil caminhos (o `perfilar` já faz 0,9 s) | sempre |
| **N1b — visão leve** | render a 72–100 DPI, linhas e retângulos por numpy, estimativa de giro e nitidez; Vision na página reduzida para achar âncoras (`ESCALA`, `FOLHA`, `PERFIL`, `QUANTIDADE`) | 2–5 s por página | só raster/híbrida, ou vetorial sem texto real e sem OCG |
| **N2 — IA pequena** | Apple FM / qwen3 sobre o texto já lido; candidato de layout medido em bancada | segundos, na vez da GPU quando é Ollama | só quando as regras empatam ou a confiança < limiar (§9) |

Esboço do núcleo (estilo do repositório, só para fixar o contrato):

```python
def inventariar(documento, rodada):
    """Etapa 1: o que existe no PDF, página a página, sem extrair. Uma linha em documentos, uma por página em paginas,
    as regiões achadas em regioes. Página que falha vira linha com o erro; o arquivo que não abre, linha de documento."""
    pdf = pdfium.PdfDocument(documento['arquivo_local'])
    doc = perfil_do_documento(pdf, documento)                       # N0
    paginas, regioes = [], []
    for numero in range(len(pdf)):
        pagina = perfil_da_pagina(pdf, numero, doc)                 # N0 + N1
        achadas = regioes_vetoriais(pdf[numero], pagina)            # §10, código
        if precisa_de_visao(pagina, achadas):
            achadas += regioes_raster(pdf[numero], pagina)          # N1b
        pagina.update(classificar(pagina, achadas, doc))            # §9: regra → empate → IA pequena
        paginas.append(pagina); regioes += achadas
    comum.gravar('inventario_documento', [doc], chaves=('id_documento',))
    comum.gravar('inventario_pagina', paginas, chaves=('id_pagina',))
    comum.gravar('inventario_regiao', regioes, chaves=('id_pagina', 'id_regiao'))
```

**Identidade.** `id_documento` = os 16 primeiros hex do SHA-256 do arquivo (o mesmo PDF que chega por zip e por
e-mail é um só); `id_pagina = f'{id_documento}_P{n:03d}'`; `id_regiao = f'{id_pagina}_R{k:03d}'`. O `id` do extrator,
o caminho, o acervo e a obra ficam como colunas de origem. O formato `PRJ001_P001` do pedido é a **vista** para
humanos (`codigo_curto`, sequencial por obra), nunca a chave — sequencial muda quando entra um arquivo novo.

**Paralelismo.** O inventário é só CPU, não pede a vez da GPU: `ProcessPoolExecutor` por documento com
`os.cpu_count() - 2` processos no CLI; na rodada, entra na 1ª passada como o `ler_prancha` hoje.

## 6. Schema do `inventario.csv`

Uma linha por página. É a visão resumida, publicada para o Excel (`;`, UTF-8 com BOM, como os outros CSVs). O
completo fica em `inventario_pagina.parquet`; o que tem cardinalidade variável fica em `inventario_regiao.parquet`
(regiões) e `inventario_documento.parquet` (arquivo). Booleanos de presença são **tri-estado**: `sim`, `nao`,
`incerto` — "não achei" e "não sei" são respostas diferentes, e só o `incerto` pede visão ou IA.

| # | coluna | tipo | domínio / exemplo | origem |
|---|---|---|---|---|
| | **identificação** | | | |
| 1 | `id_pagina` | texto | `a3f9c2e17b04d518_P002` | código |
| 2 | `codigo_curto` | texto | `PRJ001_P002` (vista humana, por obra) | código |
| 3 | `id_documento` | texto | 16 hex do SHA-256 | código |
| 4 | `hash_arquivo` | texto | SHA-256 completo | código |
| 5 | `arquivo` | texto | `ADUTORA_REV03.pdf` | entrega |
| 6 | `caminho` | texto | caminho de origem | entrega |
| 7 | `acervo`, `obra` | texto | da entrega/mapa de obras | entrega |
| 8 | `pagina` | inteiro | 1… | código |
| 9 | `total_paginas` | inteiro | | código |
| 10 | `numero_desenho` | texto | só se em texto real ou no nome | código |
| 11 | `titulo` | texto | só se em texto real | código |
| 12 | `revisao` | texto | `R3`, `A0` | código (nome ou carimbo com texto) |
| 13 | `revisao_origem` | texto | `nome` · `carimbo_texto` · `` | código |
| | **físico** | | | |
| 14 | `largura_mm`, `altura_mm` | inteiro | já com `/Rotate` aplicado | código |
| 15 | `formato` | texto | `A0` · `A1` · `A2` · `A3` · `A4` · `A1_estendido` · `fora_de_serie` · `pequeno` | código |
| 16 | `orientacao` | texto | `paisagem` · `retrato` | código |
| 17 | `rotacao` | inteiro | 0 · 90 · 180 · 270 (`/Rotate`) | código |
| | **natureza do PDF** | | | |
| 18 | `tipo_pdf` | texto | `vetorial` · `raster` · `hibrido` | código |
| 19 | `texto_pdf` | texto | `real` · `curva` · `ocr_embutido` · `ausente` | código |
| 20 | `texto_pesquisavel` | tri | `sim` · `nao` · `incerto` | código |
| 21 | `caracteres` | inteiro | `count_chars` do pdfium | código |
| 22 | `caminhos` | inteiro | objetos de caminho | código |
| 23 | `camadas_cad` | inteiro | OCG presentes na página | código |
| 24 | `imagens` | inteiro | imagens embutidas | código |
| 25 | `fracao_imagem` | decimal | 0–1 da área da folha | código |
| 26 | `dpi_imagem` | inteiro | DPI efetivo da maior imagem | código |
| 27 | `qualidade_ocr` | texto | `boa` · `media` · `ruim` · `nao_se_aplica` | código (N1/N1b) |
| 28 | `geopdf` | tri | `/Measure /GEO` presente | código |
| | **classificação preliminar** | | | |
| 29 | `tipo_documento` | texto | `planta` · `perfil` · `planta_perfil` · `detalhe` · `corte` · `locacao` · `forma` · `armacao` · `sondagem` · `ose` · `tabela` · `quantitativo` · `memorial` · `croqui` · `capa_indice` · `administrativo` · `outro` | regra → IA pequena |
| 30 | `tipo_documento_confianca` | decimal | 0–1 (§20) | derivada |
| 31 | `tipo_documento_origem` | texto | `regra` · `ia_concordante` · `humano` | — |
| 32 | `classe_obra` | texto | `obra_linear/agua/adutora` (caminho da taxonomia) | regra → IA pequena |
| 33 | `classe_obra_confianca` | decimal | 0–1 | derivada |
| | **elementos presentes** (tri-estado) | | | |
| 34 | `possui_carimbo` | tri | | §10 |
| 35 | `possui_legenda` | tri | | |
| 36 | `possui_planta` | tri | | |
| 37 | `possui_perfil` | tri | | |
| 38 | `possui_tabela` | tri | | |
| 39 | `qtd_tabelas` | inteiro | regiões do tipo tabela* | |
| 40 | `possui_tabela_quantidades` | tri | | |
| 41 | `possui_tabela_materiais` | tri | | |
| 42 | `possui_coordenadas` | tri | malha ou quadro de coordenadas | |
| 43 | `possui_estaqueamento` | tri | | |
| 44 | `possui_notas` | tri | | |
| 45 | `possui_detalhes` | tri | | |
| 46 | `possui_sondagem` | tri | | |
| 47 | `possui_imagens` | tri | imagem colada que não é a folha inteira | |
| | **decisão** | | | |
| 48 | `dificuldade_estimativa` | texto | `baixa` · `media` · `alta` | regra (§7) → depois aprendida |
| 49 | `dificuldade_motivos` | texto | `raster;A0;ocr_ruim` | regra |
| 50 | `confianca_classificacao` | decimal | mínimo das confianças de tipo e classe | derivada |
| 51 | `status` | texto | `inventariado` · `revisar` · `erro` | — |
| 52 | `erro` | texto | | — |
| 53 | `segundos` | decimal | tempo do inventário da página | — |
| 54 | `versao_codigo`, `commit`, `inventariado_em` | texto | | `comum.gravar` |

`inventario_documento.parquet` (uma linha por arquivo): `id_documento, hash_arquivo, tamanho_bytes, total_paginas,
produtor, criador, versao_pdf, criptografado, data_criacao, ocg_nomes (JSON), geopdf, classe_obra_documento,
revisao_nome, codigo_desenho_nome, paginas_por_tipo (JSON)`. O **Producer/Creator** é sinal forte e de custo zero:
`AutoCAD 2022…`/`Civil 3D` → vetorial de CAD; nome de software de escâner → digitalizado; "Paper Capture"/OCR →
`raster` com `texto_pdf = ocr_embutido`.

`inventario_regiao.parquet`: ver §10.

## 7. O que sai do PDF sem IA

| dado | como | já existe? |
|---|---|---|
| hash, tamanho, nº de páginas, versão, criptografia, Producer/Creator, datas | pdfium `get_metadata_dict`, `hashlib` | parcial (o extrator tem a versão) |
| tamanho, rotação, formato, orientação | `get_size`, `get_rotation`, `formato()` com tolerância | sim (`formato`) |
| texto real e quantidade | `get_textpage().count_chars()`; palavras com caixa (`get_charbox`/`get_text_bounded`) | sim (contagem) |
| texto em curva (fonte SHX virou desenho) | muitos caminhos pequenos agrupados em linha, com altura de 1,5–5 mm de papel e pouco texto real; hoje é só `caracteres < 1500` | heurística a melhorar |
| texto invisível sobre imagem (PDF digitalizado com OCR) | imagem cobrindo a folha **e** texto real → `ocr_embutido` (o modo de render 3 do texto confirma, se o pdfium instalado expuser) | não |
| objetos vetoriais | contagem de caminhos, segmentos retos horizontais/verticais, cores e espessuras distintas | parcial |
| camadas do CAD | OCG do catálogo; OC por objeto (`camada_da_marca`) e caixa de cada camada na página | parcial (`camadas`, `tracos_por_camada`) |
| imagens embutidas | caixa, px, **DPI efetivo** = px ÷ (lado em pt ÷ 72), bits, filtro (DCT, JBIG2, CCITT → escâner bilevel) | parcial |
| GeoPDF | `/VP` → `/Measure /GEO` (pikepdf) | não |
| nº do desenho, revisão | nome do arquivo (`codigo_desenho`, `revisao_nome`) e texto real do carimbo | sim |
| título | rótulo-âncora no texto real | sim (`ancoras.titulo`) |
| tipo de documento e classe da obra **quando há texto real** | regras de §9 sobre nome + texto + camadas | parcial (`familia`, `desenhos`) |
| regiões nas vetoriais | §10: moldura, carimbo por âncora, tabelas por grade de linhas, vistas por título, caixa por camada, imagens coladas | parcial (só imagens e carimbo fixo) |
| dificuldade estimada | pontuação por regra (abaixo) | não |

**Dificuldade por regra (versão 1, os pesos são premissa):** `raster` +2 · `hibrido` +1 · `texto_pdf = curva` +1 ·
A0/A1/estendido +1 · `qualidade_ocr = ruim` +2 / `media` +1 · giro estimado > 0,5° +1 · tabela em imagem +1 ·
caminhos > 50 mil +1. Soma 0–1 `baixa`, 2–3 `media`, ≥ 4 `alta`. A partir da F10 a dificuldade passa a ser
**aprendida**: o tempo e a qualidade que cada página de fato custou (§21) contra estas mesmas variáveis.

**Qualidade provável de OCR (raster):** DPI efetivo ≥ 300 `boa`, 200–299 `media`, < 200 `ruim`; rebaixa um nível com
imagem bilevel abaixo de 300 DPI, giro > 1° ou nitidez baixa (variância do laplaciano no render de 100 DPI, numpy).

## 8. O que exige visão

"Visão" aqui é ver a **imagem renderizada** — por código (numpy sobre o render) ou por OCR clássico — não
necessariamente um modelo generativo.

| dado | por quê | com quê |
|---|---|---|
| tudo de página `raster` | não há texto nem vetor | N1b: linhas e retângulos (numpy), Vision em resolução baixa para âncoras |
| carimbo, tabelas e vistas quando o texto é **curva** e não há OCG | o título "PERFIL" é desenho | N1b na região candidata |
| texto de imagem colada (relação de materiais) | é imagem | Etapa 3 (glm-ocr × Vision, grade) — o inventário só registra a região |
| giro, nitidez, contraste | propriedade da imagem | numpy no render |
| `possui_*` que dependem de ler | "a tabela é de quantidades ou de coordenadas?" | Vision nas âncoras do cabeçalho; sem âncora → `incerto` |
| símbolos (ventosa, registro, PV) | desenho, não texto | **não é inventário**: Etapa 3 |

Regra: **o inventário nunca manda a folha inteira a um modelo generativo** (T1 de 26/09: o gemma3 inventou 21 cotas
na folha inteira). Visão no inventário é código e OCR não generativo.

## 9. O que uma IA pequena classifica

Só depois das regras, e só com **pergunta fechada** sobre **texto já lido** (o padrão do `desempatar`,
`prancha.py:636`: vale só se os dois motores escolhem a mesma opção da lista).

| pergunta | entrada | motores | quando |
|---|---|---|---|
| `tipo_documento` | nome + títulos + texto do carimbo + notas (≤ 3.000 caracteres) + resumo estrutural (formato, nº de tabelas, tem perfil) | Apple FM e qwen3, concordância | regras empatam ou não casam |
| `classe_obra` (nó da taxonomia) | o mesmo + código do desenho | Apple FM e qwen3 | idem (hoje: `desempatar`) |
| tipo de tabela | só o cabeçalho lido (Vision/texto real) | Apple FM | cabeçalho fora dos sinônimos de `bancada.json → grade.cabecalho` |
| tipo de página pela miniatura | imagem de ~1.000 px | VLM local ou de layout | **hipótese**, só depois de medir: o T8 de 26/09 refutou o gemma3 para zonear (3 de 6) |

**Regras primeiro.** Sinais de `tipo_documento` (em `conceitos/inventario.json`, com exemplos que casam e que não
casam, como os padrões do `prancha.json`):

- `planta_perfil`: título `PLANTA E PERFIL`/`PTPER`, ou região de planta **e** região de perfil na mesma folha;
- `perfil`: grade de linhas horizontais regulares + rótulos `COTA`, `ESTACA`, `TERRENO`, `GERATRIZ`;
- `sondagem`: `e_boletim()` (já existe), formato A4/A3;
- `ose`: formulário Sanepar (rótulos `Adutora:`, `Declividade da Adutora` — os que hoje são `rotulos_ignorados`), A3;
- `quantitativo`/`tabela`: uma tabela ocupa > 50 % da folha e não há vista;
- `detalhe`: `DETALHE`, `DET`, `VENDS`, várias vistas pequenas com escala 1:10–1:50;
- `memorial`/`administrativo`: A4 retrato, texto real corrido, sem caminhos densos;
- `capa_indice`: `LISTA DE DESENHOS`, `ÍNDICE`, tabela de números de desenho.

**O formato é indício, nunca regra** (pedido do Caio): A4 aumenta a probabilidade a priori de `sondagem`, `ose`,
`memorial`; não decide. No modelo de pontuação, o formato entra como um sinal com peso, ao lado dos outros.

**Taxonomia (`conceitos/taxonomia.json`).** Hierarquia `grupo/sistema/familia`, que substitui o mapa plano
`familias.grupo` do `prancha.json` e é extensível a outras disciplinas:

```json
{
  "obra_linear": {
    "agua":        {"adutora": {}, "rede_distribuicao": {}, "linha_recalque": {}},
    "esgoto":      {"rede_coletora": {}, "coletor_tronco": {}, "interceptor": {}, "emissario": {}, "linha_recalque": {}},
    "gas": {}, "combustivel": {}, "drenagem": {}, "outros": {}
  },
  "obra_localizada": {"eta": {}, "ete": {}, "elevatoria": {}, "reservatorio": {}, "edificacao": {}},
  "apoio": {"sondagem": {}, "topografia": {}, "cadastro": {}}
}
```

Cada folha da árvore tem os sinais (regex no nome, no código do desenho, no texto, nas camadas). Hoje
`coletor_esgoto` junta rede coletora, coletor tronco, interceptor e emissário num padrão só, e `recalque` não diz se
é de água ou esgoto: o código do desenho (`SAA`/`SES`) desambigua o sistema. **A classificação é atributo, não
pasta**: o sistema não move arquivos (o extrator é dono deles); a árvore `projetos/obra_linear/agua/adutora/` do
pedido sai como **vista** (filtro do `inventario.csv`, ou links simbólicos gerados num diretório de saída).

## 10. Regiões e bounding boxes

**Convenção única:** `bbox = [x0, y0, x1, y1]` normalizado 0–1, **origem no canto superior esquerdo da página como
é exibida** (depois do `/Rotate`). É a convenção que o repositório já usa no `prancha.json → carimbo.regiao` e nas
palavras do Vision (`ia.caixa_de_cima`), e a do exemplo do pedido. A página guarda `largura_mm`/`altura_mm`, então
o recorte em pt ou px sai por multiplicação.

`inventario_regiao.parquet`:

| coluna | exemplo |
|---|---|
| `id_pagina`, `id_regiao` | `…_P002`, `…_P002_R003` |
| `tipo` | `moldura` · `carimbo` · `quadro_revisoes` · `legenda` · `notas` · `planta` · `perfil` · `corte` · `detalhe` · `situacao` · `malha` · `tabela` · `tabela_quantidades` · `tabela_materiais` · `tabela_coordenadas` · `imagem_colada` · `sondagem_perfil` · `outro` |
| `x0, y0, x1, y1` | 0–1 |
| `confianca` | 0–1 |
| `metodo` | `ocg` · `grade_vetorial` · `ancora_texto` · `imagem_embutida` · `retangulo_vetorial` · `raster_linhas` · `vision_ancora` · `modelo_layout` · `fracao_fixa` |
| `natureza` | `texto` · `curva` · `imagem` (por onde a região se lê — a "camada" do 0v2, agora por região) |
| `camada_cad` | `MALHA`, `Grade_perfil`… |
| `titulo`, `escala_h`, `escala_v` | `PERFIL`, `1:1000`, `1:100` (só se em texto real) |
| `linhas`, `colunas` | da grade, para tabela |
| `dpi_recomendado` | menor DPI em que o menor texto da região tem ≥ 20 px de altura, limitado por `ia.json → lado_max_px_ia` |
| `pai` | região que a contém (o quadro de revisões dentro do carimbo) |

**Estratégia em camadas, cada uma registra o `metodo` e a confiança dela:**

1. **Camadas do CAD (OCG) — vetorial com camadas.** A caixa dos objetos de cada camada na página é uma região de
   graça: `MALHA` → planta georreferenciável; `Grade_perfil` → perfil; `TUBO…` → traçado; `C-ROAD-SAMP` →
   estaqueamento. O mapa camada → tipo é **dado por projetista** em `inventario.json` (a viabilidade de 26/09 mostrou
   que nome engana: `600_PVCDEFoFo_DN0300` era a própria adutora) — por isso a região por camada ganha confiança
   média e é confirmada por outro método.
2. **Âncora de texto — vetorial com texto real.** Palavras com posição (pdfium). Carimbo = o menor retângulo fechado
   do canto inferior direito que contém ≥ 2 rótulos-âncora (`ESCALA`, `FOLHA`, `DESENHO`, `CREA`); vista = o título
   (`PLANTA`, `PERFIL`, `CORTE A-A`, `DETALHE 3`) + o retângulo ou o agrupamento de geometria acima dele; tabela de
   quantidades = cabeçalho com `QUANT`/`UND`/`DISCRIMINAÇÃO` (a skill `extrair-quantitativos-pdf` localiza tabela
   assim, "auto-localização por título-âncora").
3. **Geometria vetorial — sempre que há caminhos.** Segmentos retos horizontais e verticais (pdfium, sem
   pdfplumber, que levou 69 s na folha de 78 mil caminhos): moldura = maior retângulo; **tabela = malha de ≥ 3
   horizontais × ≥ 2 verticais que se cruzam**, com linhas e colunas contadas; perfil = feixe de horizontais
   regulares longas com uma polilinha contínua por cima. Retângulos fechados agrupados formam blocos candidatos.
4. **Imagens embutidas.** Caixa de cada imagem que não é a folha inteira → `imagem_colada` (já existe em
   `ler_imagens`), com o DPI efetivo.
5. **Raster (N1b).** Render a 100 DPI; binarização; corridas horizontais e verticais longas em numpy (o mesmo
   raciocínio do `ia.sem_tracos`) → moldura, retângulos e grades de tabela; o Vision na página reduzida dá as
   palavras com caixa, e as âncoras nomeiam os retângulos. Giro estimado pelas linhas longas antes de tudo (§4-A do
   `plano_projeto.md`: endireitar primeiro). OpenCV (`opencv-python-headless`, Apache-2.0) é opcional e só entra se o
   numpy puro ficar lento — medir antes.
6. **Modelo de layout — candidato, não rota.** Um detector de layout com classe e caixa (o Nemotron Parse devolvia
   isso; foi descontinuado pela transcrição em laço, não pela caixa) pode ser medido **só para regiões**, com IoU
   contra gabarito. Licença conferida antes (§5.1 do MASTER-PLAN: detector baseado em `ultralytics` é AGPL, o mesmo
   problema do PyMuPDF).
7. **Fração fixa — último recurso.** `[0.7, 0.62, 1, 1]` continua como `metodo = fracao_fixa`, confiança baixa,
   para o carimbo não sumir quando nada acima achou.

**Fusão.** Regiões do mesmo tipo de métodos diferentes com IoU ≥ 0,5 viram uma, com a caixa do método mais preciso
(texto > geometria > camada > raster > fração) e confiança combinada (dois métodos independentes concordando sobem a
confiança — é a regra dos dois leitores aplicada à região). `possui_X = sim` se há região do tipo X com confiança ≥
0,7; `nao` se todos os métodos aplicáveis rodaram e não acharam; `incerto` no resto.

## 11. Arquitetura do roteador

Módulo `codigo/roteador.py`, **código puro e determinístico**: entra inventário + catálogo + desempenho + regras,
sai uma lista de tarefas. Não chama modelo. Isso o torna testável com dados falsos e auditável (cada decisão grava o
porquê).

```
inventario_pagina + inventario_regiao
            │
            ▼
   1. unidades de trabalho        página inteira (sondagem, memorial) ou região (carimbo, tabela, perfil…)
            │                     regra em rotas.json: tipo de documento/região → unidade
            ▼
   2. processos candidatos        rotas.json: (tipo_regiao × natureza) → processos que sabem ler aquilo
            │                     ex.: tabela × texto → tabela_por_texto; tabela × imagem → tabela_por_palavras, tabela_ocr_modelo
            ▼
   3. executores viáveis          modelos.json: modalidade, ligado, prazo, política de dados, limites (lado, timeout)
            │
            ▼
   4. pontuação                   desempenho.parquet: qualidade (limite inferior) × custo × fila → §13
            │
            ▼
   5. plano de prova              leitor principal + testemunha de natureza diferente + conferência de código
            │                     escada de escalonamento (segundo leitor → modelo superior → revisão humana)
            ▼
   tarefas.parquet + decisoes.parquet
```

**`conceitos/rotas.json`** (esboço):

```json
{
  "unidades": {"sondagem": "pagina", "memorial": "pagina", "planta_perfil": "regiao", "quantitativo": "regiao"},
  "processos": {
    "carimbo":   {"texto": ["carimbo_por_ancora"], "curva": ["carimbo_ocr"], "imagem": ["carimbo_ocr"]},
    "tabela_*":  {"texto": ["tabela_por_texto"], "curva": ["tabela_por_palavras", "tabela_ocr_modelo"],
                  "imagem": ["tabela_por_palavras", "tabela_ocr_modelo"]},
    "planta":    {"texto": ["eixo_vetorial", "camadas"], "curva": ["eixo_vetorial", "camadas", "rotulos_ocr"],
                  "imagem": ["fatias_ocr"]},
    "perfil":    {"texto": ["perfil_vetorial"], "curva": ["perfil_vetorial", "rotulos_ocr"], "imagem": ["fatias_ocr"]},
    "malha":     {"*": ["malha_coordenadas"]},
    "sondagem":  {"texto": ["sondagem_texto"], "imagem": ["sondagem_ocr"]}
  },
  "prova": {"numero": "testemunha_e_leitor", "texto_livre": "um_leitor", "classe": "regra_ou_dois_votos"},
  "escada": ["segundo_leitor", "executor_superior", "revisao_humana"]
}
```

**Processos são o contrato da Etapa 3.** Cada processo é uma função registrada (`processos.py`), com entrada
(`id_pagina`, `bbox`, `dpi`, executores escolhidos) e saída (alegações no envelope de §14). Os de hoje viram
processos sem reescrever a lógica: `carimbo_por_ancora` = `campos_do_carimbo`; `carimbo_ocr` = `ler_carimbo_ocr`;
`tabela_por_palavras` = Vision + `grade.montar`; `tabela_ocr_modelo` = `ler_tabela`; `fatias_ocr` = `ler_fatias`;
`eixo_vetorial` = `eixo`; `sondagem_texto`/`sondagem_ocr` = `ler_sondagem`/`ler_sondagem_ia`. Os protótipos viram
`camadas` (`isolar`), `malha_coordenadas` (`georef.py`) e `perfil_vetorial` (`perfil.py`).

**`tarefas.parquet`:** `id_tarefa, id_pagina, id_regiao, processo, executor, testemunha, bbox, dpi, prioridade,
precisa_gpu, depende_de, estado (pendente|feita|falhou|quarentena), tentativas, versao_rota`.
**`decisoes.parquet`:** `id_tarefa, candidatos (JSON com a pontuação de cada um), escolhido, motivo, estrato_usado,
amostras_no_estrato, modo (regra|desempenho|exploracao)`. "Por que o Kimi leu esta tabela?" se responde com uma
consulta.

**O ciclo passa a executar tarefas**, não documentos: `situacao()`/`proxima_tarefa()` dão lugar a "tarefas
pendentes cuja dependência está feita", com a mesma ordem de hoje (código antes, IA na vez da GPU, prioridade 7,
quarentena, limite por prancha). O refazer por versão continua: a tarefa cuja `versao_rota` ou cujo processo está
em `muda` volta a pendente.

## 12. Catálogo das IAs

Hoje o catálogo está em três lugares (`ia.json → modelos`, `agentes.json → agentes`, `bancada.json → locais`). Um
arquivo só, `conceitos/modelos.json`, com o que é **declarado** (capacidade, custo, limite, política) — o **medido**
fica em `desempenho.parquet`, nunca no JSON escrito à mão:

```json
{
  "executores": {
    "pdf_texto":  {"motor": "codigo", "natureza": "testemunha", "onde": "local", "modalidades": ["pdf"], "custo": 0},
    "grade":      {"motor": "codigo", "natureza": "derivado", "onde": "local", "modalidades": ["palavras"], "custo": 0},
    "vision":     {"motor": "vision", "natureza": "testemunha", "onde": "local", "modalidades": ["imagem"],
                   "saida": ["texto", "palavras_com_caixa"], "gpu": false, "timeout_s": 120},
    "glm_ocr":    {"motor": "ollama", "modelo": "glm-ocr:latest", "natureza": "generativo", "onde": "gpu",
                   "modalidades": ["imagem"], "saida": ["texto", "tabela_html"], "lado_max_px": 1100, "gpu": true},
    "gemma3":     {"motor": "ollama", "modelo": "gemma3:12b", "natureza": "generativo", "onde": "gpu",
                   "modalidades": ["imagem", "texto"], "restricoes": ["nunca_fonte_unica_de_numero"]},
    "qwen3":      {"motor": "ollama", "modelo": "qwen3:8b", "natureza": "generativo", "onde": "gpu",
                   "modalidades": ["texto"], "saida": ["json_esquema"]},
    "apple_fm":   {"motor": "apple", "natureza": "generativo", "onde": "local", "modalidades": ["texto"]},
    "kimi":       {"motor": "nvidia", "modelo": "moonshotai/kimi-k3", "natureza": "generativo", "onde": "api",
                   "modalidades": ["imagem", "texto"], "custo": 0, "prazo_fim": "2026-11-03",
                   "politica_dados": "publico_somente", "limites": {"por_minuto": 36, "simultaneas": 3}}
  },
  "capacidades_declaradas": {
    "_": "priori (o que se espera antes de medir), escala 0–1; o roteador só usa enquanto o estrato tem menos de n_min amostras",
    "vision":  {"ocr_texto": 0.8, "tabela": 0.4, "invencao": 0.0},
    "glm_ocr": {"ocr_texto": 0.8, "tabela": 0.7, "invencao": 0.1},
    "kimi":    {"ocr_texto": 0.9, "tabela": 0.9, "engenharia": 0.7, "invencao": 0.1}
  }
}
```

Campos que importam para o roteamento e que o exemplo do pedido não tinha: **`natureza`** (testemunha × generativo ×
derivado — é o que decide se dois votos valem como prova), **`politica_dados`** (o que pode sair do mini; hoje
`agentes.json → obras_permitidas`, `mascarar_carimbo`), **`prazo_fim`** (a exceção §5.6), **`restricoes`**
(`nunca_fonte_unica_de_numero` para o gemma3, pela medida de 26/09) e os **limites operacionais** (lado máximo em px,
timeout, chamadas simultâneas, ritmo por provedor). `ia.json`, `agentes.json` e `bancada.json` continuam lidos na
transição; o `modelos.json` aponta para eles até a migração terminar.

## 13. Seleção automática do executor

**Estrato.** Cada medida pertence a uma célula `(tarefa, tipo_regiao, natureza, formato, dificuldade)` — por exemplo
`(transcrever_tabela, tabela_materiais, imagem, A1, media)`. Com poucas amostras, a célula **recua** para a mãe:
`(…, imagem, A1, *)` → `(…, imagem, *, *)` → `(transcrever_tabela, *, *, *)` → `capacidades_declaradas`. O nível usado
fica na decisão (`estrato_usado`, `amostras_no_estrato`).

**Pontuação** (por executor viável, na célula):

```
q_inf   = limite inferior de Wilson (90 %) da precisão por campo        ← qualidade com incerteza
inv     = taxa de invenção (inclui o controle negativo)                 ← corte duro: > inventadas_max → fora
custo   = tempo_util_p50 × peso_gpu (se precisa da GPU) + custo_api + tempo_perdido_p50 × peso_fila
U       = q_inf − λ · custo
```

- **Corte duro antes da pontuação:** fora do prazo, sem chave, política de dados violada, modalidade errada, inventa
  acima de `bancada.json → criterios.inventadas_max`, veredito `descontinua`.
- **Entre os que sobram,** o maior `U`; empate → o mais barato. Com `q_inf` de todos abaixo da meta da tarefa
  (`plano_projeto.md` §7: 95 % carimbo, 99 % quantidade), o roteador já planeja dois leitores + testemunha.
- **Plano de prova, não só escolha:** para campo numérico, sempre um leitor **e** uma testemunha de natureza
  diferente (Vision, texto do PDF ou geometria). O roteador escolhe o melhor leitor e a melhor testemunha
  separadamente.
- **Escada:** confiança da alegação (§20) entre 0,70 e 0,90 → `segundo_leitor` (o 2º melhor `U` de natureza
  diferente do 1º); divergência ou < 0,70 → `executor_superior` (o maior `q_inf` sem olhar custo); ainda divergente
  → `revisao_humana`.

**Aprender com os resultados.** As medidas chegam de três fontes, com pesos diferentes:

| fonte | é verdade? | entra em |
|---|---|---|
| bancada com gabarito (Cambé, Foz, demandas c/p/e) | sim | `q_inf` |
| revisão humana das alegações em revisão (§20) | sim | `q_inf` |
| conferências automáticas (soma = TOTAL, estacas em sequência, eixo × relação, Δcota/extensão = declividade) | **proxy** | coluna separada; só desempata |

Atualização: contadores por célula (acertos, emitidas, inventadas, tempo) em `desempenho.parquet`, recalculados a
cada bancada e a cada lote de revisão — Beta/Wilson simples, sem modelo opaco. **Exploração só fora da produção:**
na bancada, ou em modo sombra (um desafiante lê o mesmo recorte quando a GPU está ociosa, a resposta dele não é
publicada, só medida). Assim a pergunta "qual IA lê melhor planta e perfil A0 rasterizada?" vira uma consulta à
célula `(*, planta_perfil, imagem, A0, *)` com o intervalo de confiança à vista, e "vale a pena o modelo grande
nesta prancha?" é a diferença de `q_inf` dividida pela diferença de custo.

## 14. Estrutura de dados da extração

Três camadas, como no `plano_projeto.md` §5 e §7 (alegações), agora explícitas:

1. **Alegações** (bruto, uma linha por valor × executor): o que cada leitor disse, com evidência. É o que
   `carimbo.parquet`, `prancha_leitura.parquet` e `sondagem_*.parquet` já são hoje.
2. **Resolvido** (uma linha por entidade): o valor que a curadoria aceitou, com status e confiança.
3. **Espacial** (entidades com geometria): §15.

**Envelope comum** de toda linha de alegação e de resolvido:

| coluna | conteúdo |
|---|---|
| `id_registro` | estável: hash de (entidade, campo, id_pagina, bbox arredondada) |
| `entidade`, `campo`, `valor_texto`, `valor`, `unidade` | `valor_texto` como impresso; `valor` normalizado (SI; DN e bitola não se convertem — regra 15) |
| `id_documento`, `id_pagina`, `id_regiao`, `bbox` | origem (§19) |
| `id_tarefa`, `processo`, `executor`, `modelo`, `prompt_hash`, `assinatura_congelamento` | quem leu e como |
| `status` | `codigo` · `confirmado` · `confirmada_ia` · `divergente` · `so_<leitor>` · `pendente` · `revisado` |
| `confianca`, `motivo` | §20 |
| `revisao_desenho`, `valido_de` | a revisão da prancha (R0, R1…) — sem ela, a mesma tubulação soma três vezes |
| `versao_codigo`, `commit`, `em` | `comum.gravar` |

**Tabelas resolvidas** (Parquet; o CSV é vista):

- `metadados/pranchas.parquet` — uma linha por página-prancha: os campos do carimbo resolvidos (obra, projeto,
  contratante, projetista, disciplina, nº do desenho, revisão vigente, data, escala, folha, responsável técnico,
  CREA, ART, fase) + `revisoes` (lista); `metadados/projeto.parquet` — o jogo (P8: desenho × revisões, completo × lista
  de desenhos).
- `engenharia/trechos.parquet`, `dispositivos.parquet`, `estruturas.parquet`, `materiais.parquet`
  (relação de materiais linha a linha: código SAM, discriminação, quantidade, unidade), `quantitativos.parquet`
  (agregados por item, DN, material, faixa de profundidade), `sondagens.parquet` + `sondagem_spt` + `sondagem_camada`
  (os de hoje).

## 15. Tubos, dispositivos e estruturas

Para obra linear, a peça central é o **eixo com progressiva** (referência linear). Tubo, dispositivo e estrutura se
penduram nele; a geometria no mapa é uma projeção.

| entidade | geometria | atributos principais |
|---|---|---|
| `eixo` | `LINESTRING` (Z quando o perfil foi lido; M = progressiva em metros) | id_eixo, sistema (água/esgoto), família, convenção de estaca, extensão, CRS, georreferência |
| `trecho` | `LINESTRING` (sub-trecho do eixo) | id, id_eixo, progressiva_inicio_m, progressiva_fim_m, estaca_inicio/fim (texto), material, DN/DE, classe/PN, espessura, extensão impressa × medida, declividade, cota montante/jusante, profundidade média, faixa de escavação |
| `dispositivo` | `POINT` | id, subtipo (`valvula`, `registro`, `ventosa`, `descarga`, `pv`, `ti`, `conexao`, `curva`, `derivacao`, `marco`), DN, material, progressiva_m, estaca, deflexão (curva), cota, ligação ao detalhe (folha + região) |
| `estrutura` | `POINT` ou `POLYGON` | id, subtipo (`caixa`, `bloco_ancoragem`, `travessia`, `elevatoria`, `reservatorio`), dimensões, progressiva |
| `perfil_ponto` | sem geometria em planta (é `(progressiva, cota)`) | estaca, cota_terreno, cota_geratriz/fundo, profundidade — vira o Z do eixo |

**Estaca é texto e número.** Guardar `estaca` como está impresso **e** `progressiva_m` calculada, com
`convencao_estaca` declarada: o repositório trata estaca de 20 m (`12+10,00` = 12 × 20 + 10 = 250 m,
`plano_projeto.md` §2), enquanto o exemplo do pedido usa quilômetro + metro (`12+340` = 12.340 m). As duas existem
em projeto brasileiro; a convenção sai da prancha (espaçamento das marcas na geometria × rótulos) e nunca é presumida.

**Três espaços de coordenadas** em toda geometria, para não perder rastro: `folha` (0–1 da página, de onde veio),
`vista` (metros locais pela escala da vista; no perfil, H e V diferentes) e `mundo` (CRS EPSG, só depois do §16). O
GeoParquet guarda o `mundo` quando existe e a `folha` sempre (coluna WKB extra).

Exemplo de linha de `dispositivos`:

```json
{"id": "D002", "subtipo": "ventosa", "dn_mm": 100, "material": "ACO", "estaca": "66", "progressiva_m": 1320.0,
 "convencao_estaca": "20m", "geometry": "POINT (672912.31 7189877.40)", "crs": "EPSG:31982",
 "georreferencia": "absoluta_declarada", "id_pagina": "a3f9c2e17b04d518_P002", "bbox_origem": [0.413, 0.285, 0.428, 0.307],
 "processo": "dispositivos_por_camada", "executor": "codigo+vision", "status": "confirmado", "confianca": 0.94}
```

## 16. Georreferenciamento

Do mais confiável ao menos, cada um registra o método e o **resíduo medido** (MASTER-PLAN §10.4, regra 1: precisão é
medida, não declarada):

1. **GeoPDF** (`/Measure /GEO`): transformação pronta; ainda assim conferida num ponto.
2. **Malha de coordenadas** (cruzetas + rótulos `E=`/`N=`): o protótipo `georef.py` já acha os rótulos pela camada
   `MALHA`; o valor vem do texto real ou do OCR do recorte (pequeno, de natureza dupla). Ajuste de semelhança ou afim
   por mínimos quadrados com ≥ 3 pontos, **resíduo num ponto fora do ajuste**; folha girada (a 013) pede o termo de
   rotação.
3. **Quadro de coordenadas** (vértices, PVs): pontos homólogos com o símbolo na planta.
4. **Encadeamento entre folhas** do mesmo jogo: o fim do eixo de uma folha = o início da seguinte (medido: 0,05 e
   0,02 m na AAT-06). Dá georreferência **relativa** do jogo inteiro a partir de uma folha ancorada.
5. **Controle externo:** GPS de campo, foto com EXIF, marco, base cadastral da Sanepar, vias do OSM pelo nome (o
   protótipo achou os mesmos nomes de rua com desvio sistemático de ~64 m — datum não declarado).

**CRS nunca presumido** (decisão D3): o fuso sai da malha **e** do município do carimbo, que têm de concordar — a
AAT-06 de Foz é 21S (EPSG:31981), o 22S (EPSG:31982) erraria em ~600 km. Datum ausente fica `nao_declarado`.

Coluna `georreferencia` em toda feição: `ausente` · `relativa_folha` · `relativa_jogo` · `absoluta_declarada` (malha
lida, sem controle independente) · `absoluta_verificada` (resíduo medido em controle externo ≤ tolerância). Sem
georreferência a feição existe em coordenada de folha/vista — **nunca** no centroide do município (princípio 9).

O **perfil** se liga ao eixo pela progressiva, não pelo mapa: `(progressiva, cota)` do perfil → Z do eixo em planta.

## 17. Formatos espaciais

| formato | papel recomendado | a favor | contra |
|---|---|---|---|
| **GeoParquet** | **fonte canônica** das feições | colunar, tipado, comprimido; lê em pandas/geopandas, polars (WKB), DuckDB; CRS nos metadados; mesmo ecossistema dos `.parquet` de hoje | não abre no AutoCAD nem no Google Earth; o QGIS lê nas versões recentes |
| **GeoJSON** | exportação para web e conferência rápida | universal (Leaflet, Mapbox, Python); legível | RFC 7946 obriga **WGS 84**: o UTM tem de ser reprojetado (ou usar a variante com `crs`, fora da norma); verboso; sem tipos |
| **GeoPackage** | exportação SIG (QGIS, ArcGIS) e entrega a terceiros | SQLite único, várias camadas, CRS qualquer, índice espacial, padrão OGC | binário, pior para versionar; precisa de GDAL (`pyogrio`, wheels com GDAL embutido) |
| **DXF** | exportação para CAD (AutoCAD, Civil 3D) | abre em todo CAD; camadas; `ezdxf` (MIT) escreve sem dependência | sem CRS, sem atributos estruturados (só XDATA/blocos com atributos), não é consultável — é **vista** (decisão D1) |
| **KML/KMZ** | conferência visual e compartilhamento (Google Earth) | qualquer pessoa abre; estilos; KMZ leva ícones | só WGS 84; atributos pobres; XML simples, escreve-se sem biblioteca |
| **LandXML** | exportação de **alinhamento e perfil** para o Civil 3D | o formato que o Civil 3D importa como Alignment + Profile, com estaqueamento, PIs, curvas e PVs | escopo de infraestrutura linear; validar a importação no Civil 3D do Caio |
| **FlatGeobuf** | opcional, para streaming web | rápido, índice espacial | menos conhecido |
| **Shapefile** | **evitar** | — | nomes de campo de 10 caracteres, vários arquivos, sem UTF-8 garantido |
| IFC 4.3 (`IfcAlignment`) | futuro (BIM de infraestrutura) | padrão aberto de alinhamento | ecossistema Python ainda imaturo para isso |

**Decisão recomendada:**

```
DADOS ESTRUTURADOS (fonte, regenerável a partir das alegações)
   ├── Parquet        metadados, engenharia, alegações, inventário, roteamento, desempenho
   ├── GeoParquet     eixo, trechos, dispositivos, estruturas (mundo quando houver + folha sempre)
   └── JSON           referências, configuração
            │
            ▼  EXPORTADORES (codigo/exportar.py; nunca fonte, sempre regeráveis)
   ├── GeoPackage     SIG
   ├── DXF            CAD (camadas por entidade/subtipo; atributos em XDATA)
   ├── LandXML        alinhamento + perfil para o Civil 3D
   ├── KML/KMZ        Google Earth (reprojetado a WGS 84)
   └── GeoJSON        web (WGS 84)
```

Bibliotecas: `shapely` (BSD), `pyproj` (MIT), `pyarrow` (Apache), `geopandas` (BSD) só na camada espacial — o resto
do repositório continua em polars —, `ezdxf` (MIT), `pyogrio` (MIT) para o GeoPackage. KML e LandXML escritos com
`xml.etree` da biblioteca padrão.

## 18. Estrutura de arquivos

Adaptado ao que o repositório já faz (`dados/` interno e regenerável; `saidas/` publicado no Drive por obra):

```
dados/                                         fora do git, regenerável
├── inventario/        documentos.parquet  paginas.parquet  regioes.parquet
├── roteamento/        tarefas.parquet  decisoes.parquet
├── alegacoes/         carimbo, prancha_leitura, prancha_tabela, sondagem_*, ... (.parquet de hoje)
├── resolvido/         pranchas, projeto, trechos, dispositivos, estruturas, materiais, quantitativos, sondagens
├── espacial/          eixo.geoparquet  trechos.geoparquet  dispositivos.geoparquet  estruturas.geoparquet
├── desempenho/        execucoes.parquet (cada chamada)  desempenho.parquet (por célula)  bancada_*.parquet
├── evidencias/        recortes/<sha256>.png   (nome = hash do conteúdo: deduplicado e citável)
├── congelamento.jsonl  falhas.jsonl  execucoes.jsonl  gpu/  recortes/ (o de hoje, até migrar)

saidas/<acervo>/<obra>/projeto/                → Drive saida/<acervo>/<obra>/projeto/
├── inventario/        inventario.csv  regioes.csv
├── metadados/         pranchas.csv  projeto.csv
├── engenharia/        trechos.csv  dispositivos.csv  materiais.csv  quantitativos.csv  sondagens.csv ...
├── espacial/          obra.gpkg  obra.geojson
├── exportacao/        obra.dxf  obra.kmz  alinhamento.xml (LandXML)
├── revisao/           revisao.csv   (o que precisa do olho do Caio, com o link do recorte)
└── referencias.json
saidas/_sistema/projeto/   os mesmos, de todas as obras; bancada_agentes.csv; desempenho.csv
```

O `projeto_001/` do pedido corresponde a `<acervo>/<obra>/projeto/`; o "projeto" no sentido de jogo de desenhos de
uma disciplina (`plano_projeto.md` §3) é uma coluna, não uma pasta. Os CSVs de hoje (`pranchas.csv`,
`carimbos.csv`…) continuam publicados nos mesmos lugares até a F8, para nada que o Caio usa quebrar.

## 19. Rastreabilidade

Cadeia completa, toda por chave, sem texto solto:

```
feição/linha resolvida ──id_registro──► alegações (1..N, uma por executor)
      alegação ──id_tarefa──► tarefas.parquet ──► decisoes.parquet (por que este executor)
      alegação ──id_pagina, bbox──► inventario_pagina / inventario_regiao ──► arquivo (hash, caminho, obra)
      alegação ──assinatura_congelamento──► congelamento.jsonl (modelo, digest, prompt, imagem, opções, resposta)
      alegação ──evidencia──► evidencias/recortes/<sha256>.png
```

- Toda bbox é normalizada à página exibida: "clicar no elemento e abrir a prancha no trecho" é abrir o PDF na
  página `pagina` e desenhar `bbox × (largura, altura)`.
- `referencias.json` por obra: `{id_registro: {arquivo, pagina, bbox, recorte, executores, status}}` — o que um visor
  web consome sem ler Parquet.
- O DXF e o KML carregam o `id_registro` (XDATA no DXF, `ExtendedData` no KML): do CAD também se volta à prancha.
- A geometria em `folha` fica guardada ao lado da `mundo`: refazer a georreferência não perde a origem.

## 20. Confiança e revisão

**A confiança é derivada da evidência, não pedida ao modelo.** Modelo generativo declara 0,95 sobre número inventado
(o gemma3 inventou cotas com a mesma "certeza" das reais); confiança autodeclarada não entra na conta. A confiança de
uma alegação resolvida é função das provas que o repositório já define (presença, concordância, conferência, rastro):

| situação (status de hoje) | confiança inicial (premissa, calibrar) |
|---|---|
| texto real do PDF (`codigo`) + conferência fecha | 0,99 |
| `codigo` sem conferência aplicável | 0,95 |
| `confirmado` (testemunha + leitor) + conferência fecha | 0,97 |
| `confirmado` sem conferência | 0,92 |
| `confirmada_ia` (dois generativos, sem testemunha) | 0,75 |
| `so_<leitor>` testemunha | 0,70 |
| `so_<leitor>` generativo | 0,50 |
| `divergente` | 0,30 |
| conferência **reprova** com leitura confirmada | não é baixa confiança: é **achado do projeto** → `divergencias.csv` (pergunta ao projetista) |

Regras de aceite (as do pedido, como ponto de partida):

```
≥ 0,90           aceite automático         (e só se as provas exigidas pelo tipo de campo foram cumpridas)
0,70 – 0,90      segunda verificação       (escada do §13: segundo leitor de natureza diferente)
< 0,70           executor superior; depois revisão humana
```

O número **nunca passa por cima da prova**: um campo numérico sem testemunha não é aceito com 0,91. Os limiares
moram em `conceitos/rotas.json → aceite`, por tipo de campo (quantidade de tabela pede mais que título).

**Calibração.** Com o gabarito, mede-se se "0,90" acerta 90 %: curva de confiabilidade e erro de calibração (ECE) por
tarefa; a tabela acima é reajustada (regressão isotônica sobre os mesmos sinais) quando houver ≥ 200 alegações com
gabarito na tarefa. Até lá, os números são premissa e estão escritos como tal.

**Revisão humana.** `revisao.csv` por obra no Drive: uma linha por alegação a revisar, com o valor de cada leitor,
o recorte (link), a página e uma coluna `conferido` (`c`/`p`/`e`) e `correto` — o mesmo protocolo das demandas
(`demandas.json`, `respostas.py`). A resposta volta como gabarito: vira `status = revisado` e alimenta o
`desempenho.parquet` (§13). O Caio **corrige, não digita**.

## 21. Métricas de cada IA

Por executor × célula (§13), separando o que é do modelo do que é do plano ou da fila (a separação que a bancada já
faz: tempo útil × tempo perdido):

| grupo | métrica | definição |
|---|---|---|
| qualidade | precisão por campo | certas ÷ emitidas |
| | cobertura | certas ÷ esperadas |
| | exatidão numérica | número idêntico ao gabarito (após normalização) — o que move dinheiro |
| | CER/WER | erro de caractere/palavra em texto livre (títulos, notas) |
| | **invenção** | emitidas que não existem no gabarito + números no controle negativo |
| | confirmada errada | o pior erro: passou pela curadoria |
| | IoU de região | para detectores de layout (§10) |
| | acrescenta | ganho de confirmadas certas da curadoria com ele × sem ele (o `veredito` de hoje) |
| calibração | ECE, curva de confiabilidade | §20 |
| operação | tempo útil p50/p90 | só a tentativa que deu certo |
| | tempo perdido | ritmo do provedor, esperas, tentativas falhas, fila da GPU |
| | taxa de erro final | falhou depois de todas as tentativas |
| | memória | `size_vram` do Ollama (`/api/ps`) por modelo; pico RSS do processo do Vision |
| | tokens entrada/saída | do meta (NVIDIA, Ollama `eval_count`) |
| custo | R$ por página/região | tokens × preço; GPU do mini como custo de oportunidade (minutos × fila) |
| humano | taxa de revisão induzida | alegações dele que foram à revisão |
| | taxa de correção | revisadas em que o humano mudou o valor |

A unidade de relatório é a célula com o **intervalo de confiança**: "0,94 (0,88–0,97; n = 120)" diz se a diferença
entre dois modelos é real. Publicado em `saidas/_sistema/projeto/desempenho.csv`, ao lado do `bancada_agentes.csv`.

## 22. Impacto no código atual

| arquivo | mudança | risco |
|---|---|---|
| `codigo/inventario.py` **novo** | Etapa 1 (§5, §7, §10) | nenhum no que existe |
| `codigo/roteador.py` **novo** | Etapa 2 (§11, §13), puro | nenhum enquanto em modo sombra |
| `codigo/processos.py` **novo** | registro dos processos; adaptadores finos sobre as funções de `prancha.py`/`sondagem.py` | baixo |
| `codigo/espacial.py`, `exportar.py` **novos** | §15–§17 | dependências novas (shapely, pyproj, geopandas, ezdxf, pyogrio) |
| `codigo/prancha.py` | `perfilar` vira chamada a `inventario.perfil_da_pagina`; `ler_carimbo`, `eixo`, `ler_fatias`, `ler_imagens` recebem `pagina` e `bbox` (hoje fixos na 0 e na fração); `familia` passa a usar a taxonomia | **médio**: a forma das linhas de `prancha.parquet` muda — entra em `muda` e refaz |
| `codigo/sondagem.py` | `e_boletim` usado pelo inventário; leitura por página já existe | baixo |
| `codigo/ciclo.py` | `situacao`/`proxima_tarefa`/`TAREFAS` → fila de tarefas do roteador; `publicar` com as famílias novas; `status.json` com contadores do inventário | **alto**: é o coração da rodada; por isso só na F7, depois do modo sombra |
| `codigo/comum.py` | `gravar(familia, linhas, chaves=CHAVES)`; subpastas em `dados/` | baixo (o padrão continua o de hoje) |
| `codigo/entrega.py` | fonte `pasta` para inventário de diretório; do extrator, aceitar PDF com qualquer página ≥ A3 | baixo aqui; **depende do extrator** |
| `codigo/bancada.py` | grava `execucoes`/`desempenho` por célula; conjuntos novos: classificação de página, regiões (IoU) | médio |
| `codigo/ia.py`, `agentes.py`, `curadoria.py`, `grade.py`, `cliente_gpu.py` | sem mudança de lógica; `ia.executar(executor_id, …)` lê o catálogo | baixo |
| `conceitos/` | novos: `inventario.json`, `taxonomia.json`, `rotas.json`, `modelos.json`; `prancha.json` perde `reconhecer`/`classe`/`familias.grupo` para eles (com período em que os dois existem) | baixo |
| CSVs publicados | `pranchas.csv` passa a ter uma linha **por página** (hoje por arquivo) | **contrato muda**: `versoes.jsonl` sobe o maior (0v → 1v), aviso ao Caio e ao maestro antes |
| `status.json` | `inventario: {documentos, paginas, por_tipo, revisar}` | o maestro lê chaves que não conhece? conferir no `ialocal.maestro` |
| fora daqui | `ialocal.extrator`: entregar todo PDF candidato (não só 1ª página A3+); `ialocal.maestro`: nada obrigatório | pedido ao Caio |

## 23. Plano incremental

Cada fase entrega algo medível, não muda o que já é publicado antes da hora e tem verificação escrita antes de rodar.
A ordem segue a regra do `plano_projeto.md` §9: **sem saber quantas páginas são de cada classe, a ordem do resto é
palpite** — por isso o inventário vem primeiro e serve de diagnóstico do acervo.

| fase | entrega | verificação | muda o publicado? |
|---|---|---|---|
| **F1** | `inventario.py` N0 + N1 sem regiões; `documentos`/`paginas.parquet`; `inventario.csv`; CLI `pasta` e tarefa na rodada | testes sintéticos (§24); no mini, o acervo inteiro: distribuição por formato × tipo_pdf × texto_pdf; p90 por página | não (só arquivo novo) |
| **F2** | classificação por regra (`tipo_documento`, `classe_obra`, taxonomia) + gabarito estratificado de 100 páginas (sorteio pelo hash, gravado) corrigido pelo Caio | acerto ≥ 95 % em `tipo_documento` nas classes com ≥ 10 páginas | não |
| **F3** | regiões vetoriais (OCG, âncora, grade, imagens) → `regioes.parquet`; `possui_*` | IoU ≥ 0,8 em 30 páginas com caixas desenhadas pelo Caio; carimbo achado sem fração fixa em ≥ 95 % das vetoriais | não |
| **F4** | N1b: raster (linhas numpy, giro, qualidade de OCR, âncoras pelo Vision) | as mesmas metas em 20 páginas digitalizadas reais | não |
| **F5** | IA pequena no empate (Apple FM × qwen3) e bancada de classificação | ganho sobre a regra sem perder acerto nas que a regra já acertava | não |
| **F6** | `modelos.json` unificado; `desempenho.parquet` estratificado a partir da bancada; `roteador.py` em **modo sombra** (decide e grava, o ciclo segue o caminho de hoje) | onde o roteador discorda do `proxima_tarefa`, a decisão dele é explicável (consulta em `decisoes`) e, na bancada, não pior | não |
| **F7** | o ciclo executa `tarefas` por página/região; processos registrados; carimbo pela região detectada; páginas 2…N lidas | `testes.py` inteiro passa; no mini, as pranchas de Foz e Cambé dão o mesmo carimbo/eixo que hoje (ou melhor, com motivo) | **sim**: 1v0, `pranchas.csv` por página |
| **F8** | envelope de §14, resolvido, confiança derivada, `revisao.csv` e volta da revisão como gabarito | toda linha resolvida tem origem válida; o primeiro lote de revisão entra no desempenho | sim (CSVs novos) |
| **F9** | espacial: eixo/trechos/dispositivos em coordenada de folha e vista; perfil pela geometria; malha → georreferência com resíduo; GeoParquet + exportadores (GeoPackage, DXF, KML, LandXML, GeoJSON) | AAT-06: eixo 540 ± 0,1 m por folha, perfil ≤ 3 mm do quadro, emenda entre folhas ≤ 0,1 m, resíduo da malha medido; DXF abre no `ezdxf` com as camadas; LandXML importa no Civil 3D do Caio | sim (pasta espacial e exportação) |
| **F10** | roteamento por desempenho com recuo de estrato e exploração em sombra; dificuldade aprendida | em bancada, a política escolhida ≥ a fixa em qualidade e ≤ em custo | sim (as decisões mudam) |

A família **adutora** é a primeira em tudo (ordem do `plano_projeto.md` §11.6): o gabarito de Foz e o protótipo já
existem. Depois coletor de esgoto (PV e faixa de profundidade); a estrutura de ETA/ETE fica para a skill.

## 24. Testes

No padrão de `codigo/testes.py`: PDFs sintéticos gerados no próprio teste, sem modelo de verdade (Ollama numa porta
fechada, Vision e NVIDIA falsos), qualquer máquina. As metas de acerto contra gabarito real rodam no mini, na bancada.

**Etapa 1 — inventário**

- PDF de 6 páginas sintético (A1 vetorial com texto, A0 vetorial com texto em curva, A1 com imagem colada, A3
  vetorial com tabela, A4 só imagem, A4 com imagem + texto invisível) → 6 linhas, formato, orientação e
  `tipo_pdf`/`texto_pdf` certos em cada uma.
- Página com `/Rotate 90`: largura/altura e orientação depois da rotação; bbox no referencial exibido.
- Formatos na borda da tolerância (A1 ± 25 mm), estendido, não padrão, pequeno.
- DPI efetivo de imagem embutida conhecida (2.000 px em 169,3 mm = 300 DPI) e a `qualidade_ocr` resultante.
- OCG: camadas presentes por página e caixa por camada (reaproveita `pdf_com_camadas`).
- PDF corrompido, criptografado e vazio: linha com `status = erro`, a rodada segue.
- **Determinismo e idempotência:** mesmo arquivo → mesmos ids e mesmas linhas; arquivo copiado com outro nome → mesmo
  `id_documento`; segunda execução não regrava sem mudança de versão.
- **Independência:** o inventário roda com a Etapa 3 ausente/quebrada (nenhum import de `prancha_ia`).
- Desempenho: folha sintética de 80 mil caminhos inventariada em < 2 s (N1).

**Classificação**

- Cada regra de `tipo_documento` e de taxonomia com exemplos que casam e que não casam (no JSON, testados como os
  padrões de hoje em `testar_conceitos`).
- Os casos reais da auditoria de 26/09 viram testes: OSE com `Adutora:` não é adutora; `GAS GAS GAS` não é gás;
  `CORTEZ` não é corte; `PLANTA_GERAL_SONDAGEM` é apoio/sondagem.
- A4 com sinais de memorial não vira sondagem só pelo formato.
- Empate → IA pequena falsa: concordância aceita, discordância fica `incerto`.

**Regiões**

- Tabela sintética (grade 5 × 4) → uma região `tabela` com IoU ≥ 0,95 e linhas/colunas certas.
- Carimbo sintético com âncoras em posição não padrão (canto superior) → achado pela âncora, não pela fração.
- Duas tabelas lado a lado → duas regiões (a armadilha da skill).
- Raster sintético (a mesma folha renderizada e girada 0,8°) → giro estimado e regiões com IoU ≥ 0,8.
- Fusão: a mesma tabela por grade e por âncora vira uma região com confiança maior.

**Etapa 2 — roteador** (função pura, catálogo e desempenho falsos)

- Tabela em imagem → leitor + testemunha de naturezas diferentes; nunca dois generativos sem testemunha para número.
- Executor fora do prazo, sem chave, desligado ou com política de dados violada → nunca escolhido.
- Estrato sem amostras → recua para o pai e grava `estrato_usado`.
- Com o desempenho mudado (o desafiante passa a ser melhor e mais barato) → a decisão muda; com o mesmo desempenho →
  a mesma decisão (determinismo).
- Escada: confiança 0,8 gera tarefa de segundo leitor; 0,5 gera executor superior; divergência persistente gera linha
  de revisão.

**Etapa 3 — extração e dados**

- Os testes de hoje continuam passando (não regressão: `testar_rodada`, `testar_carimbo_desenhado`,
  `testar_sondagem`, `testar_curadoria`, `testar_grade`, `testar_bancada`…).
- Toda linha resolvida tem `id_pagina` existente no inventário e `bbox` em [0, 1] com x0 < x1, y0 < y1.
- Confiança derivada: tabela status → número (§20) e a regra "número sem testemunha não é aceito".
- Estaca: `12+10,00` com convenção 20 m → 250 m; `12+340` com convenção km → 12.340 m; sem convenção → não calcula.
- Georreferência: transformação afim conhecida aplicada a pontos sintéticos → parâmetros recuperados e resíduo < 1 mm;
  ponto de controle deslocado → resíduo acusa.
- GeoParquet: ida e volta com CRS; feição sem georreferência grava sem CRS e com `georreferencia = relativa_folha`.
- Exportadores: DXF abre no `ezdxf` com as camadas esperadas e o `id_registro` em XDATA; KML é XML válido em WGS 84;
  GeoJSON em WGS 84; LandXML com o alinhamento e as estacas.
- Rastro: de uma linha de `dispositivos` chega-se ao recorte PNG e à entrada do congelamento.

**Bancada (no mini, com gabarito real)**

- Classificação de página: 100 páginas estratificadas (F2).
- Regiões: 30 vetoriais + 20 digitalizadas com caixas do Caio (F3/F4).
- Calibração: curva de confiabilidade por tarefa quando houver ≥ 200 alegações com gabarito.
- Controle negativo em toda bancada de modelo (o que já existe em B2).

---

## Decisões que são do Caio

| # | decisão | recomendação |
|---|---|---|
| I1 | chave do inventário: hash do arquivo ou id do extrator? | **hash** (deduplica o mesmo PDF vindo por caminhos diferentes); id do extrator como coluna |
| I2 | pedir ao extrator que entregue todo PDF (não só 1ª página ≥ A3)? | **sim**, senão o inventário por página não vê os jogos com capa A4 |
| I3 | `pranchas.csv` por página a partir da F7 (contrato muda, 1v0)? | **sim**, com aviso antes; o resumo por arquivo continua como `documentos.csv` |
| I4 | convenção de estaca padrão quando a prancha não diz | **nenhuma**: medir pelo espaçamento das marcas; sem medida, `progressiva_m` vazia |
| I5 | dependências novas (shapely, pyproj, geopandas, ezdxf, pyogrio; opcional opencv-headless) | **sim**, todas de licença permissiva; nada AGPL |
| I6 | taxonomia: separar `coletor_esgoto` em rede coletora / coletor tronco / interceptor / emissário já na F2? | **sim** — o pedido já traz a árvore; o código do desenho e o título desambiguam |
