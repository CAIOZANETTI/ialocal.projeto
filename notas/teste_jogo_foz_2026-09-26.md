# Teste de mesa — o jogo da AAT-06 de Foz do Iguaçu (26/09/2026)

**Pergunta.** As premissas do `plano_projeto.md` valem num **jogo** de pranchas, e não só numa
folha? Pedido do Caio: focar em Foz e testar com a IA, sem código do projeto. O teste da folha 012
sozinha está em `teste_prancha_2026-09-26.md`.

**Como.** Estas 5 pranchas foram baixadas do Drive para a sessão, não para o repositório:
010, 011, 012 e 013 (`PBHI-DE-AAT06PTPER-R1`, planta e perfil) e 018 (`PBHI-DE-AAT06VENDS-R0`,
detalhe de ventosas e descargas). Todas são folhas do mesmo jogo de 19. A IA leu os recortes
a 300 DPI, e a geometria foi medida com consultas avulsas ao PDF. O leitor foi o modelo desta
sessão (grande, em nuvem): os modelos locais continuam sem teste.

## Hipóteses, definidas antes de olhar, e veredito

| # | hipótese | veredito |
|---|---|---|
| H1 | carimbo: arquivo eletrônico = nome do arquivo; revisão confere | **verdadeira** nas 5. Mas o quadro de revisões grafa a revisão de dois jeitos: "01" (010, 011, 012) e "R1" (013) |
| H2 | as folhas encadeiam sem buraco nem sobreposição | **verdadeira**: EST 23→50→77→104→130; a distância acumulada segue `(EST − 1) × 20` nas 4. Existem **duas numerações**: folha do jogo (010/019) e "desenho" da adutora (010 = desenho 02, marcas "continuação do desenho 01 / continua no desenho 03"), com desenho = folha − 8 |
| H3 | extensão no desenho = relação = perfil = estacas | **verdadeira em 3 de 4 e falsa em 1** (tabela abaixo) |
| H4 | georreferência coerente entre folhas; datum e fuso declarados | **não testada** na continuidade numérica. Nenhuma das 5 folhas declara datum ou fuso |
| H5 | ventosas e descargas da 018 = as das plantas | **verdadeira pela cota** (DET01 e DET02), mas a **numeração diverge** numa planta (abaixo) |
| H6 | todas têm camadas do CAD e texto convertido em curva | **verdadeira**: 27 a 49 camadas (ADUTORA, MALHA, CARIMBO, _PERFIL_), 528 a 876 caracteres de texto real, 8.500 a 13.300 curvas, uma imagem embutida (a relação de materiais) em cada |

### H3 — extensão por quatro caminhos

| folha | estacas | traçado medido no desenho | relação de materiais | soma dos trechos do perfil | L total |
|---|---|---|---|---|---|
| 010 | 23→50 = 540 m | **540,02 m** | 540,00 m | 40+160+100+40+60+52+48+40 = **540** | 540 |
| 011 | 50→77 = 540 m | **540,01 m** | 540,00 m | 80+80+60+100+120+100 = **540** | 540 |
| 012 | 77→104 = 540 m | **540,02 m** | 540,00 m | 90+24+**44**+80+20+40+40+60+80+60 = **538** | 540 |
| 013 | 104→130 = 520 m | **519,99 m** | 520,00 m | 111+9+100+80+100+60+60 = **520** | 520 |

O jogo soma **2.140 m** de PEAD DE 630 nas 4 folhas. O único trecho que não fecha é o 83→85 da
012, com 44 m impressos contra 46 m na geometria. Três folhas fechando por quatro caminhos dão
confiança de que o método acusa erro real e não ruído.

### Curvas: o que a revisão diz × o que o desenho faz

| folha | revisão (MAI/2025) | deflexões medidas no desenho | relação de materiais | leitura |
|---|---|---|---|---|
| 010 | "ajuste na indicação das distâncias entre as estacas" | nenhuma (0,1°, −0,6°) | só tubo | coerente |
| 011 | "… **e retirada das curvas de 45°**" | **26,6° e −38,3°** (desvio com 14,2 m entre as dobras, na EST 68–69) | **2 × curva 45°** | a revisão diz que tirou, mas a planta ainda marca C45° duas vezes e a relação lista as duas. As dobras desenhadas não são de 45° |
| 012 | "… e retirada das curvas de 22° e de 45°" | 23,3° e 43,0° | curva 22° + curva 45° | a revisão diz que tirou; desenho e relação mantêm |
| 013 | "troca da conexão de PEAD 90° para 2x 45° …" | **88,8°** | 2 × curva 45° | coerente: 2 × 45° = 90° |

**Padrão do jogo:** onde a revisão fala em **troca**, o desenho foi atualizado (013). Onde fala
em **retirada** (011, 012), nem o desenho nem a relação mudaram. Isso aparece na comparação
entre folhas, não folha a folha. É pergunta ao projetista: ou a descrição da revisão está errada,
ou a revisão não foi aplicada ao desenho e à relação.

### H5 — folha de detalhe × plantas e perfis

| peça (018) | cotas no detalhe | onde aparece | confere |
|---|---|---|---|
| descarga DET01 | terreno 243,384 · G.I. 241,784 | 010, EST 43, descarga "1" | ✓ cota e número |
| descarga DET02 | terreno 240,380 · G.I. 238,680 | 012, EST 90: **perfil "DESCARGA 2"**, **planta "DESCARGA 3"** | cota ✓; **número diverge entre planta e perfil da mesma folha** |
| descarga DET03 | terreno 255,000 · G.I. 253,157 | fora das folhas presentes (depois da EST 130) | não verificável |
| ventosa DET02 | topo 249,868 · G.I. 248,068 | 011, EST 66, ventosa "2" | ✓ |
| ventosa DET01 e DET03 | G.I. 246,807 e 254,149 | fora das folhas presentes | não verificável |

A **cota** liga detalhe e planta com segurança; o **número** da peça não liga. É a mesma lição da
extensão: identificador escrito é alegação, valor que fecha com a geometria e o perfil é evidência.

### Jogo incompleto

O carimbo diz 019 folhas; no Drive estão 5 da adutora (010–013, 018). Faltam no mínimo a 009
(desenho 01, EST 1→23) e a 014 (desenho 06, depois da EST 130), onde devem estar ventosa 1,
ventosa 3 e descarga 3. P8 (`ligar_revisoes`) precisa dizer "jogo com 5 de 19 folhas" antes de
somar qualquer quantitativo do jogo.

## Lição sobre a ferramenta de medida

Na primeira contagem, 4 das 5 folhas saíram "sem camadas". Era erro da consulta: o arquivo
era fechado antes de ser lido. Refeita, todas têm camadas. O mesmo vale para o pipeline: todo
extrator precisa de teste sintético **que falhe** quando a medida estiver errada (regra da aferição),
porque um zero falso parece um achado.

## O que muda no plano

1. **P8 compara folhas entre si**, não só o carimbo: estacas encadeadas, distância acumulada, as duas
   numerações (folha × desenho), revisões do mesmo dia com o mesmo texto e se cada uma foi aplicada.
2. **P6a mede deflexão e a compara com a conexão da relação** (C22°, C45°, 2×C45°): ângulo desenhado × ângulo da peça.
3. **Detalhe liga à planta pela cota**, não pelo número da peça.
4. **Quantitativo do jogo só com o jogo completo**, ou marcado como parcial com as folhas que faltam.

## O que continua sem teste

- Os modelos locais (gemma3, glm-ocr, Vision, Apple FM) nos mesmos recortes: item 12 do plano, no mini.
- A georreferência numérica entre folhas (H4): o fim do traçado da 010 na mesma coordenada do início da 011.
- Uma planta escaneada real e pranchas de estrutura.
