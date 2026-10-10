# Teste de fogo: o Mini extrai as tabelas das pranchas estruturais do PBES de Foz?

10/10/2026 · Drive `3. PBES/DE` (47 PDFs, 8 estruturas) · gabarito: `QUANTITATIVOS/Resumo de Materiais.pdf`

## Resposta curta

| pergunta | resposta | evidência |
|---|---|---|
| O código que o Mini tem hoje (`tabela.py`) extrai essas tabelas? | **Não: 0 itens em 12 de 12 pranchas**, e acha só 20 das 28 tabelas-alvo | `resultados/consolidado/resultado_codigo_do_mini.json`, `mini_localizacao.csv` |
| Dá para extrair com exatidão com código + OCR local? | **Sim, com ressalvas medidas**: 174 de 177 quantidades comparáveis conferem com o resumo geral (98,3%). Não entram as 3 do `ETL01`, que é outro desenho (§5.2) | `quantitativos_por_estrutura.csv` |
| O resumo geral serve de gabarito? | **Sim**: lido pelo código (camada de texto), fecha **13 de 13 colunas** com a linha TOTAIS impressa | `gabarito/gabarito_resumo.json` |
| A rastreabilidade por estrutura → prancha → tabela → quantidade foi mantida? | Sim, em pastas e em toda linha de todo CSV | `resultados/<estrutura>/<codigo_arquivo>/` |

O Mini falha porque o `ler()` dele só reconhece o cabeçalho da *relação de materiais da Sanepar* (Nº · ESPECIF · DESCRIÇÃO · QUANT · UN). Não é erro de OCR: é uma tabela de outro tipo. As tabelas das pranchas estruturais (TQS) são outras três e não têm linha horizontal entre as linhas de dado.

## 1. O que foi testado

- **47 PDFs**, todos de página única, vetoriais, com ~120 caracteres de texto real (só o nome do arquivo no carimbo). Todo o resto virou curva: **a leitura exige render + OCR** em todos.
- Estruturas (nome da pasta do Drive → unidade construtiva): `MOD_TRATAM_MICRO_AREIA_600Ls` (ACT01, 21), `MOD_TRATAM_MICRO_AREIA_360Ls` (ACT02, 12), `INTERLIGAÇÕES` (CXA01–05, 5), `BLOCOS_DE_APOIO_E_ANCORAGEM` (BLO01, 3), `GUARITA` (POR01, 2), `MOD_TRATAM_FILTROS_NOVOS` (MOD01, 2, revisão R1), `ABRIGO_BOMBAS_PRODS_QUIMICOS` (ABR01, 1), `REFORMA_EDIFIC_LODO` (ETL01, 1).
- Tabelas-alvo localizadas: **115** (34 de armadura, 34 RESUMO AÇO, 46 RESUMO DOS MATERIAIS, 1 resumo de material metálico), mais as barras LASTRO e ENCHIMENTO.
- Duas frentes: **(A)** o código do Mini, sem alteração; **(B)** um extrator de referência (Claude) com o método da skill `extrair-quantitativos-pdf`, para saber o que é possível e comparar.

## 2. (A) O código atual do Mini

Fluxo igual ao de `tabela.ler_tabelas`: `malhas()` → `e_tabela()` → `ler()` com os leitores de `conceitos/tabela.json`. Nenhuma linha do Mini foi alterada.

| | resultado |
|---|---|
| Pranchas na amostra (estratificada: uma por tipo e estrutura) | 12 de 47 |
| Itens extraídos | **0 em 12/12** |
| Caixas desenhadas que o `malhas()` achou | 20 de 28 tabelas-alvo (IoU > 0,5): RESUMO DOS MATERIAIS 10/11, RESUMO AÇO 5/8, **armadura 4/8**, metálico 1/1 |
| Por que não acha | (1) `malha_min_linhas = 5`: a tabela de armadura só tem horizontais nos títulos de elemento (verificado na GUARITA-002: sem caixa com 5; com 2, aparece); (2) a zona `carimbo = [0,70; 0,70; 1; 1]` engole o RESUMO AÇO, que fica em x ≈ 0,70 · y ≈ 0,79 da folha |
| Por que não lê o que acha | `montar()` só aceita como cabeçalho a linha com `descricao` e pelo menos 3 rótulos reconhecidos (item, código, descrição, quantidade, UN); AÇO · POS · BIT · QUANT · COMPRIMENTO não casa: `cabecalho = None`, `itens = []` |

**Limite do teste:** o Vision só existe no macOS. Aqui o leitor A foi o Tesseract (o 2º da cadeia do `tabela.json`) e o B o RapidOCR, como no Mini. O caminho `ler_prancha_ia` (glm-ocr via Ollama) **não foi executado**. A conclusão "0 itens" vem do `montar()`, que descarta a tabela antes de qualquer leitor, então o leitor A não a mudaria.

## 3. (B) O que a leitura de referência consegue

Método: grade (as funções de geometria do próprio Mini) → OCR → linhas pela tinta na coluna TOTAL → cada célula lida pelo Tesseract com lista de caracteres por coluna, com o RapidOCR como segundo leitor → reparo determinístico → conferência física.

### 3.1 Forma, concreto, lastro, enchimento (RESUMO DOS MATERIAIS)

21 pranchas de forma ou forma+armadura; 20 têm linha no resumo geral. Em **10** o resumo geral traz valores; nas outras 10 traz 0,00 ou vazio **e a tabela da prancha está em branco** (as quantidades da estrutura ficam numa folha só): nenhuma foi inventada. Das 10 com valores:

| grandeza | conferem | exceção |
|---|---|---|
| concreto (m³), forma (m²), lastro (m³) | 9 de 9 lidas | a 10ª é `REFORMA_EDIFIC_LODO`, que é outro desenho (§5.2): não extraída |
| enchimento (m³) | 2 de 2 (6,66 e 23,25) | |

A soma das divisões fecha com a linha TOTAL em 10 de 10 tabelas preenchidas lidas (as 9 acima + ABR01), em volume e em área. O TOTAL usa ponto (`11.48`) e as divisões vírgula (`0,86`) na mesma tabela: o decimal é por célula.

### 3.2 Aço (tabelas de armadura + RESUMO AÇO)

954 linhas de armadura lidas nas 34 pranchas de aço (953 com total e bitola) (33 com linha no resumo geral; ABR01 não tem).

| conferência | resultado |
|---|---|
| Aço total adotado (consenso de 3 fontes) × resumo geral | **33 de 33 a ≤ 2 kg** (23 exatos, 10 com ±1–2 kg) |
| Só a soma das tabelas de armadura (Σ comprimento × kg/m, NBR 7480) × resumo geral | 30 de 33 a ≤ 2 kg |
| Aço por bitola (soma das tabelas) × resumo geral | 112 de 115 células (≤ 3 kg) |
| Linhas com unidade numérica em que quant × unit = total (após reparo) | 883 de 883 (100%) |
| Reparos automáticos (todos registrados em `reparo`) | 40 de 954 linhas (4,2%): 19 quant, 10 unit, 10 total, 1 suspeita |
| POS que o OCR leu diferente da sequência | 52 de 954 (5,5%): é o dígito isolado; a POS é **reindexada** por elemento |

O **consenso** usa três fontes independentes: Σ das tabelas, Σ das linhas do RESUMO AÇO e o "Peso Total" impresso. O valor só é adotado quando duas concordam (princípio do Mini: número só é fato com duas leituras). Exemplo real: na ACT01-012 o OCR leu o Peso Total como `208`; as outras duas fontes dão 2081–2082 e o consenso corrige.

**Divergências que restam (3 células, todas em φ8):**

| prancha | diferença | diagnóstico |
|---|---|---|
| ACT02-009 | +275 kg | uma célula: PAR16 pos 6, total lido `77355` com 33 barras `--VAR--` (23 m por barra, impossível). Candidatos por retirada de um dígito: 7355, 7735, 7755. Fica `SUSPEITO` no CSV, sem inventar |
| CXA05 | +39 kg | soma das tabelas 838 vs 799; uma ou mais linhas com bitola ou total errados, ainda não localizadas |
| MOD01-008 **R1** | +24 kg | o resumo geral traz a revisão R0; a Σ das tabelas R1 (1471) também difere do RESUMO AÇO impresso na própria prancha (1447): erro de leitura nosso |

O que **não** ficou bom: o RESUMO AÇO por bitola perdeu dígitos em 2 células (`14` por `144` e `5` por `85`); por isso a conferência por bitola usa a soma das tabelas, e o RESUMO AÇO só entra quando bate.

### 3.3 O que não foi verificado linha a linha

Não existe gabarito por linha de armadura. A exatidão linha a linha foi garantida por regra física (quant × unit = total; bitola por peso/comprimento) e por **uma prancha conferida visualmente por inteiro** (ACT01-009: 29 linhas, todos os valores batem; só a POS 9, que o OCR não lê, e que a reindexação resolve). As 70 linhas `--CORR--`/`--VAR--` não têm unit para conferir: valem pelo total e pela soma da prancha.

## 4. Cobertura: o que o resumo geral lista e a pasta tem

| | arquivos |
|---|---|
| Linhas do resumo geral | 104 (102 nomes distintos) |
| PDFs na pasta (exatos) | 44 |
| PDFs na pasta em **outra revisão** (MOD01 001 e 008: o resumo traz R0, a pasta R1) | 2 |
| PDFs na pasta **sem linha no resumo** (ABR01) | 1 |
| Linhas do resumo **sem PDF na pasta** (MOD01 17, CAT 10, CMC 8, EEE 7, ETL01 6, REC 5, DEP 2, CXA saída de água tratada 3; 5 deles são projetos de impermeabilização) | 58 |

Os 58 desenhos que faltam impedem fechar a linha **TOTAIS** da obra (229.654 kg de aço). Só as 46 linhas comparáveis fecham: soma do aço extraído 80.659 kg × 80.662 kg no resumo (−3 kg), em 33 pranchas.

## 5. Achados sobre o próprio projeto (auditoria)

1. **Revisões diferentes.** `MOD01 001` e `008` estão em R1 na pasta e em R0 no resumo; o Peso Total impresso na prancha R1 é 6977 kg e o resumo diz 6978 kg.
2. **Arquivo que não corresponde à linha.** `REFORMA_EDIFIC_LODO/001-…ETL01FORMA-R0.PDF` é uma **estrutura metálica** ("ESTRUTURA METÁLICA · FORMAS, PLANTAS, CORTE E DETALHES"; tabela "RESUMO DO MATERIAL (TOTAL)", itens somam 1404,0 kg). A linha de mesmo nome no resumo (87,95 m³ · 576,30 m² · 4,34 m³) e a Relação de Desenhos ("LOCAÇÃO, CARGAS, FORMA DO PAVIMENTO TÉRREO…") descrevem outro desenho de concreto. Possível troca de arquivo na pasta; precisa de confirmação do Caio.
3. **Arredondamento do desenho.** Em 10 pranchas o total do resumo difere ±1–2 kg do impresso na folha. Em `BLO01-002` o Peso Total impresso é 427 kg e a soma das linhas do próprio RESUMO AÇO, 426.
4. **Nome de arquivo duplicado no próprio resumo.** `…CXA01FORMARMAD-R0` e `…CXA02FORMARMAD-R0` aparecem duas vezes (linhas 49 e 100; 51 e 101), em unidades diferentes: "Caixas saída água tratada CX01/CX02" (folha 01/02) e "Caixas de interligação chegada água bruta – caixa 01/02" (folha 01/01). Os PDFs da pasta INTERLIGAÇÕES são os da segunda. Duas linhas do resumo com o mesmo nome de arquivo e conteúdo diferente quebram qualquer chave por nome: a chave tem de ser (arquivo, unidade) ou (arquivo, folha).
5. **ABR01** (abrigo de bombas) não tem linha no resumo geral: 4,77 m³ · 35,43 m² · 0,22 m³ lastro · 477 kg de aço, extraídos aqui.

## 6. Custo

~20 min de relógio para as 47 pranchas em 4 processos (CPU ≈ 6.700 s somados), numa máquina de 4 núcleos sem GPU. Cada prancha ≈ 2 min de CPU.

## 7. Ressalvas

- O gabarito (resumo geral) é do mesmo projetista que as pranchas: mede **concordância**, não corretude do projeto. Erro comum aos dois não aparece.
- O teste do Mini cobre 12 de 47 pranchas; o resultado é uniforme (0 itens), não há razão para esperar diferença nas outras 35.
- Leitor A do Mini = Tesseract, não Vision (ver §2).
- Os números por linha de armadura **não** foram auditados por uma segunda pessoa.
