"""A folha: o perfil (é prancha? formato, classe, camadas do CAD, GeoPDF) e o vetor — cada primitiva da página (traço,
preenchimento, texto, imagem) com a camada do CAD, a cor, a espessura e as coordenadas em mm de papel, origem embaixo à
esquerda (notas/plano_projeto.md §3 e §5, D1: a fonte é o geometria.parquet; o DXF é vista, sai dele e se regenera).

Lido pelo pdfium (0,9 s na folha de 78 mil caminhos em que o pdfplumber levava 69 s, extrator 1v56). Reconhecimento e
camadas trazidos do prancha.py do ialocal.extrator até a 2v75; regras em conceitos/prancha.json.
"""
import json
import math
import re
from pathlib import Path

import ia

MM_POR_PT = 25.4 / 72


def formato(largura_mm, altura_mm):
    """A0…A4 com tolerância; `fora_de_serie` se não casa e é pelo menos A3; `pequeno` abaixo disso."""
    RECONHECER = ia.configuracao('prancha')['reconhecer']
    menor, maior = sorted((largura_mm, altura_mm))
    for nome, (lado_menor, lado_maior) in RECONHECER['formatos_mm'].items():
        if abs(menor - lado_menor) <= RECONHECER['tolerancia_mm'] and abs(maior - lado_maior) <= RECONHECER['tolerancia_mm']:
            return nome
    return 'fora_de_serie' if menor >= RECONHECER['formatos_mm']['A3'][0] else 'pequeno'


def catalogo(caminho):
    """Nomes das camadas do CAD (grupos de conteúdo opcional) e se alguma página tem georreferência (GeoPDF: /VP com
    /Measure, ou o /LGIDict da Adobe). Só o catálogo e o dicionário das páginas: nenhuma página é interpretada."""
    import pdfplumber
    from pdfminer.pdftypes import resolve1
    try:
        with pdfplumber.open(caminho) as pdf:
            grupos = resolve1((resolve1(pdf.doc.catalog.get('OCProperties')) or {}).get('OCGs')) or []
            nomes = [resolve1(g).get('Name', b'') for g in grupos]
            geo = any('VP' in p.page_obj.attrs or 'LGIDict' in p.page_obj.attrs for p in pdf.pages)
    except Exception:  # PDF que o pdfminer não lê fica sem camadas; o resto vem do pdfium
        return {'camadas': [], 'geopdf': False}
    texto = lambda n: n.decode('utf-16' if n[:2] in (b'\xfe\xff', b'\xff\xfe') else 'utf-8', errors='replace')
    return {'camadas': [texto(n) if isinstance(n, bytes) else str(n) for n in nomes], 'geopdf': geo}


def perfilar(documento, numero, nome, camadas):
    """Formato, contagens, classe e sinais de uma página. É prancha se o formato é A3 ou maior e há sinais bastantes
    (camadas do CAD, nome de desenho, palavras de carimbo, desenho vetorial denso); raster pede menos sinais."""
    import pypdfium2.raw as raw
    RECONHECER, CLASSE = ia.configuracao('prancha')['reconhecer'], ia.configuracao('prancha')['classe']
    pagina = documento[numero]
    largura, altura = pagina.get_size()
    folha = formato(largura * MM_POR_PT, altura * MM_POR_PT)
    perfil = {'pagina': numero + 1, 'formato': folha, 'largura_mm': round(largura * MM_POR_PT, 1),
              'altura_mm': round(altura * MM_POR_PT, 1), 'e_prancha': False, 'motivo': f'formato {folha}'}
    if folha not in RECONHECER['formatos_de_prancha']:
        return perfil
    objetos = list(pagina.get_objects(max_depth=1))
    caixas = [o.get_bounds() for o in objetos if o.type == raw.FPDF_PAGEOBJ_IMAGE]
    texto = pagina.get_textpage().get_text_range()
    perfil.update(caracteres=len(texto.strip()), caminhos=sum(o.type == raw.FPDF_PAGEOBJ_PATH for o in objetos), imagens=len(caixas),
                  fracao_imagem=round(min(sum((d - e) * (c - b) for e, b, d, c in caixas) / (largura * altura), 1), 3))
    if perfil['caracteres'] < CLASSE['caracteres_raster'] and perfil['fracao_imagem'] >= CLASSE['fracao_imagem_raster']:
        perfil['classe'] = 'raster'
    else:
        perfil['classe'] = 'vetorial_texto' if perfil['caracteres'] >= CLASSE['caracteres_texto'] else 'vetorial_curva'
    palavras = {p.lower() for p in re.findall(RECONHECER['carimbo'], texto)}
    sinais = [s for s, sim in (('camadas', bool(camadas)), ('nome', bool(re.search(RECONHECER['nome'], Path(nome).stem))),
                               ('carimbo', len(palavras) >= 2), ('desenho', perfil['caminhos'] >= RECONHECER['caminhos_desenho'])) if sim]
    minimo = RECONHECER['sinais_minimos_raster' if perfil['classe'] == 'raster' else 'sinais_minimos']
    perfil.update(e_prancha=len(sinais) >= minimo, sinais=sinais, motivo=f"{len(sinais)} sinal(is) de {minimo}: {', '.join(sinais) or 'nenhum'}")
    return perfil


def camada_da_marca(objeto):
    """A camada (marca OC) do objeto; None sem marca. O nome sai do valor bruto: o GetParamStringValue perde o acento do
    UTF-16 que o CAD grava ('1ª ETAPA' virava '1\\x00 ETAPA', extrator 2v60)."""
    import ctypes
    import pypdfium2.raw as raw
    texto, bruto, n = (ctypes.c_ushort * 8)(), (ctypes.c_ubyte * 2048)(), ctypes.c_ulong()
    for indice in range(raw.FPDFPageObj_CountMarks(objeto)):
        marca = raw.FPDFPageObj_GetMark(objeto, indice)
        raw.FPDFPageObjMark_GetName(marca, texto, ctypes.sizeof(texto), ctypes.byref(n))
        if bytes(texto)[:n.value].decode('utf-16-le').rstrip('\0') == 'OC' and \
                raw.FPDFPageObjMark_GetParamBlobValue(marca, b'Name', bruto, ctypes.sizeof(bruto), ctypes.byref(n)):
            nome = bytes(bruto[:n.value])
            return nome.decode('utf-16') if nome[:2] in (b'\xfe\xff', b'\xff\xfe') else nome.decode('latin-1')
    return None


def subcaminhos(objeto, matriz):
    """Os sub-caminhos de um caminho, cada um com os pontos em pt de página (matriz aplicada) e se fecha; a curva de
    Bézier entra por 8 cordas."""
    import ctypes
    import pypdfium2.raw as raw
    a, b, c, d, e, f = matriz
    x, y, achados, pontos, fechado, bezier = ctypes.c_float(), ctypes.c_float(), [], [], False, []
    for indice in range(raw.FPDFPath_CountSegments(objeto)):
        segmento = raw.FPDFPath_GetPathSegment(objeto, indice)
        raw.FPDFPathSegment_GetPoint(segmento, ctypes.byref(x), ctypes.byref(y))
        ponto, tipo = (a * x.value + c * y.value + e, b * x.value + d * y.value + f), raw.FPDFPathSegment_GetType(segmento)
        if tipo == raw.FPDF_SEGMENT_MOVETO:
            if len(pontos) > 1:
                achados.append((pontos, fechado))
            pontos, fechado, bezier = [ponto], False, []
            continue
        if tipo == raw.FPDF_SEGMENT_BEZIERTO:
            bezier.append(ponto)
            if len(bezier) < 3:
                continue
            p0, (p1, p2, p3), bezier = pontos[-1], bezier, []
            pontos += [tuple((1 - t) ** 3 * u + 3 * (1 - t) ** 2 * t * v + 3 * (1 - t) * t ** 2 * w + t ** 3 * z
                             for u, v, w, z in zip(p0, p1, p2, p3)) for t in (i / 8 for i in range(1, 9))]
        else:
            pontos.append(ponto)
        fechado = fechado or bool(raw.FPDFPathSegment_GetClose(segmento))
    if len(pontos) > 1:
        achados.append((pontos, fechado))
    return achados


def vetorizar(pagina, numero):
    """Toda primitiva da página, em mm de papel: o caminho traçado vira `traco`, o preenchido `preenchimento` (um por
    sub-caminho), o texto `texto` (com a origem da linha de base, a altura e o ângulo) e a imagem colada `imagem` (a
    caixa). O conteúdo de formulário (XObject) entra com a camada do formulário, se não tem a própria, e com a matriz
    dele composta."""
    import ctypes
    import pypdfium2.raw as raw
    textos, linhas = pagina.get_textpage(), []
    m, rgba, real = raw.FS_MATRIX(), [ctypes.c_uint() for _ in range(4)], ctypes.c_float()
    modo, traco = ctypes.c_int(), ctypes.c_int()
    esquerda, baixo, direita, cima = (ctypes.c_float() for _ in range(4))
    compor = lambda f, g: (f[0] * g[0] + f[1] * g[2], f[0] * g[1] + f[1] * g[3], f[2] * g[0] + f[3] * g[2],
                           f[2] * g[1] + f[3] * g[3], f[4] * g[0] + f[5] * g[2] + g[4], f[4] * g[1] + f[5] * g[3] + g[5])
    cor = lambda ler, bruto: '{:02x}{:02x}{:02x}'.format(*(c.value for c in rgba[:3])) if ler(bruto, *(ctypes.byref(c) for c in rgba)) else ''
    mm = lambda valores: [round(v * MM_POR_PT, 3) for v in valores]

    def caixa(objeto, pai):
        """A caixa do objeto na página: os quatro cantos da caixa dele levados pela matriz do formulário pai."""
        raw.FPDFPageObj_GetBounds(objeto, *(ctypes.byref(v) for v in (esquerda, baixo, direita, cima)))
        cantos = [(pai[0] * u + pai[2] * v + pai[4], pai[1] * u + pai[3] * v + pai[5])
                  for u in (esquerda.value, direita.value) for v in (baixo.value, cima.value)]
        return mm([min(c[0] for c in cantos), min(c[1] for c in cantos), max(c[0] for c in cantos), max(c[1] for c in cantos)])

    def visitar(objeto, camada, pai, fundo):
        camada = camada_da_marca(objeto) or camada
        raw.FPDFPageObj_GetMatrix(objeto, ctypes.byref(m))
        matriz = compor((m.a, m.b, m.c, m.d, m.e, m.f), pai)
        tipo, base = raw.FPDFPageObj_GetType(objeto), {'pagina': numero + 1, 'camada': camada or ''}
        if tipo == raw.FPDF_PAGEOBJ_FORM and fundo < 8:
            for indice in range(raw.FPDFFormObj_CountObjects(objeto)):
                visitar(raw.FPDFFormObj_GetObject(objeto, indice), camada, matriz, fundo + 1)
        elif tipo == raw.FPDF_PAGEOBJ_PATH:
            raw.FPDFPath_GetDrawMode(objeto, ctypes.byref(modo), ctypes.byref(traco))
            raw.FPDFPageObj_GetStrokeWidth(objeto, ctypes.byref(real))
            espessura = round(real.value * math.sqrt(abs(matriz[0] * matriz[3] - matriz[1] * matriz[2])) * MM_POR_PT, 3)
            pintas = [('preenchimento', cor(raw.FPDFPageObj_GetFillColor, objeto), 0.0)] * bool(modo.value) + \
                     [('traco', cor(raw.FPDFPageObj_GetStrokeColor, objeto), espessura)] * bool(traco.value)
            for pontos, fechado in subcaminhos(objeto, matriz):
                xs, ys = mm(p[0] for p in pontos), mm(p[1] for p in pontos)
                for nome, tinta, largura in pintas:
                    linhas.append({**base, 'tipo': nome, 'cor': tinta, 'espessura_mm': largura, 'fechado': fechado or nome == 'preenchimento',
                                   'x_mm': xs, 'y_mm': ys, 'x0_mm': min(xs), 'y0_mm': min(ys), 'x1_mm': max(xs), 'y1_mm': max(ys)})
        elif tipo == raw.FPDF_PAGEOBJ_TEXT:
            tamanho = raw.FPDFTextObj_GetFontSize(objeto, ctypes.byref(real)) and real.value
            quantos = raw.FPDFTextObj_GetText(objeto, textos.raw, None, 0)
            memoria = (ctypes.c_ushort * max(quantos, 1))()
            raw.FPDFTextObj_GetText(objeto, textos.raw, memoria, quantos * 2)
            escrito = bytes(memoria).decode('utf-16-le', errors='replace').rstrip('\0')
            if escrito.strip():
                x0, y0, x1, y1 = caixa(objeto, pai)
                linhas.append({**base, 'tipo': 'texto', 'cor': cor(raw.FPDFPageObj_GetFillColor, objeto), 'texto': escrito,
                               'x_mm': mm([matriz[4]]), 'y_mm': mm([matriz[5]]), 'x0_mm': x0, 'y0_mm': y0, 'x1_mm': x1, 'y1_mm': y1,
                               'tamanho_mm': round(tamanho * math.hypot(matriz[2], matriz[3]) * MM_POR_PT, 3),
                               'angulo_graus': round(math.degrees(math.atan2(matriz[1], matriz[0])), 2)})
        elif tipo == raw.FPDF_PAGEOBJ_IMAGE:
            x0, y0, x1, y1 = caixa(objeto, pai)
            linhas.append({**base, 'tipo': 'imagem', 'x0_mm': x0, 'y0_mm': y0, 'x1_mm': x1, 'y1_mm': y1})
    for indice in range(raw.FPDFPage_CountObjects(pagina.raw)):
        visitar(raw.FPDFPage_GetObject(pagina.raw, indice), None, (1, 0, 0, 1, 0, 0), 0)
    return linhas


def gravar_geometria(linhas, destino):
    """O geometria.parquet: uma linha por primitiva, com o esquema fixo (a prancha sem texto ou sem imagem tem as
    mesmas colunas)."""
    import polars as pl
    ESQUEMA = {'pagina': pl.Int32, 'tipo': pl.Utf8, 'camada': pl.Utf8, 'cor': pl.Utf8, 'espessura_mm': pl.Float64,
               'fechado': pl.Boolean, 'x_mm': pl.List(pl.Float64), 'y_mm': pl.List(pl.Float64), 'x0_mm': pl.Float64,
               'y0_mm': pl.Float64, 'x1_mm': pl.Float64, 'y1_mm': pl.Float64, 'texto': pl.Utf8, 'tamanho_mm': pl.Float64,
               'angulo_graus': pl.Float64}
    tabela = pl.DataFrame([{c: l.get(c) for c in ESQUEMA} for l in linhas], schema=ESQUEMA)
    tabela.with_row_index('primitiva').write_parquet(destino)


def gravar_dxf(linhas, destino, folha):
    """O DXF em mm de papel: uma camada do DXF por camada do CAD (sem camada, a cor e a espessura do traço); traço vira
    LWPOLYLINE, preenchimento HATCH sólido, texto TEXT com altura e ângulo, imagem um retângulo na camada IMAGEM, e a
    folha uma moldura na camada FOLHA."""
    import ezdxf
    from ezdxf import colors
    DXF = ia.configuracao('prancha')['dxf']
    documento = ezdxf.new(DXF['versao'])
    documento.header['$INSUNITS'] = 4  # milímetro
    modelo = documento.modelspace()
    documento.layers.add('FOLHA')
    documento.layers.add('IMAGEM')

    def camada(linha):
        nome = linha['camada'] or DXF['sem_camada'].format(cor=linha.get('cor') or '000000', espessura=f"{linha.get('espessura_mm', 0):.2f}")
        nome = re.sub(DXF['proibidos'], '_', nome)[:250] or 'SEM_NOME'
        if nome not in documento.layers:
            documento.layers.add(nome)
        return nome
    for linha in linhas:
        atributos = {'layer': camada(linha)}
        if linha.get('cor'):
            atributos['true_color'] = colors.rgb2int(bytes.fromhex(linha['cor']))
        if linha['tipo'] == 'traco':
            modelo.add_lwpolyline(list(zip(linha['x_mm'], linha['y_mm'])), close=linha['fechado'],
                                  dxfattribs={**atributos, 'const_width': linha['espessura_mm']})
        elif linha['tipo'] == 'preenchimento':
            hachura = modelo.add_hatch(dxfattribs=atributos)
            hachura.paths.add_polyline_path(list(zip(linha['x_mm'], linha['y_mm'])), is_closed=True)
        elif linha['tipo'] == 'texto':
            modelo.add_text(linha['texto'], height=max(linha['tamanho_mm'], 0.1),
                            dxfattribs={**atributos, 'insert': (linha['x_mm'][0], linha['y_mm'][0]), 'rotation': linha['angulo_graus']})
        elif linha['tipo'] == 'imagem':
            modelo.add_lwpolyline([(linha['x0_mm'], linha['y0_mm']), (linha['x1_mm'], linha['y0_mm']), (linha['x1_mm'], linha['y1_mm']),
                                   (linha['x0_mm'], linha['y1_mm'])], close=True, dxfattribs={'layer': 'IMAGEM'})
    modelo.add_lwpolyline([(0, 0), (folha[0], 0), folha, (0, folha[1])], close=True, dxfattribs={'layer': 'FOLHA'})
    documento.saveas(destino)
    return sorted(l.dxf.name for l in documento.layers)


def contagem(linhas):
    """Quantas primitivas de cada tipo e o comprimento traçado por camada, em mm de papel (o que o DXF tem de ter)."""
    tipos, por_camada = {}, {}
    for linha in linhas:
        tipos[linha['tipo']] = tipos.get(linha['tipo'], 0) + 1
        if linha['tipo'] == 'traco':
            pontos = list(zip(linha['x_mm'], linha['y_mm']))
            comprimento = sum(math.dist(a, b) for a, b in zip(pontos, pontos[1:] + pontos[:1] * linha['fechado']))
            por_camada[linha['camada']] = round(por_camada.get(linha['camada'], 0) + comprimento, 1)
    return {'primitivas': tipos, 'traco_por_camada_mm': json.dumps(por_camada, ensure_ascii=False)}
