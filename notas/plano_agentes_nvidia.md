# Agentes externos em paralelo — dois modelos gratuitos da NVIDIA ao lado da leitura local

**Estado: plano, antes do código** (04/10/2026). Pedido do Caio: "testar alguns agentes da NVIDIA que são gratuitos em
paralelo, abrir uma exceção no plano só para este repositório, medir a eficiência deles, sem tirar a camada
determinística; começar com dois; se der certo, continua e busca mais; se não, descontinua". Parte do documento
`PLANO_MULTIAGENTES_NVIDIA_EXTRACAO_PDF.md` (04/10), adaptado ao que o repositório já tem. Exceção de dados: MASTER-PLAN
§5.6 (`ialocal.maestro`, v7.10).

**Decisão do Caio de 04/10/2026, depois da primeira versão deste plano:** "pode mandar os projetos, porque todos eles
são de domínio público, são da Sanepar, e pode mandar também o boletim de sondagem — é amostra de solo; o boletim é o
mais difícil, é o que vai precisar de mais ajuda". Consequências: a máscara do carimbo fica **desligada**
(`agentes.json → mascarar_carimbo: false`), `obras_permitidas: ["*"]`, e o boletim entra na bancada (B5) como prioridade.
**F1 feita na 0v5** (porta, sonda, paralelo, testes).

## 1. O que muda e o que não muda

| fica como está | entra |
|---|---|
| código antes de IA (`ler_prancha`: camada, carimbo por texto real, família, eixo) | dois **agentes externos** que leem os **mesmos recortes** que a IA local |
| glm-ocr × Vision na vez da GPU, `confirmado` só com dois leitores de natureza diferente | uma **curadoria em Python** que junta N leitores e diz quem leu o quê |
| congelamento (`dados/congelamento.jsonl`), `versoes.jsonl`, falhas, status | uma **bancada** com gabarito que decide, por número escrito antes, se cada agente fica |
| os CSVs publicados e o contrato deles | nada nos CSVs enquanto a bancada não der o veredito (§8, F5) |

**A regra que não se dobra:** agente externo é mais um **leitor candidato**, nunca prova. Valor só vira `confirmado`
com uma testemunha que não gera texto — o Vision, o texto real do PDF ou a geometria — porque modelo generativo erra
do jeito dos outros: o gemma3 inventou 21 cotas em progressão e o glm-ocr continuou as estacas até a 323
(`teste_tese_modelos_2026-09-26.md`, T1 e T4b). Dois modelos que "continuam" a mesma sequência dariam dois votos a um
número inventado.

## 2. Os candidatos gratuitos (catálogo de 04/10/2026)

Conferido em `https://integrate.api.nvidia.com/v1/models` (lista da API, 81 modelos) e no catálogo
`build.nvidia.com/models`. O selo "Free Endpoint" está na página de cada modelo e **é conferido na F0**; o preço é
dado que muda (`conceitos/agentes.json → gratuito_conferido_em`).

| id na API | o que é | especialidade para prancha | papel aqui |
|---|---|---|---|
| `moonshotai/kimi-k3` | VLM generalista, MoE ~2,8 T, raciocínio sempre ligado, visão nativa | **lidera o OmniDocBench (91,1)**; leitura de documento, tabela, contexto | **agente 1** |
| `nvidia/nemotron-parse-2.0` | parser de documento < 1 B (encoder-decoder), 06/2026 | texto **com caixa (bbox)**, classe do elemento (tabela, título, figura…), ordem de leitura; tabela em HTML, CSV ou JSON; 1.024×1.280 a 1.664×2.048 px | **agente 2** |
| `z-ai/glm-5.3-flash` | VLM MoE multimodal, raciocínio, ferramentas | leitura geral de página | reserva 1 |
| `meta/muse-glimmer-30b` | VLM 30 B, texto e imagem, raciocínio | leitura geral | reserva 2 |
| `deepseek-ai/deepseek-v4.1-flash` | MoE 552 B (8 B ativos), multimodal | leitura geral | reserva 3 |
| `nvidia/nemotron-ocr-v2` | OCR **não generativo** (detector + reconhecedor), bbox e confiança | seria uma testemunha na nuvem; mas o português não está na lista de línguas e não está no `/v1/models` (outra rota) | testar depois, só números |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`, `meta/llama-3.2-90b-vision-instruct` | VLMs | leitura geral | catálogo |
| `nemotron-3-super`, `-ultra`, `gemma-4-31b-it`, `gpt-oss-20b` | só texto | desempate da família, organizar tokens (como o qwen3 no T9b) | fora desta etapa |

**Por que esses dois.** São **de natureza diferente entre si e dos locais**: um generalista gigante que lê e
interpreta (Kimi K3) e um especialista pequeno que devolve o texto **com a caixa onde o leu** (Nemotron Parse). Erros
pouco correlacionados valem mais que dois generalistas parecidos (o §30 do documento de origem). O Parse ataca a dor
medida em 26/09 — a relação de materiais colada como imagem, que abortava o glm-ocr inteira (T6) — e a caixa dele é
evidência que se confere por código. O GLM-5.3 Flash fica de reserva: se o Kimi K3 for lento demais no gratuito (MoE
enorme com raciocínio), troca-se uma linha do `agentes.json`.

## 3. O que os termos permitem (NVIDIA API Trial Terms of Service, v. 19/09/2025)

| cláusula | diz | consequência aqui |
|---|---|---|
| 1.2 | acesso "para fins de teste limitados", **sem uso em produção** | é bancada e protótipo; nada publicado depende só do agente |
| 2.3 | não guarda nem usa o conteúdo ao fim da sessão, **salvo** 2.4 e 3.3 | — |
| 3.3 (iv) | coleta **conteúdo enviado e gerado "para melhorar produtos e serviços da NVIDIA, inclusive modelos de IA"** | **não atende** à condição do MASTER-PLAN §5.5 ("termos que não usam o dado para treino"): por isso é exceção própria, §5.6, com o risco aceito pelo Caio |
| 2.6 (a), 4.3 | não enviar informação **confidencial**, dado pessoal, informação governamental | o Caio decidiu (04/10) que o acervo é projeto público da Sanepar e que o boletim pode ir; o carimbo e o boletim têm nome de engenheiro e de sondador — risco aceito. A máscara do carimbo existe como chave (`mascarar_carimbo`) se a decisão mudar |
| limites | por modelo, não publicados (cerca de 40 pedidos/min relatados); créditos viraram limite de taxa | ritmo por agente em `agentes.json`; 429 com espera |

## 4. Arquitetura — dentro do que existe

```
ler_prancha (código, sem mudança)
      │ fatias (prancha.json → fatias) e imagens coladas
      ▼
┌───────────── mesmos recortes, mesma máscara ─────────────┐
│ local, na vez da GPU        │ externos, sem GPU, em paralelo│
│ glm-ocr  (generativo)       │ kimi    (generativo)          │
│ Vision   (testemunha)       │ parse   (generativo, c/ caixa)│
└──────────────┬──────────────┴──────────────┬────────────────┘
               ▼                             ▼
        congelamento.jsonl (chave: motor, modelo, prompt, imagem, opções)
               ▼
      curadoria.py — Python determinístico: valor × leitores → status
               ▼
      bancada: gabarito → placar por agente, por padrão, por tipo de recorte
```

| arquivo | o que é | linhas (ordem) |
|---|---|---|
| `conceitos/agentes.json` **novo** | `ligado`, `prazo_fim`, `obras_permitidas`, endpoint, arquivo da chave, os agentes (modelo, tipo, prompt, `max_tokens`, `simultaneas`, `por_minuto`, `timeout_s`), `gratuito_conferido_em`, os critérios da bancada | — |
| `conceitos/prompts/agente_fatia.txt`, `agente_tabela.txt` **novos** | o pedido ao VLM: as `_regras.txt` na frente e a resposta em JSON (`linhas` ou `valores`) | — |
| `codigo/ia.py` | `nvidia(modelo, mensagens, opcoes)`: urllib, chave lida de `~/.config/ialocal/nvidia_api_key`, **fora da chave do congelamento**; 429 → espera `Retry-After` com jitter, 3 tentativas; o modelo e a data que a resposta devolve vão ao `meta` (o remoto não tem digest) | ~70 |
| `codigo/agentes.py` **novo** | `ler_com_kimi`, `ler_com_parse` (cada um devolve `{'texto', 'linhas', 'caixas', 'erro'}`), `em_paralelo` (`ThreadPoolExecutor`, um semáforo e um ritmo por agente), `permitido` (ligado, prazo, obra, chave), CLI `sondar` (F1, feito); `bancada` e `placar` (F2); `mascarar` só se `mascarar_carimbo` voltar a true | ~200 |
| `codigo/curadoria.py` **novo** | a regra de §5, pura (dict entra, dict sai) | ~80 |
| `codigo/testes.py` | servidor NVIDIA falso (`http.server` numa thread): resposta, 429 uma vez, timeout; máscara; curadoria; desligado e prazo vencido não chamam | ~120 |
| `codigo/versoes.jsonl` | 0v5, `muda: []` (a bancada não mexe no que já foi lido) | 1 |
| `LEIA.md` | a exceção, a chave, os comandos | — |

**Por que threads e não `asyncio`.** O repositório é urllib e biblioteca padrão; a espera é de rede, e
`ThreadPoolExecutor` com um semáforo por agente dá o paralelismo sem trocar o cliente HTTP. As chamadas externas **não
pedem a vez da GPU**: não usam o mini para inferir.

```python
def em_paralelo(recortes, agentes):
    """Cada recorte por cada agente ao mesmo tempo; o semáforo e o ritmo de cada agente seguram o limite do gratuito.
    Falha de um agente vira linha com o erro — a leitura segue com os outros."""
    AGENTES = comum.configuracao('agentes')['agentes']
    with ThreadPoolExecutor(max_workers=sum(AGENTES[a]['simultaneas'] for a in agentes)) as fila:
        pedidos = {fila.submit(ler_com_agente, agente, recorte): (agente, recorte) for agente in agentes for recorte in recortes}
        for feito in as_completed(pedidos):
            agente, recorte = pedidos[feito]
            yield {'agente': agente, 'recorte': str(recorte), **feito.result()}
```

## 5. Curadoria — Python decide, o modelo só lê

Leitores: `pdf` e `vision` são **testemunhas** (não geram texto); `glm_ocr`, `kimi` e `parse` são **generativos**.

| status do valor (padrões de `prancha.json`) | regra |
|---|---|
| `confirmado` | uma testemunha e mais um leitor qualquer leram o mesmo valor no mesmo recorte (a regra de hoje, com mais leitores) |
| `confirmado_ia` | dois ou mais generativos **de famílias diferentes** leram o mesmo, sem testemunha. **Não é fato**: vai à revisão e é a hipótese H8/H9 da bancada (consenso de IA acerta?) |
| `so_<leitor>` | só um leu |
| `fora_da_caixa` | o parse diz que leu o valor numa caixa onde o Vision não tem token nenhum: suspeita de invenção (H10) |

Tabela: a linha é casada pela chave (código SAP; sem código, a descrição normalizada). `confirmada` se todo número da
linha está na testemunha da mesma imagem; `confirmada_ia` se dois generativos dão as mesmas células; senão `pendente`.
Nenhuma regra escolhe "a resposta com mais campos" nem a mais longa.

## 6. Bancada — o gabarito que já existe

| conjunto | o que tem | o que mede | sai do mini? |
|---|---|---|---|
| **B1 tabelas Cambé** (`amostras/tabelas/216_cambe`) | 18 imagens, **188 linhas de material transcritas pelo Caio** (17 tabelas) (código; nº; discriminação; quantidade; unidade) | linha certa (código + quantidade + unidade), célula certa, linha inventada | sim: recortes de relação de materiais, sem nomes |
| **B2 controle negativo** | 6 recortes sem número (ruas e lotes, folha em branco, legenda), como o T3 de 26/09 | qualquer número lido é invenção | sim, se da obra permitida |
| **B3 fatias da AAT-06** | as fatias do teste de mesa com o gabarito de `teste_prancha_2026-09-26.md` (estacas, cotas, escala) | valor certo por padrão; sequência continuada | sim (decisão de 04/10) |
| B4 tabelas Foz (`211_foz`) | 78 imagens **sem transcrição** | só concordância entre leitores; vira gabarito se o Caio transcrever 10 (demanda nova) | sim |
| **B5 boletins de sondagem** (prioridade do Caio: "o mais difícil") | as páginas digitalizadas dos boletins do acervo e os que chegarem pela demanda `projeto-boletins-reais` (com o CSV gabarito: furo, coordenadas, cota da boca, N.A., profundidade final, N-SPT por metro) | campo certo e N-SPT certo por metro, pelos mesmos padrões de `sondagem.json`; a camada do perfil por faixa de profundidade; o agente lê a página inteira (Kimi: transcrição; Parse: a tabela do boletim com caixa) | sim (decisão de 04/10) |

Saídas: `dados/bancada_agentes.parquet` (uma linha por recorte × leitor × valor) e `saidas/bancada_agentes.csv`; o
placar por `groupby(['conjunto', 'leitor'])`: precisão, cobertura, inventados, falhas, segundos (mediana e p90),
tokens. **Valor marginal**: cobertura certa da curadoria local (glm-ocr + Vision) contra local + kimi, local + parse e
local + os dois — quanto cada agente acrescenta, não quanto acerta sozinho.

## 6-A. Todos os candidatos, quatro medidas e o limite por provedor (pedido do Caio, 04/10)

> "A gente devia comparar todas as IAs que a gente tem, não só as duas novas. O benchmark tem que medir qualidade, tempo
> útil, taxa de erro e tempo perdido com o retry, e ter limitador de taxa por provedor, senão a comparação fica
> injusta. Hoje vocês estão medindo mais o comportamento do plano gratuito do que o modelo."

| candidato | onde | lê | papel na bancada |
|---|---|---|---|
| glm-ocr | Ollama (GPU do mini) | imagem | a base: a curadoria `local` é ele com o Vision |
| gemma3:12b | Ollama | imagem | leitor (inventou na folha inteira em 26/09: entra para medir) |
| Vision | macOS | imagem | testemunha; como leitor, só **presença** (não tem estrutura de tabela) |
| qwen3:8b | Ollama | texto | **organizador**: monta a tabela com o texto do Vision (T9b: 0 inventados) |
| Apple FM | dispositivo | texto | organizador, com o mesmo pedido |
| Kimi K3 | NVIDIA | imagem | agente externo |
| Nemotron Parse 2.0 | NVIDIA | imagem | agente externo (parser de documento da NVIDIA) |

**As quatro medidas, separadas** (por conjunto e leitor, em `bancada_agentes.csv`): **qualidade** (linha certa,
presença, inventadas, confirmadas erradas); **tempo útil** (só a tentativa que deu certo); **taxa de erro** (o que
falhou depois de todas as tentativas); **tempo perdido** (ritmo do provedor, esperas, tentativas recusadas, fila da GPU),
com a contagem de 429 e 5xx. O perdido é do plano gratuito ou da fila, **não entra no veredito**.

**Limite por provedor:** o Kimi e o Parse dividem o limite da conta (`provedores.nvidia`: 36/min, 6 abertas), em vez,
recorte a recorte; os locais vão um por vez na vez da GPU. O tempo útil de cada chamada é comparável entre todos; o
tempo de parede, não (paralelo na NVIDIA, em fila no mini). `--refazer` mede o tempo de novo, nas mesmas condições.

## 7. Critérios — escritos antes de rodar (premissas, mudam por PR)

Um agente **continua** se, nas bancadas B1 a B3:

1. **acrescenta**: a curadoria com ele confirma, certo, **≥ 10 pontos percentuais** mais linhas da B1 (ou valores da
   B3) que a curadoria só local; **ou** sozinho acerta mais linhas da B1 que o glm-ocr;
2. **não contamina**: **zero** linha ou valor `confirmado` errado por causa dele (PR08: campo que move dinheiro ≥ 99 %);
   inventados ≤ 2 % do que emitiu na B1; na B2, não mais números que o glm-ocr;
3. **opera**: ≥ 90 % das chamadas com resposta depois das tentativas; mediana ≤ 60 s por recorte.

Falhou em 1 ou 2: **descontinua** (`ligado: false` para ele; o código, o congelamento e o placar ficam — servem ao
próximo candidato). Falhou só em 3: troca pelo reserva e repete. Os dois passaram: F5. Também é resultado "o agente não
acrescenta nada": o plano termina com menos complexidade.

## 8. Fases

| fase | o quê | quem | pronto quando |
|---|---|---|---|
| **F0** decisão | aprovar o PR do MASTER-PLAN §5.6; criar a conta NVIDIA Developer com a conta do mini (`macminicaio@gmail.com`, feito em 04/10; limite de 40 pedidos por minuto por conta); conferir o selo **Free Endpoint** nos dois modelos; gerar a chave e gravar no mini em `~/.config/ialocal/nvidia_api_key` (`chmod 600`); dizer as `obras_permitidas` | Caio, ~30 min | chave no mini, PR aprovado |
| **F1** porta e sonda — **feita (0v5)** | `ia.nvidia`, `agentes.json`, `agentes.py sondar`: a tabela 01 de Cambé a cada agente, em paralelo — autenticação, imagem aceita, formato da resposta (o Parse em tool_calls ou em marcas: os dois são lidos), tempo, tokens, placar contra o gabarito. Testes com a API falsa | código | `testes.py` passa (feito); **no mini, com a chave:** `dados/agentes_sonda.jsonl` com os dois respondendo |
| **F2** bancada de tabelas e boletins — **código feito (0v8)** | B1, B2 e **B5** com os quatro leitores (`bancada.py tudo`) (local no mini, na vez da GPU; externos em paralelo); placar e curadoria | código + mini | `bancada_agentes.csv` no Drive, `_sistema/projeto/` |
| **F3** bancada de fatias | B3 (e B4 se houver transcrição): as fatias da folha; parse com a fatia completada a 1.280 px | código + mini | placar das fatias |
| **F4** veredito | os critérios do §7, agente por agente; registro em `notas/` e no §17 do MASTER-PLAN | Caio | continua, troca ou descontinua |
| **F5** se passar | tarefa `ler_prancha_agentes` na rodada, antes da fila da GPU (rede, não GPU); a curadoria do §5 em `prancha_leitura` com colunas novas (`leitores`, `status_curadoria`) **ao lado** do `status` de hoje; versão 1v0 (o contrato muda); o terceiro agente entra só pela bancada | código | CSVs com as colunas; status com os agentes |

## 9. Riscos

| risco | o que segura |
|---|---|
| NVIDIA usa o conteúdo para melhorar modelos (termos 3.3) | acervo público da Sanepar (decisão de 04/10), prazo, interruptor, registro de cada envio; risco aceito pelo Caio no §5.6 |
| gratuito muda, modelo sai do catálogo | `gratuito_conferido_em`; `ligado: false` não quebra nada; a resposta congelada continua valendo para a bancada |
| modelo remoto muda por trás do mesmo nome, temperatura 0 não garante a mesma resposta | o `meta` guarda o modelo e a data devolvidos; a bancada roda de novo antes do veredito da F5 |
| limite de taxa, lentidão do Kimi K3 | semáforo e ritmo por agente; reserva GLM-5.3 Flash |
| chave vazada | fora do git e da chave do congelamento; `chmod 600`; nunca nos logs |
| a imagem do PDF traz instrução escrita | princípio 10: o prompt diz que a imagem é dado; a saída passa pela curadoria, nunca executa nada |
| o consenso de IA parece verdade | `confirmado_ia` não é `confirmado`; a bancada mede se acerta (H8) antes de valer qualquer coisa |

## 10. Fontes

- Lista de modelos da API: `https://integrate.api.nvidia.com/v1/models` (consultada em 04/10/2026).
- Catálogo: https://build.nvidia.com/models
- Termos: https://assets.ngc.nvidia.com/products/api-catalog/legal/NVIDIA%20API%20Trial%20Terms%20of%20Service.pdf (v. 19/09/2025)
- Acesso gratuito para desenvolvimento: https://docs.api.nvidia.com/nim/docs/product
- Nemotron Parse 2.0: https://huggingface.co/nvidia/NVIDIA-Nemotron-Parse-2.0
- Nemotron OCR v2: https://huggingface.co/nvidia/nemotron-ocr-v2
- Kimi K3 no OmniDocBench: https://llm-stats.com/benchmarks/omnidocbench
