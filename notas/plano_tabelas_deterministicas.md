# Tabelas de material: grade primeiro, leitores depois — plano de melhoria

**Estado: plano com protótipo medido** (09/10/2026). Pedido do Caio: a IA de fronteira lê as tabelas de material dos
projetos hidráulicos da Sanepar (ETA Vila C, Foz do Iguaçu: Drive `211 - SAA Foz do Iguaçu/01. RECEBIDOS/
LC2112026EDITAL_ELEMENTOS/UNIDADE 01/ANEXO C/1. PBHI`), acha as pranchas mais difíceis, confere o que o código e a IA
local do mini fazem e ensina o código a chegar perto — **com o máximo de determinismo e velocidade**. Nada aqui muda
o código de produção; o protótipo está em `notas/prototipo_tabela/` e o gabarito no `ialocal.dados`
(`orcamentos/211_saa_foz_do_iguacu/referencia/claude_opus/tabelas_pbhi/`).

## 1. O que foi feito

1. Baixei os **43 PDFs** da pasta (42 pranchas A0–A2 de 1 página e o memorial A4 de 8 páginas).
2. **Inventário** de cada folha: formato, texto real, primitivas vetoriais, imagens coladas e onde estão
   (`inventario_pranchas.csv`).
3. **Localizei 41 tabelas de material** em 27 pranchas, sem modelo: 39 são **imagem colada** (Excel → CAD → PDF, raster
   nativo de **400 dpi**) e 2 são **vetor com o texto em curva** (SHX: 008 e 042A). A 061 tem uma tabela vetorial que
   não é de material (profundidade das canaletas), e as 048–057 têm a "tabela de chapas"; ficaram fora deste placar.
4. **Gabarito**: as 41 tabelas transcritas por leitura visual (Claude), linha a linha, **661 linhas**: item,
   código SAM, descrição, quantidade(s) por etapa, unidade, seção e observação do que é ambíguo
   (`gabarito_itens.csv`). É referência de IA, não do Caio: **convém conferir uma amostra** (§8).
5. **Protótipo determinístico** (grade pelas linhas da tabela, dois OCRs de natureza diferente, regras de domínio)
   medido contra o gabarito em quatro versões. Cada versão corrigiu o erro que o placar da anterior apontou (§5).
6. Li o que o mini já publicou no Drive (`_sistema/projeto/ensaios_execucoes.csv` e o `prancha_tabelas.csv` de
   `aguas_joinville`) para medir a produção (§3).

## 2. As pranchas e o que as torna difíceis

| tipo | pranchas | o que pega |
|---|---|---|
| imagem colada, nítida, 400 dpi | 049–058, 060, 038, 065, 066, 009, 010, 059 | quase nada; erro de OCR em "14&61", "Ø", palavras coladas |
| imagem colada **com fundo colorido** (2ª etapa em roxo/magenta) | **019** (lodo, 50 linhas), **013**, 066 | o roxo vira "tinta" e apaga o asterisco e o 1º algarismo (`*21` → `1`) |
| imagem colada **pequena** (~200 dpi, letra condensada) | **013** (63 + 16 linhas) | itens, quantidades e `02` → `2`; o pior caso do lote |
| **valor empilhado** com traço entre eles (`01` sobre `5,26`, `pç` sobre `kg`) | 019, 009, 010, 004, 049 | o traço que separa pç de kg **corta os números**: parece riscado e não é |
| **11 tabelas pequenas** numa folha só, colunas 1ª/2ª etapa com `00` | **004** (layout) | `00` lido `oo`, `do`, `810`; "7" fino perdido (`71` → `1`) |
| **vetor com texto em curva** (sem texto real) | **008**, **042A** | não há texto: precisa rasterizar o recorte; na 042A o código não tem coluna própria no cabeçalho e há sub-itens (dois códigos na mesma linha) |
| imagem que **não é tabela** | 047 (5 renders 3D), 006 (fotos) | precisa ser descartada antes do OCR |

**Ranking de dificuldade** (linhas inteiras certas no protótipo v4): 042A 0/17 · 013 (drenagem) 1/16 · 065 1/6 ·
013 (entrada) 28/63 · 066 6/11 · 004 3/5 · 019 (lodo) 33/50 · 059 6/9 · 060 14/21. Estas são as do ensaio do mini (§7).

**Não há valor riscado** neste lote: as 9 linhas da 019 que parecem riscadas são o separador tracejado pç/kg. O
detector de risco do protótipo só dava falso positivo e ficou desligado. Riscado de verdade (revisão) precisa de
exemplo real antes de virar regra.

## 3. O que o código de hoje faz e onde perde (com evidência)

| # | ponto | onde | evidência |
|---|---|---|---|
| D1 | a imagem colada (2.600 px nativos) é **reduzida a 1.100 px** antes do OCR: a letra cai de ~25 px para ~10 px | `prancha.py:541` (`thumbnail`), `prancha.json → fatias.lado_px` | o mesmo leitor v4 com a imagem reduzida: 493 → 418 linhas certas (§5) |
| D2 | faixas fixas de **500 px** com 15 % de sobreposição cortam a linha da tabela ao meio; a duplicata só sai se as células forem idênticas | `prancha.py:544-547`, `linhas_html` | a 019 (50 linhas) vira ~9 faixas; cada borda corta uma linha de 2 andares |
| D3 | a linha **sem número** sai `confirmada`: "todo número da linha está no Vision" é verdade vazia quando não há número | `prancha.py:575` | Joinville (08/10): dezenas de linhas `[""]` com status `confirmada` |
| D4 | **não há classificador** "é tabela?": foto aérea, render 3D e mapa vão ao glm-ocr como tabela | `prancha.py:601-624` | Joinville RCE 03/06/09/10: nomes de rua do Google Earth gravados como linhas de tabela; aqui a 047 tem 5 renders |
| D5 | **tabela vetorial não é lida** como tabela (texto real ou em curva) | `pedido.py:613` (o próprio aviso) | 008 e 042A: 26 linhas de material ignoradas |
| D6 | `grade.py` (o leitor só de código) **não está na produção** e não reconhece o cabeçalho Sanepar `Nº / ESPECIF/COD SAM / DESCRIÇÃO / 1ª ETAPA / 2ª ETAPA / UN` | `grade.py:54-65`, `bancada.json:27-28` | todas as 41 tabelas usam esse cabeçalho |
| D7 | a "confirmação" do Vision é **presença** do número em qualquer lugar da faixa, não na célula | `prancha.py:572-576` | "01" está em toda faixa: confirma qualquer quantidade "01" |
| D8 | **tempo**: glm-ocr por faixa, com repetição e refazimento | `ensaios_execucoes.csv` | foz_10 em 08/10: **3.677 s para 10 pranchas**; Joinville: ~40–60 min por prancha com imagem |
| D9 | só a página 0 (`paginas_com_ia: 1`) | `prancha.json:167` | aqui não pesa (pranchas de 1 página); pesa no memorial e em jogos multipágina |

## 4. A proposta: grade primeiro, leitores depois

A tabela da Sanepar tem **linhas desenhadas**. A geometria diz, sem nenhum modelo, onde está cada célula; o OCR só
precisa ler o conteúdo de cada caixa. Isso troca "o modelo adivinha a estrutura" por "o código mede a estrutura".

```
PDF ─► localizar ─► é tabela? ─► raster nativo ─► grade (linhas) ─► células ─► 2 leitores ─► regras ─► linha
        imagem colada (pdfium)     linhas H ≥ 4      sem reduzir     OpenCV        Vision/Tesseract   decimal, unidade,
        malha vetorial (pdfplumber) fração clara>0,6  vetor: 400 dpi  morfologia    + PP-OCR (curtas)  PN/DN, catálogo SAM
```

| etapa | regra (determinística) | no protótipo |
|---|---|---|
| **E1 localizar** | imagem colada (já existe: `imagens_da_folha`, com Form XObject) + **malha vetorial** = ≥ 4 horizontais de mesma extensão empilhadas com passo ≤ 40 pt; fora do carimbo | `grade_vetor.py`, `rodar.py` |
| **E2 é tabela?** | ≥ 4 linhas horizontais com ≥ 50 % da largura e ≥ 60 % de pixels claros; senão é foto/render e não vai ao OCR | `tabela_raster.e_tabela` |
| **E3 raster nativo** | os pixels da imagem como vieram no PDF (400 dpi), **sem thumbnail**; vetor → recorte renderizado a 400 dpi; se a linha típica tem < 45 px, amplia até ~60 px | `ler()` |
| **E4 tinta** | escuro **e** sem saturação: o fundo roxo/magenta da 2ª etapa deixa de ser tinta | `tinta()` |
| **E5 grade** | horizontais por abertura morfológica (≥ 25 % da largura); verticais **por faixa de linha** com núcleo de 0,7 da altura típica (letra não vira coluna); moldura dupla descartada; a grade é apagada antes do OCR | `ler()` |
| **E6 papel da coluna** | rótulo do cabeçalho (`ESPECIF/COD`, `DESCRI`, `ETAPA`, `QT`, `UN`) → se ilegível, **ordem fixa da relação Sanepar** (Nº, código, descrição, quantidades, UN) e o conteúdo (4–6 algarismos = código) | `campo_do_cabecalho`, `inferir_papeis` |
| **E7 leitor A** | a tabela inteira **uma vez**, com caixa por palavra → palavra vai para a célula pela geometria. No mini: **Vision** (já devolve caixas, `ia.palavras_do_vision`); aqui: Tesseract `por` | `tesseract()` |
| **E8 leitor B** | as células curtas (item, código, quantidade, unidade) **empilhadas por coluna** numa faixa só → **uma chamada por coluna** ao PP-OCR (RapidOCR, ONNX, Apache-2.0), sem o classificador de ângulo (ele girava a palavra 180°: `299699` → `669667`) | `reler_coluna` |
| **E9 decidir** | A = B → `confirmada`; diferentes → fica a que tem a forma esperada (`\d{1,5}(,\d+)?`, código `\d{3,6}`, unidade conhecida); as duas válidas e diferentes → `divergente` (número: PP-OCR; código e unidade: leitor A) | `juntar` |
| **E10 regras** | funções Python com teste: vírgula decimal (`13.76` → `13,76`); valor empilhado em linha (`02 - 20,06` com unidade `pç / kg` → `02 / 20,06`); unidade por confusões medidas (`pg`, `ps`, `5d` → pç; `ka` → kg; `ud` → un; BARRAS); **PN/DN por vocabulário fechado** (só troca se a confusão O↔0, I↔1, Z↔2… leva a **um único** valor da série: `PNZO` → PN10, `DNI00` → DN100) | `decimal`, `empilhar`, `unidade`, `vocabulario.py` |
| **E11 catálogo** | o código SAM e a descrição conferidos no catálogo do orçamento (`catalogo.py` já existe): código que não existe ou cuja descrição não casa → `divergente` | **a fazer** (o catálogo está no mini) |
| **E12 modelo** | o glm-ocr **sai do caminho da tabela com grade**; fica para tabela sem linhas e, no máximo, para **uma célula** divergente — nunca a faixa inteira | — |

**Por que é determinístico:** a mesma imagem dá a mesma grade, o mesmo recorte e a mesma leitura (OCR clássico e
PP-OCR são funções puras da imagem; sem amostragem). O que muda a saída é código ou regra, versionado.

## 5. Medida: o protótipo contra o gabarito (661 linhas, 41 tabelas)

| versão | o que mudou | linhas inteiras certas | código + qtd + unidade certos | código | quantidade | 1ª etapa | 2ª etapa | unidade | descrição (semelhança) | faltou / inventou |
|---|---|---|---|---|---|---|---|---|---|---|
| v1 | grade + Tesseract + releitura por célula | 391 (59 %) | 421 (64 %) | 90,8 % | 81,9 % | 81,2 % | 83,8 % | 82,7 % | 96,1 % | 1 / 0 |
| v2 | + PP-OCR nas colunas curtas | 371 (56 %) | 412 | 92,3 % | 82,5 % | 92,3 % | 86,9 % | 77,9 % | 96,1 % | 1 / 0 |
| v3 | + decimal, ordem fixa, papel pelo conteúdo, sem detector de risco, sem giro | 434 (66 %) | 471 | 92,3 % | 84,8 % | 94,5 % | 93,1 % | 85,9 % | 96,1 % | 1 / 0 |
| **v4** | + confusões de unidade, código pelo leitor A na divergência, coluna entre descrição e UN = quantidade | **493 (75 %)** | **533 (81 %)** | 90,1 % | **95,1 %** | **96,1 %** | **93,8 %** | **93,8 %** | 96,1 % | 3 / 2 |

- **Estrutura**: 658 das 661 linhas saem no lugar certo, sem inventar linha. A grade resolve o que o modelo errava.
- **Tempo**: 41 tabelas em **366 s** num contêiner de CPU (mediana **6,6 s** por tabela; a maior, 019 com 50 linhas,
  45 s, quase todo no PP-OCR em CPU). Só Tesseract: ~3–4 s por tabela. A localização + classificação das 43
  pranchas leva < 1 min. Comparação: o foz_10 do mini levou **368 s por prancha** (3.677 s / 10).
- **Resolução (D1)**: a mesma v4 com a imagem reduzida a 1.100 px, como a produção faz, cai de **493 para 418**
  linhas inteiras certas, de 533 para 484 no essencial, e a unidade de 94 % para 86 %. Também fica **mais lenta**
  (611 s contra 366 s), porque precisa ampliar de volta o que perdeu (`placar_versoes.json → v4_reduzida_1100px`).
  Reduzir a imagem não economiza nada: perde informação e tempo.
- **O que ainda erra** (v4): 013 (imagem pequena com fundo roxo: item e código), 042A (sub-itens com dois códigos
  na mesma linha e código sem coluna), asterisco do item (`*21` → `21`, em fundo roxo), descrição com "&" → "8"
  (`14&61`), "Ø" → "Ó" e palavras coladas. A descrição está a 96 % de semelhança: serve para conferir no catálogo,
  não para copiar sem conferência.

## 6. O plano, por PR (cada um com teste e placar no gabarito)

| PR | muda | prova |
|---|---|---|
| **P1** | `grade.py` v2: a grade **pelas linhas do raster** (E3–E6), com as palavras do Vision (caixas que já existem). Entra o `opencv-python-headless` (Apache-2.0) | `testes.py` com 6 recortes do gabarito (019, 013, 004_t9, 049, 009_t1, 042A): linhas, colunas e papéis certos |
| **P2** | `prancha.py`: **tirar o thumbnail** da imagem colada (D1) e as faixas de 500 px (D2); o classificador "é tabela?" (D4); a linha sem número **não** vira `confirmada` (D3) | bancada: v1 → v2 na mesma amostra; Joinville sem linhas de rua |
| **P3** | leitor B: PP-OCR (RapidOCR + onnxruntime, Apache-2.0/MIT) nas colunas curtas, uma chamada por coluna; decisão A×B (E8–E9) em `curadoria.py` | placar por campo no gabarito: código ≥ 95 %, quantidade ≥ 96 % |
| **P4** | `regras_tabela.py`: decimal, empilhar, unidade, PN/DN por vocabulário fechado (E10) — **funções puras com teste**, as confusões em `conceitos/tabela.json` | cada regra com o exemplo que a motivou (está no `propostas.md` do dados) |
| **P5** | **tabela vetorial** (D5): malha pelo `pdfplumber` (`page.lines`/`rects`), recorte renderizado pelo pypdfium2 a 400 dpi, mesmo leitor | 008 e 042A no placar; a 061 (profundidades) entra como tabela genérica |
| **P6** | catálogo SAM na decisão (E11): código inexistente ou descrição que não casa → `divergente` | a taxa de `confirmada` errada no gabarito ≤ 0,5 % |
| **P7** | `bancada.py` passa a usar o gabarito `211_foz_pbhi` (661 linhas) ao lado de Cambé (188) | veredito por leitor nas duas obras |

**Metas para a produção no mini:** ≥ 90 % das linhas com código + quantidade + unidade certos; **0 linha inventada**;
`confirmada` com ≥ 99,5 % de acerto (o que não tem certeza fica `divergente`, nunca palpite); **≤ 15 s por tabela**
(Vision + PP-OCR no M4), sem a GPU — a tabela sai da fila da GPU e não espera a vez.

**Licenças:** o protótipo usa PyMuPDF (AGPL) só para medir aqui; a produção fica com pypdfium2 + pdfplumber
(D2 do `plano_projeto.md`). OpenCV, RapidOCR, modelos PP-OCR, onnxruntime e Tesseract são Apache-2.0/MIT.

## 7. O ensaio no mini

`conceitos/ensaios.json` ganha o ensaio **`foz_pbhi`**: a pasta `1. PBHI` e uma **lista fixa** das 10 pranchas mais
difíceis (§2), com o pedido `{foz_pbhi, 2026-10-09-a}`. Com o merge, a rodada de 5 min do mini roda **o código de
hoje** nessas 10 pranchas (prioridade 4) e publica `prancha_tabelas.csv` no Drive. Esse é o **antes**:

1. Comparar com o gabarito (`notas/prototipo_tabela/placar.py`, depois de converter as linhas de `celulas` para as
   colunas do gabarito). Esperado pelo diagnóstico: 0 linhas na 008 e na 042A (D5); a 019 em ~9 faixas; o tempo
   em dezenas de minutos.
2. A cada PR do §6, trocar o `id` do pedido: o mesmo ensaio roda de novo e o placar mostra se **subiu**.

## 8. O que preciso do Caio

1. **Merge** do ensaio `foz_pbhi` (ou rodar `codigo/ensaio.py rodar foz_pbhi` à mão) e, se o Drive do mini não
   alcançar a pasta `1. PBHI`, copiar os 10 PDFs para a entrada.
2. **Conferir uma amostra do gabarito** — 019 (lodo), 013 (entrada) e 042A, que são as difíceis — e decidir as
   convenções que ficaram em aberto: a faixa de título acima do cabeçalho conta como **seção**? `BARRAS` é unidade?
   `02 - 20,06` vira dois valores (`02 / 20,06`)? Asterisco do item faz parte do item?
3. Dizer se a 2ª etapa (fundo roxo, coluna "2ª ETAPA") entra no quantitativo ou fica separada.
