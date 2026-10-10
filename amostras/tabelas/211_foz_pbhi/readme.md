# ETA Vila C (211 Foz do Iguaçu, projeto hidráulico PBHI) — gabarito das tabelas de material

- `gabarito.csv`: 661 linhas de 41 tabelas em 27 pranchas, lidas na imagem por Claude em 09/10/2026 (referência de IA:
  o Caio confere uma amostra). Colunas: tabela_id; arquivo; pagina; linha; secao; item; codigo; descricao; quantidade;
  etapa1; etapa2; unidade; obs. A origem e as decisões: `ialocal.dados`, `orcamentos/211_saa_foz_do_iguacu/referencia/claude_opus/tabelas_pbhi/`.
- `medidas.jsonl`: cada medida de leitura de tabela — no mini (ensaios e rodadas) e fora dele (protótipo, código) —
  com data, onde, versão, linhas certas e segundos. Uma linha nova a cada teste; é ela que diz se subiu.
- Os PDFs ficam no Drive (`211 - SAA Foz do Iguaçu/01. RECEBIDOS/LC2112026EDITAL_ELEMENTOS/UNIDADE 01/ANEXO C/1. PBHI`), não aqui.

    .venv/bin/python codigo/placar_tabelas.py pasta <pasta_com_os_pdfs>     # o código de agora contra o gabarito
    .venv/bin/python codigo/placar_tabelas.py ensaio foz_pbhi               # o que o ensaio do mini gravou
