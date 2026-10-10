# Protótipo: tabela de material pela grade (09/10/2026)

Medida do plano `notas/plano_tabelas_deterministicas.md`. **Não é código de produção**: usa PyMuPDF (AGPL, vetado na
rota pela D2 do `plano_projeto.md`) para ler o PDF; a produção troca por pypdfium2 + pdfplumber (P1/P5 do plano).

| arquivo | o que faz |
|---|---|
| `grade_vetor.py` | acha a malha vetorial da tabela (horizontais de mesma extensão empilhadas + verticais dentro) |
| `tabela_raster.py` | o leitor: tinta sem cor, grade por morfologia, Tesseract na tabela inteira, PP-OCR (RapidOCR) por coluna curta, decisão entre os dois, papel da coluna, regras (decimal, empilhar, unidade) |
| `vocabulario.py` | PN/DN por vocabulário fechado: só troca se a confusão leva a um único valor da série |
| `rodar.py` | o laço: cada PDF → tabelas (imagem colada ou malha vetorial) → `tabelas.json`, `itens.csv`, recortes |
| `variante.py` | roda o leitor nos recortes com uma largura máxima (simula o thumbnail da produção) |
| `placar.py` | extração × gabarito, linha a linha e campo a campo |

```bash
pip install pymupdf opencv-python-headless rapidocr_onnxruntime   # e o tesseract com o idioma por
python3 notas/prototipo_tabela/rodar.py <pasta_dos_pdfs> <saida>
python3 notas/prototipo_tabela/placar.py <pasta_csv_por_tabela> <pasta_gabaritos> [placar.json]
```

O gabarito (661 linhas) está no `ialocal.dados`, `orcamentos/211_saa_foz_do_iguacu/referencia/claude_opus/tabelas_pbhi/`.
