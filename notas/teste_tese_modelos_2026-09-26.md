# Teste da tese — os modelos locais na prancha da AAT-06 (26/09/2026)

**Pergunta do Caio.** A tese de `plano_projeto.md` §11 (fatiar, pergunta fechada, pista do código,
dois leitores, prova de presença, controle negativo) funciona com os modelos que ele tem? Sem
escrever código do projeto: só recortes de imagem e chamadas diretas ao Ollama.

**Como.** O Ollama 0.34.4 foi instalado **no contêiner da sessão de nuvem** (Linux, 4 CPUs, 15 GB, sem
GPU), com os mesmos modelos do mini: `glm-ocr:latest`, `gemma3:12b` e `qwen3:8b`. Temperatura 0 e
semente 0. Ao fim, foi desinstalado e os modelos apagados. **Apple FM e Vision não rodam fora do macOS**
e ficaram de fora. Os tempos são de CPU, não do mini com GPU. O gabarito é a leitura conferida de
`teste_prancha_2026-09-26.md`. Critério de cada teste definido antes de rodar.

## Resultados

| # | premissa | teste | resultado | veredito |
|---|---|---|---|---|
| T1 | fatiar melhora | cotas do terreno: folha inteira (1.600 px) × fatia do quadro (EST 77–83) | gemma3 na folha inteira: **0 de 28**, e inventou 21 cotas em progressão perfeita (224,85 → 226,85, de 0,10 em 0,10). Na fatia: **4 de 7** (trocou 6 por 8 em 3 cotas). glm-ocr na fatia: 7 de 7 valores, 2 fora de ordem | **confirmada**: folha inteira gera invenção |
| T2 | endireitar o texto vertical ajuda | a mesma fatia girada 90° | glm-ocr **pior** girado: perdeu os comprimentos e 1 geratriz, leu "243.00" no lugar de 243.300. Normal, leu o texto vertical sem problema | **refutada** para o glm-ocr |
| T3 | o modelo inventa sem o dado | recorte com ruas e lotes, sem cotas; prompt: "responda AUSENTE, não invente" | gemma3 **inventou 20 linhas** ("EST 0+782: 217,87"…). glm-ocr só transcreveu o texto que existia | **confirmada**: o gemma3 inventa mesmo instruído |
| T4 | a prova de presença pega a invenção | números do gemma3 × tokens do glm-ocr no mesmo recorte | os 3 erros da fatia (248,929…), as 20 linhas do controle e a progressão da folha inteira: **nenhum** está nos tokens do OCR → todos seriam barrados | **confirmada**, com ressalva (abaixo) |
| T4b | o OCR por modelo é prova segura | glm-ocr na planta (fatia com EST 75–85) | leu certo as 4 ruas e as EST 75–85, e depois **continuou a sequência sozinho até a EST 323**, mais "C22 03…07" | **o glm-ocr também inventa**: continua sequência |
| T5 | a camada isolada ajuda | nomes de rua: planta normal × camada `641_TOP_VIAS` isolada | glm-ocr: normal **4/4** (a 1.100 px; a 1.600 px deu erro 500); camada **4/4**. gemma3: normal **2/4** ("Rua Brisbane", "Rua Ipananga"), camada **3/4** ("Rua Brisoe") | **confirmada para o gemma3** (2 → 3); o glm-ocr já lia tudo |
| T6 | a planilha em imagem é legível | tabela da ventosa (018): inteira × em 2 fatias com sobreposição | inteira: **abortou** ("token repeat limit", 1.100 px) e erro 500 (1.600 px). Em 2 fatias: **15/15 linhas, 14/14 códigos SAM, 15/15 quantidades**; unidade "PÇ" lida "P¢"; as 2 linhas da sobreposição concordam | **confirmada**: fatiar resolve |
| T8 | pergunta fechada de nível 1 | "que zona é esta?" (A carimbo · B tabela · C planta · D perfil · E detalhe · F nenhuma) em 6 recortes | gemma3: **3 de 6** (acertou carimbo, perfil, detalhe; disse "perfil" para tabela, planta e lotes) | **refutada**: o gemma3 não serve para zonear; zoneamento é do código |
| T9 | a pista do código melhora | a mesma fatia do T1, com os números do OCR no prompt ("use SOMENTE estes") | gemma3: **7 de 7** (sem pista: 4 de 7) | **confirmada** |
| T9b | o modelo de texto organiza os tokens | qwen3 só com o texto do OCR, sem imagem | **5 certos, 2 AUSENTE, 0 inventado** | **confirmada**: não inventa quando não sabe |
| T7 | reconhecer o tipo de projeto | qwen3 com o texto do carimbo e das notas (012 e 018) | família **adutora** ✓ nas duas; desenho ✓ (planta e perfil; detalhe); grupo ✗ ("localizada" para adutora) | **confirmada em parte**: o grupo sai da família por regra |

## Falhas operacionais (valem para o mini e para o extrator de fotos)

- **Erro 500 no glm-ocr com imagem de ~1.600 px** (planta densa, tabela): o mesmo erro do mini. Com
  1.100 px funcionou. O limite `lado_max_px_ia` = 1.600 não é seguro.
- **Laço de repetição no glm-ocr**: a mesma lista repetida até o limite de tokens em quase todas as
  chamadas. Precisa de limite de tokens menor e de deduplicação; o `repeat_penalty` 1,15 não basta.
- **Memória**: com 15 GB, três modelos carregados juntos derrubaram o servidor (processo morto).
  Um modelo por vez (`OLLAMA_MAX_LOADED_MODELS=1`) resolveu. No mini (24 GB), medir antes de paralelizar.
- **Tempo em CPU**: gemma3 180–380 s por imagem; glm-ocr 80–220 s; qwen3 texto 15–50 s. No mini,
  com GPU, deve ser uma ordem de grandeza menor: medir lá.

## O que a tese vira

1. **Fatiar é obrigatório**, e com ≤ 1.100 px. Na vetorial, a fatia é a zona ou a camada; a grade só na escaneada.
2. **Zonear é do código** (T8), não do gemma3.
3. **Número nunca sai do gemma3 olhando a imagem.** O papel que funcionou foi **associar com pista**:
   o OCR lê, e o gemma3 (T9, 7/7) ou o qwen3 (T9b, sem invenção) põe cada número no campo certo, usando só os tokens lidos.
4. **O OCR por modelo não é prova sozinho** (T4b continuou a sequência de estacas). A presença precisa
   de um segundo leitor de natureza diferente: o **Vision** (OCR clássico, no mini) ou a **geometria**
   (quantas marcas de estaca a camada tem dentro da fatia).
5. **Controle negativo pega de verdade** (T3): tem de entrar em toda bancada.
6. **O que é dedutível não se pergunta** (T7: grupo linear/localizada vem da família).

## O que continua sem teste

- **Apple FM e Vision**: só no mini. O Vision é o candidato mais importante, porque é o segundo leitor que não inventa sequência.
- Tempo real com GPU; paralelismo no mesmo modelo.
- Escaneada real, outra família e outro projetista.
