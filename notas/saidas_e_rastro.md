# Saídas e rastro da extração: o que sai, como saiu e quem extraiu

**Estado: retrato do código 0v26** (07/10/2026). Pedido do Caio: manter um acervo de **como** foi extraído, **o que**
foi extraído e **quem** extraiu, para melhorar o ciclo de lições (menos desvio, mais rápido) e ir escolhendo a melhor
ferramenta para cada etapa do documento. Este documento é a referência das saídas; atualizar quando uma versão mudar
o contrato dos dados.

O exemplo abaixo foi **executado** em 07/10 sobre os PDFs sintéticos dos testes (`codigo/testes.py`): uma folha A1 de
adutora no padrão da AAT-06, um A3 em branco e um boletim de sondagem com texto real. A IA foi **simulada** (as
respostas falsas do teste: o glm-ocr "continua" as estacas até a 323, como fez de verdade em 26/09). Os valores são os
que o código produziu; os **tempos não valem como medida** (sem modelo de verdade). O primeiro ensaio real é o
`foz_10` (`conceitos/ensaios.json`).

## 1. A sequência de hoje

```
ENTRADA          o extrator entrega o PDF (1ª página A3 ou maior; boletim A4 desde o 2v96) → entrega.py
   │
FASE 1           ler_prancha · código (pypdfium2) · sem GPU · ~0,01–0,3 s por PDF
LEITURA INICIAL  formato, nº de páginas, caracteres, caminhos, imagens, camadas do CAD (OCG)
(proto-inventário)  → classe (raster | vetorial com texto | vetorial com texto em curva) e camada de leitura
   │             → é prancha? (A3+ e 2 sinais: camadas, nome de desenho, palavras de carimbo, desenho denso)
   │             → é boletim de sondagem? (sinais no texto, ou o nome)
   ├── boletim ──► FASE 2b  ler_sondagem · código · páginas com texto real
   │                         └► FASE 3b  ler_sondagem_ia · glm-ocr × Vision · páginas digitalizadas (vez da GPU)
   ├── prancha ──► FASE 2a  ainda no ler_prancha · código
   │                         carimbo pelo texto real (rótulos-âncora), família e desenho (regras), eixo (faixa ou camadas)
   │              FASE 3a  ler_prancha_ia · vez da GPU (maestro)
   │                         carimbo desenhado (glm-ocr × Vision) · fatias de 1.100 px (glm-ocr × Vision)
   │                         tabelas coladas como imagem (glm-ocr em modo tabela × Vision)
   │                         desempate da família (qwen3 × Apple FM) · conferência eixo × escala × tubo (código)
   └── nenhum ───► para aqui (fica a linha com o motivo)
```

**O que ainda não é como no plano** (`notas/plano_inventario_roteamento.md`): a leitura inicial olha só a **página 1**,
mistura perfil com extração (o carimbo e o eixo saem na mesma tarefa) e não registra regiões; o "roteamento" é o `if`
de `ciclo.proxima_tarefa`. É o ponto de partida que o inventário por página vai substituir.

## 2. Quem extraiu cada coisa (o exemplo executado)

| documento | fase | quem (executor) | o que saiu | status |
|---|---|---|---|---|
| `012-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1.pdf` | 1 leitura inicial | código (pypdfium2 + pdfminer para as camadas) | A1, 1 camada CAD, vetorial com texto em curva, camada de leitura `vetor`; **prancha** (3 sinais: camadas, nome, carimbo) | — |
| | 2a carimbo | código (texto real na região fixa `[0.70 0.62 1 1]`) | número, título, projetista, responsável, CREA, ART, fase, folha 012/019, data, revisões R0→**R1**, confere com o nome do arquivo | `codigo` |
| | 2a família | código (regras de `prancha.json`) | **adutora**, grupo linear, desenho **planta e perfil** | `regra` |
| | 2a eixo | código (faixa colorida na geometria) | 300 mm de papel, 1 deflexão de 45° | — |
| | 3a fatias | glm-ocr **e** Vision em cada uma das 24 fatias | 96 valores confirmados (escala 1:1000, cota 246.939, EST77, EST78…); 24 só do glm-ocr (EST323: inventada, fica pendente) | `confirmado` / `so_glm` |
| | 3a conferência | código | escala 1:1000 confirmada → **eixo 300,0 m**; sem tubo confirmado na relação | `sem_tubo_confirmado` |
| `memorial_a3.pdf` | 1 leitura inicial | código | A3, 0 sinais → **não é prancha**; nenhuma IA | — |
| `SP-03.pdf` | 1 leitura inicial | código | A4 → **boletim de sondagem** | — |
| | 2b boletim | código (texto real, padrões de `sondagem.json`) | furo SP-03, E 712.400, N 7.098.200, cota 812,45, N.A. 2,30 m, final 3,45 m, impenetrável; N-SPT 9 · 14 · 27; 2 camadas de solo | `codigo` |

Leitura do quadro: **tudo o que tinha texto real saiu por código**, sem modelo. A IA só entrou onde o texto virou
desenho (as fatias da planta), e lá o número que só um leitor viu não virou fato.

## 3. O que sai: os arquivos

Publicados em `saida/<acervo>/<obra>/projeto/` (a obra) e `saida/_sistema/projeto/` (todas as obras), CSV com `;`
e UTF-8 com BOM. Toda linha leva `id, caminho, acervo, obra, versao_documento, extrator, arquivo, rodada,
versao_codigo, commit`: de onde veio, que versão do PDF, que tarefa e que código.

| arquivo | grão | colunas que importam | exemplo (do quadro acima) |
|---|---|---|---|
| `pranchas.csv` | 1 por PDF × tarefa (`prancha` = código; `prancha_ia` = depois da IA) | formato, e_prancha, motivo, boletim_sondagem, classe, camada, sinais, nomes_camadas, carimbo_* (16 campos), familia, grupo, familia_origem, desenho, eixo, eixo_mm, deflexoes, eixo_camadas, escalas_confirmadas, eixo_m, tubo_relacao_m, conferencia, fatias_lidas/planejadas, valores_confirmado/so_glm/so_vision, linhas_tabela(_confirmadas) — 71 colunas | A1 · adutora · planta e perfil · eixo 300 m · `sem_tubo_confirmado` · 24/24 fatias · 96 confirmados |
| `carimbos.csv` | 1 por campo do carimbo × leitor | leitor (`pdf` ou `glm_ocr+vision`), campo, valor, valor_vision, status, erro | `titulo = ADUTORA DE AGUA TRATADA AAT-06 · codigo` |
| `prancha_leituras.csv` | 1 por valor × fatia | fatia, caixa_px, padrao (cota, estaca, escala, DN, declividade, coordenada…), valor, status, concordancia_ocr | `fatia 1 · estaca · EST323 · so_glm` |
| `prancha_tabelas.csv` | 1 por linha de tabela colada × faixa | imagem, faixa, linha, celulas (JSON), status, nao_confirmados | vazio no exemplo (a folha sintética não tem imagem colada) |
| `sondagens.csv` | 1 por campo do boletim × página | leitor, pagina, furo, campo, valor, valor_vision, status | `nivel_agua = 2,30 · codigo` |
| `sondagem_spt.csv` | 1 por metro ensaiado | furo, profundidade_m, golpes, nspt, nspt_vision, status | `3,0 m · 10/15 12/15 15/15 · 27` |
| `sondagem_camadas.csv` | 1 por camada do perfil de solo | furo, de_m, ate_m, descricao, status | `1,20–3,45 · areia fina siltosa, cinza, pouco compacta` |

E, desde a 0v25–0v26, em `saida/_sistema/projeto/`:

| arquivo | o que é |
|---|---|
| `bancada_agentes.csv` | o placar de cada leitor (código, Vision, glm-ocr, gemma3, qwen3, Apple FM, Kimi e reservas) contra o gabarito: qualidade, tempo útil, taxa de erro, tempo perdido, veredito |
| `licoes_projeto.csv` | cada falha medida: classe, gravidade, destino da correção, se o código já acertava |
| `ensaios.csv` · `ensaios_execucoes.csv` | cada execução de ensaio × documento: tarefas, tempos, erros, o que mudou desde a anterior |

## 4. Onde está o rastro (como, o quê, quem)

| pergunta | onde responde | o que guarda |
|---|---|---|
| **o quê** foi extraído | os 7 CSVs acima | o valor como está escrito e o normalizado |
| **quem** extraiu | colunas `extrator` (tarefa), `leitor` e `status` | `codigo`/`pdf` = texto real; `confirmado` = dois leitores de natureza diferente; `so_glm`/`so_vision` = um só; `regra`/`ia_concordante` na família |
| **com que código** | `versao_codigo` e `commit` em toda linha | a linha diz com que código saiu; `versoes.jsonl` diz o que cada versão mudou |
| **com que modelo e pedido** | `dados/congelamento.jsonl` | motor, modelo, digest do Ollama, hash do prompt, hash da imagem, opções, resposta, tempo útil e perdido, tokens |
| **quanto tempo** | `dados/execucoes.jsonl` | uma linha por tarefa × documento: segundos, fatias, confirmados, erro |
| **o que falhou** | `dados/falhas.jsonl`, `licoes_projeto.csv` | o erro, o rastro do Python, a classe da lição |
| **se melhorou** | `ensaios.csv` (coluna `mudou`), `licoes_historico.jsonl` | o que mudou entre execuções do mesmo ensaio; lições novas e resolvidas |
| **tudo junto, por documento** | `rastro.csv` (0v29), `ensaios_rastro.csv` | documento × etapa × executor: entrada, resultado, valores, confirmados, pendentes, tempo da tarefa, versão |

## 5. Lacunas do rastro (para as próximas versões)

1. ~~**Não há uma vista única por documento.**~~ **Feito na 0v29:** `rastro.csv` (§7) — uma linha por documento ×
   etapa × executor. Falta nele a assinatura do congelamento de cada chamada (está em `dados/congelamento.jsonl`).
2. **Sem caixa por valor.** A leitura guarda a fatia (`caixa_px`), não a caixa do valor dentro dela; o carimbo e a
   tabela não guardam caixa nenhuma. Sem isso não se volta do dado ao trecho exato da prancha (plano §19).
3. **Só a página 1.** As páginas 2…N de um PDF não têm linha nenhuma.
4. **O tempo da tarefa mistura etapas** (`ler_prancha_ia` soma carimbo, fatias e tabelas): não diz qual etapa é cara.
5. **O executor da etapa não é escolhido, é fixo** — o placar da bancada existe, mas nada o consome (é o roteador
   do plano).

## 6. O que ainda não sai

- trecho, dispositivo (ventosa, descarga, registro, PV) e estrutura como dado, com geometria;
- estaca e progressiva; perfil (cota de terreno e geratriz por estaca);
- georreferência (malha → coordenadas, com resíduo);
- regiões da folha (inventário por página);
- DXF, GeoPackage, KML, LandXML.

Tudo isso está no `notas/plano_inventario_roteamento.md`, na ordem das fases F1–F10.

## 7. O rastro (0v29): a vista única de quem leu o quê

`codigo/rastro.py` junta o que as tarefas já gravaram — sem ler PDF nem chamar modelo — e publica `rastro.csv` por obra
e em `_sistema/projeto/` a cada publicação que muda alguma família; os ensaios levam o deles em `ensaios_rastro.csv`.
Colunas: `id, acervo, obra, arquivo, versao_documento, ordem, etapa, tarefa, executor, natureza, entrada, resultado,
valores, confirmados, pendentes, segundos_tarefa, versao_codigo, commit`.

O exemplo da §2, como sai no `rastro.csv` (tempos sem valor de medida: IA simulada):

| arquivo | # | etapa | tarefa | executor | entrada | resultado | valores | confirmados | pendentes | s |
|---|---|---|---|---|---|---|---|---|---|---|
| SP-03.pdf | 1 | leitura_inicial | ler_prancha | codigo:pypdfium2 | página 1 de 1 | A4 · boletim de sondagem | | | | 0,00 |
| SP-03.pdf | 2 | boletim | ler_sondagem | codigo:texto_do_pdf | 1 página | furo SP-03 · codigo 13 | 13 | 13 | 0 | 0,00 |
| memorial_a3.pdf | 1 | leitura_inicial | ler_prancha | codigo:pypdfium2 | página 1 de 1 | A3 · vetorial_curva · nenhum (0 sinais) | | | | 0,07 |
| 012-…-AAT06PTPER-R1.pdf | 1 | leitura_inicial | ler_prancha | codigo:pypdfium2 | página 1 de 1 | A1 · vetorial_curva · prancha (3 sinais) | | | | 0,01 |
| | 2 | carimbo | ler_prancha | codigo:texto_do_pdf | região do carimbo · camada texto | codigo 12 | 12 | 12 | 0 | 0,01 |
| | 3 | familia | ler_prancha | regra:prancha.json | nome + texto do carimbo e das notas | adutora · linear · planta_e_perfil | | | | 0,01 |
| | 4 | eixo | ler_prancha | codigo:geometria | caminhos da página 1 | faixa · 300 mm · deflexão 45° | | | | 0,01 |
| | 5 | fatias | ler_prancha_ia | glm-ocr × Vision | 24 de 24 fatias | confirmado 96, so_glm 24 | 120 | 96 | 24 | 1,93 |
| | 6 | conferencia | ler_prancha_ia | codigo:conferencia | escala 1:1000 · tubo da relação — | sem_tubo_confirmado · eixo 300 m | | | | 1,93 |

Como usar para escolher ferramenta: filtrar por `etapa` e comparar `executor` × `confirmados ÷ valores` × `pendentes`
× `segundos_tarefa` entre obras e entre execuções do mesmo ensaio. A etapa em que o executor `codigo:*` já resolve
não precisa de modelo; a etapa com muitas `pendentes` é onde a próxima lição vale mais.
