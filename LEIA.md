# ialocal.projeto

## O que é

A extração de **todos os projetos** (pranchas de engenharia em PDF) do acervo: para cada folha, se é prancha, o
formato, o carimbo, a família da obra (adutora, rede, coletor, ETA, elevatória…), o eixo desenhado e, pela IA local,
o texto de cada fatia e das tabelas coladas, com número só confirmado quando dois leitores de natureza diferente
leem o mesmo; o carimbo inteiro (quem fez, quando, responsável, revisões); e o **boletim de sondagem** (furo, coordenadas,
nível d'água, N-SPT de cada metro, perfil do solo). Saiu do `ialocal.extrator` em 03/10/2026 (0v1): o extrator lê documentos; o projeto, os desenhos. O
`ialocal.maestro` o acompanha como a etapa que extrai os projetos. Plano e tese: `notas/plano_projeto.md`.

## Como rodo

No Mac mini, em `~/dados/ialocal.projeto` (destino permitido, MASTER-PLAN §5.3, que mora no `ialocal.maestro`).

```bash
cd ~/dados
git clone git@github-projeto:CAIOZANETTI/ialocal.projeto.git   # só na primeira vez; a chave, abaixo
cd ialocal.projeto
python3 -m venv .venv && .venv/bin/pip install polars pdfplumber pypdfium2 pillow apple-fm-sdk pyobjc-framework-Vision
.venv/bin/python codigo/testes.py           # qualquer máquina: entrega falsa, Drive falso, IA falsa
.venv/bin/python codigo/ciclo.py rodada     # uma rodada à mão (a agendada faz o mesmo)
.venv/bin/python codigo/ciclo.py status     # só regrava saidas/status.json
.venv/bin/python codigo/mini.py instalar    # agenda a rodada e o atualizar a cada 5 min (com o python do .venv)
.venv/bin/python codigo/agentes.py sondar   # os agentes da NVIDIA (exceção §5.6) leem a tabela 01 de Cambé: formato, tempo, placar
.venv/bin/python codigo/bancada.py tudo     # F2: todos os leitores (o código, glm-ocr, gemma3, Vision, qwen3, Apple FM, Kimi e, desde a 0v24, os reservas GLM-5.3 Flash, Muse Glimmer e DeepSeek V4.1 Flash; o Parse descontinuado em 04/10) contra o gabarito; placar e veredito
.venv/bin/python codigo/bancada.py rapido   # a bancada inteira em ~5 min: o código nas 17 tabelas, os modelos na amostra e no controle; sem a sondagem
.venv/bin/python codigo/bancada.py tudo --refazer   # o mesmo, chamando de novo o congelado: o tempo útil medido nas mesmas condições
```

**O clone pede uma chave de acesso própria** (como os outros `ialocal.*`):

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/projeto_deploy -C "mini ialocal.projeto"
cat ~/.ssh/projeto_deploy.pub     # GitHub → ialocal.projeto → Settings → Deploy keys → Add (sem escrita: o mini só puxa)
cat >> ~/.ssh/config <<'FIM'

Host github-projeto
  HostName github.com
  User git
  IdentityFile ~/.ssh/projeto_deploy
  IdentitiesOnly yes
FIM
```

O Ollama com o `glm-ocr` e o `qwen3:8b` é o mesmo do extrator; o rclone usa o remoto `gdrive:` que o extrator já
configurou no mini.

## Onde está o quê

```
codigo/prancha.py       ler_prancha (código: camada, carimbo, família, eixo; reconhece o boletim) e ler_prancha_ia (fatias, tabelas e o carimbo desenhado pelo glm-ocr × Vision)
codigo/sondagem.py      o boletim de sondagem: ler_sondagem (páginas com texto, código) e ler_sondagem_ia (digitalizadas, glm-ocr × Vision)
codigo/ciclo.py         a rodada: o que está pendente, código antes, IA na vez da GPU; publica; status.json
codigo/entrega.py       lê o que o extrator entregou (só lê): PDFs A3 ou maiores e o mapa das obras; e os anexos das respostas
codigo/respostas.py     as respostas da equipe às demandas (guardadas pelo ialocal.web): PDFs para a rodada, CSV gabarito, o resultado
codigo/ia.py            a porta para os modelos locais (Ollama, Vision, Apple FM) e, na exceção §5.6, a API da NVIDIA (nvidia), com congelamento das respostas
codigo/bancada.py       a bancada de todos os leitores: código primeiro, depois agentes e modelos; qualidade, tempo útil, taxa de erro e tempo perdido; placar e veredito (saidas/bancada_agentes.csv)
codigo/grade.py         o leitor só de código: a tabela pelas caixas das palavras do Vision (linhas pela altura, colunas pelo cabeçalho), sem modelo
codigo/curadoria.py     Python decide o que vale entre N leitores: confirmada (com testemunha), confirmada_ia, divergente, so_<leitor>
codigo/agentes.py       os agentes externos (Kimi K3, Nemotron Parse 2.0): leitura por agente, em paralelo, registro, sonda contra o gabarito de Cambé
codigo/comum.py         pastas, conceitos, Parquet com troca por chave, CSV para o Drive
codigo/cliente_gpu.py   cópia do cliente da trava de GPU do ialocal.maestro (não editar aqui)
codigo/mini.py          atualizar (só fast-forward da main) e instalar (launchd)
codigo/testes.py        prancha A1 sintética, entrega e Drive falsos, regras com os casos reais de 26/09
codigo/versoes.jsonl    0v1…: data, resumo e as tarefas que cada versão muda (muda: refeitas sozinhas)

conceitos/prancha.json  o que reconhece a prancha, famílias, carimbo (campos por rótulo-âncora, revisões), eixo, fatias, padrões, conferência
conceitos/sondagem.json o boletim: como reconhecer, por onde ler cada página, os padrões do cabeçalho, do N-SPT e das camadas
conceitos/ia.json       modelos e parâmetros das chamadas (cópia do extratores.json do extrator, 2v93)
conceitos/agentes.json  os agentes externos: ligado, prazo da exceção, obras, modelos, o limite por provedor, tentativas, reservas
conceitos/bancada.json  os candidatos do mini na bancada (o código, glm-ocr, gemma3, Vision, qwen3, Apple FM), as regras da grade, o --rapido e os critérios do veredito
conceitos/demandas.json o que o projeto pede ao Caio e à equipe (id, gabarito, texto do e-mail, aberta)
conceitos/operacao.json de onde lê a entrega e as respostas, para onde publica, limites, a prioridade na GPU
conceitos/prompts/      prompts versionados (o hash entra na chave de congelamento)

amostras/tabelas/       recortes de tabelas de prancha (Foz, Cambé) com a transcrição do Caio: o gabarito das tabelas
notas/                  plano_projeto.md (tese e itens), testes de mesa de 26/09, protótipo da prancha (camadas, georreferência),
                        plano_agentes_nvidia.md (dois agentes externos gratuitos em paralelo; exceção do MASTER-PLAN §5.6),
                        plano_inventario_roteamento.md (inventário por página → roteador → extração especializada; plano)

dados/    prancha, prancha_leitura, prancha_tabela, carimbo, sondagem, sondagem_campo, sondagem_spt, sondagem_camada (.parquet), recortes/, congelamento.jsonl,
          execucoes.jsonl, falhas.jsonl, agentes.jsonl (cada chamada externa), agentes_sonda.jsonl, bancada_*.parquet, bancada/ (recortes da bancada), gpu/ (pedidos ao maestro), launchd.log — regenerável, fora do git
saidas/   status.json (formato comum, o maestro lê) e os CSVs publicados — fora do git

Drive  saida/<acervo>/<obra>/projeto/   pranchas.csv, prancha_leituras.csv, prancha_tabelas.csv, carimbos.csv, sondagens.csv,
                                        sondagem_spt.csv e sondagem_camadas.csv da obra
       saida/_sistema/projeto/          os mesmos, de todas as obras
```

## O que não é óbvio

- **O extrator entrega; o projeto só lê.** Cada repositório escreve na própria pasta. A tarefa `entregar_projeto` do
  extrator (2v94) olha a primeira página de todo PDF — de zip, de e-mail, de PDF dentro de PDF — e, se é A3 ou maior,
  deixa o arquivo em `~/dados/extracao/projetos/` e uma linha em `~/dados/extracao/projeto_entrega/`. O projeto lê
  essa entrega e o mapa das obras (`~/dados/extracao/por_obra/.obras`). Obra que sai do mapa sai da saída.
- **Cada folha tem a sua camada** (0v2, pedido do Caio): `texto` — o PDF vetorial com texto real, lido pelo código
  (pypdfium2, pdfplumber), sem IA; `vetor` — o desenho é vetor mas o texto virou curva (AutoCAD): a geometria pelo código,
  o texto pelo OCR; `imagem` — digitalizada: tudo pelo OCR. O carimbo tem a camada dele (`carimbo_camada`): na AAT-06 só
  o carimbo tinha texto real.
- **O carimbo diz o que é, quem fez e quando.** No canto inferior direito, cada campo pelo rótulo-âncora
  (`prancha.json → carimbo.ancoras`): número do desenho, título, projetista, responsável técnico, CREA, ART, fase,
  contratante, obra, local, data, escala, folha, e o quadro de revisões com a vigente. Com texto real, o código lê
  (status `codigo`); desenhado, o recorte vai ao glm-ocr e ao Vision e o campo só é `confirmado` se os dois leram igual.
  Projetista com rótulo diferente: acrescentar o rótulo no JSON, o código não muda.
- **O boletim de sondagem é projeto, mesmo em A4.** Reconhecido pelos sinais do texto (SPT, golpes, N.A., impenetrável,
  compacidade) ou, digitalizado, pelo nome; nunca vai à leitura de prancha. Página com texto, pelo código; digitalizada,
  pelo OCR com os dois leitores. N-SPT = golpes dos dois últimos trechos de 15 cm. Os padrões são de boletim típico e
  são tese: boletim de outro laboratório que não casa entra em `conceitos/sondagem.json`.
- **Código antes de IA, e a IA na vez da GPU.** A rodada faz o `ler_prancha` em tudo o que falta (rápido) e só
  depois chama a IA, uma prancha por vez, pedindo a vez ao maestro com prioridade 7 — atrás da extração de
  documentos (5), à frente da conferência do revisor (8). É a decisão do Caio de 26/09 ("documentos primeiro,
  projetos depois"), que no extrator era uma cota diária e aqui é a trava. Sem o maestro, a trava falha aberta.
- **Número só é fato com dois leitores.** glm-ocr e Vision leem a mesma fatia; o valor que só um leu fica `so_glm`
  ou `so_vision`, nunca `confirmado` (o glm-ocr "continuou" as estacas até a 323 no teste de 26/09).
- **Refazer é sozinho.** A linha lida com código anterior à última versão que declara a tarefa em `muda`, ou com
  outro conteúdo do PDF (a versão da entrega), é lida de novo na rodada seguinte. Falha volta até 3 vezes por
  versão do código; depois fica em `dados/falhas.jsonl` e a saúde do status vira atenção.
- **A prancha tem limite.** A leitura de IA para entre fatias em 20 min (`operacao.json → limite_ia_s`): o que foi
  lido fica, e o motivo sai no `pranchas.csv`.
- **A equipe responde direto ao mini** (0v4). Cada demanda de `conceitos/demandas.json` vai por e-mail ao Caio (status →
  maestro → ialocal.web) com `[demanda <id>]` no assunto; ele encaminha, e quem tem o material responde ao endereço
  do mini com os PDFs e o CSV. O web guarda em `~/dados/ialocal.web/saidas/demandas/<demanda>/`; o projeto só lê: os
  PDFs entram na rodada como obra `_demandas/<demanda>`, o CSV é o gabarito. Respondida, a demanda sai da lista;
  lidos os PDFs, o status leva o `resultado` (acerto por campo, divergências) e o Caio recebe por e-mail. Cada
  resposta nova gera um resultado novo. Para ajustar os padrões: comparar as divergências e mexer no JSON por PR.
- **Agentes externos só neste repositório, com prazo** (0v5; MASTER-PLAN §5.6, até 03/11/2026). Dois modelos gratuitos
  do catálogo da NVIDIA leem os mesmos recortes que o glm-ocr e o Vision, em paralelo e fora da vez da GPU. São
  leitores candidatos: o número que só eles leram nunca vira `confirmado`. A chave fica fora do git, em
  `~/.config/ialocal/nvidia_api_key` (`chmod 600`; criar em build.nvidia.com com a conta do Developer Program). Desligar:
  `agentes.json → ligado: false` por PR. Por ora só a sonda e a bancada (`bancada.py`, 0v8) chamam; a rodada não (`notas/plano_agentes_nvidia.md`).
- **A bancada E3 (qualidade) continua no extrator** por ora: a classe `prancha_pdf` mede os modelos numa amostra, à
  parte da produção. Trazê-la para cá é o passo seguinte, junto com os itens pendentes do `plano_projeto.md` §9.
