# Conferência dos materiais pelo cadastro da Sanepar — a segunda camada, só código

Pedido do Caio (09/10/2026): "a IA continua extraindo as tabelas, mas a gente tem essa segunda camada de código que
valida os materiais da Sanepar. A mesma sequência de estoque deve trazer o mesmo produto; pode ter variação de nome
(uma curva que poderia se chamar joelho), então um dicionário de sinônimos e de unidades (metro, M; peça, PÇ, PC,
peca). Nem tudo precisa estar no cadastro (serviços, formas, concreto, material novo): não é regra, é uma boa
indicação de que a extração foi feita de forma correta."

Estado: **plano em espera** (stand-by por pedido do Caio em 09/10; nada implementado). **Atualização 09/10 (0v36):** a primeira parte entrou por outro caminho — `codigo/catalogo.py` confere cada linha das tabelas no catálogo único do ialocal.orcamento (Sanepar + SINAPI + SICRO + Sienge), pelo código e, sem ele, pela descrição normalizada (sinônimos, unidades, etiquetas DN/PN/DE/material/junta), com `conferencia.csv` no pedido; testado com o catálogo real em Foz e Cambé (versoes.jsonl 0v36). Continuam deste plano: a equivalência DE ↔ polegada (§2.2) e o sinônimo por família (curva ↔ joelho, §2.3). As medidas abaixo são do arquivo entregue e de um protótipo rodado na nuvem
com as linhas reais da tabela da Giselle (pedido 20261008-154155-874c26, o print de 08/10).

## 1. O arquivo

`sanepar_materiais_2026-08-21.parquet` (2,7 MB): **40.371 itens**, 15 colunas.

| coluna | o que é | observação |
|---|---|---|
| `seq` | a sequência de estoque (o "COD SAM" / "ESPECIF" das relações de materiais) | **única**, inteira (19 a 343.531), sem nulo; vem como Float64 → ler como Int64 |
| `desc` | a descrição oficial, em maiúsculas | ex.: `JOELHO CPVC JS BB 90 SCH80 ASTM F439 NSF/ANSI STD14/61 FDA 21 POL 1”` |
| `un` | a unidade | 26 códigos: UN 32.130, CJ 4.584, M 2.126, KG 317, FR, CX, PT, PA, L, JG, M2, G, AP, M3, ML, BR, RL, BD, GL, LA, BL, MI, BB, RM, TA, T |
| `familia` | a família já classificada | tubo 4.880, te 1.754, curva 1.629, joelho 210, cotovelo 181, cap 195… |
| `categoria`, `subcategoria` | o grupo | tubulacao_conexoes 14.426, eletrica_automacao 4.957, valvulas_registros 3.405… |
| `material` | o material, quando classificado | ferro_fundido_ductil… (nulo no CPVC) |
| `dn`, `pol`, `pn`, `classe` | diâmetro nominal (mm), polegada, pressão, classe | dn em 10.518, pol em 7.362, pn em 11.053 itens |
| `norma` | a norma | NBR 7675, EB/… |
| `situacao` | a situação no cadastro | 6 - Para Obra 19.558, 3 - Licitável 13.025, 1 - Licitável 7.775, 2 - SCD 12, 4 - Despadronizado 1 |
| `busca`, `registro` | a descrição normalizada e o registro inteiro em JSON (com as `marcas`) | o `registro` traz campos que as colunas não trazem |

Busca por `seq`: um dicionário `seq → linha` montado em **0,03 s**; cada consulta é O(1). Polars basta (já está no
`.venv` do mini); NumPy não é preciso.

O maestro já casa licitações com um catálogo mais simples (`dados/sanepar/catalogo.csv`, `seq_estoque;descricao`,
`ialocal.maestro/codigo/sanepar.py`). O parquet é o mesmo cadastro, mais rico; os dois devem ler **o mesmo arquivo**
(§7).

## 2. O que o protótipo mostrou (a tabela da Giselle)

| linha | código | o projeto diz | o cadastro diz | família | un | diâmetro | veredito |
|---|---|---|---|---|---|---|---|
| 40 | 300491 | CURVA CPVC JS BB 90 … DE 32 · PÇ | JOELHO CPVC JS BB 90 SCH80 … POL 1” · UN | curva≈joelho | PÇ=UN | DE 32 = 1" | confere (sinônimo) |
| 41 | 300498 | CURVA … BB 45 … DE 32 · PÇ | JOELHO … BB 45 … POL 1” · UN | ✔ | ✔ | ✔ | confere (sinônimo) |
| 42 | 300386 | TUBO CPVC SCH80 SOLDAVEL … DE 32 · m | TUBO CPVC JS PP SCH80 … POL 1” · M | ✔ | ✔ | ✔ | confere (o texto só 43% igual) |
| 43 | 300456 | CAP CPVC JS SCHEDULE 80 … DE 32 · PÇ | CAP CPVC JS BOLSA SCH80 … POL 1” · UN | ✔ | ✔ | ✔ | confere |
| 44/52 | 300536 | TE CPVC JS BBB … DE 32 · PÇ | TE CPVC JS BBB SCH80 … POL 1” · UN | ✔ | ✔ | ✔ | confere |
| 53 | 300583 | VALVULA ESFERA DUPLA UNIAO CPVC … DE 32 · PÇ | VALVULA ESFERA DUPLA UNIAO CPVC … | ✔ | ✔ | ✔ | confere |
| S/N | 302026 | PECA ESPECIAL EM ACO INOX AISI 316 · CJ / Kg | — | | | | **não cadastrado** (peça especial: esperado) |
| *55, *56 | VER ESPECI. | ADAPTADOR … / APLICADOR DE CLORO | — | | | | **sem código** (a especificação técnica) |
| teste | 300491 | TUBO PEAD PE100 DE 110 · m | JOELHO CPVC … 1” | ✘ | ✘ | 4" ≠ 1" | **diverge** (o código ou a descrição foram lidos errados) |

Três conclusões:

1. **Família, unidade e diâmetro decidem**; a semelhança do texto sozinha engana (o tubo da linha 42 confere e tem só
   17% de Jaccard, porque o projeto escreve "SOLDAVEL P/ TUBULACAO DE32MM" e o cadastro "JS PP 43KGF/CM2 … 6,00M").
2. O diâmetro precisa de **equivalência**: o projeto escreve o DE em mm (DE 32), o cadastro a polegada (POL 1") ou o
   DN. É uma tabela por material (PVC/CPVC soldável: DE 20 = 1/2", 25 = 3/4", 32 = 1", 40 = 1.1/4", 50 = 1.1/2",
   60 = 2", 75 = 2.1/2", 85 = 3", 110 = 4"; PEAD: DE em mm; FD: DN).
3. O sinônimo vale **por família**, não por palavra solta: CURVA ↔ JOELHO ↔ COTOVELO só nas conexões de pequeno
   diâmetro (no FD, "curva" é família própria com 1.629 itens). Por isso o dicionário compara família com família.

## 3. Onde entra

No **ialocal.projeto**, como tarefa de **código** depois da leitura das tabelas, sem GPU:

```
ler_prancha (código) → ler_prancha_ia (glm-ocr × Vision: as tabelas) → conferir_materiais (código, cadastro Sanepar)
```

- Uma tarefa nova no ciclo (`conferir_materiais`, família `prancha_material`), que roda sempre que a
  `prancha_tabela` do documento muda — e também no pedido por e-mail, logo depois da IA.
- Não muda o que a IA extraiu: acrescenta, linha a linha, o que o cadastro diz e o veredito.
- É a **testemunha de natureza diferente** que o princípio pede ("número só é fato com leitor + testemunha"): a linha
  da tabela que confere no cadastro (código + família + diâmetro + unidade) passa a ter uma testemunha que não é OCR.
- O revisor (ialocal.revisor) pode ler a `prancha_material` depois, mas a regra mora aqui, perto da extração, porque
  é ela que diz se a tabela foi bem lida.

## 4. As regras (conceitos/materiais.json)

Tudo declarado, com `fonte` e data, editável por PR:

```json
{
  "cadastro": {"arquivo": "sanepar_materiais_2026-08-21.parquet", "sha256": "…", "drive": "gdrive:saida/web/sanepar/"},
  "unidades": {"UN": ["UN", "UND", "UNID", "PC", "PÇ", "PCS", "PECA", "PEÇA", "PECAS"], "M": ["M", "MT", "METRO", "METROS"],
               "KG": ["KG", "KGS", "QUILO"], "CJ": ["CJ", "CONJ", "CONJUNTO"], "M2": ["M2", "M²"], "M3": ["M3", "M³"], "L": ["L", "LT", "LITRO"]},
  "sinonimos_familia": {"joelho": ["curva", "cotovelo"], "te": ["t", "tee"], "luva": ["manga"], "reducao": ["bucha_reducao"]},
  "sinonimos_termo": {"SCH80": ["SCHEDULE 80", "SCH 80"], "STD14/61": ["STD 14&61", "STD 14/61"], "JS": ["SOLDAVEL", "JUNTA SOLDAVEL"]},
  "diametro": {"pvc_cpvc_soldavel": {"20": "1/2", "25": "3/4", "32": "1", "40": "1.1/4", "50": "1.1/2", "60": "2", "75": "2.1/2", "85": "3", "110": "4"}},
  "sem_codigo": ["S/N", "VER ESPECI", "VER ESPEC", "-", "—"],
  "limiares": {"texto_minimo": 0.30}
}
```

As unidades com variação de grafia (PÇ, PC, peca) normalizam **antes** de comparar; uma unidade que não está em
nenhuma lista fica como está e conta como "unidade desconhecida", não como erro.

## 5. O algoritmo (codigo/materiais.py — funções puras, com teste)

1. **Achar as colunas** da linha extraída: o código (`^\d{5,6}$` na coluna ESPECIF/COD SAM, ou a 2ª coluna), a
   descrição (a célula mais longa), a quantidade e a unidade (as duas últimas). A linha de título de seção
   ("APLICAÇÃO DE CLORO") e o cabeçalho ficam de fora.
2. **Buscar** o código no cadastro (dicionário `seq → item`).
3. **Comparar**, cada um com o seu resultado:
   - família: a primeira palavra da descrição, pelo sinônimo de família, contra `familia` do cadastro;
   - material: CPVC/PVC/PEAD/FD/AÇO/INOX na descrição contra `material` e a descrição;
   - diâmetro: DE/DN/POL da descrição, pela equivalência do material, contra `dn`/`pol` do cadastro;
   - ângulo (90/45/22/11), tipo de junta (JS, JE, JGS, flange), PN/SCH quando os dois dizem;
   - unidade normalizada contra `un`;
   - texto: a cobertura das palavras do projeto pelas do cadastro (depois dos sinônimos), só como desempate.
4. **Veredito** por linha:

| veredito | quando | o que diz para a extração |
|---|---|---|
| `confere` | família, diâmetro e unidade batem | a linha está bem lida (testemunha) |
| `confere_sinonimo` | bate com sinônimo (curva → joelho) | idem, com o sinônimo anotado |
| `confere_parcial` | família bate, um detalhe não (ângulo, PN, unidade) | conferir o detalhe (amarelo) |
| `diverge` | família ou diâmetro não batem | o código ou a descrição foram lidos errado (vermelho) |
| `nao_cadastrado` | o código não existe no cadastro | peça especial ou código lido errado (§5.5) |
| `sem_codigo` | S/N, VER ESPECI., vazio | serviço, peça especial ou especificação: fora da conferência |

5. **Código lido errado** (fase 3): quando `diverge` ou `nao_cadastrado`, procura no cadastro os itens da mesma família
   e diâmetro cuja descrição cobre a do projeto e cujo código está a **um dígito** do lido (300419 ↔ 300491) ou a
   uma troca de dígitos vizinhos: a sugestão vai na linha (`codigo_sugerido`), nunca no lugar do lido.
6. A quantidade **não** é conferida pelo cadastro (ele não sabe quanto a obra usa); a soma dos tubos com o eixo é a
   conferência dela (já existe: `prancha.conferir`).

## 6. As saídas

- `prancha_material` (Parquet e `prancha_materiais.csv` no Drive): uma linha por linha de tabela, com o código lido,
  o item do cadastro (desc, un, família, dn/pol, situação), cada comparação e o veredito.
- **XLSX do pedido**: aba "Materiais Sanepar" (código, descrição lida, descrição do cadastro, un lida × un do
  cadastro, veredito em cor) e, na aba Tabelas, a coluna "Cadastro Sanepar".
- **resultado.txt / resposta**: uma linha — "Materiais: 6 de 7 com código conferem no cadastro da Sanepar (2 por
  sinônimo: curva → joelho); 1 não cadastrado (302026, peça especial); 2 sem código (VER ESPECI.)".
- **Lições**: `diverge` vira lição `leitura_errada` com o destino "a leitura da tabela" (o código ou a descrição),
  e a fração que confere entra no placar por prancha — a medida de que a extração das tabelas melhora.

## 7. O arquivo do cadastro

- Mora no Drive, numa pasta de referências (sugestão: `gdrive:saida/web/sanepar/`, ao lado do `catalogo.csv` que o
  maestro já lê), com a data no nome; o mini baixa por `rclone` para `~/dados/ialocal.projeto/referencias/` e confere
  o `sha256` declarado em `conceitos/materiais.json`. Não vai ao git (2,7 MB que mudam a cada atualização).
- Trocar o cadastro é um PR que muda o nome e o sha: a `prancha_material` refaz sozinha (a versão entra em `muda`).
- O maestro pode passar a gerar o `catalogo.csv` deste parquet (ou ler o parquet direto): um cadastro só.

## 8. Fases (um PR cada)

| fase | o que | prova |
|---|---|---|
| F1 | `codigo/materiais.py` (carregar, normalizar unidade, sinônimo, diâmetro, comparar, veredito) + `conceitos/materiais.json` | testes com as linhas reais da Giselle (fixture com os 7 itens do cadastro, não o arquivo inteiro): os vereditos da tabela do §2 |
| F2 | a tarefa `conferir_materiais` no ciclo e no pedido; a aba no XLSX; a linha no texto | o pedido da Giselle rodado de novo mostra os vereditos |
| F3 | a sugestão de código (um dígito) e a busca por descrição para a linha sem código | caso de teste com o código trocado |
| F4 | as lições, o placar por prancha, o cadastro único com o maestro | o laudo seguinte com a fração que confere |

## 9. A decidir

1. **Onde fica o parquet** no Drive (a sugestão é `saida/web/sanepar/`) e de quanto em quanto tempo ele é atualizado.
2. Se a linha que `confere` deve **subir o status** da linha da tabela (de `pendente` para `confirmada`) — o plano
   propõe que sim quando código, família, diâmetro e unidade batem, porque é uma testemunha que não é OCR.
3. Se a `situacao` "4 - Despadronizado" ou fora de "Para Obra/Licitável" deve virar um aviso ao orçamentista.
