# ialocal.projeto

## O que é

A extração de **todos os projetos** (pranchas de engenharia em PDF) do acervo: para cada folha, se é prancha, o
formato, o carimbo, a família da obra (adutora, rede, coletor, ETA, elevatória…), o eixo desenhado e, pela IA local,
o texto de cada fatia e das tabelas coladas, com número só confirmado quando dois leitores de natureza diferente
leem o mesmo. Saiu do `ialocal.extrator` em 03/10/2026 (0v1): o extrator lê documentos; o projeto, os desenhos. O
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
codigo/prancha.py       as duas leituras: ler_prancha (código) e ler_prancha_ia (fatias e tabelas pelo glm-ocr × Vision)
codigo/ciclo.py         a rodada: o que está pendente, código antes, IA na vez da GPU; publica; status.json
codigo/entrega.py       lê o que o extrator entregou (só lê): PDFs A3 ou maiores e o mapa das obras
codigo/ia.py            a porta para os modelos locais (Ollama, Vision, Apple FM), com congelamento das respostas
codigo/comum.py         pastas, conceitos, Parquet com troca por chave, CSV para o Drive
codigo/cliente_gpu.py   cópia do cliente da trava de GPU do ialocal.maestro (não editar aqui)
codigo/mini.py          atualizar (só fast-forward da main) e instalar (launchd)
codigo/testes.py        prancha A1 sintética, entrega e Drive falsos, regras com os casos reais de 26/09
codigo/versoes.jsonl    0v1…: data, resumo e as tarefas que cada versão muda (muda: refeitas sozinhas)

conceitos/prancha.json  o que reconhece a prancha, famílias, carimbo, eixo, fatias, padrões, conferência
conceitos/ia.json       modelos e parâmetros das chamadas (cópia do extratores.json do extrator, 2v93)
conceitos/operacao.json de onde lê a entrega, para onde publica, limites, a prioridade na GPU
conceitos/prompts/      prompts versionados (o hash entra na chave de congelamento)

amostras/tabelas/       recortes de tabelas de prancha (Foz, Cambé) com a transcrição do Caio: o gabarito das tabelas
notas/                  plano_projeto.md (tese e itens), testes de mesa de 26/09, protótipo da prancha (camadas, georreferência)

dados/    prancha.parquet, prancha_leitura.parquet, prancha_tabela.parquet, recortes/, congelamento.jsonl,
          execucoes.jsonl, falhas.jsonl, gpu/ (pedidos ao maestro), launchd.log — regenerável, fora do git
saidas/   status.json (formato comum, o maestro lê) e os CSVs publicados — fora do git

Drive  saida/<acervo>/<obra>/projeto/   pranchas.csv, prancha_leituras.csv, prancha_tabelas.csv da obra
       saida/_sistema/projeto/          os mesmos, de todas as obras
```

## O que não é óbvio

- **O extrator entrega; o projeto só lê.** Cada repositório escreve na própria pasta. A tarefa `entregar_projeto` do
  extrator (2v94) olha a primeira página de todo PDF — de zip, de e-mail, de PDF dentro de PDF — e, se é A3 ou maior,
  deixa o arquivo em `~/dados/extracao/projetos/` e uma linha em `~/dados/extracao/projeto_entrega/`. O projeto lê
  essa entrega e o mapa das obras (`~/dados/extracao/por_obra/.obras`). Obra que sai do mapa sai da saída.
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
- **A bancada E3 (qualidade) continua no extrator** por ora: a classe `prancha_pdf` mede os modelos numa amostra, à
  parte da produção. Trazê-la para cá é o passo seguinte, junto com os itens pendentes do `plano_projeto.md` §9.
