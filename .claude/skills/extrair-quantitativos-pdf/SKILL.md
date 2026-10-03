---
name: extrair-quantitativos-pdf
description: Pipeline ETL para extrair quantitativos (aço, concreto, formas) de pranchas estruturais em PDF vetorial (TQS/Sanepar e similares) — render + OCR + reconstrução de tabelas → CSV rastreável → Excel. Usar quando o Caio pedir extração de quantidades/tabelas de PDFs de projeto estrutural, leitura de acervo de pranchas CAD, ou conversão de resumos de aço/materiais em planilha. Método validado em acervo real de 488 PDFs (99,8% extraído).
---

# Extração de quantitativos de pranchas PDF (TQS/Sanepar)

Método completo, validado num acervo real de 488 pranchas Sanepar (487 extraídas,
~20 min em 8 processos, 1.418 t de aço e 19.900 m³ de concreto consolidados).
Implementação de referência: `~/Documents/gel_engenharia/sanepar_eta/` (módulos em
`etl/`, plano em `plano.md`). Reaproveitar esse código quando o acervo for do mesmo
padrão; para padrão novo, seguir as fases abaixo.

Aplicar junto com a skill `estilo-caio-python` (pt-BR, dict puro, metadados em JSON,
cálculo em Python → CSV → apresentação só lê).

## Fase 0 — Diagnosticar a amostra ANTES de qualquer código

Nunca assumir que PDF de CAD tem camada de texto. Rodar primeiro:

```python
import fitz
p = fitz.open(pdf)[0]
len(p.get_text("text"))     # ~0-200 chars => texto virou curva vetorial → OCR obrigatório
len(p.get_images())         # 0 => vetorial puro (render sai perfeito, OCR ~1.00)
len(p.get_drawings())       # dezenas de milhares => prancha CAD típica
p.rect                      # A1 paisagem (~2908×1684 pts) → nunca OCR na folha inteira
```

- **Vetorial sem texto** (caso TQS): render em alta DPI + OCR. Fonte CAD limpa → confiança ~1.00.
- Se `get_text()` retornar as tabelas: não precisa de OCR, extrair direto (caminho raro).

Depois, renderizar a página inteira a ~100 DPI, LER a imagem e mapear visualmente:
onde estão as tabelas-alvo, o carimbo, e recortar cada uma em ~300 DPI para confirmar
colunas e montar o **gabarito de validação** (valores lidos a olho da amostra — a
extração automática deve bater 100% com ele antes de escalar).

## Ambiente (Mac sem brew)

- **Render:** PyMuPDF (`fitz`) — dispensa poppler, controla DPI e clip por região.
- **OCR:** `rapidocr-onnxruntime` (pip puro, sem binário de sistema; NÃO usar
  tesseract que exige brew). Importa como `from rapidocr_onnxruntime import RapidOCR`.
- **Grade/caixas:** OpenCV. **Dados:** pandas + CSV. **Excel:** openpyxl.

## A descoberta central — como reconstruir as tabelas

Tabelas TQS têm separador vertical de coluna mas **NÃO têm linha horizontal entre as
linhas de dados** → detecção de células por grade falha. O que funciona:

1. **1 passada de OCR** na imagem da tabela → tokens `(cx, cy, txt, conf)`.
2. **Agrupar em linhas por `cy`** (tolerância ~18 px a 300 DPI).
3. **Atribuir colunas pela âncora do cabeçalho**: cada token vai para a coluna cujo
   rótulo (POS/BIT/QUANT/UNIT/TOTAL…) tem `cx` mais próximo.
4. **Classificar cada linha**: dado / sub-cabeçalho de grupo (célula única larga, vira
   coluna `elemento` propagada) / cabeçalho / linha especial (TOTAL, ENCHIMENTO, LASTRO).
5. **Campos fracos**: dígito isolado (coluna POS) erra ocasionalmente → **reindexar
   determinístico por grupo**, nunca confiar no OCR dele. Os numéricos compostos saem ~100%.

## Auto-localização por título-âncora (fração fixa NÃO generaliza)

Validado no acervo: cada prancha põe as tabelas em posição diferente, e pode haver
**duas tabelas do mesmo tipo lado a lado**. Localizar assim:

- Varrer a **metade direita** da folha em ladrilhos 2×2 **com 15% de sobreposição**
  (sem sobreposição o título é cortado no limite do ladrilho — bug real).
- OCR a **70 DPI** (títulos são grandes; DPI baixo corta o custo da varredura).
- Achar o título pela **menor janela contígua de tokens** que contém a frase
  normalizada (NFKD sem acento — OCR devolve "ACO"/"AÇO" inconsistente).
- Deduplicar ocorrências vistas em ladrilhos sobrepostos (distância < 0.03 da página).
- Delimitar a caixa a 150 DPI com OpenCV (morfologia H+V) escolhendo o **MENOR
  retângulo que contém o título** (o maior engloba notas e carimbo vizinhos);
  limitar altura (~0.30 da página) porque tabelas compartilham borda com a coluna da prancha.
- Extrair o recorte da caixa em **350 DPI**.
- O extrator valida a caixa exigindo o cabeçalho completo — caixa errada falha limpo.

## Carimbo (metadados do projeto)

Selo padrão no canto inferior direito (~fração `[0.715, 0.775, 1.0, 1.0]`). Extrair
por **rótulo-âncora → zona relativa**: achar o token do rótulo ("MUNICIPIO/SISTEMA:",
"DATA:", "ARQUIVO ELETRONICO:"…) e capturar tokens na janela (dy, dx) em fração do
tamanho da imagem (robusto a DPI). O campo "arquivo eletrônico" deve bater com o nome
do PDF — é a **chave de rastreabilidade** (`codigo_arquivo`) presente em toda linha
de todo CSV.

O nome do arquivo segue convenção com separador `-` (ex.:
`001-SAA-0043-9597-PBES-DE-05ETAACFLUOSSILICICO-R0`): parsear por regex e validar o
parser contra **todos** os nomes do acervo antes de rodar (no acervo real: 488/488).

## Roteiro determinístico com prestação de contas

1. **Inventário primeiro** (`inventario.py`): loop sobre todos os PDFs (rglob
   recursivo — acervo vem em pastas por unidade) → `mestre_arquivos.csv` com ordem,
   código, unidade (nome da pasta), status. Isso fixa a **META = N arquivos**.
2. **Validar em amostra estratificada** (~30 arquivos, cobrindo todas as pastas)
   ANTES do lote completo. Medir cobertura de localização e divergências.
3. **Lote paralelo** (`multiprocessing.Pool`, ~8 processos, ~20 s/arquivo): cada PDF
   em try/except — um arquivo ruim NÃO aborta o lote, vira `status=erro`.
4. Ao final, prestar contas: `CONCLUÍDO: N/N (X% da lista inventariada)` listando as
   falhas. PDF com 0 páginas = corrompido na origem (aconteceu: 1,4 MB e 0 páginas).

## Conferência automática + reparo por DPI

Toda tabela extraída é conferida contra os **totais impressos na própria prancha**:

- aço: o melhor teste é **físico** — `peso_kg ≈ comprimento_m × massa linear da bitola`
  (NBR 7480: φ5→0.154, φ6.3→0.245, φ8→0.395, φ10→0.617, φ12.5→0.963, φ16→1.578,
  φ20→2.466, φ25→3.853 kg/m), pois valida comprimento e peso **juntos**; somar também
  os pesos por classe contra o "Peso Total <classe>" impresso;
- materiais: soma dos elementos = linha TOTAL (volume e área);
- armadura: `comprimento_total ≈ quantidade × comprimento_unit` (tolerância; pular `--VAR--`).

Se a conferência acusar → **re-extrair a 650 DPI**. Isso separa duas causas:
- **erro de OCR** → some com mais resolução (21 arquivos auto-reparados no acervo);
- **inconsistência do próprio desenho** → persiste idêntica → manter a leitura fiel e
  sinalizar em `divergencias.csv` (achamos pranchas com TOTAL impresso errado em 200 m²
  — o relatório vira auditoria dos projetos, valor para o cliente).

## Materialização (CSV é a fonte, Excel é apresentação)

- `saidas/csv/<codigo_arquivo>/` — detalhe por projeto (resumo_aco, resumo_materiais,
  tabela_armadura), toda linha com `codigo_arquivo`.
- `saidas/consolidado/` — detalhe empilhado do acervo.
- `saidas/mestre_quantitativos.csv` — **entregável**: 1 linha por prancha com
  identificação (nome + carimbo), concreto/formas (TOTAL, enchimento, lastro), aço
  total/por classe/**por bitola em colunas fixas** (φ 5.0–25.0, NBR 7480),
  comprimento de armadura, contadores e `divergencias`/`reparos_ocr`.
- **Mockup primeiro**: preencher o schema com a amostra real + 1 linha ilustrativa e
  validar as colunas com o Caio ANTES de rodar o lote.
- Excel via `etl/exportar.py`: um `.xlsx` por pasta em `saidas/excel/<nome>/`,
  cabeçalho congelado + negrito + filtro automático + largura ajustada.

## Armadilhas conhecidas (todas aconteceram)

| Armadilha | Correção |
|---|---|
| `read_csv` sem dtype come zero à esquerda (`08.10`→`8.1`, `001`→`1`) | `dtype=str` para `item_mos`, `folha`, `codigo_arquivo` em TODA releitura |
| OCR devolve dígito de largura total (`5０A`) | `unicodedata.normalize("NFKC", txt)` em todo token |
| Título cortado no limite do ladrilho | ladrilhos com sobreposição de 15% + dedupe |
| Caixa da tabela engolindo vizinhos | menor retângulo que contém o título + altura máxima |
| Ruído do desenho ao lado entra no OCR da tabela | isolar caixa pela grade antes de aceitar tokens; extrator exige cabeçalho |
| Âncora de coluna capturada no lugar errado (título "RESUMO AÇO" contém "AÇO"; "CONCRETO" reaparece em "LASTRO DE CONCRETO SIMPLES") | descartar as linhas até o título e usar a ocorrência **mais ao topo** de cada rótulo |
| Tabela presente porém **vazia** (quantidades distribuídas entre as folhas da edificação) | `None` é resposta correta, não erro — não forçar reprocessamento |
| Decimal misto pt-BR (bitola `6.3` com ponto; volume `17,32` com vírgula) | locale **por coluna** definido em `dados/config_tabelas.json` |
| Mais de uma tabela do mesmo tipo na prancha | localizar TODAS as ocorrências e concatenar |
| Mais de um TOTAL na tabela de materiais (bloco ESTACAS) | usar o **último** TOTAL (fecha com a soma) |
| Duplicação de totais entre pranchas da mesma obra | verificar estrutura: materiais só vem preenchida numa folha-resumo por obra |
| `timeout` não existe no zsh do Mac | rodadas longas com `run_in_background`, não timeout |

## Casca de aplicativo (opcional)

Para uso sem terminal, o projeto de referência tem `app/servidor.py` + `app/interface.html`:
servidor stdlib (`http.server`) preso em 127.0.0.1, processamento em thread com
`pipeline.executar(pasta, ao_progredir)` (motor único, sem duplicar lógica), polling em
`/progresso`, seletor nativo de pasta via `osascript` e atalho de duplo clique
(`Processar PDFs.command`). HTML+JS **não substitui** o Python: navegador não roda OCR
nem varre disco — a página é só o painel de controle do pipeline local. Cuidado ao
testar: o pipeline grava em `saidas/` — fazer backup antes de rodar com pasta de teste.
Distribuição p/ máquinas sem Python: PyInstaller (build por SO, ~300-500 MB).

## Sequência resumida para acervo novo

1. Diagnóstico da amostra (Fase 0) → gabarito a olho.
2. Extração das tabelas da amostra → bater 100% com o gabarito.
3. Parser do nome + carimbo → validar contra todos os nomes do acervo.
4. Mockup do CSV mestre → validar colunas com o Caio.
5. Inventário (META) → amostra estratificada (~30) → ajustar → lote completo paralelo.
6. Conferência + divergencias.csv → exportar Excel → reportar N/N com totais.
