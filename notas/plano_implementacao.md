# Plano de implementação — ialocal.projeto (02/10/2026)

**Pedido do Caio (02/10/2026).** Separar do `ialocal.extrator` tudo o que é **prancha de projeto**: folha maior que
A4, com carimbo, legenda e desenho — de engenharia ou editorial. Aqui ela vira **dado e vetor**: o desenho em DXF (ou
outro vetorial), as tabelas, o carimbo (projetista, responsável, data, revisão, escala, folha), as notas e as
observações, e o contexto de engenharia (família da obra, grupo linear ou localizado, eixo). As IAs locais entram
(modelos do Ollama e o Foundation Model da Apple), sempre conferidas por código. O extrator fica com as tarefas
simples (texto, planilha, e-mail, OCR de documento) e deixa de extrair projeto; o maestro passa a coordenar mais
este repositório.

Base: `notas/plano_projeto.md` (a tese de 26/09, trazida do extrator), os testes de mesa de Foz
(`notas/teste_*.md`, `notas/viabilidade_prancha_2026-09-26.md`) e o `codigo/prancha.py` do extrator até a 2v75
(commit `35fc7e9` do `ialocal.extrator`), que é a origem do código de reconhecimento, carimbo, família, eixo e
leitura por fatias trazido para cá.

## Fronteira

| fica no extrator | vem para o projeto |
|---|---|
| inventário, zip, conversão de texto, menções, planilha, e-mail, OCR de documento | tudo o que a prancha diz além do texto corrido |
| **triagem barata por código** (`ler_prancha`): é prancha? (A3 ou maior + sinais), formato, classe, camadas | vetor (geometria + DXF), zonas, carimbo, revisões, notas, tabelas, família, eixo |
| a **entrega**: copia o PDF que é prancha para a pasta de entrega e anota no manifesto | a leitura com IA local (Vision × glm-ocr, qwen3 × Apple FM), na vez da GPU do maestro |

**Contrato extrator → projeto** (cada um escreve na própria pasta, MASTER-PLAN §6.5): o extrator grava em
`~/dados/extracao/para_projeto/` o PDF (`<sha256>.pdf`) e uma linha em `entregas.jsonl` (`id`, `caminho`, `nome`,
`sha256`, `formato`, `classe`, `sinais`, `em`). O projeto só lê essa pasta. Nenhum import entre os repositórios.

## Itens

Estado: `pendente` → `feito` → `verificado`. Cada item fecha com a verificação escrita ao lado, executada.

| # | item | verificação | estado |
|---|---|---|---|
| 1 | Conceitos: `conceitos/prancha.json` (reconhecer, família, carimbo por rótulo-âncora, notas, tabelas, eixo, fatias, padrões, conferência), `conceitos/extratores.json` (modelos e parâmetros), prompts versionados | teste de conceito em `testes.py`: todo padrão compila, toda família tem grupo, todo campo do carimbo tem âncora ou padrão, todo prompt citado existe | verificado |
| 2 | `codigo/ia.py`: a porta para os motores locais — Ollama (qwen3, glm-ocr), Apple FM, Vision — com congelamento de cada resposta (§8.2) e a vez da GPU pelo `cliente_gpu.py` copiado do maestro | testes com motores falsos: a mesma chave não chama o modelo de novo; sem motor instalado, o motivo fica escrito e a leitura segue | verificado |
| 3 | `codigo/folha.py`: perfil da folha (formato, classe, camadas, sinais, GeoPDF) e o vetor — toda primitiva (traço, preenchimento, texto) com camada, cor, espessura, em `geometria.parquet` — e o DXF por camada (ezdxf) | prancha sintética A1: formato A1, camada ADUTORA, o DXF abre no ezdxf com a camada e o texto, o comprimento dos traços confere | verificado |
| 4 | `codigo/leitura.py`: o que a folha diz por código — zonas (retângulos fechados), carimbo por rótulo-âncora, quadro de revisões, notas e observações, tabelas vetoriais (pdfplumber na zona), família e grupo por regra | prancha sintética: projetista, responsável, CREA, data, escala, folha e título certos; 2 revisões; 3 notas; a tabela de materiais com 3 linhas; família adutora, grupo linear | verificado |
| 5 | IA local no que o código não fecha: o texto em curva e a raster pelo OCR em recorte (Vision × glm-ocr), o carimbo organizado no esquema pelo qwen3 e pelo Apple FM com as provas de **presença** (o valor está nos tokens do recorte) e **concordância** (dois leitores de natureza diferente), o desempate da família, a tabela colada como imagem | motores falsos: valor da IA que não está no texto é `inventado` e nunca entra; dois motores que concordam dão `confirmado`; um só, `um_leitor` | verificado |
| 6 | `codigo/linear.py`: eixo desenhado (faixa colorida ou camadas de tubo), deflexões e a conferência eixo × escala × tubo da relação (trazidos do extrator) | eixo de 300 mm com a dobra de 45°; fecha, diverge e espera o tubo confirmado | verificado |
| 7 | `codigo/projeto.py`: `ler <pdf>`, `pasta <dir>`, `rodada` (lê as entregas do extrator), `status`; uma pasta por prancha em `dados/pranchas/`, o DXF e os CSV em `saidas/`, o `status.json` no formato comum do maestro, publicação no Drive (`gdrive:saida/projeto/`) | rodada com entrega sintética: lê uma vez (sha256), não relê na segunda, relê quando a versão muda; `saidas/pranchas.csv`, `tabelas.csv`, `notas.csv`, `status.json` | verificado |
| 8 | `codigo/mini.py`: `atualizar` (main por fast-forward) e `instalar` (launchd: rodada a cada 10 min, atualizar a cada 5) | as agendas montam o plist com o python do .venv; testado em `testes.py` sem chamar o launchctl | verificado |
| 9 | `codigo/testes.py`: a prancha sintética de ponta a ponta e a aferição (regra 17: órfã, duplicata, comprimento, profundidade) | `python codigo/testes.py` sem falha; linha nova em `codigo/afericao.jsonl` | verificado |
| 10 | Extrator deixa de extrair projeto (2v94): `ler_prancha` vira triagem + entrega; sai a `ler_prancha_ia`, a cota diária, a tabela `nao_prancha` e a reconferência; prompts e notas de prancha saem (ponteiro para cá) | `testes.py` do extrator sem falha; prancha sintética chega a `para_projeto/` com a linha no manifesto; PDF A4 não chega | verificado |
| 11 | Maestro (0v44): `ialocal.projeto` no cadastro (pasta, status, GPU, prioridade 5, depende do extrator, launchd, ambiente), papel do extrator atualizado, MASTER-PLAN §2 e §6.5, LEIA | `testes.py` do maestro sem falha; o levantamento mostra o projeto `sem_dados` (pasta ausente na máquina de teste) | verificado |
| 12 | `LEIA.md` do projeto: o que é, como rodo, onde está o quê, o que não é óbvio | lido contra a árvore real | verificado |
| 13 | Bancada de tabelas com o gabarito de Cambé (`notas/amostras_tabelas_2026-10-03.md`): o TXT do Caio em CSV, como impresso (com a correção 31041 → 310410 da tabela 03, confirmada por ele em 03/10), e as 17 imagens lidas no mini pelo `ocr.ler_tabela` | acerto por campo (código, quantidade, unidade, descrição normalizada) nas 190 linhas; meta do plano §7: quantidade ≥ 99 % | pendente |
| 14 | Leitor de tabela: mapa de colunas por sinônimo, linha de seção como título, quantidade dupla (pç e kg) em duas linhas, marcador `*` com a nota, unidade em SI | teste com as quatro formas de Foz e a de Cambé, sintéticas | verificado (0v2: `testar_itens`, `testar_tabela_com_secao`, `testar_itens_colados`; as 190 linhas do gabarito de Cambé voltam iguais) |
| 15 | Gabarito de Foz: uma imagem de cada layout transcrita pelo Caio | quatro arquivos no formato do de Cambé | pendente |
| 16 | Os PDFs de origem das tabelas de Foz e Cambé, para a rota vetorial | o mesmo gabarito lido pelo vetor | pendente |

## Fica para depois (do `plano_projeto.md` §9, na ordem dele)

- Prancha raster: endireitar, moldura e zonas pela imagem (§4-A).
- Georreferência pela malha (`notas/prototipo_prancha/georef.py`) → GPKG, com resíduo medido; KML como vista.
- Rede (planta + perfil: trechos, PV, estacas) e estrutura (forma + armação: elementos, aço) por família.
- Ligar revisões do mesmo desenho e o jogo completo × lista de desenhos.
- Bancada E3 da prancha (gabarito do Caio, controle negativo): as classes `prancha_pdf` e `prancha_imagem` seguem
  na bancada do extrator até a do projeto existir; mudá-las é um item próprio, com a bancada inteira.
- Fotos de obra: repositório próprio (`ialocal.fotos`), decisão de 30/09, ainda não criado.

## Emendas

- **03/10/2026, itens 13–16.** Novos, pelas amostras de tabelas que o Caio pôs em `amostras/tabelas/` (análise em
  `notas/amostras_tabelas_2026-10-03.md`).
- **02/10/2026, itens 7, 10 e 11.** O clone do extrator desta sessão estava na 2v75; a `main` tinha andado até a 2v93.
  A mudança do extrator foi refeita sobre a 2v93 e virou a **2v94** (a 2v76 de verdade é outra). Dela vieram duas
  coisas: a 2v81 adiava a `ler_prancha_ia` para o fim de semana (o adiamento fica só com foto e desenho), e a 2v93 pôs
  cada etapa numa pasta dentro da obra — a publicação do projeto passou a `saida/<acervo>/<obra>/projeto/`, com a obra
  vinda do mapa do extrator na entrega. O maestro já estava na 0v43: o item 11 é a 0v44.
- **02/10/2026, item 10.** A suíte do extrator já falhava na `main` (2v93) em dois pontos, sem relação com a prancha: a
  2v93 sem `muda` (corrigido na 2v94 com `"muda": []`, que não muda o refazer) e o `testar_ordem_por_tipo` (a foto
  adiada não chega na fila compartilhada do teste; falha igual na `main`, não mexido aqui). O resto da suíte passa.
