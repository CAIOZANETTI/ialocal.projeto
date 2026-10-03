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
import types
from pathlib import Path

import polars as pl

import ciclo
import comum
import ia
import prancha

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
    carimbo = ['FOLHA N: 012/019', 'DATA: 09/2020', 'ADUTORA DE AGUA TRATADA AAT-06', 'PLANTA E PERFIL',
               'ARQUIVO ELETRONICO: 012-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1']
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
    obra = status['por_obra']['obras/Foz AAT-06']
    conferir((obra['feito'], obra['total'], obra['pranchas'], obra['arquivos']) == (2, 2, 1, 2) and obra['bytes'] > 0,
             'status por obra (a tela 8 do maestro): 2 de 2 feitas, 1 prancha; pranchas e leituras publicadas (sem imagem colada, sem tabela)')
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
        testar_conceitos()
        testar_regras(raiz)
        testar_eixo_por_camada()
        testar_rodada(raiz)
        testar_falha(raiz)


if __name__ == '__main__':
    principal()
