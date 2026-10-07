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
from datetime import datetime
from pathlib import Path

import polars as pl

import ciclo
import cliente_gpu
import comum
import ia
import prancha
import respostas

LER_COM_VISION = ia.ler_com_vision  # a de verdade: outros testes trocam ia.ler_com_vision por uma falsa

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
    vez = {'kimi': 0, 'vazia': False}

    def responder(corpo):
        time.sleep(0.4)
        if corpo['model'] == 'moonshotai/kimi-k3':
            vez['kimi'] += 1
            if vez['kimi'] == 1:
                return 429, {'error': 'Too Many Requests'}, {'Retry-After': '0'}
            if 'erro400' in json.dumps(corpo):
                return 400, {'error': 'bad request'}, {}
            return 200, resposta_nvidia('moonshotai/kimi-k3', '' if vez['vazia'] else f'```html\n{TABELA}\n```'), {}
        marcas = f'<x_0.05><y_0.1>{TABELA}<x_0.95><y_0.9><class_Table><x_0.05><y_0.0>TABELA 01<x_0.5><y_0.05><class_Title>'
        return 200, resposta_nvidia('nvidia/nemotron-parse-2.0', marcas), {}

    endereco, pedidos, servidor = servidor_nvidia(responder)
    os.environ['NVIDIA_API_KEY'] = 'nvapi-segredo-do-teste'
    AGENTES.update(endpoint=endereco, espera_s=0, ligado=True, prazo_fim='2999-12-31')
    AGENTES['agentes']['parse']['ligado'] = True  # descontinuado no mini (04/10); o código dele segue testado
    reservas = [n for n in AGENTES['agentes'] if n not in ('kimi', 'parse')]
    conferir({'glm_flash', 'muse', 'deepseek_flash'} <= set(reservas) and all(AGENTES['agentes'][n]['tipo'] == 'vlm' for n in reservas),
             'os reservas (05/10) são agentes vlm: entram na bancada pelo mesmo leitor do Kimi')
    for nome in reservas:  # a porta é medida com os dois de sempre: os reservas usam o mesmo leitor do Kimi
        AGENTES['agentes'][nome]['ligado'] = False
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
                 and next(p for p in pedidos if 'kimi' in p['corpo']['model'])['corpo']['temperature'] == 0.6
                 and (lambda corpo: 'tools' not in corpo and 'max_tokens' not in corpo and corpo['temperature'] == 0
                      and corpo['repetition_penalty'] == 1.1 and corpo['top_k'] == 1 and corpo['skip_special_tokens'] is False
                      and corpo['messages'][0]['content'][0]['text'].startswith('</s><s><predict_bbox>'))(
                     next(p for p in pedidos if 'parse' in p['corpo']['model'])['corpo']),
                 'a porta: 429 espera o Retry-After e tenta de novo; a chave vai no cabeçalho; a imagem como data URI; o Parse com as '
                 'marcas de controle antes da imagem e sem ferramenta (a API recusou o tool_choice na sonda de 04/10), com '
                 'repetition_penalty 1,1, top_k 1 e as marcas preservadas; o Kimi a temperatura 0,6 (a 0 degenerou)')
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
        AGENTES['agentes']['parse']['ligado'] = False
        antes = len(pedidos)
        nova = raiz / 'agentes' / 'nova.png'
        Image.new('RGB', (300, 300), (7, 7, 7)).save(nova)
        so_kimi = list(agentes.em_paralelo([nova], modo='tabela'))
        AGENTES['agentes']['parse']['ligado'] = True
        conferir([l['agente'] for l in so_kimi] == ['kimi'] and len(pedidos) - antes == 1 and agentes.ligados() == ['kimi', 'parse'],
                 'agente descontinuado (ligado false, §7 do plano): a leitura em paralelo não o chama; o código e o congelamento ficam')
        vazio = raiz / 'agentes' / 'vazio.png'
        Image.new('RGB', (300, 300), (9, 9, 9)).save(vazio)
        vez['vazia'], antes = True, len(pedidos)
        primeira_vazia = agentes.ler_com_agente('kimi', vazio, 'tabela')
        vez['vazia'] = False
        nova_chance = agentes.ler_com_agente('kimi', vazio, 'tabela')
        de_novo = agentes.ler_com_agente('kimi', vazio, 'tabela')
        conferir(primeira_vazia['erro'].startswith('RespostaRuim: vazia') and "pensou: 'pensando…'" in primeira_vazia['erro']
                 and len(nova_chance['linhas']) == 4
                 and not nova_chance['meta']['congelado'] and de_novo['meta']['congelado'] and len(pedidos) - antes == 2,
                 'a resposta ruim desta rodada conta como erro (a vazia diz o começo do que o modelo pensou); a que veio do congelamento ganha uma nova chamada (04/10: a bancada '
                 'repetia em 0,0 s as vazias do Kimi), e a boa fica no lugar dela')
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
    motivos = []
    for texto, meta in (('', {'fim': 'stop', 'tokens_saida': 32}), ('<table' + '!' * 30, {'fim': 'stop'}),
                        ('<x_' * 40, {'fim': 'length', 'tokens_saida': 4090}), ('<table><tr><td>298738</td></tr></table>', {'fim': 'stop'})):
        try:
            agentes.falha_da_resposta(texto, meta)
            motivos.append('ok')
        except RuntimeError as falha:
            motivos.append(str(falha).split(':')[0])
            ultimo = str(falha) if 'cortada' in str(falha) else locals().get('ultimo', '')
    conferir(motivos == ['vazia', 'degenerada', 'cortada', 'ok'] and "em laço de '<x_'" in ultimo,
             'resposta que não é leitura vira erro (taxa de erro), não leitura vazia: vazia, degenerada (o "!!!!" do Kimi a '
             'temperatura 0) e cortada no limite (o laço de 4.090 tokens do Parse)')
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


def palavras_de(linhas, altura=0.05):
    """Linhas de texto → as palavras com caixa, como o Vision dá: cada linha uma faixa de altura; cada palavra (texto,
    x0, x1) na posição dada."""
    return [{'texto': texto, 'x0': x0, 'x1': x1, 'y0': 0.02 + n * altura * 1.6, 'y1': 0.02 + n * altura * 1.6 + altura}
            for n, linha in enumerate(linhas) for texto, x0, x1 in linha]


def testar_grade():
    """O leitor só de código (codigo/grade.py), com as caixas das palavras numa tabela de Cambé: o cabeçalho dá as
    colunas; a quantidade alinhada à direita e a unidade saem certas mesmo quando a discriminação acaba em número; a
    linha sem a quantidade lida fica de fora (não pega o 'DE 63' da discriminação); a segunda relação empilhada, com o
    seu cabeçalho, repete o código; sem cabeçalho, a regra das pontas; 'UN,' é unidade."""
    import grade
    cabecalho = [('CÓDIGO', 0.01, 0.10), ('Nº', 0.12, 0.14), ('DISCRIMINAÇÃO', 0.35, 0.52), ('QUANT.', 0.85, 0.91), ('UND.', 0.93, 0.98)]
    material = lambda codigo, descricao, quant, und: ([(codigo, 0.03, 0.09), ('S/N', 0.12, 0.15)]
                                                      + [(p, 0.16 + 0.04 * n, 0.19 + 0.04 * n) for n, p in enumerate(descricao.split())]
                                                      + ([(quant, 0.90 - 0.012 * len(quant), 0.90)] if quant else []) + [(und, 0.94, 0.97)])
    palavras = palavras_de([
        cabecalho, [('REDE', 0.30, 0.38), ('DE', 0.39, 0.43), ('DISTRIBUIÇÃO', 0.44, 0.65)],
        material('298738', 'TUBO PE 100 PN 10 DE 63', '1634,9', 'M'),
        material('294924', 'LUVA PE 100 DE 63', '', 'UN.'),
        material('309341', 'TE PE 100 DN 50', '6', 'UN,'),
        cabecalho, material('298738', 'TUBO PE 100 PN 10 DE 63', '14', 'M')])
    linhas = grade.montar(palavras)
    sem_cabecalho = grade.montar(palavras_de([[('20117', 0.02, 0.08), ('S/N', 0.1, 0.13), ('ADAPTADOR', 0.15, 0.3),
                                               ('POL', 0.31, 0.35), ('2"', 0.36, 0.38), ('3', 0.88, 0.89), ('UN.', 0.94, 0.97)],
                                              [('LEGENDA', 0.1, 0.3), ('REDE', 0.32, 0.4), ('63', 0.5, 0.52)]]))
    conferir([[c[0], c[3], c[4]] for c in linhas] == [['298738', '1634,9', 'M'], ['309341', '6', 'UN,'], ['298738', '14', 'M']]
             and linhas[0][2] == 'TUBO PE 100 PN 10 DE 63' and linhas[0][1] == 'S/N'
             and sem_cabecalho == [['20117', 'S/N', 'ADAPTADOR POL 2"', '3', 'UN.']],
             'grade (só código): o cabeçalho dá as colunas; a linha sem quantidade lida fica de fora (não pega o "DE 63"); a '
             'relação empilhada repete o código; sem cabeçalho, código, unidade e quantidade pelas pontas; legenda não é linha')


VISION_TABELA_01 = """CÓDIGO@0.017-0.084 N°@0.096-0.124 DISCRIMINAÇÃO@0.411-0.555 QUANT.@0.848-0.925 UND@0.927-0.970
REDE@0.398-0.445 DE@0.448-0.467 DISTRIBUIÇÃO@0.470-0.591
298738@0.019-0.085 S/N@0.087-0.126 TUBO@0.128-0.181 POLIETILENO@0.184-0.290 PE@0.292-0.312 100@0.314-0.348 PN@0.350-0.375 10@0.377-0.401 (ROLO@0.404-0.454 COM@0.457-0.496 50,0@0.498-0.539 M)@0.541-0.563 DE@0.566-0.590 63@0.592-0.616 1634,9@0.848-0.912
294924@0.019-0.088 S/N@0.090-0.131 LUVA@0.133-0.181 POLIETILENO@0.183-0.289 PE@0.291-0.311 100@0.314-0.347 PN@0.349-0.374 16@0.376-0.398 PARA@0.401-0.446 ELTROFUSAO@0.448-0.554 DE@0.556-0.579 63@0.581-0.605 33@0.867-0.892 UN.@0.936-0.967
309341Śł@0.019-0.089 S/N@0.086-0.129 TE@0.132-0.156 POLIETILENO@0.158-0.262 PARA@0.265-0.308 ELETROFUSAO@0.310-0.426 BBP@0.429-0.460 PE@0.463-0.484 100@0.487-0.521 PN@0.523-0.547 16@0.550-0.571 DE@0.574-0.598 63@0.600-0.624 UN.@0.936-0.967
275476@0.017-0.084 S/N@0.086-0.125 TE@0.128-0.154 FD@0.156-0.180 JE@0.182-0.198 BBB@0.200-0.234 PARA@0.237-0.281 PVC@0.283-0.317 PBA@0.320-0.353 COM@0.356-0.397 ANEIS@0.400-0.446 CONFORME@0.449-0.545 NBR@0.547-0.581 15880@0.584-0.638 DNSO@0.641-0.696 UN.@0.936-0.967
275522@0.019-0.088 S/N@0.090-0.129 LUVA@0.131-0.181 DE@0.183-0.206 CORRER@0.208-0.274 FD@0.276-0.297 JE@0.299-0.318 PARA@0.320-0.365 PVC@0.367-0.401 PBA@0.403-0.438 COM@0.440-0.479 ANEIS@0.481-0.529 CONFORME@0.531-0.626 NBR@0.628-0.664 15880@0.666-0.722 DN5O@0.724-0.773 UN.@0.936-0.967
277428@0.017-0.085 S/N@0.088-0.128 CAP@0.132-0.166 FD@0.169-0.194 JE@0.197-0.212 PARA@0.215-0.259 PVC@0.262-0.296 PBA@0.299-0.330 COM@0.334-0.374 ANEL@0.377-0.421 CONFORME@0.424-0.517 NBR@0.520-0.554 15880@0.557-0.610 DN50@0.613-0.667 UN.@0.936-0.970
310410@0.019-0.084 S/N@0.086-0.125 LUVA@0.127-0.181 TRANSICAO@0.183-0.274 POLIETILENO@0.276-0.384 PE@0.386-0.407 100@0.409-0.442 PN@0.444-0.469 16@0.471-0.494 ELETROFUSAO@0.496-0.610 ROSCA@0.612-0.668 MACHO@0.670-0.734 DE@0.736-0.759 63@0.761-0.784 POL@0.786-0.821 2@0.823-0.837 З@0.873-0.887 UN.@0.936-0.967
30791@0.022-0.080 S/N@0.094-0.129 LUVA@0.131-0.181 FG@0.183-0.206 BSP@0.208-0.239 POL@0.241-0.276 2"@0.278-0.301 З@0.873-0.887 UN.@0.936-0.967
20117@0.022-0.086 S/N@0.094-0.130 ADAPTADOR@0.133-0.237 PVC@0.239-0.273 JE@0.275-0.292 BOLSA/ROSCA@0.295-0.411 COM@0.413-0.452 ANEL@0.454-0.498 DN50@0.500-0.548 POL@0.551-0.585 2"@0.587-0.608 UN.@0.936-0.967"""
# o que o Vision do mini leu na Tabela 01 de Cambé (04/10): pulou os algarismos sozinhos (6, 2, 3, 1, 3) e a unidade M,
# leu o 3 como o З cirílico e grudou 'Śł' no código 309341


def testar_grade_com_o_vision():
    """A grade com as palavras que o Vision do mini leu na Tabela 01 de Cambé: sem releitura, só 3 linhas (e o З vira
    3); com a releitura das 6 células vazias (5 quantidades e a unidade M), as 9 do gabarito certas; o código com
    'Śł' grudado é o 309341."""
    import agentes
    import bancada
    import curadoria
    import grade
    palavras = palavras_de([[(t.rsplit('@', 1)[0], float(t.rsplit('@', 1)[1].split('-')[0]), float(t.rsplit('@', 1)[1].split('-')[1]))
                             for t in linha.split(' ')] for linha in VISION_TABELA_01.splitlines()])
    pedidas = []

    def reler(caixas):
        pedidas.extend(caixas)
        return ['M', '6', '| 2 |', '3', '1', '3']
    gabarito = agentes.gabarito_cambe()['TABELA 01']
    certas = lambda linhas: sum(r['resultado'] == 'certa' for r in bancada.comparar(curadoria.por_codigo(linhas), gabarito, {}, {}, None))
    sem, com = grade.montar(palavras), grade.montar(palavras, reler)
    conferir((len(sem), certas(sem), certas(com), len(pedidas)) == (3, 3, 9, 6) and com[2][0] == '309341'
             and all(0.62 < c[0] < 0.86 and c[2] == pedidas[1][2] for c in pedidas[1:]) and pedidas[0][0] > 0.92,
             'grade com o Vision real da Tabela 01: sem releitura 3 linhas; relidas as 6 células vazias (o traço da grade sai), '
             '9 de 9 certas; o código com lixo grudado é o 309341')


def testar_celulas():
    """A releitura da célula: o recorte sai ampliado, sem os traços da grade (a coluna inteira escura) e com o
    algarismo; as células vão todas num processo só do Vision."""
    from PIL import Image, ImageDraw
    pasta = Path(tempfile.mkdtemp())
    imagem = Image.new('RGB', (200, 40), 'white')
    desenho = ImageDraw.Draw(imagem)
    desenho.line([(150, 0), (150, 39)], fill='black', width=2)  # traço da grade
    desenho.line([(110, 12), (110, 28)], fill='black', width=2)  # o "1"
    imagem.save(pasta / 'tabela.png')
    recorte = ia.recortar_celulas(pasta / 'tabela.png', [(0.5, 0.2, 0.9, 0.8)], pasta / 'celulas')[0]
    grande = Image.open(recorte).convert('L')
    escuros = lambda x0, x1: sum(1 for x in range(x0, x1) for y in range(grande.height) if grande.getpixel((x, y)) < 128)
    original = ia.VISION_CELULAS
    try:
        ia.VISION_CELULAS = [sys.executable, '-c', 'import json, sys; print(json.dumps({"textos": [str(len(sys.argv) - 1)] * (len(sys.argv) - 1)}))']
        lidos = ia.ler_celulas(pasta / 'tabela.png', [(0.5, 0.2, 0.9, 0.8), (0.1, 0.2, 0.4, 0.8)], pasta / 'celulas')
    finally:
        ia.VISION_CELULAS = original
    # no recorte (x de 100 a 180, margem 12, ampliado 4×): o "1" em x 10 → (12 + 10) × 4; o traço em x 50 → (12 + 50) × 4
    conferir(grande.size == ((80 + 1 + 24) * 4, (24 + 1 + 24) * 4) and escuros(80, 100) > 0 and escuros(240, 260) == 0
             and lidos == ['2', '2'],
             'célula relida: recorte ampliado 4×, o traço da grade apagado e o algarismo mantido; as células num processo só do Vision')


def testar_palavras_do_vision():
    """As caixas das palavras do Vision: a do trecho (boundingBoxForRange), com a origem passada para cima; e, quando o
    Vision devolve a linha inteira para cada palavra, a fatia da linha na proporção dos caracteres."""
    from types import SimpleNamespace as N
    retangulo = lambda x, y, w, h: N(origin=N(x=x, y=y), size=N(width=w, height=h))
    linha = retangulo(0.1, 0.8, 0.8, 0.05)
    exato = N(boundingBoxForRange_error_=lambda faixa, _: (N(boundingBox=lambda: retangulo(0.1 + faixa[0] * 0.1, 0.8, 0.05, 0.05)), None))
    inteira = N(boundingBoxForRange_error_=lambda faixa, _: (N(boundingBox=lambda: linha), None))
    precisas = ia.palavras_do_vision('298738 TUBO', exato, linha)
    proporcao = ia.palavras_do_vision('AB CD', inteira, linha)
    conferir([p['texto'] for p in precisas] == ['298738', 'TUBO'] and precisas[1]['x0'] == 0.8 and precisas[0]['y0'] == 0.15
             and precisas[0]['y1'] == 0.2 and proporcao[1]['x0'] == round(0.1 + 0.8 * 3 / 5, 5) and proporcao[0]['x1'] == round(0.1 + 0.8 * 2 / 5, 5),
             'Vision com as caixas das palavras: a do trecho, com a origem em cima; a linha inteira repetida vira a proporção')


def testar_curadoria_repetidos():
    """O código repetido na mesma imagem (duas relações empilhadas) ganha a chave da ordem: 282665 e 282665#2, cada um
    com a sua quantidade; o valor que só o leitor de código leu não se confirma pelo Vision (é o Vision)."""
    import curadoria
    linha = lambda codigo, quant: [codigo, 'S/N', 'REGISTRO', quant, 'UN.']
    lidas = curadoria.por_codigo([linha('282665', '2'), linha('309898', '4'), linha('282665', '23')])
    curadas = curadoria.curar_tabela({'codigo': [linha('282665', '2'), linha('309898', '4')], 'glm_ocr': [linha('282665', '2')]},
                                     testemunha='282665 S/N REGISTRO 2 UN.\n309898 S/N COLARINHO 4 UN.')
    conferir(lidas == {'282665': ('2', 'UN'), '309898': ('4', 'UN'), '282665#2': ('23', 'UN')}
             and curadas['282665']['status'] == 'confirmada' and curadas['309898']['status'] == 'so_codigo',
             'curadoria: o código repetido conta pela ordem (282665#2); o código confirma com o glm-ocr, sozinho fica so_codigo')


def testar_rapido():
    """O --rapido: os modelos só na amostra de bancada.json; passado o prazo, os locais nem pedem a vez da GPU."""
    import bancada
    imagens = [Path('Tabela 01.png'), Path('Tabela 02.png'), Path('Tabela 12.png')]
    try:
        bancada.RAPIDO, bancada.PRAZO = True, time.monotonic() - 1
        amostra, passado = bancada.da_amostra(imagens), bancada.locais(imagens, 'tabela')
    finally:
        bancada.RAPIDO, bancada.PRAZO = False, None
    conferir([i.name for i in amostra] == ['Tabela 01.png', 'Tabela 12.png'] and passado == ({}, 0.0) and bancada.da_amostra(imagens) == imagens,
             '--rapido: os modelos leem só a amostra (01 e 12 aqui); passado o prazo, os locais ficam de fora sem pedir a GPU')


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

    codigo = [linha(g) for g in gabarito[:8]]  # a geometria monta 8 das 9 (a 9ª ficou sem quantidade: de fora)

    def codigo_primeiro(imagens, modo, com_grade=True):
        lidas = {}
        for imagem in imagens:
            tabela = Path(imagem).name.startswith('Tabela')
            lidas[str(imagem)] = {'vision': {'linhas': [], 'texto': vision if tabela else '', 'erro': '', 'util': 1.0, 'congelado': False}}
            if com_grade:
                lidas[str(imagem)]['codigo'] = {'linhas': codigo if tabela else [], 'texto': texto_de(codigo) if tabela else '',
                                                'erro': '', 'util': 1.01, 'congelado': False}
        return lidas

    def locais(imagens, modo, vistas=None):
        lidas = {}
        for imagem in imagens:
            tabela = Path(imagem).name.startswith('Tabela')
            lidas[str(imagem)] = {
                'glm_ocr': {'linhas': glm if tabela else [], 'texto': texto_de(glm) if tabela else '', 'erro': '', 'util': 8.0, 'congelado': False}}
            if tabela:
                lidas[str(imagem)]['qwen3'] = {'linhas': kimi, 'texto': texto_de(kimi), 'erro': '', 'util': 12.0, 'congelado': False}
        return lidas, 6.0
    arquivo, agora = raiz / 'vez.json', datetime(2026, 10, 4, 22, 0)
    arquivo.write_text(json.dumps({'vez': {'repo': 'ialocal.extrator', 'prioridade': 5, 'modelo': 'glm-ocr', 'devolver': False,
                                           'desde': '2026-10-04T21:52:00', 'posse_ate': '2026-10-04T22:02:00'}}))
    no_pedaco = bancada.quem_tem_a_vez(arquivo, agora)
    arquivo.write_text(json.dumps({'vez': {'repo': 'ialocal.extrator', 'prioridade': 5, 'devolver': True,
                                           'desde': '2026-10-04T21:40:00', 'posse_ate': '2026-10-04T21:50:00'}}))
    vencido = bancada.quem_tem_a_vez(arquivo, agora)
    arquivo.write_text(json.dumps({'vez': None}))
    conferir(no_pedaco == 'com ialocal.extrator (prioridade 5, modelo glm-ocr) há 8 min; o pedaço vence em 2 min'
             and vencido.endswith('há 20 min; o pedaço dele venceu: devolve ao terminar o item em curso')
             and bancada.quem_tem_a_vez(arquivo, agora).startswith('a GPU está livre'),
             f'esperando a vez, a bancada diz quem está com a GPU e quando devolve: {no_pedaco}')
    bancada.externos, bancada.locais, bancada.codigo_primeiro = externos, locais, codigo_primeiro
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
    conferir((pega('tabelas', 'codigo')['certas'], pega('tabelas', 'codigo')['faltou'], pega('tabelas', 'local+codigo')['confirmadas_certas'],
              pega('tabelas', 'codigo+kimi')['confirmadas_certas'], pega('tabelas', 'codigo')['veredito'], pega('controle', 'codigo')['inventadas'])
             == (8, 1, 5, 9, 'continua', 0),
             'o leitor só de código: 8 certas e 1 faltou (nunca palpite); com o glm-ocr confirma só as 5 que o glm-ocr também '
             'leu (o Vision não confirma o código que saiu dele mesmo); o código como base com o Kimi confirma 9; continua '
             f"({pega('tabelas', 'codigo')['motivo']})")
    kimi_t, glm_t = pega('tabelas', 'kimi'), pega('tabelas', 'glm_ocr')
    conferir(kimi_t['util_mediana_s'] == 20.0 and kimi_t['n_429'] == 1 and kimi_t['perdido_pct'] == 0.2 and kimi_t['taxa_erro'] == 0
             and kimi_t['provedor'] == 'nvidia' and glm_t['provedor'] == 'gpu' and glm_t['perdido_pct'] == round(3 / 11, 3),
             'as quatro medidas separadas: tempo útil 20 s, erro 0 %, perdido 20 % do tempo (o 429 do plano) e 1 recusa no Kimi; '
             'no glm-ocr, a fila da GPU (6 s rateados entre as 2 chamadas dos modelos locais; o código não espera vez) é o perdido')
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
    geradas = pl.read_parquet(comum.DADOS / 'licoes.parquet')
    de = lambda conjunto, leitor, classe: geradas.filter((pl.col('conjunto') == conjunto) & (pl.col('leitor') == leitor)
                                                        & (pl.col('classe') == classe))
    glm_omissao = de('tabelas', 'glm_ocr', 'omissao')
    conferir((de('tabelas', 'parse', 'leitura_errada').height, de('tabelas', 'parse', 'invencao').height,
              de('controle', 'parse', 'invencao').height, glm_omissao.height, de('tabelas', 'codigo', 'omissao').height,
              glm_omissao['codigo_acertou'].sum(), de('sondagem', 'parse', 'invencao').height,
              geradas.filter(pl.col('leitor') == 'kimi').height, geradas.filter(pl.col('classe') == 'confirmou_errado').height)
             == (1, 1, 3, 4, 1, 3, 1, 0, 0) and (comum.SAIDAS / 'licoes_projeto.csv').exists(),
             'o placar gera as lições: o Parse leu 1 linha errada e inventou 1 (e 3 no controle, 1 no boletim), o glm-ocr '
             'deixou 4 linhas sem ler — em 3 delas o código já acertava —, o código deixou 1; o Kimi não tem lição e a '
             'curadoria não confirmou nada errado; saidas/licoes_projeto.csv')
    historico = [json.loads(l) for l in (comum.DADOS / 'licoes_historico.jsonl').read_text().splitlines()]
    conferir(historico[-1]['licoes'] == geradas.height and historico[-1]['por_classe']['invencao'] == 5,
             f"cada geração de lições deixa uma linha de progresso em dados/licoes_historico.jsonl ({historico[-1]['licoes']} lições)")


def testar_licoes():
    """As regras das lições sem bancada: a classe pelo resultado, a confirmação errada da curadoria, a falha de operação,
    a situação provável no boletim digitalizado, o id estável e o progresso entre gerações (no --rapido, a lição de
    recorte que não foi medido de novo não conta como resolvida)."""
    import licoes
    base = {'conjunto': 'tabelas', 'tipo': 'leitor', 'recorte': 'Tabela 03.png', 'presente': None, 'status': ''}
    tabela = pl.DataFrame([
        {**base, 'leitor': 'codigo', 'chave': '282665', 'lido': '12 M', 'esperado': '12 M', 'resultado': 'certa'},
        {**base, 'leitor': 'glm_ocr', 'chave': '282665', 'lido': '72 M', 'esperado': '12 M', 'resultado': 'errada'},
        {**base, 'leitor': 'glm_ocr', 'chave': '999999', 'lido': '1 UN', 'esperado': '', 'resultado': 'inventada'},
        {**base, 'leitor': 'vision', 'chave': '282665', 'lido': '', 'esperado': '12 M', 'resultado': ''},
        {**base, 'leitor': 'local', 'tipo': 'curadoria', 'chave': '282665', 'lido': '72 M', 'esperado': '12 M',
         'resultado': 'errada', 'status': 'confirmada'},
        {**base, 'conjunto': 'sondagem', 'tipo': 'digitalizada', 'recorte': 'SP-01.pdf#pagina01', 'leitor': 'kimi',
         'chave': 'nspt_3m', 'lido': '17', 'esperado': '14', 'resultado': 'errada'}])
    chamadas = pl.DataFrame([{'conjunto': 'tabelas', 'recorte': 'Tabela 03.png', 'leitor': 'gemma3', 'erro': 'Ollama 500 (gemma3:12b)'},
                             {'conjunto': 'tabelas', 'recorte': 'Tabela 03.png', 'leitor': 'kimi', 'erro': ''}])
    geradas = licoes.das_medidas(tabela, chamadas)
    por = {(l['leitor'], l['classe']): l for l in geradas}
    conferir([l['classe'] for l in geradas][:2] == ['confirmou_errado', 'invencao']
             and por[('glm_ocr', 'leitura_errada')]['codigo_acertou'] is True and por[('glm_ocr', 'invencao')]['codigo_acertou'] is False
             and por[('gemma3', 'operacao')]['gravidade'] == 'media' and por[('kimi', 'leitura_errada')]['situacao'] == 'provavel'
             and por[('glm_ocr', 'leitura_errada')]['situacao'] == 'confirmada' and not any(l['leitor'] == 'vision' for l in geradas)
             and len(geradas) == 5,
             'lições pela classe: a confirmação errada da curadoria e a invenção primeiro (gravidade alta); o código já acertava '
             'o que o glm-ocr leu errado; a falha do gemma3 é de operação; o boletim digitalizado dá lição provável; o Vision '
             '(sem estrutura) não dá lição de linha')
    conferir(licoes.das_medidas(tabela, chamadas)[0]['id'] == geradas[0]['id'], 'o id da lição é estável entre gerações')
    resolvida = {**geradas[1], 'id': 'antiga'}
    fora = {**geradas[1], 'id': 'fora_da_amostra', 'recorte': 'Tabela 12.png'}
    medidos = {(l['conjunto'], l['recorte'], l['leitor']) for l in geradas}
    conferir(licoes.progresso([geradas[0], resolvida, fora], geradas, medidos) == {'novas': 4, 'resolvidas': 1, 'continuam': 1},
             'progresso: a lição que sumiu de um recorte medido de novo está resolvida; a de um recorte fora da amostra não '
             'foi medida, não conta')


def testar_vision_com_prazo():
    """O Vision num processo à parte, com prazo: o que responde devolve o texto; o que trava (04/10: 11 h dentro de
    performRequests, a vez da GPU presa o tempo todo) é encerrado no prazo e sobe como erro, sem segurar a rodada."""
    original, IA = ia.VISION, comum.configuracao('ia')
    prazo = IA.get('vision_timeout_s')
    try:
        ia.VISION = [sys.executable, '-c', 'import json; print(json.dumps({"texto": "EST 77"}))']
        lido = LER_COM_VISION('qualquer.png')
        ia.VISION, IA['vision_timeout_s'] = [sys.executable, '-c', 'import time; time.sleep(30)'], 1
        marca = time.monotonic()
        try:
            LER_COM_VISION('travado.png')
            erro = ''
        except RuntimeError as falha:
            erro = str(falha)
        conferir(lido['texto'] == 'EST 77' and lido['palavras'] == [] and erro.startswith('Vision travou') and time.monotonic() - marca < 5,
                 f'Vision num processo à parte: responde com o texto; travado, morre no prazo e o erro sobe ({erro})')
    finally:
        ia.VISION, IA['vision_timeout_s'] = original, prazo


def testar_sinal_de_vida_e_quarentena(raiz):
    """O vigia de progresso do maestro (0v66): cada resposta de modelo dá o sinal de vida da vez da GPU (o pedido passa a
    ser vigiado, com o item em curso); o documento que o vigia registrou travado 2 vezes fica em quarentena — fora da
    fila de IA —, o que travou uma vez tenta de novo."""
    pasta = raiz / 'gpu_sinal'
    with cliente_gpu.vez_da_gpu('ialocal.projeto', str(pasta), 7, 'glm-ocr', 'prancha') as vez:
        vez.avancei('DOC/1')
        ia.congelado({'teste': 'sinal de vida'}, lambda: ('resposta', {}))
        pedido = json.loads(next((pasta / 'pedidos').glob('*.json')).read_text())
    conferir(pedido['vigia'] and pedido['item'] == 'DOC/1' and pedido['avancos'] == 2,
             'sinal de vida: o item em curso e cada resposta de modelo marcam avanço no pedido da vez da GPU')
    travados = cliente_gpu.VEZ.with_name('travados.jsonl')
    travados.parent.mkdir(parents=True, exist_ok=True)
    travados.write_text(''.join(json.dumps({'repo': 'ialocal.projeto', 'item': i}) + '\n' for i in ('DOC/1', 'DOC/1', 'DOC/2')))
    try:
        conferir(ciclo.em_quarentena({'id': 'DOC/1'}) and not ciclo.em_quarentena({'id': 'DOC/2'}),
                 'quarentena: o documento que travou 2 vezes sai da fila de IA; o que travou 1 vez tenta de novo')
    finally:
        travados.unlink()
    import subprocess
    pedidos = raiz / 'pedidos_cede'
    pedidos.mkdir()
    morto = subprocess.Popen([sys.executable, '-c', 'pass'])
    morto.wait()
    escrever = lambda nome, tarefa, pid: (pedidos / f'{nome}.json').write_text(json.dumps({'tarefa': tarefa, 'pid': pid}))
    escrever('rodada', 'prancha', os.getppid())
    escrever('propria', 'bancada', os.getpid())
    escrever('morta', 'bancada', morto.pid)
    sem_bancada = ciclo.bancada_esperando(pedidos)
    escrever('viva', 'bancada', os.getppid())
    conferir(not sem_bancada and ciclo.bancada_esperando(pedidos),
             'a rodada cede a vez entre um documento e outro quando a bancada viva do repositório espera (a de processo morto, '
             'o próprio pedido e o de outra tarefa não contam)')


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
        testar_vision_com_prazo()
        testar_sinal_de_vida_e_quarentena(raiz)
        testar_agentes(raiz)
        testar_curadoria()
        testar_grade()
        testar_grade_com_o_vision()
        testar_celulas()
        testar_palavras_do_vision()
        testar_curadoria_repetidos()
        testar_rapido()
        testar_licoes()
        testar_bancada(raiz)


if __name__ == '__main__':
    principal()
