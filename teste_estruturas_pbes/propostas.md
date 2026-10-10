# Propostas para o `ialocal.projeto` (a partir do teste do PBES de Foz, 10/10/2026)

Cada proposta diz o que mudar, onde, e o exemplo real que mostra o erro. Nada aqui altera o código do Mini: são pedidos de PR, na ordem em que mais
mudam o resultado. As funções já existem e têm teste em `codigo/testes_pbes.py`; falta decidir onde moram.

## P1. Um perfil de tabela por tipo, em `conceitos/tabela.json`

**Erro:** `tabela.montar()` só conhece a relação de materiais da Sanepar (Nº · ESPECIF · DESCRIÇÃO · QUANT · UN). Em 12 de 12 pranchas devolveu
`cabecalho = None` e 0 itens, inclusive nas 5 caixas que o `malhas()` achou direito.

**Proposta:** `tabela.json → perfis`: cada perfil declara o rótulo que o reconhece, as colunas e como achar as linhas. Três perfis cobrem o PBES:

| perfil | reconhece por | colunas | linhas |
|---|---|---|---|
| `resumo_materiais` | `RESUMO DOS MATERIAIS` | DIVISÃO · ÁREA DE FORMAS (m²) · VOLUME DE CONCRETO (m³) | entre as horizontais; linha `TOTAL :` |
| `resumo_aco` | `RESUMO AÇO CA 50-60` | AÇO · BIT (mm) · COMPR (m) · PESO (kg) + `Peso Total 50A = N kg` | tinta na coluna PESO |
| `armadura_tqs` | `AÇO · POS · BIT · QUANT · COMPRIMENTO UNIT/TOTAL (cm)` | 6 colunas pelas verticais **do cabeçalho** | tinta na coluna TOTAL; linha sem tinta ali = título de elemento (`PAR1`, `V3`…) |

Duas barras de uma linha (`LASTRO DE CONCRETO SIMPLES … m³`, `ENCHIMENTO … m³`) ficam acima do RESUMO DOS MATERIAIS e saem por rótulo + número. Casos que
o perfil `armadura_tqs` precisa tratar (todos vistos): **duas tabelas lado a lado na mesma caixa** (7 verticais por tabela, a do meio comum; 7 pranchas: POR01-002, ACT02-008/010/011, ACT01-019/021, MOD01-008),
a **grade interrompida** pelos títulos de elemento (as colunas se medem só no cabeçalho), e `--CORR--`/`--VAR--` na coluna UNIT.

## P2. Localização: duas constantes que escondem as tabelas

| constante | hoje | por quê erra | proposta |
|---|---|---|---|
| `localizar.malha_min_linhas` | 5 | a tabela de armadura só tem horizontais longas no cabeçalho e nos títulos de elemento (GUARITA-002: nenhuma caixa; com 2, aparece) | 2, e classificar a caixa pelo **título** (OCR do topo) em vez de pelo número de linhas |
| `localizar.carimbo` | `[0,70; 0,70; 1; 1]` | engole o RESUMO AÇO (x ≈ 0,70 · y ≈ 0,79 da folha) | excluir só o selo real, `x > 0,84`, ou melhor: pelo conteúdo (SANEPAR, `ARQUIVO ELETRÔNICO`) |

Efeito medido (12 pranchas): o `malhas()` acha 20 de 28 tabelas-alvo; armadura 4/8 e RESUMO AÇO 5/8. Com as duas mudanças o extrator de referência achou uma tabela de armadura e um RESUMO AÇO em cada uma das 34 pranchas de aço, e um RESUMO DOS MATERIAIS nas outras (115 tabelas).

## P3. Célula isolada: o leitor B não pode ser o RapidOCR nas colunas curtas

**Erro:** o detector do PP-OCR descarta o dígito isolado. Na coluna BIT, o `8` some (ACT01-009: 8 de 29 linhas); na POS, o `9`. O `tabela.json` põe o RapidOCR como
leitor B das colunas `curtas`, justo onde ele falha.

**Proposta:** por célula, `tesseract --psm 7` com `tessedit_char_whitelist` por coluna (POS `0-9`; BIT `0-9.`; QUANT `0-9`; UNIT `0-9CORVA-`; TOTAL `0-9`; classe `0-9AB`).
Os dois leitores só concordam em célula de vários dígitos; nas curtas o Tesseract lê e a regra física (P4–P6) é a testemunha. O mesmo vale para a bitola:
`6.3` e `12.5` o RapidOCR lê; `8` e `5` ele perde.

## P4. `reparar(q, u, t)`: quant × unit = total (cm) é uma regra do desenho

**Função** (em `conferir.py`, com teste): se `q × u ≠ t`, corrige a **uma** célula que, com distância de edição ≤ 2, fecha a conta; se falta uma, calcula. Registra o reparo.

| lido | corrigido | por quê |
|---|---|---|
| 56 · 693 · `538808` | `38808` | dígito espúrio no total (360 L, PAR9 pos 12) |
| 6 · `3582` · 2292 | unit `382` | 6 × 382 |
| 44 · `541` · 15004 | unit `341` | 44 × 341 |
| `—` · 809 · 7281 | quant `9` | 7281 ÷ 809 |

42 de 968 linhas (4,3%) precisaram de reparo; **depois dele, 885 de 890 linhas com unit numérico fecham a conta** e nenhuma falha. É a mesma ideia do princípio do Mini
("número só é fato com testemunha de natureza diferente"), com uma testemunha que não é OCR.

## P5. Física NBR 7480 e consenso de três fontes

**Funções** (`extrator_pbes.bitola_pela_massa`, `conferir` consenso): (a) a bitola que o OCR perdeu sai de `peso ÷ comprimento` ≈ kg/m (`2810 m · 1110 kg` → φ8,0; `2504 · 1545` → φ10;
`70 · 67` → φ12,5); (b) o **aço total** só é adotado quando duas das três fontes concordam: Σ das tabelas de armadura, Σ das linhas do RESUMO AÇO, `Peso Total` impresso.

Exemplo: ACT01-012, o OCR leu o Peso Total como `208`; Σ tabelas = 2081 e Σ linhas = 2082 → adotado 2082 (resumo geral: 2082). Resultado: **33 de 33 pranchas a ≤ 2 kg do resumo geral**,
contra 30 de 33 usando só a soma das tabelas. Sem consenso (2 pranchas) o aço fica marcado `sem consenso` e não vira fato.

## P6. POS reindexada por elemento

O dígito isolado erra (185 de 968 POS, 19%). A POS é sequência 1..n dentro do elemento: `groupby(elemento).cumcount() + 1`, guardando `pos_lida` para auditoria. É o que a skill
`extrair-quantitativos-pdf` já prescreve ("reindexar determinístico por grupo").

## P7. O resumo geral é uma segunda testemunha de graça

O `Resumo de Materiais.pdf` tem camada de texto: `codigo/resumo_gabarito.py` lê as 104 linhas × 13 colunas pelo x do cabeçalho e **fecha 13 de 13 colunas com a linha TOTAIS**
(2336,84 m³ · 12304,84 m² · 229.654 kg …). Proposta: o Mini lê esse tipo de resumo por código e confere cada prancha contra a linha de mesmo `codigo_arquivo`. Cada diferença vira linha
em `divergencias.csv` com a classe (`revisao`, `diferenca`, `nao_extraido`), como já sai aqui. Achados que só esse cruzamento mostrou: o PDF `ETL01FORMA` da pasta REFORMA_EDIFIC_LODO é
uma estrutura metálica, não o desenho de concreto que a linha do resumo descreve; `MOD01` está em R1 na pasta e R0 no resumo.

## P8. Decimal por célula

Na mesma tabela: `0,86` (divisões) e `11.48` (TOTAL). `num_br()`: vírgula e ponto são decimais; só 2 casas aqui; `--` é vazio, não zero.

## P9. Tabela em branco é resposta, não falha

10 de 20 folhas de forma têm o RESUMO DOS MATERIAIS em branco (as quantidades da estrutura ficam numa folha só), e o resumo geral traz `0,00` nelas. O Mini deve gravar `None` com o motivo
(`tabela_vazia`), nunca reprocessar nem inventar.

## O que o teste **não** mostrou (pedir antes de decidir)

- Se o **Vision** lê as células curtas melhor que o Tesseract (só existe no Mac mini). Rodar `placar_tabelas.py` com os perfis P1 e comparar Vision × Tesseract × RapidOCR por coluna.
- O caminho `ler_prancha_ia` (glm-ocr em fatias) não foi executado: as fatias da prancha inteira vão a outro lugar, não a estas tabelas.
- As 3 divergências que restam (ACT02-009 +275 kg, CXA05 +39 kg, MOD01-008 R1 +24 kg) precisam de releitura por célula a 600 DPI e de um segundo leitor; hoje ficam sinalizadas, não corrigidas.
