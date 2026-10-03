# Viabilidade — extrair tudo de uma planta e perfil de adutora (26/09/2026)

**Pergunta do Caio.** Com código por fora, dá para extrair de verdade o que a planta tem: a
adutora, as estacas, a elevação e o que está no perfil, as quadras, as ruas, o entorno, as peças
(ventosa, descarga) com a planilha delas e as interferências?

**Como.** Protótipo fora do pipeline (`notas/prototipo_prancha/`, não roda no mini) sobre as
folhas 010, 011, 012 e 013 da AAT-06 de Foz do Iguaçu e o detalhe 018. Os gabaritos são os
testes de mesa (`teste_prancha_2026-09-26.md`, `teste_jogo_foz_2026-09-26.md`). A conferência
externa foi feita contra o OpenStreetMap (vias da região, Overpass).

## A descoberta que torna viável

O PDF do AutoCAD guarda o desenho **em blocos marcados por camada**: 210 blocos `/OC … BDC/EMC`,
sem aninhamento, em 45 camadas. Um separador de 60 linhas (`camadas.py`) gera um PDF por camada.
A 012 se separa assim:

| tema | camada(s) | o que sai |
|---|---|---|
| adutora na planta | faixa roxa (`_PERFIL_`) | eixo, vértices, deflexões |
| estacas | `C-ROAD-SAMP` (marcas) e `_TXT-PERFIL_` (rótulos) | 28 marcas sobre o eixo |
| quadras e lotes | `549_QUADRAS`, `733_LOTES` (7.188 objetos) | polígonos do cadastro urbano |
| nomes de ruas | `641_TOP_VIAS` | Rua Guarujá, Barra Velha, Brusque, Av. Gramado… (texto em curva) |
| bairros | `180 - TOP NÍVEL 179-textos`, `547_BAIRROS_TOPS` | Jardim Lancaster V, Jardim Aurora |
| hidrografia, edificações, pontos de apoio | `560_…`, `703_…`, `520_…` | no quadro de situação |
| peças | `DESCARGA`, `TXT_RD_PVC` (C22°, C45°, "continua no desenho") | posição e rótulo |
| malha | `MALHA` | rótulos E= e N= a cada 100 m |
| perfil | terreno em azul, tubo em roxo, `Grade_perfil` | cotas por estaca |

Houve um erro no primeiro corte: o recorte (*clip*) da janela de vista era descartado junto com a
camada, e o desenho saía em branco. Recorte agora vale para todas as camadas.

## O que foi medido

| item | resultado | natureza |
|---|---|---|
| eixo da adutora | 540,02 · 540,01 · 540,02 · 519,99 m nas 4 folhas (relação: 540, 540, 540, 520) | código puro |
| estacas | 28 marcas projetadas no eixo a **exatamente 20,0 m** (0 a 540 m) | código puro |
| perfil × quadro | terreno em 27 estacas e geratriz em 8 vértices: **diferença ≤ 3 mm**, depois de corrigir a âncora da escala vertical | código + 1 rótulo lido (a cota de uma linha da grade) |
| emenda entre folhas | fim da 010 × início da 011: **0,05 m**; fim da 011 × início da 012: **0,02 m** | código + 2 rótulos lidos por folha (E= e N=) |
| georreferência absoluta | as vias mais próximas do eixo têm **os mesmos nomes do desenho** (Sasdelli, Guarujá, Barra Velha, Brusque, Gramado), mas com desvio sistemático: o melhor encaixe é **+61 m E, −20 m N** (mediana 21 → 1,2 m), e ainda sobram 30 m no percentil 90, no trecho da 012 | não resolvida |
| peças × detalhe | descarga 1 (010, EST 43) e 2 (012, EST 90) e ventosa 2 (011, EST 66) ligam ao detalhe 018 pela cota | código + OCR |
| planilha da ventosa e da descarga (018) | **imagem colada** (2577 × 3801 px, ~400 DPI), sem texto real | OCR obrigatório |
| interferências | **nenhuma desenhada** nas 4 plantas nem nos perfis. A camada `600_PVCDEFoFo_DN0300` (nome de rede existente) é a continuação da própria adutora: cai a 0,11 m do eixo da folha vizinha | — |

## Veredito por item

| o que o Caio quer | viável? | com o quê | o que falta |
|---|---|---|---|
| adutora (traçado, extensão, deflexões) | **sim** | código | mapa de camadas e cores por projetista |
| estacas | **sim** | código; número da estaca por sequência + OCR de 1 ou 2 rótulos | — |
| elevação: terreno, geratriz, profundidade, declividade | **sim**, ao milímetro | geometria do perfil + 1 rótulo da escala; o quadro impresso confere | o erro de âncora (1,000 m constante) só aparece porque se confere com o quadro: a conferência é obrigatória |
| quadras, lotes, vias, bairros, hidrografia | **sim** a geometria | código | **nomes** são texto em curva: OCR em recorte por camada (a camada isolada dá recorte limpo, só com os nomes) |
| peças: ventosa, descarga, curvas | **sim** a posição e o tipo; o **número** não é confiável (descarga 2 × 3 na 012) | camada + cota do perfil + detalhe | ligar pela cota, não pelo número |
| planilha de materiais da peça | **sim**, por OCR | imagem de ~400 DPI, tabela limpa | leitura pelos modelos locais: não testada |
| georreferência relativa (entre folhas) | **sim**, ao centímetro | malha + 2 rótulos por folha | folha girada (013): ajuste com rotação, não testado |
| georreferência absoluta (no mundo) | **não sem controle** | — | datum não declarado; desvio de ~64 m que nenhum datum padrão explica (SAD 69: −54,5/−41,5; Córrego Alegre: −81,4/−3,4) e forma divergente do OSM na 012. Precisa de **ponto de controle**: GPS de campo, foto com EXIF na obra, marco, ou a base cadastral da Sanepar com datum conhecido |
| interferências | **não deste projeto** | — | o projeto não as desenha. Cadastro de interferências vem de outra fonte (concessionárias de gás, telefonia, drenagem, esgoto; sondagem; *as built*; fotos da vala). O sistema recebe como camada própria, com origem |

## Consequências para o plano

1. **Camada é o primeiro separador, não a verdade.** O nome engana (`600_PVCDEFoFo_DN0300` é a
   adutora), então vale camada + cor + espessura + geometria + conferência. O mapa camada → tema é
   dado por projetista, em JSON (`conceitos/prancha.json`), revisado pelo Caio, com a mesma regra
   dos padrões de menção: exemplos que casam e que não casam.
2. **Geometria primeiro, texto para conferir.** Eixo, estacas e perfil saem do vetor com precisão de
   milímetro; o quadro impresso e a relação servem para **conferir**, e é aí que aparecem os erros de
   projeto (44 × 46 m) e os erros do extrator (âncora de 1 m).
3. **IA só onde o texto virou desenho ou imagem**: nomes de rua e de bairro, rótulos da malha e da
   escala, planilhas coladas como imagem, carimbo. Sempre em recorte da **camada isolada**, que é
   limpo, e com um valor que o código confere (sequência de estacas, espaçamento da malha, soma da planilha).
4. **Georreferência absoluta é uma etapa com ponto de controle**, não um cálculo. Sem controle, a
   feição fica com `coordenada_relativa` e `georreferencia: nao_verificada` (MASTER-PLAN §10.4,
   regra 1: precisão é medida, não declarada).
5. **Interferência é outra fonte.** A extração de projeto registra "nenhuma interferência desenhada"
   como fato da prancha, e a camada de interferências nasce vazia, à espera do cadastro.
6. **Custo**: separar 45 camadas levou ~60 s por folha (uma leitura do pdfplumber por camada).
   Uma única passada que já classifica cada objeto na camada dele deve cair para poucos segundos. Premissa, a medir.

## O que continua sem teste

- Os modelos locais (gemma3, glm-ocr, Vision, Apple FM) lendo nomes de rua, rótulos da malha e as
  planilhas da 018 a partir das camadas isoladas: é o próximo teste, no mini.
- Outro projetista (camadas e cores diferentes) e prancha de estrutura.
- Folha girada (013) e planta escaneada real.
