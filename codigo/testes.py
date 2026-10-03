"""Testes com prancha sintética (nenhum dado da obra sai do mini; o desenvolvimento é fora dele, MASTER-PLAN §5.4) e a
aferição do código (regra 17). Roda em qualquer máquina, sem Ollama, sem Apple FM e sem Vision: os motores de IA são
trocados por falsos.

    .venv/bin/python codigo/testes.py
"""
import ast
import json
import math
import sys
import tempfile
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'codigo'))


def conferir(condicao, mensagem):
    if not condicao:
        raise AssertionError(mensagem)
    print(f'ok  {mensagem}')


def pdf_prancha():
    """Prancha A1 sintética no formato das da AAT-06 de Foz (notas/teste_prancha): a camada ADUTORA com o eixo em faixa
    roxa (200 mm reto e 100 mm a 45°), a camada TEXTO com o carimbo em células (rótulo pequeno, valor embaixo), o quadro
    de revisões, as notas e a relação de materiais em grade, a 1:1000 — o tubo da relação (300,00 m) fecha com o eixo."""
    PT = 72 / 25.4
    eixo = [(300.0, 1300.0), (300.0 + 200 * PT, 1300.0)]
    eixo.append((eixo[1][0] + 100 * PT * math.cos(math.radians(-45)), 1300.0 + 100 * PT * math.sin(math.radians(-45))))
    normais, meia = [(0.0, 1.0), (0.3827, 0.9239), (0.7071, 0.7071)], [3.0, 3.0 / 0.9239, 3.0]
    lados = [((x + n[0] * m, y + n[1] * m), (x - n[0] * m, y - n[1] * m)) for (x, y), n, m in zip(eixo, normais, meia)]
    triangulos = [t for i in range(2) for t in ((lados[i][0], lados[i][1], lados[i + 1][0]), (lados[i][1], lados[i + 1][0], lados[i + 1][1]))]
    faixa = ''.join(f'{a[0]:.2f} {a[1]:.2f} m {b[0]:.2f} {b[1]:.2f} l {c[0]:.2f} {c[1]:.2f} l h f\n' for a, b, c in triangulos)
    texto = lambda x, y, tamanho, escrito: f'BT /F1 {tamanho} Tf {x} {y} Td ({escrito}) Tj ET\n'
    grade = lambda xs, ys: ''.join(f'{xs[0]} {y} m {xs[-1]} {y} l S\n' for y in ys) + ''.join(f'{x} {ys[0]} m {x} {ys[-1]} l S\n' for x in xs)
    celulas = [((1700, 2364), (260, 320), 'PROJETISTA', ['HIDRO ENGENHARIA LTDA']),
               ((1700, 2364), (200, 260), 'TÍTULO', ['ADUTORA DE ÁGUA TRATADA AAT-06', 'PLANTA E PERFIL']),
               ((1700, 2032), (140, 200), 'RESP. TÉCNICO', ['ENG. JOÃO DA SILVA', 'CREA-PR 12345/D']),
               ((2032, 2364), (140, 200), 'MUNICÍPIO', ['FOZ DO IGUAÇU']),
               ((1700, 1866), (80, 140), 'DATA', ['09/2020']), ((1866, 2032), (80, 140), 'ESCALA', ['1:1000']),
               ((2032, 2198), (80, 140), 'FOLHA', ['012/019']), ((2198, 2364), (80, 140), 'REV.', ['R1']),
               ((1700, 2364), (20, 80), 'Nº DO DESENHO', ['012-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1'])]
    carimbo = '1700 20 664 300 re S\n' + ''.join(f'{x0} {y0} {x1 - x0} {y1 - y0} re S\n' for (x0, x1), (y0, y1), _, _ in celulas)
    carimbo += ''.join(texto(x0 + 4, y1 - 9, 5, rotulo) + ''.join(texto(x0 + 10, y1 - 24 - 12 * n, 9, v) for n, v in enumerate(valores))
                       for (x0, x1), (y0, y1), rotulo, valores in celulas)
    revisoes = grade([1700, 1760, 1860, 2250, 2364], [320, 345, 370, 395])
    revisoes += ''.join(texto(x + 4, y + 8, 7, v) for y, linha in ((370, ('REV.', 'DATA', 'DESCRIÇÃO', 'POR')), (345, ('R1', '09/2020', 'AJUSTE DO TRAÇADO', 'JS')),
                                                                  (320, ('R0', '05/2020', 'EMISSÃO INICIAL', 'JS')))
                        for x, v in zip((1700, 1760, 1860, 2250), linha))
    materiais = grade([1700, 1760, 2100, 2200, 2300], [500, 530, 560, 590, 620])
    materiais += ''.join(texto(x + 4, y + 10, 8, v) for y, linha in ((590, ('ITEM', 'MATERIAL', 'UNID', 'QUANT')), (560, ('1', 'TUBO PEAD DE 630', 'm', '300,00')),
                                                                    (530, ('2', 'CURVA 45 DE 630', 'pç', '1')), (500, ('3', 'VENTOSA DN 100', 'pç', '2')))
                         for x, v in zip((1700, 1760, 2100, 2200), linha))
    notas = ''.join(texto(1700, 1000 - 12 * n, 8, linha) for n, linha in enumerate(
        ['NOTAS:', '1. COTAS EM METROS.', '2. TUBULAÇÃO EM PEAD PE100 DE 630', '   CONFORME NBR 15561.', '3. VER DETALHES NA FOLHA 015.']))
    conteudo = (f'/OC /MC0 BDC 0.64706 0 0.86667 rg\n{faixa}EMC\n/OC /MC1 BDC 0 0 0 rg 0 0 0 RG 0.5 w\n{carimbo}{revisoes}EMC\n'
                f'0 0 0 rg 0 0 0 RG 0.35 w\n{materiais}{notas}').encode('cp1252')
    objetos = [b'<< /Type /Catalog /Pages 2 0 R /OCProperties << /OCGs [5 0 R 7 0 R] /D << /ON [5 0 R 7 0 R] >> >> >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 2384 1684] /Contents 6 0 R '
               b'/Resources << /Font << /F1 4 0 R >> /Properties << /MC0 5 0 R /MC1 7 0 R >> >> >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>', b'<< /Type /OCG /Name (ADUTORA) >>',
               f'<< /Length {len(conteudo)} >>\nstream\n'.encode() + conteudo + b'\nendstream', b'<< /Type /OCG /Name (TEXTO) >>']
    corpo, posicoes = b'%PDF-1.7\n', []
    for numero, objeto in enumerate(objetos, 1):
        posicoes.append(len(corpo))
        corpo += f'{numero} 0 obj\n'.encode() + objeto + b'\nendobj\n'
    xref = f'xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n' + ''.join(f'{p:010d} 00000 n \n' for p in posicoes)
    return corpo + xref.encode() + f'trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{len(corpo)}\n%%EOF\n'.encode()


def pdf_simples(largura, altura, linhas):
    """PDF de uma página com texto: o A4 de memorial que não é prancha."""
    conteudo = ''.join(f'BT /F1 10 Tf 50 {altura - 60 - 14 * n} Td ({linha}) Tj ET\n' for n, linha in enumerate(linhas)).encode('cp1252')
    objetos = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {largura} {altura}] /Contents 5 0 R /Resources << /Font << /F1 4 0 R >> >> >>'.encode(),
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
               f'<< /Length {len(conteudo)} >>\nstream\n'.encode() + conteudo + b'\nendstream']
    corpo, posicoes = b'%PDF-1.7\n', []
    for numero, objeto in enumerate(objetos, 1):
        posicoes.append(len(corpo))
        corpo += f'{numero} 0 obj\n'.encode() + objeto + b'\nendobj\n'
    xref = f'xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n' + ''.join(f'{p:010d} 00000 n \n' for p in posicoes)
    return corpo + xref.encode() + f'trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{len(corpo)}\n%%EOF\n'.encode()


def testar_conceitos():
    """Teste de conceito: todo padrão compila, toda família tem padrão e grupo, todo campo do carimbo tem âncora, os
    campos da IA são os do prompt e todo prompt que o código cita existe."""
    import re
    import ia
    PRANCHA = ia.configuracao('prancha')

    def textos(no, chave=''):
        if isinstance(no, dict):
            return [t for k, v in no.items() if not k.startswith('_') and k != 'metadata' for t in textos(v, k)]
        return [no] if isinstance(no, str) else [t for v in no for t in textos(v)] if isinstance(no, list) else []
    for padrao in textos(PRANCHA):
        re.compile(padrao)
    conferir(True, f'conceitos: os {len(textos(PRANCHA))} textos de prancha.json compilam como expressão regular')
    FAMILIAS = PRANCHA['familias']
    conferir(set(FAMILIAS['ordem']) == set(FAMILIAS['padroes']) == set(FAMILIAS['grupo']), 'conceitos: toda família tem padrão e grupo')
    conferir(all('ancora' in regra for regra in PRANCHA['carimbo']['campos'].values()), 'conceitos: todo campo do carimbo tem rótulo-âncora')
    prompt = (RAIZ / 'conceitos' / 'prompts' / 'prancha_carimbo.txt').read_text()
    conferir(all(f'- {campo}:' in prompt for campo in PRANCHA['carimbo']['campos_ia']), 'conceitos: os campos da IA são os do prompt do carimbo')
    citados = {n for a in (RAIZ / 'codigo').glob('*.py') for n in re.findall(r"ler_prompt\('(\w+)'", a.read_text())}
    conferir(citados and all((RAIZ / 'conceitos' / 'prompts' / f'{n}.txt').exists() for n in citados | {'_regras'}),
             f"conceitos: os prompts citados existem ({', '.join(sorted(citados))})")


def testar_folha(pasta):
    """Perfil, vetor, geometria e DXF da prancha sintética; o A4 de memorial não é prancha."""
    import ezdxf
    import polars as pl
    import pypdfium2 as pdfium
    import folha
    arquivo, a4 = pasta / '012-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1.pdf', pasta / 'memorial.pdf'
    arquivo.write_bytes(pdf_prancha())
    a4.write_bytes(pdf_simples(595, 842, ['MEMORIAL DESCRITIVO', 'ESCALA: 1:100', 'FOLHA 1/3']))
    catalogo, documento, memorial = folha.catalogo(arquivo), pdfium.PdfDocument(arquivo), pdfium.PdfDocument(a4)
    perfil = folha.perfilar(documento, 0, arquivo.name, catalogo['camadas'])
    conferir(catalogo == {'camadas': ['ADUTORA', 'TEXTO'], 'geopdf': False} and perfil['formato'] == 'A1' and perfil['e_prancha']
             and perfil['sinais'] == ['camadas', 'nome', 'carimbo'], 'folha: A1 com as camadas do CAD, três sinais, é prancha')
    memorial = folha.perfilar(memorial, 0, a4.name, [])
    conferir(memorial['formato'] == 'A4' and not memorial['e_prancha'], 'folha: o A4 de memorial não é prancha (formato abaixo do A3)')
    primitivas = folha.vetorizar(documento[0], 0)
    documento.close()
    contagem = folha.contagem(primitivas)
    conferir(contagem['primitivas'] == {'preenchimento': 4, 'traco': 29, 'texto': 53}
             and {p['camada'] for p in primitivas} == {'ADUTORA', 'TEXTO', ''},
             'folha: 4 triângulos da faixa, 29 traços e 53 textos, cada um com a camada do CAD (ou nenhuma)')
    titulo = next(p for p in primitivas if p['tipo'] == 'texto' and p['texto'] == 'TÍTULO')
    conferir(abs(titulo['tamanho_mm'] - 5 * 25.4 / 72) < 0.01 and titulo['angulo_graus'] == 0 and titulo['camada'] == 'TEXTO',
             'folha: o texto com o acento, a altura em mm e o ângulo')
    folha.gravar_geometria(primitivas, pasta / 'geometria.parquet')
    camadas = folha.gravar_dxf(primitivas, pasta / 'folha.dxf', (841, 594))
    desenho = ezdxf.readfile(pasta / 'folha.dxf')
    tipos = [e.dxftype() for e in desenho.modelspace()]
    conferir(len(pl.read_parquet(pasta / 'geometria.parquet')) == len(primitivas) and {'ADUTORA', 'TEXTO', 'FOLHA'} <= set(camadas)
             and tipos.count('TEXT') == 53 and tipos.count('HATCH') == 4 and 'TÍTULO' in {e.dxf.text for e in desenho.modelspace().query('TEXT')},
             'folha: geometria.parquet com uma linha por primitiva; o DXF abre com as camadas do CAD, os textos e a faixa')
    return primitivas


def testar_leitura(primitivas):
    """Carimbo por rótulo-âncora, revisões, notas, tabela de materiais e família na prancha sintética."""
    import leitura
    linhas, celulas = leitura.linhas_de_texto(primitivas), leitura.celulas(primitivas)
    tabelas = leitura.tabelas(linhas, celulas)
    materiais = next(t for t in tabelas if t['tipo'] == 'relacao_materiais')
    conferir(materiais['linhas'] == [['ITEM', 'MATERIAL', 'UNID', 'QUANT'], ['1', 'TUBO PEAD DE 630', 'm', '300,00'],
                                     ['2', 'CURVA 45 DE 630', 'pç', '1'], ['3', 'VENTOSA DN 100', 'pç', '2']],
             'leitura: a relação de materiais pela grade, cabeçalho e três linhas')
    revisoes = leitura.revisoes(next(t for t in tabelas if t['tipo'] == 'revisoes'))
    conferir([(r['revisao'], r['data'], r['descricao']) for r in revisoes] == [('R1', '09/2020', 'AJUSTE DO TRAÇADO'), ('R0', '05/2020', 'EMISSÃO INICIAL')],
             'leitura: o quadro de revisões, a mais recente primeiro')
    carimbo = leitura.carimbo(linhas, celulas, (841, 594), '012-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1.pdf', fora=tabelas)
    esperado = {'projetista': 'HIDRO ENGENHARIA LTDA', 'titulo': 'ADUTORA DE ÁGUA TRATADA AAT-06 PLANTA E PERFIL',
                'responsavel_tecnico': 'ENG. JOÃO DA SILVA', 'registro': 'CREA-PR 12345/D', 'municipio': 'FOZ DO IGUAÇU', 'data': '09/2020',
                'escala': '1:1000', 'folha': '012/019', 'revisao': 'R1', 'desenho': '012-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1'}
    conferir(all(carimbo['campos'].get(c) == v for c, v in esperado.items()) and carimbo['zona']['origem'] == 'celulas'
             and carimbo['arquivo_confere'] and carimbo['revisao_nome'] == '1' and carimbo['disciplina'] == 'hidraulica',
             'leitura: carimbo pelas células — projetista, título, responsável e CREA, município, data, escala, folha, revisão, desenho')
    conferir(carimbo['campos']['data'] == '09/2020', 'leitura: o DATA do quadro de revisões não é a data do carimbo')
    notas = leitura.notas(linhas)
    conferir(len(notas) == 1 and [(i['numero'], i['texto']) for i in notas[0]['itens']] ==
             [('1', 'COTAS EM METROS.'), ('2', 'TUBULAÇÃO EM PEAD PE100 DE 630 CONFORME NBR 15561.'), ('3', 'VER DETALHES NA FOLHA 015.')],
             'leitura: as notas em itens, a linha sem número continua o item de cima')
    conferir(leitura.familia('012-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1.pdf', carimbo['texto'])
             == {'familia': 'adutora', 'grupo': 'linear', 'familia_origem': 'regra', 'desenho': 'planta_e_perfil'},
             'leitura: família adutora, grupo linear e desenho planta e perfil pela regra')
    conferir_familias_do_acervo()
    return carimbo, tabelas


def conferir_familias_do_acervo():
    """As famílias que a auditoria de 26/09 pegou erradas no acervo (testes do extrator até a 2v75): cada uma é regra em
    conceitos/prancha.json, e a regra não pode voltar atrás."""
    import leitura
    familia = lambda nome, texto='': leitura.familia(nome, texto)
    layout = 'SISTEMA DE ABASTECIMENTO DE ÁGUA REDE DE DISTRIBUIÇÃO DE ÁGUA REMANEJAMENTOS LAYOUT RUA CORTEZ DATA: AGO/25 ESCALA: 1:7.500'
    conferir((familia('LAYOUT-CAMBE.pdf', layout)['familia'], familia('LAYOUT-CAMBE.pdf', layout)['desenho']) == ('rede_agua', 'locacao'),
             'família: o LAYOUT de Cambé é rede de água e locação (a rua CORTEZ não é corte)')
    conferir((familia('PLANTA_GERAL_SONDAGEM_CAMBÉ_01.pdf', 'PLANTA DE LOCAÇÃO DOS FUROS')['grupo'], familia('012-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1.pdf', 'ver boletim de sondagem')['familia'])
             == ('apoio', 'adutora'), 'família: planta de sondagem é apoio; a adutora que cita sondagem continua adutora')
    cambe = '05V-SAA-0153-8127-PULI-DE-0000RDA00REMANEJ-R0.pdf'
    ose = 'OSE075 ' + 'GAS ' * 40 + 'PV CT.943.544 PV CT.945.343 REDE DE GÁS\nSISTEMA DE ABASTECIMENTO DE ÁGUA 002-SAA-0001-6745-PULI-DE-RDA00TATCADBL01-R0'
    conferir((familia(cambe)['familia'], familia(cambe)['grupo']) == ('rede_agua', 'linear') and familia('05_OSE-075.pdf', ose)['familia'] == 'rede_agua'
             and familia('x.pdf', 'OSE075 ' + 'GAS ' * 40)['familia'] == 'indefinida',
             'família: RDA no meio do nome é rede de água; o código do desenho decide antes do GAS GAS GAS da interferência e dos PV da rede existente')
    ose102 = 'Adutora: RDA CFA JNE JDA FUNDOS AV. COMENDADOR FRANCO Declividade da\nAdutora SENTIDO DE FLUXO DA ADUTORA'
    eet = 'DRENAGEM - EXISTENTE ESTAÇÃO ELEVATÓRIA TRATADA - EET 003-SAA-0001-6745-PEXE-DE-EET00TATUQUAPL-A0'
    conferir((familia('10_OSE-102.pdf', ose102)['familia'], familia('x.pdf', eet)['familia'], familia('03_003-SAA-0001-6745-PEXE-DE-EET00TATUQUACT-A0.pdf')['familia'],
              familia('01_056-SAA-0001-7739-PBHI-DE-0708RAP01CX1INTDN900-R0F.pdf')['familia']) == ('rede_agua', 'elevatoria', 'elevatoria', 'reservatorio'),
             'família: o campo "Adutora:" da OSE e a legenda "DRENAGEM - EXISTENTE" não decidem; EET e RAP colados ao número')


def gabarito_cambe():
    """O gabarito do Caio para Cambé (amostras/tabelas/216_cambe, o TXT): tabela → linhas
    (CÓDIGO, Nº, DISCRIMINAÇÃO, QUANT., UND., TÍTULO), como ele digitou."""
    arquivo = next((RAIZ / 'amostras' / 'tabelas' / '216_cambe').glob('*.txt'))
    tabelas, nome = {}, None
    for linha in arquivo.read_text(encoding='utf-8').replace('\r', '').splitlines():
        if linha.strip().upper().startswith('TABELA'):
            nome, tabelas[linha.strip()] = linha.strip(), []
        elif linha.strip() and not linha.startswith('CÓDIGO;'):
            tabelas[nome].append(linha.split(';'))
    return tabelas


def testar_itens():
    """Item 14: a tabela vira itens nos quatro layouts das amostras — Cambé, a ETA, a AAT e a lista de equipamentos de
    Foz (notas/amostras_tabelas_2026-10-03.md) — e as 190 linhas do gabarito de Cambé, montadas como a imagem as mostra
    (cabeçalho, linha de seção, linhas), voltam iguais."""
    import itens
    conferir([itens.numero(x) for x in ('7.113,99', '10221,25', '3.30', '02', '1.250', '0 - 00')] ==
             [Decimal('7113.99'), Decimal('10221.25'), Decimal('3.30'), Decimal('2'), Decimal('1250'), None],
             'itens: 7.113,99 e 10221,25 no mesmo projeto; 3.30 é decimal, 1.250 é milhar; o riscado não é número')
    eta = [['RELAÇÃO DE MATERIAIS'], ['SAÍDA ÁGUA TRATADA'], ['Nº', 'ESPECIF/ COD SAM', 'DESCRIÇÃO', '1ª ETAPA', '2ª ETAPA', 'UN'],
           ['20', '134554', 'TUBO FD PF PN10 DN900', '00', '01', 'pç'],
           ['S/N', '308783', 'ABA DE VEDACAO ESPECIAL ACO CARBONO', '0 - 00', '01\n13,76', 'pç\nkg/m'],
           ['*07', '-', 'BOMBA CENTRÍFUGA AUTOASPIRANTE', '', '01', 'PÇ'], ['* VER ESPECIFICAÇÃO TÉCNICA']]
    lidos = [(i['item'], i['marcador'], i['nota'], i['codigo'], i['etapa'], i['quantidade_impressa'], i['unidade_si'], i['dimensao'])
             for i in itens.itens(eta)]
    conferir(lidos == [('20', '', '', '134554', '2', '01', 'pç', 'contagem'), ('S/N', '', '', '308783', '2', '01', 'pç', 'contagem'),
                       ('S/N', '', '', '308783', '2', '13,76', 'kg/m', 'massa_linear'),
                       ('07', '*', 'VER ESPECIFICAÇÃO TÉCNICA', '', '2', '01', 'pç', 'contagem')],
             'itens (ETA de Foz): a etapa com 00 sai, 02 pç e 13,76 kg/m são dois itens, *07 leva a nota do rodapé, código "-" fica vazio')
    aat = itens.itens([['AAT - PARTE 05'], ['CÓDIGO', 'QT', 'ITEM', 'DESCRIÇÃO', 'UN.'],
                       ['301218', '486,60', 'A1', 'TUBO POLIETILENO PE 100 PN10 (BARRA COM 6,0 M) DE 315', 'M']])
    equipamento = itens.itens([['Nº', 'CÓD.', 'DESCRIÇÃO', 'QTDE', 'UN'], ['8', '', 'Tubo rigido para Ar Comprimido\nMaterial: Aluminio', '180', 'M'],
                               ['1', '332836', 'COMPORTA RETANGULAR 400X400', '6', 'CJ']])
    conferir((aat[0]['secao'], aat[0]['codigo'], aat[0]['item'], aat[0]['valor_si'], aat[0]['unidade_si']) == ('AAT - PARTE 05', '301218', 'A1', '486.60', 'm')
             and [(i['descricao'], i['unidade_si']) for i in equipamento] == [('Tubo rigido para Ar Comprimido Material: Aluminio', 'm'), ('COMPORTA RETANGULAR 400X400', 'cj')],
             'itens (AAT e equipamentos de Foz): a coluna pelo nome, não pela ordem; a especificação em várias linhas fica numa descrição')
    gabarito, montadas, lidos = gabarito_cambe(), 0, []
    for nome, linhas in gabarito.items():
        tabela, secao = [['CÓDIGO', 'N°', 'DISCRIMINAÇÃO', 'QUANT.', 'UND.']], None
        for linha in linhas:
            if linha[5] != secao:
                secao = linha[5]
                tabela.append([secao])
            tabela.append(linha[:5])
        montadas += len(linhas)
        lidos += [[i['codigo_impresso'], i['item'], i['descricao'], i['quantidade_impressa'], i['unidade_declarada'], i['secao']] for i in itens.itens(tabela)]
    esperado = [l for linhas in gabarito.values() for l in linhas]
    conferir(montadas == len(lidos) == 190 and lidos == esperado and {i for l in esperado for i in [l[4]]} == {'UN.', 'M'},
             'itens (gabarito de Cambé): as 190 linhas das 17 tabelas voltam iguais, com a seção da linha de cima')


def testar_tabela_com_secao():
    """A linha de seção (célula da largura da tabela entre o cabeçalho e as linhas, como em Cambé) entra na tabela; a
    célula larga que só encosta por fora (o carimbo embaixo do quadro) fica fora."""
    import leitura
    traco = lambda x0, y0, x1, y1: {'tipo': 'traco', 'fechado': False, 'camada': '', 'x_mm': [x0, x1], 'y_mm': [y0, y1]}
    texto = lambda x, y, escrito: {'tipo': 'texto', 'texto': escrito, 'x_mm': [x], 'y_mm': [y], 'x0_mm': x, 'y0_mm': y, 'x1_mm': x + 2 * len(escrito),
                                   'y1_mm': y + 2.5, 'tamanho_mm': 2.5, 'angulo_graus': 0.0, 'camada': ''}
    ys, xs = [0, 10, 20, 30, 40, 50], [0, 20, 30, 140, 160, 180]
    primitivas = [traco(0, y, 180, y) for y in ys] + [traco(x, y, x, y + 10) for x in xs[1:-1] for y in (20, 40)]  # a seção (30–40) sem divisão
    primitivas += [traco(0, 0, 0, 50), traco(180, 0, 180, 50)]
    linhas = [('CÓDIGO', 'N°', 'DISCRIMINAÇÃO', 'QUANT.', 'UND.', 42), ('282665', 'S/N', 'REGISTRO DE GAVETA DN 50', '4', 'UN.', 22)]
    primitivas += [texto(x + 1, y, v) for *valores, y in linhas for x, v in zip(xs, valores)]
    primitivas += [texto(60, 32, 'REGISTRO DE DESCARGA'), texto(5, 12, 'CARIMBO: PROJETISTA'), texto(5, 2, 'OBRA')]
    tabelas = leitura.tabelas(leitura.linhas_de_texto(primitivas), leitura.celulas(primitivas))
    conferir(len(tabelas) == 1 and tabelas[0]['linhas'] == [['CÓDIGO', 'N°', 'DISCRIMINAÇÃO', 'QUANT.', 'UND.'], ['REGISTRO DE DESCARGA'],
                                                           ['282665', 'S/N', 'REGISTRO DE GAVETA DN 50', '4', 'UN.']] and tabelas[0]['y0'] == 20,
             'leitura: a linha de seção no meio da tabela entra; as células largas de baixo, que só encostam, ficam fora')


def testar_itens_colados():
    """As faixas da tabela colada viram uma tabela só: a linha que a sobreposição repetiu no começo da faixa seguinte sai;
    a situação de cada linha do OCR (confirmada, pendente) vai para o item."""
    import projeto
    linha = lambda faixa, n, celulas, status='confirmada': {'imagem': 1, 'faixa': faixa, 'linha': n, 'celulas': celulas, 'status': status}
    coladas = [linha(1, 1, ['ITEM', 'CÓDIGO', 'DESCRIÇÃO', 'QUANT.', 'UND.']), linha(1, 2, ['01', '309244', 'TUBO PE 100 DE 630', '540,00', 'm']),
               linha(2, 1, ['01', '309244', 'TUBO PE 100 DE 630', '540,00', 'm']), linha(2, 2, ['02', '312059', 'CURVA 45 DE 630', '02', 'PÇ'], 'pendente')]
    lidos = [(i['tabela'], i['codigo'], i['valor_si'], i['situacao']) for i in projeto.itens_colados(coladas)]
    conferir(lidos == [('imagem1', '309244', '540.00', 'confirmada'), ('imagem1', '312059', '2', 'pendente')],
             'itens colados: as faixas juntas sem a linha repetida da sobreposição, com a situação do OCR')


def testar_linear(primitivas):
    """Eixo da faixa com a dobra e a conferência eixo × escala × tubo."""
    import linear
    eixo = linear.eixo(primitivas)
    conferir(eixo['eixo'] == 'faixa' and abs(eixo['eixo_mm'] - 300) < 0.5 and eixo['deflexoes'] == [-45.0],
             'linear: eixo de 300 mm tirado da faixa roxa, com a dobra de 45°')
    tubo = lambda metros: ['1', 'TUBO PEAD DE 630', 'm', metros]
    conferir(linear.conferir(eixo, [1000], [tubo('300,00')])['conferencia'] == 'fecha'
             and linear.conferir(eixo, [1000], [tubo('298,00')])['conferencia'] == 'diverge'
             and linear.conferir(eixo, [1000], [])['conferencia'] == 'sem_tubo_confirmado'
             and linear.conferir(eixo, [], [tubo('300,00')])['conferencia'] == 'sem_escala_confirmada'
             and linear.escala('H=1:1000 V=1:100 e 1:7.500') == [1000, 100, 7500],
             'linear: extensão desenhada × tubo da relação fecha, diverge, ou diz o que faltou; escala 1:7.500 não vira 1:7')
    camadas = [{'tipo': 'traco', 'fechado': False, 'camada': c, 'x_mm': [0, 100], 'y_mm': [0, 0]} for c in ('1ª ETAPA-TUBO-PEAD-DE630', 'TEXTO-TUBO', 'EIXO-VIAS')]
    conferir(linear.eixo(camadas) == {'eixo': 'camada', 'eixo_mm': 100.0, 'eixo_vertices': 0, 'deflexoes': [], 'eixo_camadas': {'1ª ETAPA-TUBO-PEAD-DE630': 100.0}},
             'linear: sem faixa, o eixo é a camada de tubo projetado (o texto do tubo e o eixo de via ficam de fora)')


def motores_falsos(ia, qwen3=None, apple=None, glm='', vision=''):
    """Troca os motores do mini por falsos (o teste é o mesmo em qualquer máquina) e devolve como desfazer."""
    antes = {n: getattr(ia, n) for n in ('ollama', 'apple', 'ocr_glm', 'vision', 'instalado')}
    ia.ollama = lambda modelo, prompt, esquema=None, imagens=(), parcial=False: (json.dumps(qwen3(prompt) if callable(qwen3) else qwen3), {})
    ia.apple = lambda prompt, esquema=None: (json.dumps(apple(prompt) if callable(apple) else apple), {})
    ia.ocr_glm = lambda caminho, instrucao: glm(caminho, instrucao) if callable(glm) else glm
    ia.vision = lambda caminho: vision
    ia.instalado = lambda modulo: modulo == 'Vision' or (modulo == 'apple_fm_sdk' and apple is not None)
    return lambda: [setattr(ia, n, f) for n, f in antes.items()]


def testar_ia(carimbo):
    """A IA conferida: valor que não está no texto é inventado; dois motores que concordam confirmam; família só da
    lista; número do OCR só confirmado nos dois leitores; tabela colada sem a linha repetida."""
    import conferencia
    import ia
    import ocr
    respostas = {'escala': '1:1000', 'data': '09/2020', 'projetista': 'HIDRO ENGENHARIA LTDA', 'obra': 'DUPLICAÇÃO DA BR-277'}
    desfazer = motores_falsos(ia, qwen3=respostas, apple={**respostas, 'escala': '1:500'})
    try:
        campos, erros = conferencia.carimbo_conferido(carimbo, {}, True)
        eta = conferencia.desempatar('ESTAÇÃO DE TRATAMENTO')
    finally:
        desfazer()
    conferir(campos['escala']['status'] == 'confirmado' and campos['escala']['valor'] == '1:1000' and campos['escala']['inventado'] == ['apple']
             and campos['projetista']['status'] == 'confirmado' and campos['obra']['status'] == 'vazio' and campos['obra']['inventado'] == ['apple', 'qwen3']
             and campos['municipio']['status'] == 'um_leitor' and not erros,
             'ia: código × qwen3 × Apple FM — o que concorda é confirmado; a obra e a escala 1:500 que não estão no carimbo são inventadas e não entram')
    desfazer = motores_falsos(ia, qwen3={'familia': 'ponte'}, apple={'familia': 'eta'})
    try:
        fora = conferencia.desempatar('?')
    finally:
        desfazer()
    conferir(eta['familia'] == 'indefinida' and fora['familia'] == 'indefinida', 'ia: desempate sem resposta da lista ou sem acordo fica indefinida')
    desfazer = motores_falsos(ia, qwen3={'familia': 'eta'}, apple={'familia': 'eta'})
    try:
        eta = conferencia.desempatar('ESTAÇÃO DE TRATAMENTO')
    finally:
        desfazer()
    conferir((eta['familia'], eta['grupo'], eta['familia_origem']) == ('eta', 'localizada', 'ia_concordante'), 'ia: os dois motores escolhem eta: família e grupo')
    valores = ocr.alegacoes({'glm_ocr': 'PLANTA ESCALA H=1:1000\nEST 77\n246,939\nEST 323', 'vision': 'ESCALA H = 1:1000\nEST 77 246.939'}, {}, {'fatia': 1})
    status = {(v['padrao'], v['valor']): v['status'] for v in valores}
    conferir(status[('estaca', 'EST323')] == 'so_glm' and status[('estaca', 'EST77')] == 'confirmado' and status[('cota', '246.939')] == 'confirmado'
             and status[('escala', '1:1000')] == 'confirmado', 'ia: número do OCR só é confirmado quando Vision e glm-ocr leram o mesmo (a EST 323 fica so_glm)')
    linha = '<tr><td>01</td><td>310015</td><td>COLARINHO PE 100 DE 630</td><td>06</td><td>PÇ</td></tr>'
    desfazer = motores_falsos(ia, glm=f'<table>{linha}{linha}<tr><td>02</td><td>284983</td><td>FLANGE</td><td>06</td><td>PÇ</td></tr></table>',
                              vision='01 310015 COLARINHO PE 100 DE 630 06 PÇ\n02 FLANGE 06 PÇ')
    try:
        tabela = ocr.ler_tabela(Path('faixa.png'), {'imagem': 1})
    finally:
        desfazer()
    conferir([l['status'] for l in tabela] == ['confirmada', 'pendente'] and tabela[1]['nao_confirmados'] == ['284983'],
             'ia: tabela colada sem a linha repetida; número que o Vision não leu deixa a linha pendente')


def testar_congelamento(pasta):
    """A mesma pergunta ao mesmo modelo devolve a resposta guardada, sem chamar de novo (§8.2)."""
    import ia
    ia.DADOS, chamadas = pasta / 'dados', []
    ia.congelados.cache_clear()
    chamar = lambda: (chamadas.append(1) or 'resposta', {'motor': 'falso'})
    primeira, segunda = ia.congelado({'pergunta': 1}, chamar), ia.congelado({'pergunta': 1}, chamar)
    ia.congelados.cache_clear()
    terceira = ia.congelado({'pergunta': 1}, chamar)
    conferir(len(chamadas) == 1 and primeira[0] == segunda[0] == terceira[0] == 'resposta' and terceira[1]['congelado'],
             'ia: a mesma chave não chama o modelo de novo, nem em outra execução (congelamento.jsonl)')


def testar_rodada(pasta):
    """A rodada lê o que o extrator entregou, uma vez por versão; com a IA (falsa) ligada, a prancha sai inteira nos CSV."""
    import hashlib
    import ia
    import projeto
    projeto.DADOS, projeto.SAIDAS, ia.DADOS = pasta / 'dados', pasta / 'saidas', pasta / 'dados'
    entregas = pasta / 'para_projeto'
    entregas.mkdir()
    ia.configuracao('operacao')['entregas'] = str(entregas)
    conteudo = pdf_prancha()
    sha = hashlib.sha256(conteudo).hexdigest()
    (entregas / f'{sha}.pdf').write_bytes(conteudo)
    linha = {'id': 'ARQ-000812', 'caminho': 'obras/foz.zip/012-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1.pdf', 'nome': '012-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1.pdf',
             'sha256': sha, 'acervo': 'obras', 'obra': 'Foz AAT-06', 'formato': 'A1', 'classe': 'vetorial_curva', 'sinais': ['camadas', 'nome', 'carimbo']}
    (entregas / 'entregas.jsonl').write_text(json.dumps({'tipo': 'metadata'}) + '\n' + json.dumps(linha) + '\n' + json.dumps(linha) + '\n')
    respostas = {'escala': '1:1000', 'folha': '012/019', 'titulo': 'ADUTORA DE ÁGUA TRATADA AAT-06 PLANTA E PERFIL'}
    desfazer = motores_falsos(ia, qwen3=respostas, apple=respostas, glm='ESCALA 1:1000\nEST 77\nEST 323', vision='ESCALA 1:1000 EST 77')
    try:
        projeto.rodada()
        segunda = json.loads((pasta / 'saidas' / 'status.json').read_text())['ultima_rodada']
        projeto.rodada()
        terceira = json.loads((pasta / 'saidas' / 'status.json').read_text())['ultima_rodada']
        versao = projeto.versao
        projeto.versao = lambda: {'versao': '0v999', 'commit': 'teste'}
        projeto.rodada()
        projeto.versao = versao
        quarta = json.loads((pasta / 'saidas' / 'status.json').read_text())
    finally:
        desfazer()
    conferir(segunda['lidas'] == 1 and terceira['pendentes'] == 0 and quarta['ultima_rodada']['lidas'] == 1 and quarta['versao'] == '0v999',
             'rodada: a entrega repetida vale uma vez; não relê na mesma versão; relê quando a versão muda')
    projeto.publicar({'lidas': 0})
    conferir(json.loads((pasta / 'saidas' / 'status.json').read_text())['saude'] == 'ok'
             and (pasta / 'saidas' / 'obras' / 'Foz AAT-06' / 'projeto' / '012-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1.dxf').exists()
             and (pasta / 'saidas' / 'obras' / 'Foz AAT-06' / 'projeto' / 'pranchas.csv').exists(),
             'rodada: o DXF e os CSV em <acervo>/<obra>/projeto/ (a obra do extrator, ao lado do extrator/) e o status.json ok')
    conferir(projeto.obra_de({'caminho': 'obras/SAIC.zip/pranchas/f.pdf'}) == ('obras', 'SAIC') and projeto.obra_de({'caminho': 'obras/f.pdf'}) == ('obras', '_avulsos'),
             'rodada: sem a obra na entrega, ela sai do caminho com a regra do extrator (o zip do 1º nível; o arquivo solto é _avulsos)')
    sistema = pasta / 'saidas' / '_sistema' / 'projeto'
    prancha = (sistema / 'pranchas.csv').read_text(encoding='utf-8-sig')
    carimbo = (sistema / 'carimbo.csv').read_text(encoding='utf-8-sig')
    valores = (sistema / 'valores_ocr.csv').read_text(encoding='utf-8-sig')
    lista = (sistema / 'itens.csv').read_text(encoding='utf-8-sig')
    conferir('TUBO PEAD DE 630;;300,00;m;m;comprimento;300.00' in lista and lista.count('\n') == 4,
             'rodada: itens.csv com os 3 materiais da relação, o tubo em metros (300,00 → 300.00 m)')
    conferir(';fecha;' in prancha and 'escala;1:1000;confirmado' in carimbo and 'EST323;so_glm' in valores and 'EST77;confirmado' in valores,
             'rodada: escala do carimbo confirmada por código e IA, a conferência fecha, o OCR das fatias com o status de cada valor')


def testar_mini():
    """As agendas do launchd: a rodada a cada 10 min e o atualizar a cada 5, com o python que instala."""
    import plistlib
    import mini
    agendas = {nome: plistlib.loads(mini.plist(f'{mini.PREFIXO}.{nome}', argumentos, agenda)) for nome, (argumentos, agenda) in mini.agendas().items()}
    conferir(agendas['rodada']['ProgramArguments'][1:] == [str(RAIZ / 'codigo' / 'projeto.py'), 'rodada'] and agendas['rodada']['StartInterval'] == 600
             and agendas['atualizar']['StartInterval'] == 300 and agendas['rodada']['ProgramArguments'][0] == sys.executable
             and list(agendas)[-1] == 'atualizar', 'mini: rodada a cada 10 min, atualizar a cada 5 (por último), com o python que instala')


def aferir():
    """Régua da regra 17 sobre codigo/*.py: órfã, comprimento, profundidade, duplicata, arquivo raso."""
    LIMITE = {'linhas': 60, 'fundo': 4, 'funcoes_por_arquivo': 5}
    arvores = {a.name: ast.parse(a.read_text()) for a in sorted((RAIZ / 'codigo').glob('*.py'))}
    citados = {no.id if isinstance(no, ast.Name) else no.attr if isinstance(no, ast.Attribute) else no.value
               for arvore in arvores.values() for no in ast.walk(arvore)
               if isinstance(no, (ast.Name, ast.Attribute)) or (isinstance(no, ast.Constant) and isinstance(no.value, str))}
    funcoes = [(nome, no) for nome, arvore in arvores.items() for no in ast.walk(arvore) if isinstance(no, ast.FunctionDef)]

    def fundo(no, nivel=0):
        filhos = [f for campo in ('body', 'orelse', 'finalbody', 'handlers') for f in getattr(no, campo, [])
                  if not (campo == 'orelse' and isinstance(f, ast.If) and len(no.orelse) == 1)]
        indentam = (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.ExceptHandler, ast.FunctionDef)
        return max([fundo(f, nivel + isinstance(f, indentam)) for f in filhos] + [nivel])
    corpos = {}
    for nome, no in funcoes:
        corpos.setdefault(ast.dump(ast.Module(body=no.body, type_ignores=[])), []).append(f'{nome}:{no.name}')
    return {'rodada': date.today().isoformat(), 'funcoes': len(funcoes),
            'orfas': sorted(f'{n}:{f.name}' for n, f in funcoes if f.name not in citados and f.col_offset == 0),
            'longas': sorted(f'{n}:{f.name}' for n, f in funcoes if f.end_lineno - f.lineno + 1 > LIMITE['linhas']),
            'fundas': sorted(f'{n}:{f.name}' for n, f in funcoes if fundo(f) > LIMITE['fundo']),
            'duplicatas': sorted(v for v in corpos.values() if len(v) > 1),
            'rasos': sorted(n for n in arvores if n != 'cliente_gpu.py' and sum(isinstance(f, ast.FunctionDef) for f in arvores[n].body) < LIMITE['funcoes_por_arquivo'])}


def conferir_afericao(medida, segundos, registrar):
    """Falha com órfã ou duplicata; com longa, funda ou rasa só se piorou desde a última linha (17.1); tempo dos testes
    acima de 1,5× o da última linha da mesma máquina também falha, menos ao registrar (o tempo novo vira a referência)."""
    import socket
    historico = RAIZ / 'codigo' / 'afericao.jsonl'
    linhas = [json.loads(l) for l in historico.read_text().splitlines() if l.strip()] if historico.exists() else []
    anterior, maquina = (linhas or [{}])[-1], socket.gethostname()
    da_maquina = next((l for l in reversed(linhas) if l.get('maquina') == maquina), None)
    linha = {**{k: len(v) if isinstance(v, list) else v for k, v in medida.items()}, 'segundos_testes': round(segundos, 1), 'maquina': maquina}
    print(json.dumps(linha, ensure_ascii=False))
    for chave in ('longas', 'fundas', 'rasos'):
        if medida[chave]:
            print(f'     {chave}: {", ".join(medida[chave])}')
    conferir(not medida['orfas'], f"sem função órfã {medida['orfas'] or ''}")
    conferir(not medida['duplicatas'], f"sem duplicata {medida['duplicatas'] or ''}")
    for chave in ('longas', 'fundas', 'rasos'):
        conferir(linha[chave] <= anterior.get(chave, linha[chave]), f'{chave}: não piorou ({anterior.get(chave, "—")} → {linha[chave]})')
    if not registrar and da_maquina:
        conferir(segundos <= 1.5 * da_maquina['segundos_testes'] + 1, f'tempo dos testes dentro de 1,5× o registrado em {maquina}')
    if registrar:
        with historico.open('a') as arquivo:
            arquivo.write(json.dumps(linha, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    marca = time.perf_counter()
    with tempfile.TemporaryDirectory() as temporaria:
        pasta = Path(temporaria)
        testar_conceitos()
        primitivas = testar_folha(pasta)
        carimbo, _ = testar_leitura(primitivas)
        testar_linear(primitivas)
        testar_itens()
        testar_tabela_com_secao()
        testar_itens_colados()
        testar_ia(carimbo)
        testar_congelamento(pasta)
        testar_rodada(pasta)
        testar_mini()
    conferir_afericao(aferir(), time.perf_counter() - marca, 'registrar' in sys.argv)
