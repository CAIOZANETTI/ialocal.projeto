# ialocal.projeto

## O que é

A prancha de projeto vira **vetor e dado**. Prancha é a folha de formato A3 ou maior, de engenharia ou editorial,
com carimbo e desenho. Dela saem:
- o desenho em DXF, por camada do CAD;
- as tabelas (relação de materiais, resumo de aço, coordenadas…);
- o carimbo (título, desenho, revisão, data, escala, folha, projetista, responsável técnico e CREA, contratante, obra, município);
- o quadro de revisões, as notas e observações;
- a família da obra (adutora, rede, ETA…) e o grupo (linear, localizada);
- na obra linear, o eixo desenhado, conferido contra o tubo da relação.

A IA local entra onde o código não fecha: o qwen3 e o Apple FM no carimbo, o Vision e o glm-ocr no texto desenhado
como curva, na folha escaneada e na tabela colada como imagem. Ela é **sempre conferida por código**.

Nasceu em 02/10/2026, separado do `ialocal.extrator`. O extrator ficou com as leituras simples (texto, planilha,
e-mail, OCR de documento) e com a triagem barata "é prancha?", e **entrega** aqui o PDF que é prancha. O plano e o
estado de cada item estão em `notas/plano_implementacao.md`; a tese, em `notas/plano_projeto.md`.

## Como rodo

No Mac mini, em `~/dados/ialocal.projeto`. Clone com a chave de acesso própria, como os outros `ialocal.*`
(LEIA do maestro, "O clone pede uma chave de acesso própria"):

```bash
cd ~/dados/ialocal.projeto
python3 -m venv .venv && .venv/bin/pip install polars pdfplumber pypdfium2 pillow ezdxf   # só na primeira vez
.venv/bin/pip install apple-fm-sdk pyobjc-framework-Vision                               # a IA do Mac (sem eles, segue sem)
ollama pull qwen3:8b && ollama pull glm-ocr                                               # se o extrator ainda não puxou
.venv/bin/python codigo/testes.py                       # prancha sintética de ponta a ponta + aferição (qualquer máquina)
.venv/bin/python codigo/mini.py instalar                # agenda a rodada (10 min) e o atualizar (5 min)
.venv/bin/python codigo/projeto.py rodada               # uma rodada à mão (o agendado faz o mesmo)
.venv/bin/python codigo/projeto.py ler <arquivo.pdf>    # uma prancha qualquer → saidas/avulsas/ (sem_ia no fim: só código)
.venv/bin/python codigo/projeto.py pasta <pasta>        # todo PDF da pasta
.venv/bin/python codigo/projeto.py status               # só regera os CSV e o status.json
```

## Onde está o quê

```
codigo/projeto.py      ler, pasta, rodada, status: uma pasta por prancha em dados/, o DXF e os CSV em saidas/
codigo/folha.py        perfil da folha (formato, classe, camadas, GeoPDF, é prancha?), vetor (primitivas) e DXF
codigo/leitura.py      por código: linhas de texto, células das grades, tabelas, revisões, carimbo, notas, família
codigo/linear.py       eixo desenhado (faixa colorida ou camadas de tubo), deflexões e a conferência eixo × escala × tubo
codigo/conferencia.py  IA no carimbo e na família, com as provas: presença (está no texto lido) e concordância (duas fontes)
codigo/ocr.py          folha sem texto real em fatias e a tabela colada em faixas, cada pedaço pelo Vision e pelo glm-ocr
codigo/ia.py           a porta para os motores locais (Ollama, Apple FM, Vision) e o congelamento de cada resposta
codigo/cliente_gpu.py  cópia do cliente da trava de GPU do ialocal.maestro (não editar aqui); sem o maestro, falha aberta
codigo/mini.py         atualizar (main por fast-forward) e instalar (launchd)
codigo/testes.py       prancha sintética A1 (camadas, carimbo em células, revisões, notas, materiais, eixo) e a aferição
codigo/versoes.jsonl   0v1, 0v2…; a última carimba cada leitura, o status.json e os CSV
codigo/afericao.jsonl  a régua da regra 17, uma linha por rodada registrada
conceitos/prancha.json      reconhecer, famílias, carimbo (rótulos-âncora, padrões), revisões, notas, tabelas, DXF, eixo, fatias
conceitos/extratores.json   modelos (qwen3, glm-ocr) e os contornos do glm-ocr medidos no mini
conceitos/operacao.json     de onde lê (entregas do extrator), para onde publica (Drive), GPU, limites por rodada
conceitos/prompts/          prompts versionados (o texto entra na chave de congelamento)
notas/                      plano de implementação, a tese (plano_projeto) e os testes de mesa de Foz, protótipos de georreferência

~/dados/extracao/para_projeto/   o que o EXTRATOR escreve: <sha256>.pdf e entregas.jsonl — aqui só se lê
dados/pranchas/<sha>/            leitura.json (a prancha inteira) e p<N>_geometria.parquet (as primitivas da página N)
dados/lidas.jsonl                sha256 × versão × erro: o que já foi lido
dados/congelamento.jsonl         cada resposta de IA com a chave inteira (§8.2)
dados/gpu/                       pedidos de vez ao maestro e o que foi usado (feitos.jsonl)
saidas/<acervo>/<obra>/projeto/  O PROJETO DA OBRA, ao lado do extrator/, revisor/ e contexto/ dela (extrator 2v93):
                                 o DXF de cada prancha (mm de papel, uma camada por camada do CAD) e os CSV abaixo, só da obra
saidas/_sistema/projeto/         os mesmos CSV de todas as pranchas:
    pranchas.csv                 uma linha por folha: formato, classe, família, carimbo aceito, contagens, conferência
    carimbo.csv                  cada campo do carimbo com o valor, o status (confirmado, um_leitor, divergente, vazio) e as fontes
    tabelas.csv                  cada linha de cada tabela (vetor ou colada), célula a célula
    revisoes.csv, notas.csv, valores_ocr.csv
saidas/avulsas/_avulsos/projeto/ o que se leu à mão (ler, pasta): fica no mini
saidas/status.json               o status no formato comum do maestro (fica no mini)
Drive  gdrive:saida/             saidas/ sem o status e as avulsas (rclone copy --checksum: só o que mudou)
```

## O que não é óbvio

- **O DXF é vista, não fonte** (D1 do `plano_projeto`). A fonte é o `geometria.parquet`: cada traço, preenchimento,
  texto e imagem, com a camada do CAD, a cor, a espessura e as coordenadas em mm de papel (origem embaixo à esquerda).
  O DXF sai dele e se regenera. Ele tem linha, hachura e texto; não tem bloco nem cota associativa de CAD.
- **Célula é retângulo de verdade.** Os traços horizontais e verticais que se cruzam formam a grade. Duas células
  vizinhas só se separam onde o traço entre elas existe: o carimbo tem linhas com divisões diferentes. Tabela é achada
  pelo cabeçalho (`tabelas.tipos`) e cresce para cima e para baixo pelas fileiras com as mesmas divisões.
- **Carimbo por rótulo-âncora, não por posição fixa.** O carimbo é a área das células onde aparecem rótulos de 3 ou
  mais campos diferentes. O valor de cada campo é o resto da linha do rótulo ("DATA: 09/2020") ou a linha mais perto
  na mesma célula. Sem grade, vale a região do canto inferior direito. Rótulo novo de projetista é uma linha em
  `conceitos/prancha.json`. O "DATA" do quadro de revisões não conta como data do carimbo.
- **A IA não inventa: a invenção é medida e barrada.** O valor que o qwen3 ou o Apple FM devolve e que não aparece
  no texto lido do recorte vai para `inventado` e não entra. O valor é `confirmado` quando duas fontes de natureza
  diferente concordam: rótulo do código, regra sobre os dois OCRs, qwen3, Apple FM. Uma fonte só dá `um_leitor`, e
  fontes discordantes dão `divergente` (fica o do código). No OCR das fatias, número só é confirmado quando o Vision e
  o glm-ocr leram o mesmo; a estaca 323 que o glm-ocr "continuou" fica `so_glm`.
- **Texto real primeiro, OCR só onde falta.** Na folha com texto de verdade, o carimbo e as tabelas saem do vetor. As
  fatias (até 60, em pedaços de até 1.100 px) só rodam na folha com texto em curva ou escaneada. A tabela colada como
  imagem é lida em faixas. A leitura para em `limite_prancha_s` e diz quanto faltou.
- **Família e grupo saem de regra; a IA só desempata**, escolhendo numa lista. Vale só se os motores concordam; o
  grupo nunca é perguntado ao modelo.
- **Uma leitura por versão.** `dados/lidas.jsonl` guarda sha256 × versão. A versão nova relê tudo na rodada
  seguinte, e a IA congelada não chama o modelo de novo para a mesma pergunta. A rodada lê no máximo 20 pranchas e
  sai; a próxima continua.
- **A vez da GPU é do maestro.** A rodada pede a vez com prioridade 5 (extração) e devolve quando alguém mais
  importante espera. Sem o maestro, segue sem a trava (falha aberta).
- **Nenhuma IA em nuvem** (MASTER-PLAN §5.4): só o Ollama local, o modelo do dispositivo da Apple e o Vision. O código
  chega ao mini só pela `main`, por PR aprovado pelo Caio.
- **A obra é a do extrator.** A entrega traz acervo e obra pelo mapa do extrator (`por_obra/.obras`, com os nomes do
  `obras.csv`); sem eles, a obra sai do caminho com a mesma regra (o zip ou a pasta do 1º nível; arquivo solto é
  `_avulsos`). Assim `saida/<acervo>/<obra>/` tem `extrator/`, `projeto/`, `revisor/` e `contexto/` lado a lado.
- **`dados/` e `saidas/` não vão para o git.** O GitHub guarda código, conceitos e notas.
