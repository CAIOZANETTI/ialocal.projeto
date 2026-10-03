# Teste de mesa — uma prancha lida sem código do projeto (26/09/2026)

**Pergunta.** As premissas de `notas/plano_projeto.md` valem numa prancha real? Pedido do
Caio: testar só com a IA lendo e ferramentas prontas (render, contagem de objetos do PDF),
antes de escrever qualquer extrator.

**Como.** Folhas baixadas do Drive para a sessão (não para o repositório). O "leitor" foi a
IA da sessão, que é um modelo **grande, em nuvem**: o teste mede o que a **prancha**
permite, não o que o gemma3, o glm-ocr ou o Apple FM conseguem. A leitura pelos modelos
locais fica para a bancada E3 no mini (item 12 do plano).

## Amostra

| arquivo | o que é | classe achada |
|---|---|---|
| `012-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1.pdf` | Sanepar, Foz do Iguaçu, adutora AAT-06, planta e perfil, EST 77 a 104 | vetorial, A1, AutoCAD 2022 |
| `7685764-Cadastro As Built.pdf` | procedimento PAJ 12.02.03 da Águas de Joinville (8 páginas A4) | raster, copiadora Ricoh, ~200 DPI |
| a 012 "escaneada" (render a 200 DPI, cinza, girada 0,8°, desfoque, ruído, JPEG 55) | cópia de controle, com gabarito exato | raster simulado |

Não se achou, na busca rápida, planta escaneada de verdade. O arquivo com nome de
cadastro *as built* era um procedimento escrito. Por isso o controle simulado.

## Perfil da 012 (P0)

- A1 (841 × 594 mm), 1 página. Criado no AutoCAD 2022 e plotado pelo `pdfplot16.hdi`. Data de criação do PDF: 12/06/2025.
- **47 camadas do CAD preservadas como OCG**: `ADUTORA`, `CARIMBO`, `Carimbo Padrão`,
  `MALHA`, `_PERFIL_`, `Grade_perfil`, `Quadro_perfil`, `_TXT-PERFIL_`, `DESCARGA`,
  `520_PONTOS_APOIO`, `CAMINHAMENTO`, `600_PVCDEFoFo_DN0300`, lotes, quadras, vias,
  hidrografia…
- Texto real: **662 caracteres**, só o carimbo e alguns rótulos. Todo o resto do texto
  (estacas, cotas, quadro do perfil, malha) virou **curva**: são 12.905 curvas, 2.862 linhas e 824 retângulos.
- O texto real que existe sai **embaralhado** onde há rótulos girados sobrepostos:
  `PEADPC55-351m0m263.219,0 m`.
- **Uma imagem embutida** (2698 × 756 px), exatamente sobre a **Relação de Materiais**. A
  tabela de materiais foi colada como figura (print do Excel) dentro da folha vetorial.

## O que se leu (P3, P4, P6a)

**Carimbo.** Todos os campos foram lidos: município e sistema, projeto, "EST. 77 A EST. 104",
folha 012/019, data 09/2020, escala INDICADA, gerência, projetista contratada, responsáveis
com CREA e arquivo eletrônico. O arquivo eletrônico **é igual ao nome do arquivo**.
Quadro de revisões: 00 "EMISSÃO FINAL" (SETEMBRO/2020) e 01 "AJUSTE NA INDICAÇÃO DAS
DISTÂNCIAS ENTRE AS ESTACAS E RETIRADA DAS CURVAS DE 22° E DE 45°" (MAI/25). O sufixo
`R1` do nome confere com a revisão 01.

**Relação de materiais.** Três linhas: tubo PE 100 PN 10 DE 630, 540,00 m; curva injetada
22°, 1 pç; curva injetada 45°, 1 pç. Cada linha traz o código SAM.

**Quadro do perfil.** 28 estacas, cota do terreno e distância acumulada por estaca.
São 10 trechos, cada um com geratriz inferior nos vértices, profundidade, comprimento e DN, material e declividade.
L total = 540,00 m.

## Redundância — o que conferiu e o que não

| verificação | resultado |
|---|---|
| escala pela geometria | estacas a cada **56,69 pt** no quadro = 20 m → 2,835 pt/m = **1:1000**, igual ao rótulo "ESCALA H=1:1000" |
| malha pela geometria | rótulos E=747.000 e E=747.100 a ~283 pt → 100 m em 1:1000 ✓ |
| declividade = Δ geratriz / comprimento | **10 de 10** conferem com o impresso (ex.: (245,339 − 243,400) / 90 = 0,02154) |
| profundidade = terreno − geratriz | **9 de 9** vértices dão 1,60 ou 1,70, como impresso |
| extensão total | estacas 77→104 = 27 × 20 = 540 ✓; distância acumulada 1520→2060 = 540 ✓; relação de materiais 540,00 ✓ |
| **soma dos comprimentos dos trechos** | 90 + 24 + **44** + 80 + 20 + 40 + 40 + 60 + 80 + 60 = **538 ≠ 540** |
| **terceiro trecho pela geometria** | divisórias do quadro em x = 602,3 e 732,7 pt → 130,4 / 2,835 = **46,0 m**; impresso **44,00**, único escrito com vírgula. A declividade impressa (0,03761) foi calculada com 44 m; com 46 m daria 0,03598 |
| **revisão × materiais** | a revisão 01 diz "retirada das curvas de 22° e de 45°", mas a relação de materiais ainda lista as duas curvas, e a planta e o perfil ainda marcam C22° e C45° |
| data | a data do carimbo (09/2020) não é a da revisão vigente (MAI/25), e o PDF é de 12/06/2025 |

**Os dois achados (46 × 44 m e as curvas) são perguntas ao projetista, não conclusões.** O
primeiro só apareceu porque a geometria foi medida. Ler o texto duas vezes não o
revelaria, porque as duas leituras dariam "44,00" e concordariam.

## Georreferenciamento (P7)

- A malha está na folha (E=747.000 / 747.100 / 747.200, N=7.178.200 / 7.178.100), mas a
  folha **não diz datum nem fuso**: nem no texto real, nem nas notas visíveis.
- E=747.000 e N=7.178.200 dão (−54,54°, −25,49°) no **fuso 21S**, que é Foz do Iguaçu. No
  **fuso 22S** dão (−48,54°, −25,49°), no litoral do Paraná. A sugestão do plano (22S como
  padrão) **teria errado a obra em ~600 km**.
- Sem o datum, SIRGAS 2000 e SAD 69 diferem em dezenas de metros. A georreferência dessa
  folha fica "provável SIRGAS 2000 / 21S, pelo município", e isso precisa ser confirmado pela folha
  de notas gerais do jogo (001/019) ou pelo Caio.

## O traçado tirado do desenho (emenda, a pedido do Caio: "o projeto tem que ter desenho")

Até aqui a leitura era quase só do que está **escrito** (carimbo, relação, quadro do perfil).
O desenho da planta foi lido depois. A adutora é uma faixa roxa preenchida, formada por
triângulos, e o eixo sai do ponto médio de cada par de bordas. Foram 7 vértices, medidos em 1:1000:

| segmento | comprimento | rumo |
|---|---|---|
| 1 (chegada da folha 03) | 11,38 m | −14,0° |
| 2 | 153,88 m | −0,2° |
| 3 | 133,84 m | 23,1° |
| 4 | 59,08 m | 20,1° |
| 5 | 118,91 m | 21,9° |
| 6 | 62,93 m | 64,9° |
| **total** | **540,02 m** | |

- **Extensão do desenho = 540,02 m**, contra 540,00 da relação, 540 do perfil e 27 estacas × 20 m. São quatro fontes independentes e todas concordam.
- **Deflexões no desenho: 23,3° perto da EST 85 e 43,0° perto da EST 101**, exatamente onde a
  planta marca C22° e C45°. O traçado **ainda dobra** nesses pontos, e isso inverte a leitura
  anterior: a relação de materiais (que ainda lista as duas curvas) é **coerente com o desenho**. Quem
  destoa é a descrição da revisão 01 ("retirada das curvas"). Pode ser que as curvas tenham sido
  trocadas por curvatura do próprio PEAD, mas então a relação estaria desatualizada. Continua sendo
  pergunta ao projetista, agora com o desenho como terceira testemunha.
- Há também uma deflexão de 13,7° na chegada (EST 77), sem conexão listada. Pode estar na folha 03.

**Lição para o plano:** o desenho é a testemunha que desempata. Texto contra texto (revisão × relação)
não decide; o traçado medido decide. P6a precisa extrair **o eixo e as deflexões**, não só o quadro.

## A escaneada (controle simulado a 200 DPI)

- **Leitura:** carimbo, quadro de revisões e quadro do perfil (a metade direita inteira,
  inclusive o texto vertical pequeno) saíram **iguais** à leitura vetorial.
- **Localização:** recorte por fração fixa da folha **desloca** com 0,8° de giro e com a
  borda do escâner. O recorte do perfil começou na EST 91 em vez da 92, e o carimbo
  desceu. Confirma a skill: endireitar primeiro e achar a zona pela moldura e pelo título, nunca por fração.
- **Geometria:** sem vetor, sobra o pixel. A 200 DPI, 1 px = 0,127 mm = 0,13 m em 1:1000, o que
  ainda separa 44 de 46 m (≈ 16 px). A conferência por geometria vale no escaneado, com
  tolerância maior.

## O que muda no plano

1. **Redundância na vetorial vem de métodos diferentes, não de dois leitores de texto**: texto
   (ou OCR) × geometria medida × aritmética (declividade, profundidade, estacas, soma). É isso que acha
   erro de projeto.
2. **Folha vetorial também precisa de OCR**: texto virou curva, e há tabela como imagem
   embutida. P1 precisa separar vetor, texto real e imagem embutida por região.
3. **Camada do CAD é um sinal forte**, mas falta testar se cada objeto do PDF diz a que OCG pertence
   (o pdfplumber não entrega isso direto; o fluxo de conteúdo marca `/OC`). É premissa do P1.
4. **Nenhum fuso padrão**: o fuso sai da malha **e** do município do carimbo (os dois têm de
   concordar); o datum fica "não declarado" até vir de outra folha.
5. **Data vigente = revisão mais recente do quadro**, não o campo DATA do carimbo.
6. **Escaneada tem rota própria**: endireitar → moldura → zonas por âncora → OCR em recorte
   (texto vertical girado antes) → mesma aritmética → geometria por pixel.
7. **Nome do arquivo não classifica prancha**: "Cadastro As Built" era procedimento. O P0 decide
   pelo conteúdo (formato da folha, moldura, carimbo), e o nome é só um sinal.

## O que este teste não mede

- Os modelos locais: gemma3 12B, glm-ocr e Apple FM leem pior que o modelo desta sessão. O texto
  vertical de 2 mm é o caso mais provável de falhar neles.
- Escaneado real: dobra, mancha, cópia de cópia e anotação à mão (*as built* rabiscado em
  vermelho). O controle simulado é o melhor caso do escaneado.
- Estrutura (forma e armação): só uma folha, de obra linear.
