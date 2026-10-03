# Projeto — extração de pranchas: vetor, carimbo, tabelas, elementos e lugar

**Estado: tese, com teste de mesa** (26/09/2026; `notas/teste_prancha_2026-09-26.md`). Plano de implementação, antes do código. Muda por
medida, registrada no §17 do `MASTER-PLAN.md`. Detalha o §8 (extração) e o §10.4
(geografia) para a classe `prancha_pdf` da bancada E3.

## 1. Premissa do Caio, e o que a corrige

> *"O projeto é muito complexo e tem informação de desenho, então quero várias
> extrações para o mesmo arquivo. São as informações mais ricas sobre o escopo da
> obra, o core business da engenharia. O PDF precisa virar vetor, talvez DXF. Toda
> prancha tem carimbo no canto inferior direito, que diz quando e a que se refere.
> Tem tabela de materiais. A obra é localizada (estrutura de concreto: viga, pilar,
> laje) ou linear (rede de água, esgoto, adutora). E o projeto precisa ser
> georreferenciado."*

**Certo no essencial, com três ajustes.**

| premissa | ajuste | por quê |
|---|---|---|
| "converter para DXF" | o DXF é **vista**, não fonte. A fonte é uma tabela de primitivas (`geometria.parquet`: segmento, polilinha, curva, texto, com coordenada, espessura, cor, traço e camada). O DXF sai dela, regenerável, para abrir no AutoCAD ou no QGIS | DXF não se consulta (não dá "todos os textos dentro do carimbo" nem "polilinhas grossas na zona da planta"); e é derivado, como o `.md` da conversão |
| "o PDF vira vetor" | só se **já for** vetor, e mesmo a vetorial é **mista**: na AAT-06 (AutoCAD 2022) só o carimbo tem texto real (662 caracteres); estacas, cotas e o quadro do perfil viraram curva, e a relação de materiais é uma **imagem colada**. A escaneada não vira vetor: tem rota própria por imagem (§4-A) | teste de mesa de 26/09 |
| "várias extrações do mesmo arquivo" | sim, e cada uma é **uma tarefa da fila** com dependência declarada (`conceitos/rotas.json`), não um script único. Uma que falha não derruba as outras; uma que melhora refaz só a si mesma (`refazer`) | é o desenho que o orquestrador já tem (§3 de `plano_orquestracao.md`) |

**O que o carimbo não diz sozinho.** A prancha é **uma revisão** de **um desenho**
de **um projeto**. A mesma folha em R0, R1 e R2 são três alegações sobre o mesmo
escopo, em vigências diferentes (§7.4: `valido_de` / `valido_ate`). Sem ligar as
revisões, o sistema soma a mesma tubulação três vezes (§7.6).

## 2. Como os profissionais fazem

- **Orçamentista e planejador** não leem o desenho inteiro: leem o **carimbo**
  (o que é, que revisão), a **lista de desenhos** (se o jogo está completo), as
  **tabelas** (resumo de aço, resumo de materiais, lista de materiais hidráulicos,
  quadro de PVs) e só então **medem no desenho** o que a tabela não traz.
- **Obra linear** (rede, adutora, coletor): o projeto é **planta + perfil**. A planta
  dá o traçado com **estacas** (20 m, `12+10,00`) e os **PVs**; o perfil dá, por
  estaca, **cota do terreno, cota de fundo, profundidade, declividade, DN e
  material**. O quantitativo que move dinheiro sai do perfil: **escavação por faixa
  de profundidade** (0–1,5; 1,5–3; 3–4,5 m…), escoramento, reaterro, extensão por DN
  e material, número de PVs por faixa de altura. A conferência clássica é
  `declividade = (cota montante − cota jusante) / extensão` e `extensão = diferença
  de estacas`.
- **Obra localizada** (estrutura): o projeto é **forma + armação**. A forma dá os
  elementos com rótulo e seção (`V12 (20×50)`, `P3 (20×40)`, `L4 h=10`); a armação dá
  a **tabela de aço** (posição, bitola, quantidade, comprimento) e o **resumo por
  bitola**; a folha-resumo dá concreto por fck e forma. A conferência é física
  (NBR 7480: `peso ≈ comprimento × massa linear da bitola`) e de soma (itens = total).
  A skill `extrair-quantitativos-pdf` fez isso em 488 pranchas (99,8 %).
- **Carimbo** (legenda, NBR 16752:2020, que substituiu NBR 10068, 10582 e 13142): canto
  inferior direito, com contratante, projetista, obra, local, título, disciplina,
  fase (estudo, básico, executivo, *as built*), número do desenho, revisão, data,
  escala, folha `n/N`, formato, responsável técnico, CREA/CAU e ART; acima dele, o
  **quadro de revisões** (revisão, data, descrição).
- **CAD → PDF**: o AutoCAD e o Civil 3D exportam as **camadas como grupos de conteúdo
  opcional (OCG)** do PDF, e o próprio AutoCAD importa PDF de volta para DWG
  (`PDFIMPORT`) aproveitando essas camadas. Quando elas existem, "TUBULAÇÃO",
  "PV", "COTAS", "TEXTO" separam o desenho sem nenhuma IA. Quando não existem, a
  separação é por cor, espessura e tipo de traço — a convenção da prancha.
- **Georreferenciamento**: a planta de rede traz **malha de coordenadas** (cruzetas
  com `E = 712.400` / `N = 7.098.200`) ou **quadro de coordenadas** dos vértices e PVs,
  quase sempre em **SIRGAS 2000 / UTM** (no Paraná e em Santa Catarina, fuso 22S,
  EPSG:31982). Com três ou mais pontos se ajusta uma transformação (semelhança ou
  afim) por mínimos quadrados e se **mede o resíduo** num ponto que não entrou no
  ajuste (§10.4, regra 1). O GeoPDF (dicionário `/Measure /GEO` na página) dá a
  transformação pronta, mas é raro em projeto de saneamento. Estrutura localizada
  quase nunca tem malha: o lugar vem da planta de situação ou do endereço, e isso é
  **lugar aproximado**, não georreferenciamento.

## 3. Conceitos

| conceito | o que é |
|---|---|
| **projeto** | o conjunto de desenhos de uma obra e disciplina (o jogo de pranchas) |
| **desenho** | a folha pelo número (`001-SAA-0043-9597-PBES-DE-05`), sem a revisão |
| **prancha** | um PDF (ou página) = um desenho numa revisão; a unidade que a fila lê |
| **zona** | retângulo da folha com papel: carimbo, quadro de revisões, tabela, vista (planta, perfil, corte, detalhe), notas, malha |
| **vista** | desenho dentro da folha com título e escala própria (`PLANTA — ESC. 1:500`, `PERFIL — H 1:1000 V 1:100`) |
| **primitiva** | segmento, polilinha, curva, retângulo ou texto, em coordenada da folha (pt) |
| **coordenada de vista** | primitiva em metro no mundo, pela escala da vista (perfil tem escala H e V diferentes) |
| **coordenada geográfica** | coordenada de vista transformada para CRS (SIRGAS 2000 / UTM), com resíduo medido |
| **elemento** | o que a engenharia quantifica: trecho, PV, estaca, viga, pilar, laje, bloco |

Um ponto de pt para metro: `1 pt = 25,4 / 72 mm = 0,3528 mm` no papel; na escala
1:500, `0,3528 × 500 = 176 mm` no mundo. A escala vem do carimbo **e** da vista, e é
**conferida** contra as cotas escritas (§6).

## 4. As extrações — tarefas da fila

Tipo novo `prancha` (nível 1: PDF que casa com a classe `prancha_pdf` de
`conceitos/qualidade.json`, ou anotado pelo Caio), com as tarefas abaixo. Todas
gravam em `~/dados/extracao/<família>/` em 64 partes, como as outras.

| # | tarefa | família | depende de | executores (ordem) | sai |
|---|---|---|---|---|---|
| P0 | `perfilar_prancha` | `prancha` | `converter_texto` | código: pypdfium2 + pikepdf | formato (A0–A4 pela página), classe (vetorial com texto · texto em curva · raster), nº de primitivas, OCGs, imagens, GeoPDF sim/não |
| P1 | `vetorizar` | `geometria` | P0, não raster | código: pdfplumber (pdfminer) → candidato pypdfium2 bruto | `geometria.parquet` (primitivas) + `<ARQ>.dxf` (vista, camadas = OCG ou cor × espessura) |
| P2 | `zonear` | `zonas` | P1 (ou P0, se raster) | código: retângulos fechados da geometria; raster: linhas por OpenCV no render a 100 DPI | `zonas.parquet`: papel, retângulo, título, escala da vista |
| P3 | `ler_carimbo` | `carimbo` | P2 | código (texto da zona + rótulo-âncora) · Vision · glm-ocr (recorte a 300 DPI) · gemma3 (recorte + esquema) | campos do carimbo + quadro de revisões + conferência com o nome do arquivo |
| P4 | `ler_tabelas_prancha` | `tabela_prancha` | P2 | código (texto na grade) · OCR por âncora de cabeçalho (método da skill) · gemma3 só no que a conferência reprova | linhas de cada tabela com tipo, unidade SI e resultado da conferência |
| P5 | `classificar_projeto` | `projeto` | P3, P4 | regras (sinais abaixo) · Apple FM no texto, só na dúvida | `localizada` · `linear` · `mista` · `outra`, e a disciplina |
| P6a | `ler_rede` | `rede` | P5 = linear | código: eixo, estacas, PVs, perfil | trechos (PV montante, jusante, extensão, DN, material, declividade, cotas, profundidade) |
| P6b | `ler_estrutura` | `estrutura` | P5 = localizada | código: rótulos `V/P/L` + geometria vizinha | elementos (tipo, nome, seção, vão, pavimento) |
| P7 | `georreferenciar` | `lugar` | P2, P3 | código: GeoPDF → malha → quadro de coordenadas; pyproj | transformação por vista, CRS, resíduo; `<ARQ>.gpkg` |
| P8 | `ligar_revisoes` | `projeto` | P3 de todas as pranchas do acervo | código | desenho × revisões, a vigente, jogo completo × lista de desenhos |

**Sinais de P5** (regra primeiro, IA só no empate): linear se aparecem `PV`, estaca
(`\d+\+\d+,\d+`), `DN`, `i = … %`, "perfil", "trecho", "rede", "adutora",
"coletor"; localizada se aparecem `V\d+`, `P\d+`, `L\d+`, `fck`, "armação", "forma",
"resumo de aço", "bloco", "sapata". Os padrões moram em `conceitos/prancha.json`,
com exemplos que casam e que não casam, como em `conceitos/mencoes.json`.

**Onde entram os agentes de IA locais** — sempre em **recorte**, nunca na folha A1
inteira (o glm-ocr dava 500 em prancha grande; a skill mediu que OCR na folha
inteira não serve), sempre com esquema e sempre **conferidos por código**:

| agente | onde | conferido por |
|---|---|---|
| Vision (macOS) | texto do recorte quando a prancha tem texto em curva | concordância com o glm-ocr, página a página |
| glm-ocr | idem, segundo leitor | idem |
| gemma3 | carimbo e tabela que o código não fechou; título de vista | nome do arquivo, lista de desenhos, conferência N1/N2 da tabela |
| Apple FM | classificar o projeto e a disciplina pelo texto já extraído | as regras de P5 (o que ele diz contra a regra vai à revisão) |

É a estratégia `dificil` de `rotas.json` (dois leitores, o que diverge vai à
revisão) aplicada por zona, não por documento.

## 4-A. Redundância e a prancha escaneada (depois do teste de mesa)

**Redundância na vetorial vem de três métodos diferentes, não de dois leitores de texto.**
Duas leituras do mesmo rótulo concordam no erro: na AAT-06, as duas leriam "44,00". A
geometria mediu **46,0 m** e a soma dos trechos deu 538 contra 540. Cada valor de tabela
é conferido por:

| método | o que dá | exemplo na AAT-06 |
|---|---|---|
| texto (camada real ou OCR em recorte) | o valor impresso | "44,00 − 630mm" |
| geometria medida na escala da vista | o valor desenhado | divisórias a 130,4 pt → 46,0 m |
| aritmética entre campos | o valor implicado | Δ geratriz / comprimento = declividade; terreno − geratriz = profundidade; estacas × 20 = extensão |

Se os três concordam, o valor está verde. Se o texto diverge dos outros dois, o valor
vai para `divergencias.csv` como **pergunta ao projetista**, e a leitura fica fiel ao impresso.

**Rota da escaneada** (tipo `prancha_raster`: PDF sem texto e sem vetor, uma imagem por
página, ou foto de prancha):

1. **Endireitar**: ângulo pela moldura (linhas longas por OpenCV), girar e cortar a borda do escâner.
2. **Moldura e zonas pela imagem**: retângulos fechados; o carimbo é o conjunto do canto
   inferior direito que contém os rótulos-âncora (MUNICÍPIO, FOLHA, ESCALA, ARQUIVO). Nunca
   recortar por fração fixa: 0,8° de giro já deslocou o recorte uma estaca.
3. **OCR em recorte**, com o texto vertical girado 90° antes. Leem dois leitores de natureza
   diferente, Vision e glm-ocr, com concordância por campo; o gemma3 preenche o esquema do
   carimbo e da tabela a partir do recorte **e** do texto dos dois OCRs.
4. **A mesma aritmética da vetorial**, que não depende de vetor.
5. **Geometria por pixel**: a 200 DPI, 1 px ≈ 0,13 m em 1:1000, o que ainda separa 44 de 46 m.
   A escala vem da malha ou das estacas detectadas, com tolerância maior que a vetorial.
6. **Georreferência pela malha lida no OCR** (rótulos E=/N= e cruzetas detectadas), com o
   mesmo resíduo medido da vetorial.

O que a escaneada não tem: DXF e camada. O que ela tem de pior: anotação à mão (*as
built* em vermelho), que vai para a classe `manuscrito` da E3.

## 5. O que se guarda — contrato dos dados

Cada linha leva `id` (ARQ-n), `pagina` e a origem (tarefa, executor, versão), como
o resto da extração. Unidade em SI (regra 15); DN e bitola não se convertem.

- `geometria.parquet` — `id, pagina, primitiva, tipo, x0, y0, x1, y1, pontos,
  espessura_pt, cor, traco, camada, texto, tamanho_fonte, angulo`.
- `zonas.parquet` — `id, pagina, zona, papel, x0, y0, x1, y1, titulo, escala_h,
  escala_v, fonte_escala`.
- `carimbo.parquet` — uma linha por campo × executor: `campo, valor_texto, valor,
  executor, concorda, conferencia` (ex.: `numero_desenho` × nome do arquivo).
- `revisoes.parquet` — `id, revisao, data, descricao` do quadro de revisões.
- `tabela_prancha.parquet` — `id, pagina, tabela, tipo_tabela, linha, coluna,
  valor_texto, valor, unidade, conferencia`.
- `rede.parquet` / `estrutura.parquet` — um elemento por linha, com a primitiva de
  onde saiu (rastro até a folha).
- `lugar.parquet` + `<ARQ>.gpkg` — transformação por vista (`crs, parametros,
  pontos_usados, residuo_m, ponto_controle_m`) e as feições em SIRGAS 2000.
- `saida/<acervo>/projetos/` — `.dxf` e `.gpkg` por prancha, e `pranchas.csv`
  (uma linha por prancha: carimbo, classe, contagens, conferências) para o Excel.

Cada valor vira **alegação** no modelo do §7 com `estado.plano = projetado`,
`tempo.valido_de` = data da revisão e `espaco` = trecho/estaca (linear) ou
coordenada (quando georreferenciado). Sem malha, o lugar fica `desconhecido_na_fonte`
— **nunca** no centroide do município (princípio 9).

## 6. Conferências — o que torna a extração confiável

| verificação | natureza (§4.1) | como |
|---|---|---|
| escala | aritmética | comprimento medido na geometria × cota escrita ao lado (texto de cota), em 5+ cotas por vista; mediana do erro < 1 % |
| número do desenho | sintática | carimbo = nome do arquivo (parser validado contra todos os nomes do acervo, como na skill) |
| revisão | sintática | carimbo = sufixo `R\d` do nome = última linha do quadro de revisões |
| tabela de aço | aritmética | `peso ≈ comprimento × massa linear` (NBR 7480) e soma por bitola = resumo |
| tabela de materiais | aritmética | soma dos elementos = linha TOTAL |
| trecho | aritmética | extensão impressa × diferença de estacas × comprimento da polilinha na escala; declividade impressa × Δcota / extensão |
| georreferência | aritmética | resíduo no ponto de controle fora do ajuste; o PV com coordenada no quadro cai no símbolo do PV |
| jogo completo | sintática | lista de desenhos × pranchas presentes (faltante e revisão desatualizada) |

Conferência que reprova com a leitura confirmada por dois leitores é **achado do
projeto** (a skill achou TOTAL impresso errado em 200 m²), vai para
`divergencias.csv` — é auditoria de projeto, valor para o cliente.

## 7. Métricas — definidas antes de rodar

**Gabarito**: as 10 pranchas da E3 (`prancha_pdf`) + amostra estratificada de 20
(10 de rede do SAIC, 10 de estrutura da ETA), sorteio pelo sha1 do id, gravado.
O Caio **corrige, não digita**: planilha com as respostas lado a lado e o recorte
em `vistas/`, marca `c`/`p`/`e`, como na E3.

| medida | meta (PR08) |
|---|---|
| carimbo, campos críticos (número, título, revisão, data, escala) | ≥ 95 % certo (identificação) |
| quantidade de tabela (aço por bitola, concreto, forma, extensão por DN) | ≥ 99 % certo (move dinheiro) |
| trecho: extensão, DN, profundidade média | ≥ 99 % |
| classe de P0 e de P5 | ≥ 95 % |
| georreferência | resíduo no controle ≤ 1 m em planta de 1:1000 — **premissa**, muda pela medida |
| tempo | p90 por prancha, por tarefa, no mini (premissa: < 60 s sem IA) |

Veredito por tarefa: passa com a meta em ≥ 8 pranchas corrigidas; menos, inconclusivo.

## 8. Decisões que são do Caio

| # | decisão | recomendação |
|---|---|---|
| D1 | DXF é fonte ou vista? | **vista**: fonte é o `geometria.parquet`; o DXF sai dele e é regenerável |
| D2 | PyMuPDF (AGPL, §5.1) no catálogo? | **não na rota**: pdfplumber/pdfminer (MIT), pypdfium2 (Apache/BSD), ezdxf (MIT), pyproj (MIT), shapely (BSD). PyMuPDF só como candidato de bancada se o pdfminer for lento demais em prancha com 100 mil+ primitivas — medir antes |
| D3 | CRS padrão quando a prancha não diz | **nenhum** (aceito): o fuso sai da malha **e** do município do carimbo, que têm de concordar; o datum fica "não declarado" até vir de outra folha. Teste de 26/09: a AAT-06 (Foz do Iguaçu) é fuso **21S**; o 22S sugerido antes erraria em ~600 km |
| D4 | acervo primeiro | **SAIC (linear)**: é onde o georreferenciamento e o perfil pagam mais; a ETA já tem o método da skill |
| D5 | prancha raster | **rota própria por imagem** (§4-A, pedido do Caio em 26/09): carimbo, tabelas, conferência aritmética e geometria por pixel; sem gerar DXF |

## 9. Itens

| # | item | verificação | estado |
|---|---|---|---|
| 1 | Fase 0 da skill no acervo (teste de mesa com 1 prancha feito em 26/09): perfil de 30 pranchas (classe, OCG, primitivas, texto, formato, GeoPDF) sem mudar a rota | `saida/_sistema/projeto/perfil_amostra.csv`; quantas de cada classe decide a ordem dos itens 3–8 | pendente |
| 2 | `conceitos/prancha.json` (sinais de classe, rótulos do carimbo, tipos de tabela, padrões V/P/L, estaca, PV, malha) com exemplos que casam e que não casam | teste de conceito em `testes.py` | pendente |
| 3 | P0 + P1: `vetorizar` → `geometria.parquet` + DXF | prancha sintética em `testes.py` (linhas, texto, OCG) volta igual; DXF abre no ezdxf com as camadas | pendente |
| 4 | P2 `zonear` + P3 `ler_carimbo` (código + Vision + glm-ocr + gemma3) | gabarito do carimbo, conferência com o nome e o quadro de revisões | pendente |
| 5 | P4 `ler_tabelas_prancha` (método da skill, sem PyMuPDF) | N1/N2 fecham; gabarito das quantidades | pendente |
| 6 | P5 `classificar_projeto` | gabarito da classe | pendente |
| 7 | P6a `ler_rede` (planta + perfil) — SAIC | trechos × gabarito; extensão, declividade e estacas conferem | pendente |
| 8 | P6b `ler_estrutura` — ETA | elementos × resumo de materiais | pendente |
| 9 | P7 `georreferenciar` → GPKG | resíduo no controle; sobreposição com os `.shp` do acervo e com o GPS das fotos (EXIF) | pendente |
| 10 | P8 `ligar_revisoes` + `pranchas.csv` | jogo completo × lista de desenhos; nenhuma quantidade somada em duas revisões (teste de conservação, §7.6) | pendente |
| 11 | rotas: as tarefas `ler_prancha` e `ler_prancha_ia` em todo PDF (`rotas.json`), `codigo/prancha.py`, `conceitos/prancha.json` | `testes.py` (`testar_prancha`); no mini, `saida/_sistema/pranchas.csv` auditado contra as folhas de Foz | **feito 1v47** — auditoria no mini pendente |
| 15 | P8 compara folhas do jogo (estacas encadeadas, folha × desenho, revisão aplicada ou não) e P6a compara deflexão desenhada × conexão da relação; detalhe liga à planta pela cota (`teste_jogo_foz_2026-09-26.md`) | jogo da AAT-06: acusa 012 (44 × 46 m; descarga 2 × 3) e 011/012 (curvas "retiradas" ainda no desenho), e não acusa 010 e 013 | pendente |
| 12 | os recortes do teste de mesa (carimbo, materiais, quadro do perfil; vetorial e escaneada) lidos pelo Vision, glm-ocr, gemma3 e Apple FM no mini | mesma planilha da E3; gabarito = `teste_prancha_2026-09-26.md` | pendente |
| 13 | rota `prancha_raster` (§4-A): endireitar, moldura, zonas por âncora, OCR em recorte girado | controle simulado da AAT-06 + 5 escaneadas reais do acervo | pendente |
| 14 | P1 diz a que OCG pertence cada objeto (`/OC` no fluxo de conteúdo) e separa imagem embutida | AAT-06: tubulação só em `ADUTORA`, relação de materiais como imagem | pendente |

Os itens 1 e 2 vêm antes de qualquer executor: sem saber quantas pranchas são
vetoriais com texto, texto em curva ou raster, a ordem dos outros é palpite.

## 11. Famílias de projeto, todos os modelos e nenhuma invenção (tese, 26/09/2026)

Pedido do Caio: o escopo é o *core business*; o Ollama e o Apple FM têm de entrar e funcionar ao
lado do código; nenhum modelo pode inventar (o gemma3 inventou NSPT de 3 em 3 na E3); a prancha
grande é fatiada e remontada; o orquestrador reconhece o tipo de projeto e chama o código e os
agentes certos; o entorno (rua, calçada, lote) entra porque compõe interferência.

### 11.1 Nenhuma invenção: um valor só é aceito com quatro provas

"Certeza total" não vem do modelo, vem da regra de aceite. Nenhum valor de IA entra como fato sem:

| prova | o que é | pega o NSPT inventado? |
|---|---|---|
| **presença** | o valor (normalizado) aparece como token no OCR do **mesmo recorte**, com a caixa onde está | sim: 12, 15, 18… não estavam no OCR |
| **concordância** | dois leitores de natureza diferente (Vision × glm-ocr; OCR × geometria) dão o mesmo valor | sim |
| **conferência** | a regra de código fecha: soma, sequência de estacas, espaçamento da malha, cota × perfil, ângulo × peça | sim: progressão aritmética perfeita é sinal suspeito |
| **rastro** | recorte, caixa, modelo, prompt e resposta congelados (§8.2 do MASTER-PLAN) | permite auditar |

Falhou uma prova: o valor fica **pendente, com motivo**, e nunca é preenchido (princípio 9).
Mais três regras:
- **Pergunta fechada, não interpretação.** O modelo responde "qual o texto neste retângulo" ou
  "qual destas classes", e não "extraia o NSPT". Interpretação é código.
- **Ausente é resposta certa.** O esquema tem `ilegivel` e `ausente`, e o prompt diz isso.
- **Controle negativo.** Cada bancada mistura recortes **sem** o dado pedido (em branco, só hachura,
  outra tabela). Modelo que responde valor num controle negativo é **barrado daquela tarefa**. Meta:
  **zero invenção aceita** no gabarito, e é medida, não suposta.

### 11.2 Fatiar e remontar: pelo desenho primeiro, às cegas só se precisar

- **Não é quebra-cabeça.** Cada fatia guarda o deslocamento (x, y) na folha; o que o modelo lê volta
  para a coordenada da folha por soma. Nas sobreposições, o mesmo texto lido duas vezes é deduplicado
  pela posição. Duas leituras da mesma área são também a concordância da §11.1.
- **Quatro ou oito partes não bastam.** O limite medido dos modelos locais é ~1.600 px de lado
  (`conceitos/extratores.json`). Texto de 2 mm precisa de ~150–200 DPI. A0 a 200 DPI = 9.362 × 6.622 px
  → **~35 fatias** de 1.600 px com 15 % de sobreposição; A1 → ~20.
- **Fatia pelo sentido, antes da grade.** Na vetorial, a fatia é a zona (carimbo, cada tabela, cada
  vista) e a camada isolada (só os nomes de rua, só os rótulos das estacas): recorte limpo e pequeno.
  A grade às cegas fica para a escaneada e para o que sobrar.
- **Texto girado é endireitado pelo código** (o ângulo vem da geometria) antes de ir ao modelo.

### 11.3 Todos os modelos, cada um no que medir melhor

Hipótese de papéis, a confirmar pela bancada (tarefa × modelo, com gabarito e controle negativo):

| modelo | papel provável | por quê |
|---|---|---|
| Vision (macOS) | leitor de texto no recorte | OCR clássico, rápido, não inventa frase |
| glm-ocr (Ollama) | segundo leitor, e tabela em imagem | OCR por modelo, diferente do Vision |
| gemma3 (Ollama) | olhar o recorte e responder pergunta fechada (tipo de zona, qual peça é este símbolo) | visão + linguagem; **nunca** fonte única de número |
| qwen3 (Ollama) | organizar os tokens do OCR no esquema (texto → campos) | só texto; o número tem de estar nos tokens |
| Apple FM | triagem e classificação curta sobre texto já extraído | pequeno e rápido; sai do caminho do número |

Nenhum sai do catálogo por perder (MASTER-PLAN §4.4); quem vence cada tarefa vai para a rota daquela família.

### 11.4 Famílias: o orquestrador reconhece o projeto e chama o módulo certo

Dois níveis de reconhecimento, sempre do mais barato ao mais caro:
1. **Obra** (contexto): pasta, documentos vizinhos, edital; código Sanepar no nome (`SAA` água, `SES`
   esgoto; `PBHI` hidráulica, `PBES` estrutura, `PARQ` arquitetura; `AAT`, `RDA`, `ETA`, `ETE`, `EEE`).
2. **Folha**: nome → camadas do CAD → texto do carimbo → Apple FM só no empate.

Árvore de famílias (cada folha pode ter uma disciplina diferente dentro da obra):

| grupo | família | desenho típico | o que se extrai |
|---|---|---|---|
| **linear** | adutora | planta e perfil, detalhe de ventosa e descarga | eixo, estacas, perfil, peças, deflexões |
| | rede de água (distribuição) | planta de rede, nós, trechos | trechos, DN, nós, registros, ligações |
| | coletor, interceptor, emissário de esgoto | planta e perfil com PV | PV, trechos, profundidade por faixa, degrau |
| | linha de recalque | planta e perfil | como adutora, com pressão |
| | gás | planta e perfil | trechos, válvulas, faixa |
| | drenagem, viária | planta, perfil, seções | bocas de lobo, galerias, pavimento |
| **localizada** | ETA, ETE, elevatória, reservatório | forma, armação, locação, hidráulica | elementos de concreto (viga, pilar, laje, bloco), aço e concreto (skill `extrair-quantitativos-pdf`), tubulação e peças |
| | edificação | arquitetura, estrutura, instalações | ambientes, elementos, quadros |

Cada família é um **pacote**: `conceitos/familias/<familia>.json` (sinais, mapa camada → tema por
projetista, esquemas, regras de conferência), o módulo Python, os prompts dos agentes locais, o
gabarito com controles negativos e o **estado** (`em_bancada`, `na_rota`). Família nova ou
projetista novo entra por PR, com o roteiro da skill da nuvem; depois roda só local.

### 11.5 Entorno: tudo o que a planta tem pode ser interferência

Quadra, lote, alinhamento predial, meio-fio e calçada, via e nome, edificação, hidrografia,
pontos de apoio, rede existente desenhada — cada um vira camada `entorno` com origem, e o código
deriva o que importa para orçar e executar:
- **travessias**: eixo × via, eixo × curso d'água (com estaca);
- **faixa de trabalho**: distância do eixo ao alinhamento dos lotes, trecho a trecho;
- **extensão por tipo de via** (rua, avenida, fora de via) — base para recomposição de pavimento;
- **rede existente** só quando a geometria confirma (na AAT-06 a camada "PVC DN300" era a própria adutora).

A extração registra "interferência desenhada: nenhuma" como fato da prancha. O cadastro de
interferências (gás, telefonia, drenagem, esgoto) vem de outra fonte e entra na mesma camada, com origem.

### 11.6 Ordem

1. Família **adutora** inteira (protótipo de Foz → módulo), com a bancada de 5 tarefas de IA e os
   controles negativos, no mini.
2. **Coletor de esgoto** (planta e perfil como a adutora, mais PV e faixa de profundidade).
3. **Estrutura de ETA/ETE** (a skill `extrair-quantitativos-pdf` já tem o método).
Uma família só passa para a rota quando a bancada dela passa, com zero invenção aceita.

## 10. O que este plano não faz

- Não vetoriza prancha raster nem reconstrói DWG com blocos e cotas associativas: o
  DXF de saída tem linha e texto, não objeto de CAD.
- Não mede quantidade no desenho que nenhuma tabela traz (área de laje por contorno,
  volume de escavação por seção) antes de as tarefas 3–9 passarem: é o passo seguinte.
- Não liga item de orçamento a elemento de projeto (§7.7, V2): só deixa o elemento
  pronto, com lugar, revisão e rastro, para essa ligação.
