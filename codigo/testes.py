"""Testes do projeto, em qualquer máquina: a entrega do extrator falsa (uma prancha A1 sintética, uma folha A3 em branco
e um PDF A4 que não é candidato), o Drive falso (rclone que copia para uma pasta), a IA falsa (glm-ocr e Vision que
devolvem texto fixo) e o maestro ausente (a trava de GPU falha aberta). As regras da prancha vieram do extrator com os
casos que as decidiram (auditoria de 26/09).

    .venv/bin/python codigo/testes.py
"""
import io
import json
import math
import os
import sys
import tempfile
import time
import types
from pathlib import Path

import polars as pl

import ciclo
import cliente_gpu
import comum
import ia
import prancha
import respostas

RCLONE_FALSO = '''#!/bin/sh
# rclone copyto [--checksum] ORIGEM gdrive:DESTINO → $DRIVE_FALSO/DESTINO
for ultimo; do :; done
origem=$(eval echo \\${$(($#-1))})
destino="$DRIVE_FALSO/${ultimo#gdrive:}"
mkdir -p "$(dirname "$destino")" && cp "$origem" "$destino"
'''


def conferir(condicao, mensagem):
    if not condicao:
        raise AssertionError(mensagem)
    print(f'ok  {mensagem}')


def pdf_prancha():
    """Prancha A1 sintética: camada ADUTORA com o eixo em faixa roxa (200 mm reto e 100 mm a 45°, 300 mm no papel) e o
    carimbo em texto real no canto inferior direito — o formato das pranchas da AAT-06 de Foz (notas/teste_prancha)."""
    eixo = [(300.0, 1300.0), (300.0 + 200 / 25.4 * 72, 1300.0)]
    eixo.append((eixo[1][0] + 100 / 25.4 * 72 * math.cos(math.radians(-45)), 1300.0 + 100 / 25.4 * 72 * math.sin(math.radians(-45))))
    normais = [(0.0, 1.0), (0.3827, 0.9239), (0.7071, 0.7071)]
    meia = [3.0, 3.0 / 0.9239, 3.0]
    lados = [((x + n[0] * m, y + n[1] * m), (x - n[0] * m, y - n[1] * m)) for (x, y), n, m in zip(eixo, normais, meia)]
    triangulos = [t for i in range(2) for t in ((lados[i][0], lados[i][1], lados[i + 1][0]), (lados[i][1], lados[i + 1][0], lados[i + 1][1]))]
    faixa = ''.join(f'{a[0]:.2f} {a[1]:.2f} m {b[0]:.2f} {b[1]:.2f} l {c[0]:.2f} {c[1]:.2f} l h f\n' for a, b, c in triangulos)
    carimbo = ['FOLHA N: 012/019', 'DATA: 09/2020', 'TITULO: ADUTORA DE AGUA TRATADA AAT-06', 'PLANTA E PERFIL',
               'ARQUIVO ELETRONICO: 012-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1', 'PROJETISTA: SANEPAR - USPE',
               'RESP. TECNICO: ENG. JOAO DA SILVA', 'CREA: PR-12345/D', 'ART: 1720203456789', 'FASE: EXECUTIVO',
               'R0 10/08/2020 EMISSAO INICIAL', 'R1 15/09/2020 ALTERACAO DO TRACADO']
    texto = ''.join(f'BT /F1 9 Tf 1720 {300 - 20 * n} Td ({linha}) Tj ET\n' for n, linha in enumerate(carimbo))
    conteudo = f'/OC /MC0 BDC 0.64706 0 0.86667 rg\n{faixa}EMC\n0 0 0 rg\n{texto}'.encode()
    objetos = ['<< /Type /Catalog /Pages 2 0 R /OCProperties << /OCGs [5 0 R] /D << /ON [5 0 R] >> >> >>',
               '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 2384 1684] /Contents 6 0 R '
               '/Resources << /Font << /F1 4 0 R >> /Properties << /MC0 5 0 R >> >> >>',
               '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', '<< /Type /OCG /Name (ADUTORA) >>',
               f'<< /Length {len(conteudo)} >>\nstream\n' + conteudo.decode() + '\nendstream']
    corpo, posicoes = b'%PDF-1.7\n', []
    for numero, objeto in enumerate(objetos, 1):
        posicoes.append(len(corpo))
        corpo += f'{numero} 0 obj\n{objeto}\nendobj\n'.encode()
    xref = f'xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n' + ''.join(f'{p:010d} 00000 n \n' for p in posicoes)
    return corpo + xref.encode() + f'trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{len(corpo)}\n%%EOF\n'.encode()


def pdf_em_branco(largura_pt, altura_pt):
    import pypdfium2 as pdfium
    documento = pdfium.PdfDocument.new()
    documento.new_page(largura_pt, altura_pt)
    saida = io.BytesIO()
    documento.save(saida)
    documento.close()
    return saida.getvalue()


def pdf_com_camadas(conteudo, camadas, formulario=None):
    """PDF de uma folha A3 deitada com camadas do CAD (grupos de conteúdo opcional, nome em UTF-16 como o CAD grava);
    `formulario` = (conteúdo, matriz), um XObject chamado por /F0 Do. A camada i é /L{i} no conteúdo."""
    ocgs = list(range(5, 5 + len(camadas)))
    propriedades = ' '.join(f'/L{i} {o} 0 R' for i, o in enumerate(ocgs))
    lista = ' '.join(f'{o} 0 R' for o in ocgs)
    objetos = [f"<< /Type /Catalog /Pages 2 0 R /OCProperties << /OCGs [{lista}] /D << /Order [{lista}] >> >> >>",
               "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1190.55 841.89] /Resources << /Properties << {propriedades} >> "
               f"{f'/XObject << /F0 {5 + len(camadas)} 0 R >>' if formulario else ''} >> /Contents 4 0 R >>",
               f"<< /Length {len(conteudo)} >>\nstream\n{conteudo}\nendstream"]
    objetos += [f"<< /Type /OCG /Name <FEFF{nome.encode('utf-16-be').hex().upper()}> >>" for nome in camadas]
    if formulario:
        objetos.append(f"<< /Type /XObject /Subtype /Form /BBox [0 0 1190 842] /Matrix [{formulario[1]}] /Resources << /Properties "
                       f"<< {propriedades} >> >> /Length {len(formulario[0])} >>\nstream\n{formulario[0]}\nendstream")
    saida, posicoes = b'%PDF-1.7\n', []
    for numero, objeto in enumerate(objetos, 1):
        posicoes.append(len(saida))
        saida += f'{numero} 0 obj\n{objeto}\nendobj\n'.encode('latin-1')
    tabela = f'xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n' + ''.join(f'{p:010d} 00000 n \n' for p in posicoes)
    return saida + f'{tabela}trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{len(saida)}\n%%EOF\n'.encode()


def testar_eixo_por_camada():
    """Sem a faixa colorida, o eixo da prancha linear é a soma dos traços abertos das camadas de tubo projetado (2v60;
    a cor só achava o da AAT-06, 12 de 435 lineares): a polilinha (300 + 400 pt), o arco (quarto de círculo de 100 pt,
    157,1 pt) e o formulário da mesma camada com escala 2 (2 × 200 pt) contam; o quadrado fechado (símbolo), o texto do
    tubo, o cadastro existente (600_) e o preenchido sem traço não; o nome com acento sai inteiro. Na localizada, nada."""
    import pypdfium2 as pdfium
    k = 100 * 0.5523
    conteudo = ("/OC /L0 BDC 2 w 100 100 m 400 100 l 400 500 l S 600 100 m "
                f"{600 + k:.2f} 100 700 {200 - k:.2f} 700 200 c S 800 100 m 850 100 l 850 150 l 800 150 l h S EMC\n"
                "/OC /L1 BDC 100 700 m 300 700 l S EMC /OC /L2 BDC 100 750 m 900 750 l S EMC\n"
                "/OC /L0 BDC 100 50 m 500 50 l 500 60 l f EMC /OC /L0 BDC /F0 Do EMC")
    camadas = ['1ª ETAPA-TUBO-PVC-DN50', '1ª ETAPA-TEXTO-TUBO-PVC-DN50', '600_PVC_DN0050']
    with tempfile.TemporaryDirectory() as pasta:
        arquivo = Path(pasta) / 'rede.pdf'
        arquivo.write_bytes(pdf_com_camadas(conteudo, camadas, ('0 0 m 0 200 l S', '2 0 0 2 50 50')))
        documento = pdfium.PdfDocument(arquivo)
        tracos, linear, localizada = (prancha.tracos_por_camada(documento[0]), prancha.eixo(documento[0], 'linear'),
                                      prancha.eixo(documento[0], 'localizada'))
        documento.close()
    esperado = (700 + 157.08 + 400) * 25.4 / 72
    por_camada = json.loads(linear['eixo_camadas'])
    conferir(linear['eixo'] == 'camada' and abs(linear['eixo_mm'] - esperado) < 0.5 and list(por_camada) == [camadas[0]]
             and set(tracos) == set(camadas) and abs(tracos['600_PVC_DN0050'] - 800) < 0.01 and localizada['eixo'] == 'nao_encontrado'
             and list(json.loads(linear['tracos_camadas'])) == ['1ª ETAPA-TUBO-PVC-DN50', '600_PVC_DN0050', '1ª ETAPA-TEXTO-TUBO-PVC-DN50']
             and localizada['tracos_camadas'] == '{}',
             f"eixo por camada: {linear['eixo_mm']} mm ≈ {esperado:.1f} (polilinha, arco e formulário da camada de tubo; fora o "
             "símbolo fechado, o texto, o cadastro 600_ e o preenchido); na prancha localizada, não se procura")
    linha = {'eixo': 'camada', 'eixo_mm': 500.0, 'eixo_camadas': json.dumps({'1ª ETAPA-TUBO-PVC-DN50': 300.0, '1ª ETAPA-TUBO-PVC-DN100': 200.0})}
    leituras = [{'padrao': 'escala', 'valor': '1:1000', 'status': 'confirmado'}]
    tabelas = [{'status': 'confirmada', 'celulas': json.dumps(c)} for c in (['TUBO PVC DN50', '300', 'm'], ['TUBO PVC DN100', '200', 'm'])]
    resultado = prancha.conferir(linha, leituras, tabelas)
    conferir(resultado['conferencia'] == 'fecha' and resultado['eixo_m'] == 500.0 and resultado['tubo_relacao_m'] == '500.0'
             and json.loads(resultado['eixo_m_camadas']) == {'1ª ETAPA-TUBO-PVC-DN50': 300.0, '1ª ETAPA-TUBO-PVC-DN100': 200.0}
             and json.loads(prancha.conferir(linha, leituras, [])['eixo_m_camadas'])['1ª ETAPA-TUBO-PVC-DN50'] == 300.0,
             'eixo por camada: a conferência soma os tubos da relação (300 + 200 m = 500 m, a rede tem vários diâmetros); os metros '
             'por diâmetro saem com a escala, mesmo sem relação na folha')


def montar_entrega(raiz, versao_prancha='sha-1'):
    """O que o extrator 2v94 deixa no disco: a entrega em partes, os arquivos em projetos/ e o mapa .obras."""
    pasta = raiz / 'extracao' / 'projetos'
    pasta.mkdir(parents=True, exist_ok=True)
    arquivos = {'prancha.pdf': pdf_prancha(), 'a3.pdf': pdf_em_branco(842, 1191), 'a4.pdf': pdf_em_branco(595, 842)}
    for nome, conteudo in arquivos.items():
        (pasta / nome).write_bytes(conteudo)
    linha = lambda i, caminho, arquivo, local, versao, candidata: {
        'id': i, 'extrator': 'entrega', 'caminho': caminho, 'arquivo': arquivo, 'versao': versao, 'candidata': candidata,
        'arquivo_local': str(pasta / local)}
    entrega = pl.DataFrame([
        linha('ARQ-000001/pranchas/012-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1.pdf', 'obras/foz.zip/pranchas/012-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1.pdf',
              '012-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1.pdf', 'prancha.pdf', versao_prancha, True),
        linha('ARQ-000001/memorial_a3.pdf', 'obras/foz.zip/memorial_a3.pdf', 'memorial_a3.pdf', 'a3.pdf', 'sha-2', True),
        linha('ARQ-000001/oficio.pdf', 'obras/foz.zip/oficio.pdf', 'oficio.pdf', 'a4.pdf', 'sha-3', False),
        linha('ARQ-000009/saiu.pdf', 'obras/velha.zip/saiu.pdf', 'saiu.pdf', 'a3.pdf', 'sha-4', True)])
    (raiz / 'extracao' / 'projeto_entrega').mkdir(parents=True, exist_ok=True)
    entrega.write_parquet(raiz / 'extracao' / 'projeto_entrega' / 'parte_07.parquet')
    (raiz / 'extracao' / 'por_obra').mkdir(parents=True, exist_ok=True)
    (raiz / 'extracao' / 'por_obra' / '.obras').write_text(json.dumps({'ARQ-000001': 'obras/Foz AAT-06'}))


def ia_falsa():
    """O glm-ocr "continua" a sequência de estacas até a 323 (o que ele fez em 26/09); o Vision não."""
    ia.ler_com_glm_ocr = lambda caminho: {'texto': 'PLANTA ESCALA H=1:1000\nEST 77\nEST 78\n246,939\nEST 323'}
    ia.ler_com_vision = lambda caminho: {'texto': 'PLANTA ESCALA H = 1:1000\nEST 77 EST 78\n246.939'}
    sys.modules['Vision'] = types.ModuleType('Vision')


def testar_conceitos():
    """Conceitos e versões contam a mesma história: toda tarefa em `muda` existe; versões em ordem."""
    import re
    PRANCHA = comum.configuracao('prancha')
    conferir(all(re.compile(p) for k, p in PRANCHA['padroes'].items() if not k.startswith('_'))
             and all(f in PRANCHA['familias']['padroes'] and f in PRANCHA['familias']['grupo'] for f in PRANCHA['familias']['ordem']),
             'prancha.json: padrões compilam; toda família da ordem tem padrão e grupo')
    numeros = [ciclo.numero(v['versao']) for v in comum.versoes()]
    conferir(numeros == sorted(set(numeros)) and all(set(v.get('muda', [])) <= set(ciclo.TAREFAS) for v in comum.versoes()),
             'versões em ordem, sem repetir; muda só com tarefas que existem')


def testar_regras(pasta):
    """As regras da prancha com os casos reais que as decidiram (auditoria de 26/09 no extrator)."""
    tubo = lambda metros, status: {'status': status, 'celulas': json.dumps(['01', '309244', 'TUBO POLIETILENO PE 100 DE 630', metros, 'm'])}
    escala = [{'padrao': 'escala', 'valor': '1:1000', 'status': 'confirmado'}, {'padrao': 'escala', 'valor': '1:100', 'status': 'confirmado'}]
    conferir(prancha.conferir({'eixo_mm': 540.0}, escala, [tubo('540,00', 'confirmada')])['conferencia'] == 'fecha'
             and prancha.conferir({'eixo_mm': 540.0}, escala, [tubo('538,00', 'confirmada')])['conferencia'] == 'diverge'
             and prancha.conferir({'eixo_mm': 540.0}, escala, [tubo('540,00', 'pendente')])['conferencia'] == 'sem_tubo_confirmado',
             'extensão desenhada × tubo da relação fecha, diverge, ou espera o tubo confirmado')
    layout = 'SISTEMA DE ABASTECIMENTO DE ÁGUA REDE DE DISTRIBUIÇÃO DE ÁGUA REMANEJAMENTOS LAYOUT RUA CORTEZ DATA: AGO/25 ESCALA: 1:7.500'
    conferir((prancha.familia('LAYOUT-CAMBE.pdf', layout)['familia'], prancha.familia('LAYOUT-CAMBE.pdf', layout)['desenho']) == ('rede_agua', 'locacao')
             and prancha.achar(layout)['escala'] == {'1:7.500'}
             and prancha.conferir({'eixo_mm': 100.0}, [{'padrao': 'escala', 'valor': '1:7.500', 'status': 'confirmado'}], [])['eixo_m'] == 750.0,
             'LAYOUT de Cambé é locação (a rua CORTEZ não é corte) e a escala 1:7.500 não vira 1:7')
    sondagem = prancha.familia('PLANTA_GERAL_SONDAGEM_CAMBÉ_01.pdf', 'PLANTA DE LOCAÇÃO DOS FUROS')
    conferir((sondagem['familia'], sondagem['grupo']) == ('sondagem', 'apoio')
             and prancha.familia('012-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1.pdf', 'ver boletim de sondagem')['familia'] == 'adutora',
             'planta de sondagem é família sondagem, grupo apoio; a adutora que cita sondagem continua adutora')
    cambe = '05V-SAA-0153-8127-PULI-DE-0000RDA00REMANEJ-R0.pdf'
    conferir(prancha.sinais(cambe, '', [], 78234) == ['nome', 'desenho'] and prancha.sinais('memorial.pdf', '', [], 40) == []
             and (prancha.familia(cambe, '')['familia'], prancha.familia(cambe, '')['grupo']) == ('rede_agua', 'linear'),
             'desenho vetorial denso sem texto e sem camadas (Cambé, 78 mil caminhos) é prancha; RDA no meio do nome é rede de água')
    ose = 'OSE075 ' + 'GAS ' * 40 + 'PV CT.943.544 PV CT.945.343 REDE DE GÁS\nSISTEMA DE ABASTECIMENTO DE ÁGUA 002-SAA-0001-6745-PULI-DE-RDA00TATCADBL01-R0'
    conferir(prancha.familia('05_OSE-075.pdf', ose)['familia'] == 'rede_agua'
             and prancha.familia('x.pdf', 'OSE075 ' + 'GAS ' * 40)['familia'] == 'indefinida'
             and prancha.sinais('01_FECHAMENTO DE DEDUÇÕES - INFRATEK NOV25.pdf', '', [], 0) == [],
             'o código do desenho (RDA) decide antes do GAS GAS GAS da interferência; "FECHAMENTO DE DEDUÇÕES" não é desenho')
    ose102 = 'Adutora: RDA CFA JNE JDA FUNDOS AV. COMENDADOR FRANCO Declividade da\nAdutora SENTIDO DE FLUXO DA ADUTORA'
    eet = 'DRENAGEM - EXISTENTE ESTAÇÃO ELEVATÓRIA TRATADA - EET 003-SAA-0001-6745-PEXE-DE-EET00TATUQUAPL-A0'
    conferir((prancha.familia('10_OSE-102.pdf', ose102)['familia'], prancha.familia('x.pdf', eet)['familia'],
              prancha.familia('03_003-SAA-0001-6745-PEXE-DE-EET00TATUQUACT-A0.pdf', '')['familia'],
              prancha.familia('01_056-SAA-0001-7739-PBHI-DE-0708RAP01CX1INTDN900-R0F.pdf', '')['familia'])
             == ('rede_agua', 'elevatoria', 'elevatoria', 'reservatorio'),
             'o campo "Adutora:" da OSE e a legenda "DRENAGEM - EXISTENTE" não decidem a família; EET e RAP colados ao número')
    from PIL import Image
    imagem = pasta / 'faixa.png'
    Image.new('RGB', (1100, 300), 'white').save(imagem)
    linha = '<tr><td>01</td><td>310015</td><td>COLARINHO PE 100 DE 630</td><td>06</td><td>PÇ</td></tr>'
    ocr_glm, ollama, vision = ia.ocr_glm, ia.ollama, ia.ler_com_vision
    ia.ocr_glm = lambda caminho, instrucao: f'<table>{linha}{linha}<tr><td>02</td><td>284983</td><td>FLANGE</td><td>06</td><td>PÇ</td></tr></table>'
    ia.ler_com_vision = lambda caminho: {'texto': '01 310015 COLARINHO PE 100 DE 630 06 PÇ\n02 FLANGE 06 PÇ'}
    try:
        linhas = prancha.ler_tabela(imagem, True, {'id': 'x'})
        ia.ollama = lambda modelo, prompt, esquema=None, imagens=(): ('{"familia": "eta"}', {})
        eta = prancha.desempatar('ESTAÇÃO DE TRATAMENTO')
        ia.ollama = lambda modelo, prompt, esquema=None, imagens=(): ('{"familia": "ponte"}', {})
        fora = prancha.desempatar('?')
    finally:
        ia.ocr_glm, ia.ollama, ia.ler_com_vision = ocr_glm, ollama, vision
    conferir([l['status'] for l in linhas] == ['confirmada', 'pendente'] and linhas[1]['nao_confirmados'] == '284983',
             'tabela colada sem a linha repetida; número que o Vision não leu deixa a linha pendente')
    conferir((eta['familia'], eta['grupo']) == ('eta', 'localizada') and fora['familia'] == 'indefinida',
             'desempate da família só vale com opção da lista (e o grupo sai da família)')


def testar_rodada(raiz):
    """De ponta a ponta: a rodada lê a entrega, o código reconhece a prancha e a folha A3 em branco não; só a prancha
    vai à IA; a estaca que só o glm-ocr leu fica so_glm; publica por obra e no _sistema; o status no formato comum."""
    montar_entrega(raiz)
    ia_falsa()
    ciclo.rodada()
    linhas = comum.ler('prancha').to_dicts()
    codigo = next(l for l in linhas if l['extrator'] == 'prancha' and l['arquivo'].startswith('012-SAA'))
    lida = next(l for l in linhas if l['extrator'] == 'prancha_ia')
    conferir(codigo['e_prancha'] and codigo['formato'] == 'A1' and codigo['camadas'] == 1 and codigo['classe'] == 'vetorial_curva'
             and (codigo['familia'], codigo['grupo'], codigo['desenho']) == ('adutora', 'linear', 'planta_e_perfil')
             and (codigo['acervo'], codigo['obra']) == ('obras', 'Foz AAT-06'),
             'prancha A1 com camada do CAD; família adutora, grupo linear e desenho pela regra; a obra pelo mapa do extrator')
    conferir(abs(codigo['eixo_mm'] - 300) < 0.5 and json.loads(codigo['deflexoes']) == [45.0] and codigo['carimbo_folha'] == '012/019'
             and codigo['carimbo_arquivo_confere'] and codigo['carimbo_revisao_nome'] == '1',
             'eixo de 300 mm com a dobra de 45° tirado da faixa; carimbo com a folha e o nome do arquivo')
    carimbo = {l['campo']: l for l in comum.ler('carimbo').to_dicts() if l['arquivo'].startswith('012-SAA')}
    conferir(codigo['camada'] == 'vetor' and codigo['carimbo_camada'] == 'texto'
             and {c: carimbo[c]['valor'] for c in ('numero_desenho', 'titulo', 'projetista', 'responsavel_tecnico', 'crea', 'art', 'fase', 'revisao_vigente')}
             == {'numero_desenho': '012-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1', 'titulo': 'ADUTORA DE AGUA TRATADA AAT-06',
                 'projetista': 'SANEPAR - USPE', 'responsavel_tecnico': 'ENG. JOAO DA SILVA', 'crea': 'PR-12345/D',
                 'art': '1720203456789', 'fase': 'EXECUTIVO', 'revisao_vigente': 'R1'}
             and len(json.loads(carimbo['revisoes']['valor'])) == 2 and {l['status'] for l in carimbo.values()} == {'codigo'},
             'camada: desenho vetorial com o texto em curva, carimbo em texto real lido pelo código — número, título, projetista, '
             'responsável, CREA, ART, fase e o quadro de revisões (a vigente é a R1)')
    conferir(not next(l for l in linhas if l['arquivo'] == 'memorial_a3.pdf')['e_prancha']
             and not any(l['arquivo'] in ('oficio.pdf', 'saiu.pdf') for l in linhas)
             and [l['arquivo'] for l in linhas if l['extrator'] == 'prancha_ia'] == [codigo['arquivo']],
             'A3 em branco não é prancha e não vai à IA; o PDF A4 e o da obra que saiu do mapa nem entram')
    leituras = {(l['padrao'], l['valor']): l['status'] for l in comum.ler('prancha_leitura').to_dicts()}
    conferir(leituras[('estaca', 'EST323')] == 'so_glm' and leituras[('estaca', 'EST77')] == 'confirmado'
             and leituras[('cota', '246.939')] == 'confirmado' and leituras[('escala', '1:1000')] == 'confirmado',
             'número só confirmado quando glm-ocr e Vision leram o mesmo; a estaca que só o glm-ocr leu fica pendente')
    drive = Path(os.environ['DRIVE_FALSO'])
    conferir(lida['eixo_m'] == 300.0 and lida['conferencia'] == 'sem_tubo_confirmado' and lida['fatias_lidas'] == lida['fatias_planejadas'] == 24
             and (drive / 'saida' / '_sistema' / 'projeto' / 'pranchas.csv').exists()
             and (drive / 'saida' / 'obras' / 'Foz AAT-06' / 'projeto' / 'prancha_leituras.csv').exists(),
             '24 fatias de A1 lidas, eixo em metros pela escala confirmada; CSV no _sistema/projeto e em <obra>/projeto/')
    status = json.loads((comum.SAIDAS / 'status.json').read_text())
    conferir((status['saude'], status['progresso'], status['fila']['na_fila'], status['pranchas']['lidas_pela_ia'])
             == ('ok', {'feito': 2, 'total': 2}, 0, 1) and status['repo'] == 'ialocal.projeto',
             'status.json no formato comum: 2 de 2 candidatas feitas, fila vazia, 1 prancha lida pela IA')
    conferir(status['precisa_do_caio'] == len(status['demandas']) >= 1
             and all(d['id'] and d['titulo'] and len(d['texto']) > 100 for d in status['demandas']),
             'status: as demandas abertas ao Caio (conceitos/demandas.json), com título e texto, e quantas em precisa_do_caio')
    obra = status['por_obra']['obras/Foz AAT-06']
    conferir((obra['feito'], obra['total'], obra['pranchas'], obra['arquivos']) == (2, 2, 1, 3) and obra['bytes'] > 0,
             'status por obra (a tela 8 do maestro): 2 de 2 feitas, 1 prancha; pranchas, leituras e carimbos publicados (sem imagem colada, sem tabela)')
    chamadas = []
    ia.ler_com_glm_ocr = lambda caminho: chamadas.append(caminho) or {'texto': ''}
    ciclo.rodada()
    conferir(not chamadas, 'rodada seguinte sem nada novo não lê nada de novo')
    montar_entrega(raiz, versao_prancha='sha-1b')
    ia_falsa()
    ciclo.rodada()
    refeita = next(l for l in comum.ler('prancha').to_dicts() if l['extrator'] == 'prancha_ia')
    conferir(refeita['versao_documento'] == 'sha-1b', 'conteúdo novo da prancha (outra versão na entrega): código e IA refeitos')


def testar_falha(raiz):
    """A leitura que falha volta na rodada seguinte até `tentativas` vezes; depois a saúde é atenção, com o motivo."""
    original = prancha.ler_prancha
    montar_entrega(raiz, versao_prancha='sha-1c')

    def quebra(documento, rodada):
        raise ValueError('PDF quebrado')
    prancha.ler_prancha = quebra
    try:
        for _ in range(comum.configuracao('operacao')['tentativas']):
            ciclo.rodada()
    finally:
        prancha.ler_prancha = original
    status = json.loads((comum.SAIDAS / 'status.json').read_text())
    conferir(status['saude'] == 'atenção' and status['fila']['falhou'] == 1 and 'falhas.jsonl' in status['motivo'],
             'falha três vezes com este código: fica falhou, a saúde diz atenção e onde ver')


def pdf_de_texto(linhas, largura=595, altura=842):
    """PDF de uma página com as linhas em texto real, de cima para baixo (o boletim que o laboratório gerou no computador)."""
    texto = ''.join(f'BT /F1 9 Tf 40 {altura - 60 - 14 * n} Td ({linha}) Tj ET\n' for n, linha in enumerate(linhas)).encode('latin-1')
    objetos = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {largura} {altura}] /Contents 5 0 R /Resources << /Font << /F1 4 0 R >> >> >>'.encode(),
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', f'<< /Length {len(texto)} >>\nstream\n'.encode() + texto + b'\nendstream']
    corpo, posicoes = b'%PDF-1.7\n', []
    for numero, objeto in enumerate(objetos, 1):
        posicoes.append(len(corpo))
        corpo += f'{numero} 0 obj\n'.encode() + objeto + b'\nendobj\n'
    xref = f'xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n' + ''.join(f'{p:010d} 00000 n \n' for p in posicoes)
    return corpo + xref.encode() + f'trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{len(corpo)}\n%%EOF\n'.encode()


BOLETIM = ['BOLETIM DE SONDAGEM A PERCUSSAO - SPT   NBR 6484', 'FURO: SP-03   COTA DA BOCA: 812,45 m', 'E = 712.400   N = 7.098.200',
           'DATA: 12/03/2021', 'PROF.  GOLPES  AMOSTRADOR', '1,00 3/15 4/15 5/15', '2,00 5/15 6/15 8/15', '3,00 10/15 12/15 15/15',
           '0,00 - 1,20 ATERRO DE ARGILA SILTOSA, MARROM', '1,20 - 3,45 AREIA FINA SILTOSA, CINZA, POUCO COMPACTA',
           "NIVEL D'AGUA: 2,30 m", 'IMPENETRAVEL A PERCUSSAO', 'PROFUNDIDADE FINAL: 3,45 m']


def testar_carimbo_desenhado(pasta):
    """O carimbo que é desenho vai ao OCR em recorte: campo que os dois leram igual é confirmado; o que leram diferente
    fica divergente com os dois valores; o que só um leu fica so_glm — nunca vira fato."""
    from PIL import Image
    imagem = pasta / 'carimbo.png'
    Image.new('RGB', (800, 400), 'white').save(imagem)
    glm, vision = ia.ler_com_glm_ocr, ia.ler_com_vision
    ia.ler_com_glm_ocr = lambda c: {'texto': 'CREA: PR-12345/D\nRESP. TECNICO: ENG. JOAO DA SILVA\nART: 1720203456789'}
    ia.ler_com_vision = lambda c: {'texto': 'CREA: PR-12345/D\nRESP. TECNICO: ENG. JOSE DA SILVA'}
    try:
        linhas = {l['campo']: l for l in prancha.ler_carimbo_ocr(imagem, 'x.pdf', True, {'id': 'x'})}
    finally:
        ia.ler_com_glm_ocr, ia.ler_com_vision = glm, vision
    conferir((linhas['crea']['status'], linhas['responsavel_tecnico']['status'], linhas['art']['status']) == ('confirmado', 'divergente', 'so_glm')
             and linhas['responsavel_tecnico']['valor_vision'] == 'ENG. JOSE DA SILVA',
             'carimbo desenhado: CREA confirmado pelos dois; o responsável que leram diferente fica divergente com os dois; a ART que só o glm-ocr leu fica pendente')


def testar_sondagem(raiz):
    """O boletim de sondagem (A4) é reconhecido e lido por camada: o de texto pelo código (furo, coordenadas, cota da boca,
    nível d'água, profundidade final, N-SPT de cada metro, camadas), o digitalizado pelo OCR, com os dois leitores — o
    metro que só um leu fica pendente e a cota que leram diferente fica divergente."""
    from PIL import Image
    pasta = raiz / 'extracao' / 'projetos'
    (pasta / 'boletim.pdf').write_bytes(pdf_de_texto(BOLETIM))
    Image.new('RGB', (595, 842), 'white').save(pasta / 'boletim_escaneado.pdf')
    pl.DataFrame([{'id': f'ARQ-000001/{nome}', 'extrator': 'entrega', 'caminho': f'obras/foz.zip/{nome}', 'arquivo': nome, 'versao': f'sha-{nome}',
                   'candidata': True, 'arquivo_local': str(pasta / local)}
                  for nome, local in (('SP-03.pdf', 'boletim.pdf'), ('BOLETIM_SP-04.pdf', 'boletim_escaneado.pdf'))]
                 ).write_parquet(raiz / 'extracao' / 'projeto_entrega' / 'parte_08.parquet')
    texto_vision = '\n'.join(l.replace('812,45', '812,46') for l in BOLETIM if not l.startswith('3,00')).replace('SP-03', 'SP-04')
    ia.ler_com_glm_ocr = lambda c: {'texto': '\n'.join(BOLETIM).replace('SP-03', 'SP-04')}
    ia.ler_com_vision = lambda c: {'texto': texto_vision}
    ciclo.rodada()
    perfis = {l['arquivo']: l for l in comum.ler('prancha').to_dicts() if l['extrator'] == 'prancha'}
    campos = {(l['arquivo'], l['campo']): l for l in comum.ler('sondagem_campo').to_dicts()}
    spt = {(l['arquivo'], l['profundidade_m']): l for l in comum.ler('sondagem_spt').to_dicts()}
    camadas = [l for l in comum.ler('sondagem_camada').to_dicts() if l['arquivo'] == 'SP-03.pdf']
    conferir(perfis['SP-03.pdf']['boletim_sondagem'] and perfis['BOLETIM_SP-04.pdf']['boletim_sondagem']
             and not perfis['SP-03.pdf']['e_prancha'] and perfis['SP-03.pdf']['formato'] == 'A4',
             'sondagem: o boletim A4 com texto (pelos sinais) e o digitalizado (pelo nome) são reconhecidos, e não como prancha')
    texto = {c: campos[('SP-03.pdf', c)]['valor'] for c in ('furo', 'coordenada_e', 'coordenada_n', 'cota_boca', 'nivel_agua', 'profundidade_final', 'data')}
    conferir(texto == {'furo': 'SP-03', 'coordenada_e': '712.400', 'coordenada_n': '7.098.200', 'cota_boca': '812,45', 'nivel_agua': '2,30',
                       'profundidade_final': '3,45', 'data': '12/03/2021'}
             and 'IMPENETRAVEL' in campos[('SP-03.pdf', 'paralisacao')]['valor']
             and [(spt[('SP-03.pdf', m)]['nspt'], spt[('SP-03.pdf', m)]['status']) for m in (1.0, 2.0, 3.0)] == [(9, 'codigo'), (14, 'codigo'), (27, 'codigo')]
             and [(c['de_m'], c['ate_m']) for c in sorted(camadas, key=lambda c: c['de_m'])] == [(0.0, 1.2), (1.2, 3.45)],
             f'sondagem com texto, pelo código: furo, coordenadas, cota da boca, N.A., profundidade final, paralisação, N-SPT de cada metro '
             f'(soma dos dois últimos trechos) e as camadas ({texto})')
    conferir(campos[('BOLETIM_SP-04.pdf', 'furo')]['status'] == 'confirmado' and campos[('BOLETIM_SP-04.pdf', 'cota_boca')]['status'] == 'divergente'
             and campos[('BOLETIM_SP-04.pdf', 'cota_boca')]['valor_vision'] == '812,46'
             and (spt[('BOLETIM_SP-04.pdf', 1.0)]['status'], spt[('BOLETIM_SP-04.pdf', 3.0)]['status']) == ('confirmado', 'so_glm'),
             'sondagem digitalizada, pelo OCR: o furo que os dois leram é confirmado, a cota que leram diferente fica divergente, '
             'o metro que só o glm-ocr leu fica pendente')
    drive = Path(os.environ['DRIVE_FALSO']) / 'saida' / 'obras' / 'Foz AAT-06' / 'projeto'
    conferir(all((drive / n).exists() for n in ('sondagens.csv', 'sondagem_spt.csv', 'sondagem_camadas.csv', 'carimbos.csv')),
             'sondagem: sondagens, N-SPT e camadas publicados na pasta da obra')


def resposta(demanda, pasta, anexos, de='equipe@exemplo.com.br'):
    """Uma resposta guardada como o ialocal.web (0v8) guarda: <demanda>/<pasta>/anexos/, corpo.txt e meta.json."""
    destino = respostas.RESPOSTAS / demanda / pasta
    (destino / 'anexos').mkdir(parents=True)
    for nome, conteudo in anexos.items():
        (destino / 'anexos' / nome).write_bytes(conteudo)
    (destino / 'corpo.txt').write_text('segue o material')
    (destino / 'meta.json').write_text(json.dumps({'demanda': demanda, 'de': de, 'contato': 'equipe', 'assunto': f'Re: [demanda {demanda}]',
                                                   'message_id': f'<{pasta}@exemplo>', 'recebido_em': f'2026-10-03T{pasta[:2]}:00:00',
                                                   'anexos': sorted(anexos)}))


def testar_respostas(raiz):
    """A equipe responde a demanda por e-mail direto ao mini: o PDF anexo entra na rodada (obra _demandas/<demanda>) e
    é lido como os outros; o CSV é o gabarito. A demanda respondida sai da lista; o resultado (acerto por campo, as
    divergências) sai no status para o maestro e o web levarem ao Caio. O CSV do Excel (cp1252, vírgula) também vale."""
    boletim = [l.replace('SP-03', 'SP-05') for l in BOLETIM]
    gabarito = ('arquivo;furo;coordenada_e;coordenada_n;cota_boca;nivel_agua;profundidade_final;nspt_1m;nspt_2m;nspt_3m\n'
                'SP-05.pdf;SP-05;712.400;7.098.200;812,45;2,30;3,45;9;14;28\n')
    resposta('projeto-boletins-reais', '10-00_boletins', {'SP-05.pdf': pdf_de_texto(boletim), 'gabarito_sondagem.csv': gabarito.encode('utf-8-sig')})
    resposta('projeto-carimbos-conferir', '11-00_carimbos',
             {'carimbos_conferidos.csv': 'arquivo,campo,valor,conferido,correto\nx.pdf,crea,PR-1,c,\nx.pdf,titulo,ADUTORA,p,\nx.pdf,art,17,e,1720\n'.encode('cp1252')})
    ciclo.rodada()
    status = json.loads((comum.SAIDAS / 'status.json').read_text())
    resultados = {r['demanda']: r for r in status['resultados']}
    sondagem = resultados['projeto-boletins-reais']
    conferir(not {d['id'] for d in status['demandas']} & {'projeto-boletins-reais', 'projeto-carimbos-conferir'}
             and status['precisa_do_caio'] == len(status['demandas']) and sondagem['id'] == 'projeto-boletins-reais-resultado-1',
             'resposta guardada pelo web: a demanda respondida sai da lista do Caio e vira um resultado, com id próprio')
    conferir('PDFs lidos: 1 de 1' in sondagem['texto'] and 'Acerto contra o gabarito: 8 de 9 campos' in sondagem['texto']
             and "nspt_3m: lido '27' × gabarito '28'" in sondagem['texto']
             and status['por_obra']['_demandas/projeto-boletins-reais']['feito'] == 1,
             f"o boletim anexo é lido na rodada (obra _demandas) e medido contra o gabarito, com a divergência ({sondagem['texto'].splitlines()[2]})")
    conferir('Conferência da equipe: 1 de 3 campos certos' in resultados['projeto-carimbos-conferir']['texto']
             and 'art: 0 certo, 0 parcial, 1 errado' in resultados['projeto-carimbos-conferir']['texto'],
             'carimbos conferidos (CSV do Excel, cp1252 e vírgula): o acerto por campo')
    resposta('projeto-boletins-reais', '12-00_mais', {'SP-06.pdf': pdf_de_texto([l.replace('SP-03', 'SP-06') for l in BOLETIM])})
    ciclo.rodada()
    status = json.loads((comum.SAIDAS / 'status.json').read_text())
    conferir({r['id'] for r in status['resultados']} >= {'projeto-boletins-reais-resultado-2'}
             and 'PDFs lidos: 2 de 2' in next(r['texto'] for r in status['resultados'] if r['demanda'] == 'projeto-boletins-reais'),
             'resposta nova da mesma demanda: lida na rodada seguinte, e um resultado novo (outro id) com tudo o que chegou')


def servidor_nvidia(responder):
    """A API da NVIDIA falsa, numa thread em 127.0.0.1: cada POST guarda o pedido e devolve responder(corpo) —
    (código HTTP, corpo da resposta, cabeçalhos). Devolve (endereço, pedidos, servidor)."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    pedidos = []

    class Falsa(BaseHTTPRequestHandler):
        def do_POST(self):
            corpo = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            pedidos.append({'corpo': corpo, 'autorizacao': self.headers.get('Authorization'), 'em': time.monotonic()})
            codigo, resposta, cabecalhos = responder(corpo)
            texto = json.dumps(resposta).encode()
            self.send_response(codigo)
            for nome, valor in {'Content-Type': 'application/json', **cabecalhos}.items():
                self.send_header(nome, valor)
            self.send_header('Content-Length', str(len(texto)))
            self.end_headers()
            self.wfile.write(texto)

        def log_message(self, *argumentos):
            pass

    servidor = ThreadingHTTPServer(('127.0.0.1', 0), Falsa)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return f'http://127.0.0.1:{servidor.server_port}/v1/chat/completions', pedidos, servidor


def resposta_nvidia(modelo, conteudo='', ferramentas=()):
    return {'model': modelo, 'usage': {'prompt_tokens': 1200, 'completion_tokens': 80},
            'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': conteudo, 'reasoning_content': 'pensando…',
                                                              'tool_calls': [{'type': 'function', 'function': {'name': 'markdown_bbox', 'arguments': a}}
                                                                             for a in ferramentas]}}]}


def testar_agentes(raiz):
    """Os agentes externos (MASTER-PLAN §5.6) pela API falsa: os dois leem a mesma imagem em paralelo; o 429 espera e
    tenta de novo; a resposta é congelada (a segunda sonda não chama) e a chave da API não vai ao congelamento; a tabela
    do Kimi (HTML em cerca) e a do Parse (caixas nos argumentos da ferramenta) viram linhas, medidas contra o gabarito
    de Cambé; erro de um agente vira leitura vazia com o motivo; desligado, fora do prazo ou sem chave, nada é chamado."""
    import agentes
    from PIL import Image
    AGENTES = comum.configuracao('agentes')
    original = json.loads(json.dumps(AGENTES))
    agentes.REGISTRO, agentes.SONDA = comum.DADOS / 'agentes.jsonl', comum.DADOS / 'agentes_sonda.jsonl'
    TABELA = ('<table><tr><td>CÓDIGO</td><td>Nº</td><td>DISCRIMINAÇÃO</td><td>QUANT.</td><td>UND.</td></tr>'
              '<tr><td>298738</td><td>S/N</td><td>TUBO POLIETILENO PE 100 PN 10 DE 63</td><td>1634,9</td><td>M</td></tr>'
              '<tr><td>294924</td><td>S/N</td><td>LUVA POLIETILENO</td><td>38</td><td>UN.</td></tr>'
              '<tr><td>999999</td><td>S/N</td><td>INVENTADA</td><td>1</td><td>UN</td></tr></table>')
    vez = {'kimi': 0}

    def responder(corpo):
        time.sleep(0.4)
        if corpo['model'] == 'moonshotai/kimi-k3':
            vez['kimi'] += 1
            if vez['kimi'] == 1:
                return 429, {'error': 'Too Many Requests'}, {'Retry-After': '0'}
            if 'erro400' in json.dumps(corpo):
                return 400, {'error': 'bad request'}, {}
            return 200, resposta_nvidia('moonshotai/kimi-k3', f'```html\n{TABELA}\n```'), {}
        marcas = f'<x_0.05><y_0.1>{TABELA}<x_0.95><y_0.9><class_Table><x_0.05><y_0.0>TABELA 01<x_0.5><y_0.05><class_Title>'
        return 200, resposta_nvidia('nvidia/nemotron-parse-2.0', marcas), {}

    endereco, pedidos, servidor = servidor_nvidia(responder)
    os.environ['NVIDIA_API_KEY'] = 'nvapi-segredo-do-teste'
    AGENTES.update(endpoint=endereco, espera_s=0, ligado=True, prazo_fim='2999-12-31')
    AGENTES['provedores']['nvidia']['por_minuto'] = 6000
    try:
        imagem = raiz / 'agentes' / 'Tabela 01.png'
        imagem.parent.mkdir()
        Image.new('RGB', (900, 600), 'white').save(imagem)
        lidas = {l['agente']: l for l in agentes.sondar([imagem])}
        primeira = len(pedidos)
        kimi, parse = lidas['kimi'], lidas['parse']
        conferir(kimi['placar'] == {'gabarito': 9, 'achadas': 2, 'certas': 1, 'inventadas': 1, 'lidas': 4}
                 and parse['placar']['certas'] == 1 and parse['caixas'][0]['caixa'] == (0.05, 0.1, 0.95, 0.9)
                 and parse['caixas'][0]['classe'] == 'Table',
                 'sonda: a tabela do Kimi (HTML em cerca) e a do Parse (marcas de posição com a classe) viram linhas; contra o gabarito de '
                 'Cambé, 1 certa (código, quantidade e unidade), a de quantidade errada só achada e a de código inventado contada')
        meta = kimi['meta']
        conferir(meta['motivos'] == ['429'] and 0.3 <= meta['segundos_util'] < 1.5 and 0.3 <= meta['segundos_falhas'] < 1.5
                 and meta['segundos_espera'] >= 0,
                 f"o tempo separa o modelo do plano: útil {meta['segundos_util']} s (a tentativa que deu certo), perdido "
                 f"{meta['segundos_falhas']} s na tentativa recusada (429) e {meta['segundos_espera']} s de espera")
        conferir(kimi['meta']['tentativas'] == 2 and primeira == 3
                 and all(p['autorizacao'] == 'Bearer nvapi-segredo-do-teste' for p in pedidos)
                 and all(p['corpo']['messages'][0]['content'][-1]['image_url']['url'].startswith('data:image/png;base64,') for p in pedidos)
                 and (lambda corpo: 'tools' not in corpo and 'max_tokens' not in corpo
                      and corpo['messages'][0]['content'][0]['text'].startswith('</s><s><predict_bbox>'))(
                     next(p for p in pedidos if 'parse' in p['corpo']['model'])['corpo']),
                 'a porta: 429 espera o Retry-After e tenta de novo; a chave vai no cabeçalho; a imagem como data URI; o Parse com as '
                 'marcas de controle antes da imagem e sem ferramenta (a API recusou o tool_choice na sonda de 04/10)')
        agentes.sondar([imagem])
        import contextlib
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            agentes.respostas('kimi', [imagem])
        conferir('kimi-k3' in saida.getvalue() and 'linhas 4' in saida.getvalue() and 'fim stop' in saida.getvalue(),
                 'agentes.py respostas: a última resposta crua de cada agente por recorte, com como parou e quantas linhas deu')
        conferir(len(pedidos) == primeira and 'nvapi-segredo' not in ia.CONGELAMENTO.read_text()
                 and 'pensando' not in ia.CONGELAMENTO.read_text(),
                 'a resposta é congelada (a segunda sonda não chama a API); nem a chave nem o raciocínio vão ao congelamento')
        recortes = []
        for numero in range(2):
            recortes.append(raiz / 'agentes' / f'fatia{numero}.png')
            Image.new('RGB', (300, 300), (numero, 255, 255)).save(recortes[-1])
        marca, antes = time.monotonic(), len(pedidos)
        lidas = list(agentes.em_paralelo(recortes, modo='tabela'))
        segundos = time.monotonic() - marca
        conferir(len(lidas) == 4 and len(pedidos) - antes == 4 and segundos < 1.2 and not any(l['erro'] for l in lidas),
                 f'em paralelo: 2 recortes × 2 agentes, cada pedido de 0,4 s, em {segundos:.1f} s (um por vez seriam 1,6 s)')
        AGENTES['agentes']['kimi']['prompt'] = {**AGENTES['agentes']['kimi']['prompt'], 'texto': 'agente_texto'}
        AGENTES['agentes']['kimi']['max_tokens'] = 'erro400'
        errada = agentes.ler_com_agente('kimi', recortes[0])
        conferir(errada['erro'].startswith('RuntimeError: NVIDIA 400') and errada['linhas'] == [],
                 'erro 400 de um agente: leitura vazia com o motivo, sem tentar de novo e sem subir erro')
        antes = len(pedidos)
        motivos = []
        for mudanca in ({'ligado': False}, {'prazo_fim': '2020-01-01'}, {'obras_permitidas': ['orcamentos/saic']}):
            AGENTES.update({'ligado': True, 'prazo_fim': '2999-12-31', 'obras_permitidas': ['*'], **mudanca})
            motivos.append(agentes.ler_com_agente('parse', recortes[0], obra='orcamentos/outra')['erro'])
        AGENTES.update(ligado=True, prazo_fim='2999-12-31', obras_permitidas=['*'])
        del os.environ['NVIDIA_API_KEY']
        AGENTES['chave'] = str(raiz / 'sem_chave')
        motivos.append(agentes.ler_com_agente('parse', recortes[0])['erro'])
        conferir(len(pedidos) == antes and [m.split(' ')[0] for m in motivos] == ['agentes', 'fora', 'obra', 'sem'],
                 'desligado, fora do prazo da exceção, obra fora da lista ou sem chave: nada é chamado, e o motivo fica')
        registro = [json.loads(l) for l in agentes.REGISTRO.read_text().splitlines()]
        conferir(all(r['agente'] in ('kimi', 'parse') and 'versao_codigo' in r for r in registro)
                 and any(r['congelado'] for r in registro) and 'nvapi-segredo' not in agentes.REGISTRO.read_text(),
                 'cada chamada fica em dados/agentes.jsonl (agente, modelo, recorte, obra, tempo, tokens, erro), sem a chave')
    finally:
        servidor.shutdown()
        os.environ.pop('NVIDIA_API_KEY', None)
        AGENTES.clear()
        AGENTES.update(original)


def testar_formatos_dos_agentes():
    """O que os agentes podem devolver: o Parse em marcas <x_><y_>…<class_> no texto; a tabela em LaTeX (o modo markdown
    do Parse) e em markdown com barras; o raciocínio que vaza em <think> sai."""
    import agentes
    marcas = '<x_0.1><y_0.2>EST 77<x_0.3><y_0.25><class_Text><x_0.1><y_0.5>1:2000<x_0.2><y_0.55><class_Text>'
    elementos = agentes.elementos_do_parse({'texto': marcas, 'ferramentas': []})
    ferramenta = agentes.elementos_do_parse({'texto': '', 'ferramentas': [json.dumps(
        [[{'bbox': {'xmin': 0.1, 'ymin': 0.2, 'xmax': 0.3, 'ymax': 0.25}, 'text': 'EST 77', 'type': 'Text'}]])]})
    conferir([e['texto'] for e in elementos] == ['EST 77', '1:2000'] and elementos[0]['caixa'] == (0.1, 0.2, 0.3, 0.25)
             and ferramenta == [{'classe': 'Text', 'texto': 'EST 77', 'caixa': (0.1, 0.2, 0.3, 0.25)}],
             'Parse: as marcas de posição no texto e os argumentos da ferramenta viram elementos com caixa')
    latex = '\\begin{tabular}{lll}\\hline 298738 & TUBO & 1634,9 \\\\ \\multicolumn{2}{c}{TOTAL} & 1634,9 \\\\ \\hline\\end{tabular}'
    barras = '| CÓDIGO | QUANT. |\n|---|---|\n| 298738 | 1634,9 |\n| 298738 | 1634,9 |'
    conferir(agentes.linhas_da_tabela(latex) == [['298738', 'TUBO', '1634,9'], ['TOTAL', '1634,9']]
             and agentes.linhas_da_tabela(barras) == [['CÓDIGO', 'QUANT.'], ['298738', '1634,9']]
             and agentes.sem_cerca('<think>hmm</think>\n```\nEST 77\n```') == 'EST 77',
             'tabela em LaTeX e em markdown viram linhas (a repetida sai); o <think> e a cerca saem')


def testar_curadoria():
    """A curadoria em Python: o valor com testemunha (Vision) e mais um leitor é confirmada; dois generativos de
    famílias diferentes sem testemunha, confirmada_ia (não é fato); um só leitor, so_<leitor>; valores diferentes sem
    testemunha, divergente. Contra a testemunha, a quantidade que o Vision viu vence a maioria."""
    import curadoria
    linha = lambda codigo, quant, und='UN.': [codigo, 'S/N', 'MATERIAL', quant, und]
    curadas = curadoria.curar_tabela({
        'glm_ocr': [linha('298738', '1634,9', 'M'), linha('294924', '38'), linha('309341', '6')],
        'kimi': [linha('298738', '1634,9', 'M.'), linha('294924', '33'), linha('275476', '2'), linha('309341', '9')],
        'parse': [linha('294924', '38'), linha('275476', '2'), linha('277428', '1')]},
        testemunha='298738 S/N TUBO 1634,9 M\n294924 S/N LUVA 33 UN.')
    conferir({c: (v['status'], v['quant']) for c, v in curadas.items()} == {
        '298738': ('confirmada', '1634.9'), '294924': ('confirmada', '33'), '275476': ('confirmada_ia', '2'),
        '277428': ('so_parse', '1'), '309341': ('divergente', '6')},
        'curadoria: Vision e mais um leitor confirmam (a unidade M. é M); o 33 que o Vision viu vence o 38 de dois '
        'generativos; dois generativos sem testemunha, confirmada_ia; um só, so_parse; dois valores sem testemunha, divergente')


def testar_bancada(raiz):
    """A bancada da F2 com todos os candidatos falsos: na tabela 01 de Cambé (9 linhas no gabarito) o Kimi lê as 9, o
    Parse 7 certas, 1 errada e 1 inventada, o glm-ocr 5, o qwen3 monta as 9 com o texto do Vision, e o Vision vê todos
    os números (presença, sem estrutura). A curadoria local confirma 5; com o Kimi ou o qwen3, 9. Kimi e qwen3
    continuam; o Parse inventa e escreve número no recorte em branco: descontinua. O tempo útil, a taxa de erro e o
    tempo perdido (429 do plano, fila da GPU) saem separados. No boletim com texto real, o gabarito é a leitura do
    código: o Kimi acerta tudo, o Parse erra um N-SPT e inventa um metro."""
    import agentes
    import bancada
    import shutil
    pasta = raiz / 'cambe'
    pasta.mkdir()
    shutil.copy(comum.RAIZ / 'amostras' / 'tabelas' / '216_cambe' / 'Tabela 01.png', pasta / 'Tabela 01.png')
    bancada.CAMBE, bancada.PASTA = pasta, comum.DADOS / 'bancada'
    gabarito = agentes.gabarito_cambe()['TABELA 01']
    linha = lambda g, quant=None: [g['codigo'], 'S/N', 'MATERIAL', quant or g['quant'], g['und']]
    kimi = [linha(g) for g in gabarito]
    parse = [linha(g) for g in gabarito[:7]] + [linha(gabarito[7], '99'), ['123456', 'S/N', 'X', '1', 'UN']]
    glm = [linha(g) for g in gabarito[:5]]
    vision = '\n'.join(' '.join(linha(g)) for g in gabarito)
    texto_boletim = '\n'.join(BOLETIM)
    errado = texto_boletim.replace('3,00 10/15 12/15 15/15', '3,00 10/15 12/15 16/15') + '\n4,00 20/15 22/15 25/15'
    texto_de = lambda linhas: '\n'.join(' '.join(c) for c in linhas)

    def externos(imagens, modo):
        lidas = {}
        for imagem in imagens:
            nome = Path(imagem).name
            if nome.startswith('Tabela'):
                textos = {'kimi': (texto_de(kimi), kimi), 'parse': (texto_de(parse), parse)}
            elif 'pagina' in nome:
                textos = {'kimi': (texto_boletim, []), 'parse': (errado, [])}
            else:
                textos = {'kimi': ('', []), 'parse': ('LEGENDA 1 2', [])}
            for agente, (texto, linhas) in textos.items():
                meta = {'segundos_util': 20.0 if agente == 'kimi' else 30.0, 'segundos_espera': 5.0, 'segundos_falhas': 0.0,
                        'tentativas': 2, 'motivos': ['429'], 'congelado': False}
                lidas[(agente, str(imagem))] = {'agente': agente, 'recorte': str(imagem), 'texto': texto, 'linhas': linhas,
                                                'segundos': 25.0, 'erro': '', 'meta': meta}
        return lidas

    def locais(imagens, modo):
        lidas = {}
        for imagem in imagens:
            tabela = Path(imagem).name.startswith('Tabela')
            lidas[str(imagem)] = {
                'vision': {'linhas': [], 'texto': vision if tabela else '', 'erro': '', 'util': 1.0, 'congelado': False},
                'glm_ocr': {'linhas': glm if tabela else [], 'texto': texto_de(glm) if tabela else '', 'erro': '', 'util': 8.0, 'congelado': False}}
            if tabela:
                lidas[str(imagem)]['qwen3'] = {'linhas': kimi, 'texto': texto_de(kimi), 'erro': '', 'util': 12.0, 'congelado': False}
        return lidas, 9.0
    bancada.externos, bancada.locais = externos, locais
    bancada.tabelas()
    bancada.controle()
    boletim = raiz / 'SP-03.pdf'
    boletim.write_bytes(pdf_de_texto(BOLETIM))
    bancada.sondagem_bancada([boletim], com_local=False)
    saida = bancada.placar(publicar=False)
    pega = lambda conjunto, leitor: saida.filter((pl.col('conjunto') == conjunto) & (pl.col('leitor') == leitor)).to_dicts()[0]
    conferir((pega('tabelas', 'kimi')['certas'], pega('tabelas', 'parse')['certas'], pega('tabelas', 'parse')['erradas'],
              pega('tabelas', 'parse')['inventadas'], pega('tabelas', 'local')['confirmadas_certas'],
              pega('tabelas', 'local+kimi')['confirmadas_certas'], pega('tabelas', 'local+qwen3')['confirmadas_certas'],
              pega('tabelas', 'local+parse')['confirmadas_erradas'], pega('tabelas', 'vision')['presenca'], pega('tabelas', 'vision')['certas'])
             == (9, 7, 1, 1, 5, 9, 9, 0, 1.0, 0),
             'bancada das tabelas com todos os candidatos: cada leitor contra as 9 linhas; a curadoria local confirma 5, com o '
             'Kimi ou com o qwen3 (que monta a tabela com o texto do Vision) 9; a linha errada do Parse não vira confirmada; '
             'o Vision, sem estrutura de tabela, é medido pela presença (9 de 9)')
    kimi_t, glm_t = pega('tabelas', 'kimi'), pega('tabelas', 'glm_ocr')
    conferir(kimi_t['util_mediana_s'] == 20.0 and kimi_t['n_429'] == 1 and kimi_t['perdido_pct'] == 0.2 and kimi_t['taxa_erro'] == 0
             and kimi_t['provedor'] == 'nvidia' and glm_t['provedor'] == 'gpu' and glm_t['perdido_pct'] == round(3 / 11, 3),
             'as quatro medidas separadas: tempo útil 20 s, erro 0 %, perdido 20 % do tempo (o 429 do plano) e 1 recusa no Kimi; '
             'no glm-ocr, a fila da GPU (9 s rateados entre 3 chamadas locais) é o perdido')
    conferir(pega('tabelas', 'kimi')['veredito'] == 'continua' and pega('tabelas', 'qwen3')['veredito'] == 'continua'
             and pega('tabelas', 'parse')['veredito'] == 'descontinua'
             and 'inventa no controle' in pega('tabelas', 'parse')['motivo'] and pega('controle', 'parse')['inventadas'] == 3,
             f"veredito pelos critérios do §7 para todos os candidatos: kimi e qwen3 continuam; parse descontinua "
             f"({pega('tabelas', 'parse')['motivo']})")
    kimi_b, parse_b = pega('sondagem', 'kimi'), pega('sondagem', 'parse')
    conferir(kimi_b['erradas'] == kimi_b['faltou'] == kimi_b['inventadas'] == 0 and kimi_b['certas'] >= 8
             and parse_b['erradas'] == 1 and parse_b['inventadas'] == 1,
             f"bancada do boletim com texto real (gabarito = leitura do código): kimi {kimi_b['certas']} certas; parse erra o "
             f"N-SPT do 3º metro e inventa o 4º")
    conferir((comum.SAIDAS / 'bancada_agentes.csv').exists(), 'o placar sai em saidas/bancada_agentes.csv (no mini, também no Drive)')


def principal():
    with tempfile.TemporaryDirectory() as temporaria:
        raiz = Path(temporaria)
        (raiz / 'bin').mkdir()
        (raiz / 'bin' / 'rclone').write_text(RCLONE_FALSO)
        (raiz / 'bin' / 'rclone').chmod(0o755)
        os.environ.update(DRIVE_FALSO=str(raiz / 'drive'), PATH=f"{raiz / 'bin'}:{os.environ['PATH']}")
        comum.DADOS, comum.SAIDAS, comum.EXTRATOR = raiz / 'dados', raiz / 'saidas', raiz / 'extracao'
        ia.CONGELAMENTO, ciclo.FALHAS = comum.DADOS / 'congelamento.jsonl', comum.DADOS / 'falhas.jsonl'
        comum.DADOS.mkdir()
        ia.OLLAMA = 'http://127.0.0.1:9'  # porta fechada: nenhum teste chama modelo de verdade
        ia.instalado = lambda modulo: modulo in sys.modules  # no mini o Vision e o Apple FM existem: só o falso do teste conta
        respostas.RESPOSTAS = raiz / 'web' / 'demandas'  # no mini a pasta do web existe: só as respostas do teste contam
        cliente_gpu.VEZ = raiz / 'sem_maestro' / 'vez.json'  # no mini o maestro está de pé e nunca daria a vez ao pedido da pasta do teste
        testar_conceitos()
        testar_regras(raiz)
        testar_eixo_por_camada()
        testar_rodada(raiz)
        testar_falha(raiz)
        testar_carimbo_desenhado(raiz)
        testar_sondagem(raiz)
        testar_respostas(raiz)
        testar_formatos_dos_agentes()
        testar_agentes(raiz)
        testar_curadoria()
        testar_bancada(raiz)


if __name__ == '__main__':
    principal()
