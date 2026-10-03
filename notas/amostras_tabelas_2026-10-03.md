# Amostras de tabelas de Foz e Cambé — o que são e o que pedem (03/10/2026)

O Caio pôs em `amostras/tabelas/` recortes das tabelas de materiais de dois orçamentos que ele extraiu à mão: Foz do
Iguaçu (`211_foz`) e Cambé (`216_cambe`). São **imagens** (PNG), não os PDFs. Esta nota diz o que há nelas, o que o
gabarito de Cambé vale e o que o leitor de tabela do projeto precisa para lê-las.

## O que há

| | Cambé | Foz |
|---|---|---|
| imagens | 17 (tabelas 01 a 22; algumas imagens têm 2 ou 3 tabelas) | 78 (tabelas 01 a 126, com partes 10.1, 19 1/2, 122.1…) |
| gabarito | **sim**: o TXT com 17 blocos, 190 linhas, `CÓDIGO;Nº;DISCRIMINAÇÃO;QUANT.;UND.;TÍTULO` | não |
| layout | um só: código, Nº, discriminação, quantidade, unidade; a linha de seção ("REDE DE DISTRIBUIÇÃO") é o título | quatro, abaixo |
| qualidade da imagem | nítida, texto real renderizado | de nítida (CAD) a borrada (imagem colada no PDF) |

**Os quatro layouts de Foz**, vistos em amostra (tabelas 01–03, 19, 60–63, 95, 108, 122.1):

1. **Relação de materiais da ETA (planilha colada):** `Nº | ESPECIF/COD SAM | DESCRIÇÃO | 1ª ETAPA | 2ª ETAPA | UN`, com
   título e subtítulo de seção ("SAÍDA DE ÁGUA FILTRADA"). Duas quantidades na mesma linha (02 pç **e** 31,57 kg,
   separadas por tracejado), marcadores `*` e `**` com nota de rodapé ("* VER ESPECIFICAÇÃO TÉCNICA"), código `-` ou
   `S/N`, valor riscado e corrigido à mão ("0 - 00" riscado, 01 ao lado), linha que quebra em duas.
2. **Tabela do CAD (AAT):** `CÓDIGO | QT | ITEM | DESCRIÇÃO | UN.` — a mesma informação **em outra ordem**, quantidade
   antes da descrição; título "AAT - PARTE 05".
3. **Lista de equipamentos:** `Nº | CÓD. | DESCRIÇÃO | QTDE | UN`, com especificação em várias linhas dentro da célula
   (pressão, material, "Fab.: FESTO - MS9"), sem código Sanepar, unidade CJ.
4. **Imagem de baixa resolução** (tabela 19): a mesma relação da ETA, mas borrada e com o Nº destacado em roxo — é o
   caso da relação de materiais colada como imagem da AAT-06 (`teste_prancha_2026-09-26.md`).

A tabela 95 é a da folha 012 da AAT-06 (tubo PE 100 DE 630, **540,00 m**): a mesma que o teste de mesa mediu em 538 m
no desenho. Ela liga esta amostra à conferência eixo × relação que o projeto já faz.

Unidades que aparecem: `m`, `M`, `pç`, `PÇ`, `UN`, `UN.`, `cj`, `CJ`, `kg`, `kg/m`, `BARRAS`. Quantidade com e sem
separador de milhar no mesmo projeto (Cambé: `7.113,99` na tabela 03 e `10221,25` na 12).

## O gabarito de Cambé, conferido contra as imagens

Conferido linha a linha nas tabelas 02, 03, 12 e 16–17. Ele é bom e modela bem a tabela (a linha de seção vira a coluna
TÍTULO). Três pontos:

| onde | gabarito | imagem | o que é |
|---|---|---|---|
| tabela 03, luva de transição DE 63 | `31041` | `310410` | **erro de digitação do gabarito** — o código 310410 aparece em 9 outras tabelas |
| tabela 03 e 12, luva PE DE 63 | `ELETROFUSAO` | `ELTROFUSAO` | **o gabarito corrigiu a grafia.** A regra da extração é copiar como está impresso (`_regras.txt`, regra 3); a grafia corrigida vai numa coluna à parte, senão o leitor que acerta é contado como erro |
| 5 tabelas, tubo 298738 | ora `PN 10`, ora `PN 15` | igual ao gabarito | fiel: é achado do projeto, abaixo |

O mesmo código aparece com grafias diferentes (`DN50`/`DN 50`, `PN16`/`PN 16`, `DE75`/`DN75`). Nas imagens conferidas
(03, 12, 16–17) as variações estão impressas assim, e o gabarito as copiou; as outras não foram conferidas. Comparar
descrição pede normalizar o espaço antes.

## Achados de projeto (o que a prancha diz e não fecha)

São perguntas ao projetista, não erros de leitura; entram no `divergencias.csv` quando a bancada existir (plano §6).

1. **Código 298738 com duas classes de pressão:** "TUBO PE 100 **PN 10** (ROLO 50 M) DE 63" na rede e "PN **15**" nas
   descargas (tabelas 02, 04–06, 08, 10–11, 13–14). PN 15 não é classe comercial de PE 100 (PN 6, 8, 10, 12,5, 16, 20).
2. **"PE 10"** na tabela 17 (luva de transição DE 90, código 310411): nas outras é "PE 100".
3. **Linha repetida** na tabela 12: luva de correr DN 100 (275549), 9 un., duas vezes — somar dá 18.
4. **Cap PVC PBA DN 60 sem código** (tabelas 12 e 21): o PBA da NBR 5647 é DN 50, 75 e 100 — o DN 50 tem diâmetro
   externo 60 mm, então "DN 60" é provavelmente o DE 60 (DN 50). Conferir com o projetista.

## O que o leitor de tabela do projeto precisa para isto

Hoje (0v1) a tabela sai célula a célula (`c1…cn`), achada pelo cabeçalho, só da **grade vetorial**. Para estas
amostras faltam:

1. **Mapa de colunas por sinônimo** (`conceitos/prancha.json`): código = `CÓDIGO`, `COD SAM`, `ESPECIF/COD SAM`, `CÓD.`;
   item = `Nº`, `ITEM`; descrição = `DISCRIMINAÇÃO`, `DESCRIÇÃO`; quantidade = `QUANT.`, `QTDE`, `QT`, `1ª ETAPA`,
   `2ª ETAPA` (a etapa vira atributo); unidade = `UND.`, `UN`, `UN.`. Sem isso, a ordem diferente do layout 2 não se
   compara com o 1.
2. **Linha de seção vira título** das linhas de baixo (como o gabarito faz).
3. **Duas quantidades numa linha** (pç e kg) viram duas linhas com unidades diferentes — nunca somadas (regra 15).
4. **Marcador e nota de rodapé:** `*07` é o item 07 com a nota `*`; a nota vai como atributo.
5. **Unidade em SI** com a tabela de grafias do extrator (`unidades.json`): `pç`/`PÇ`/`UN.` são contagem, mas `cj` e
   `BARRAS` são espécies diferentes (não se somam).
6. **Imagem:** estas amostras só passam pela rota de OCR (glm-ocr em modo tabela × Vision, `ocr.ler_tabela`), que não
   roda fora do mini. A rota vetorial precisa dos **PDFs de origem**.

## Próximos passos (itens 13–16 do plano)

13. Bancada de tabelas com o gabarito de Cambé (190 linhas), no mini: OCR das 17 imagens, comparação por campo.
14. Mapa de colunas, seção, quantidade dupla, marcador e unidade em SI no leitor de tabela, com teste.
15. Gabarito de Foz: transcrição de uma imagem de cada layout (4), do mesmo jeito que a de Cambé.
16. Os PDFs de onde estas tabelas saíram, para medir a rota vetorial contra o mesmo gabarito.
