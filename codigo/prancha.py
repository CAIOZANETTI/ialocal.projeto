"""Prancha de projeto em PDF (notas/plano_projeto.md §4, §4-A e §11): duas tarefas da fila, regras em conceitos/prancha.json.

ler_prancha (código): é prancha? (formato A3 ou maior e sinais: camadas do CAD, nome de desenho, palavras de carimbo);
se é, a classe (vetorial com texto, vetorial com texto em curva, raster), o carimbo pelo texto real, a família (linear ou
localizada, por regra) e o eixo desenhado — comprimento em mm de papel e deflexões — tirado da faixa colorida ou, sem
ela, dos traços das camadas de tubo projetado (2v60), por camada.
ler_prancha_ia (IA local): a folha em fatias de até 1.100 px, cada uma lida pelo glm-ocr e pelo Vision; um valor só é
`confirmado` quando os dois leram o mesmo no mesmo recorte (teste de 26/09: o gemma3 inventou cotas e o glm-ocr continuou
a sequência de estacas até a 323). A imagem colada (relação de materiais) é lida como tabela, em faixas. O qwen3 e o
Apple FM só desempatam a família, e só valem se concordam. Escala × eixo × tubo da relação é conferido pelo código.

Veio do ialocal.extrator (1v47 a 2v93) em 03/10/2026: lá eram duas tarefas da fila dele; aqui o ciclo do projeto
(ciclo.py) chama as duas sobre o PDF que o extrator entregou (entrega.py). A lógica de leitura é a mesma.
"""
import json
import math
import re
import time
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path

import comum
import ia
import tabela

MM_POR_PT = 25.4 / 72
NUMERO = r'\d+(?:[.,]\d+)?'


def formato(largura_mm, altura_mm):
    """A0…A4 com tolerância; `fora_de_serie` se não casa e é pelo menos A3; `pequeno` abaixo disso."""
    RECONHECER = comum.configuracao('prancha')['reconhecer']
    menor, maior = sorted((largura_mm, altura_mm))
    for nome, (lado_menor, lado_maior) in RECONHECER['formatos_mm'].items():
        if abs(menor - lado_menor) <= RECONHECER['tolerancia_mm'] and abs(maior - lado_maior) <= RECONHECER['tolerancia_mm']:
            return nome
    return 'fora_de_serie' if menor >= RECONHECER['formatos_mm']['A3'][0] else 'pequeno'


def camadas(caminho):
    """Nomes das camadas do CAD que o PDF guardou (grupos de conteúdo opcional); vazio se não há ou se não se lê. Só o
    catálogo é lido: o pdfplumber não abre página nenhuma aqui."""
    import pdfplumber
    from pdfminer.pdftypes import resolve1
    try:
        with pdfplumber.open(caminho) as pdf:
            grupos = resolve1((resolve1(pdf.doc.catalog.get('OCProperties')) or {}).get('OCGs')) or []
            nomes = [resolve1(g).get('Name', b'') for g in grupos]
    except Exception:  # PDF que o pdfminer não lê fica sem camadas; o resto do perfil vem do pdfium
        return []
    texto = lambda n: n.decode('utf-16' if n[:2] in (b'\xfe\xff', b'\xff\xfe') else 'utf-8', errors='replace')  # o CAD grava
    return [texto(n) if isinstance(n, bytes) else str(n) for n in nomes]  # nome com acento em UTF-16 (LAYOUT de Cambé)


def classe(perfil):
    """raster (quase sem texto, imagem cobrindo a folha), vetorial_texto ou vetorial_curva (texto desenhado como curva)."""
    LIMITE = comum.configuracao('prancha')['classe']
    if perfil['caracteres'] < LIMITE['caracteres_raster'] and perfil['fracao_imagem'] >= LIMITE['fracao_imagem_raster']:
        return 'raster'
    return 'vetorial_texto' if perfil['caracteres'] >= LIMITE['caracteres_texto'] else 'vetorial_curva'


def sinais(nome, texto, nomes_camadas, caminhos):
    """Quais sinais de prancha aparecem: camadas do CAD, nome de desenho, duas ou mais palavras de carimbo distintas e
    desenho vetorial denso (a folha de Cambé tinha 78 mil caminhos, nenhum texto e nenhuma camada: só o nome acendia)."""
    RECONHECER = comum.configuracao('prancha')['reconhecer']
    palavras = {p.lower() for p in re.findall(RECONHECER['carimbo'], texto)}
    return [s for s, sim in (('camadas', bool(nomes_camadas)), ('nome', bool(re.search(RECONHECER['nome'], Path(nome).stem))),
                             ('carimbo', len(palavras) >= 2), ('desenho', caminhos >= RECONHECER['caminhos_desenho'])) if sim]


def limites(objeto):
    """Caixa (esquerda, baixo, direita, cima) do objeto na página: get_bounds no pypdfium2 5, get_pos no 4."""
    return (objeto.get_bounds if hasattr(objeto, 'get_bounds') else objeto.get_pos)()


def perfilar(documento, caminho, nome):
    """Formato, contagens e sinais da primeira página pelo pdfium (0,9 s na folha de 78 mil caminhos em que o pdfplumber
    levava 69 s); o texto volta junto para a família."""
    import pypdfium2.raw as raw
    RECONHECER = comum.configuracao('prancha')['reconhecer']
    pagina = documento[0]
    largura, altura = pagina.get_size()
    folha = formato(largura * MM_POR_PT, altura * MM_POR_PT)
    perfil = {'paginas': len(documento), 'formato': folha, 'largura_mm': round(largura * MM_POR_PT),
              'altura_mm': round(altura * MM_POR_PT), 'e_prancha': False, 'motivo': f'formato {folha}', 'texto': ''}
    if folha not in RECONHECER['formatos_de_prancha']:
        return perfil
    objetos = list(pagina.get_objects(max_depth=1))
    caixas = [limites(o) for o in objetos if o.type == raw.FPDF_PAGEOBJ_IMAGE]
    textos = pagina.get_textpage()
    nomes = camadas(caminho)
    perfil.update(caracteres=textos.count_chars(), curvas=sum(o.type == raw.FPDF_PAGEOBJ_PATH for o in objetos),
                  imagens=len(caixas), camadas=len(nomes), nomes_camadas=json.dumps(nomes[:200], ensure_ascii=False),
                  fracao_imagem=round(min(sum((d - e) * (c - b) for e, b, d, c in caixas) / (largura * altura), 1), 3),
                  texto=textos.get_text_range(),
                  texto_folhas='\n'.join(documento[i].get_textpage().get_text_range()
                                          for i in range(min(len(documento), RECONHECER['maximo_paginas']))))
    perfil['classe'] = classe(perfil)
    achados = sinais(nome, perfil['texto'], nomes, perfil['curvas'])
    minimo = RECONHECER['sinais_minimos_raster' if perfil['classe'] == 'raster' else 'sinais_minimos']
    perfil.update(e_prancha=len(achados) >= minimo, sinais=','.join(achados),
                  motivo=f"{len(achados)} sinal(is) de {minimo}: {', '.join(achados) or 'nenhum'}")
    return perfil


def regiao_do_carimbo(pagina):
    """A região do carimbo na página em pt do pdfium (esquerda, baixo, direita, cima), pela fração de prancha.json."""
    x0, y0, x1, y1 = comum.configuracao('prancha')['carimbo']['regiao']
    largura, altura = pagina.get_size()
    return x0 * largura, (1 - y1) * altura, x1 * largura, (1 - y0) * altura


def campo_por_ancora(linhas, regra):
    """O valor de um campo do carimbo: o resto da linha do rótulo ou, se vazio, a linha de baixo; com `valor`, só o
    trecho que casa (nas duas). '' se o rótulo não aparece."""
    for numero, linha in enumerate(linhas):
        achado = re.search(regra['rotulo'], linha)
        if not achado:
            continue
        candidatos = [linha[achado.end():].strip(' :-–.\t'), *(l.strip() for l in linhas[numero + 1:numero + 2])]
        for candidato in candidatos:
            valor = re.search(regra['valor'], candidato) if regra.get('valor') else None
            if regra.get('valor') and valor:
                return valor.group(0).strip()
            if not regra.get('valor') and len(candidato) >= 3:
                return candidato[:120]
    return ''


def campos_do_carimbo(texto, nome):
    """Os campos do carimbo no texto (real ou lido): os por padrão (folha, data, escala, revisão do nome), os por
    rótulo-âncora (número, título, projetista, responsável, CREA, ART…), o quadro de revisões e se o número do desenho
    confere com o nome do arquivo."""
    CARIMBO = comum.configuracao('prancha')['carimbo']
    campos = {}
    for campo, padrao in CARIMBO['campos'].items():
        achado = re.search(padrao, Path(nome).stem if campo == 'revisao_nome' else texto)
        campos[campo] = ('/'.join(achado.groups()) if campo == 'folha' else achado.group(1)) if achado else ''
    linhas = [l for l in unicodedata.normalize('NFKC', texto).splitlines() if l.strip()]
    campos.update({campo: campo_por_ancora(linhas, regra) for campo, regra in CARIMBO['ancoras'].items()})
    revisoes = [m.groups() for m in (re.match(CARIMBO['revisoes'], l) for l in linhas) if m]
    campos['revisoes'] = json.dumps([{'revisao': r, 'data': d, 'descricao': x.strip()[:120]} for r, d, x in revisoes], ensure_ascii=False)
    campos['revisao_vigente'] = revisoes[-1][0] if revisoes else ''
    compacto = lambda s: re.sub(r'\s+', '', unicodedata.normalize('NFKC', s)).upper()
    campos['arquivo_confere'] = compacto(Path(nome).stem) in compacto(texto) or (
        bool(campos['numero_desenho']) and compacto(campos['numero_desenho']) in compacto(Path(nome).stem))
    return campos


def ler_carimbo(pagina, nome):
    """O carimbo pelo texto real da região (pdfium): os campos com o prefixo carimbo_ e a camada — `texto` se há texto
    bastante para ler por código, `imagem` se o carimbo é desenho (texto em curva ou escaneado) e vai ao OCR em recorte."""
    esquerda, baixo, direita, cima = regiao_do_carimbo(pagina)
    texto = pagina.get_textpage().get_text_bounded(left=esquerda, bottom=baixo, right=direita, top=cima)
    camada = 'texto' if len(texto.strip()) >= comum.configuracao('prancha')['carimbo']['caracteres_texto'] else 'imagem'
    campos = campos_do_carimbo(texto, nome) if camada == 'texto' else {}
    return {'carimbo_texto': texto[:2000], 'carimbo_camada': camada, **{f'carimbo_{c}': v for c, v in campos.items()}}


def recorte_do_carimbo(caminho, pasta):
    """A região do carimbo renderizada a ocr_dpi (o lado maior até ocr_lado_max_px), em PNG: o recorte que vai ao OCR."""
    import pypdfium2 as pdfium
    CARIMBO = comum.configuracao('prancha')['carimbo']
    destino = pasta / 'carimbo.png'
    if destino.exists():
        return destino
    documento = pdfium.PdfDocument(caminho)
    pagina = documento[0]
    esquerda, baixo, direita, cima = regiao_do_carimbo(pagina)
    largura, altura = pagina.get_size()
    escala = min(CARIMBO['ocr_dpi'] / 72, CARIMBO['ocr_lado_max_px'] / max(direita - esquerda, cima - baixo, 1))
    imagem = pagina.render(scale=escala, crop=(esquerda, baixo, largura - direita, altura - cima)).to_pil()
    documento.close()
    pasta.mkdir(parents=True, exist_ok=True)
    imagem.save(destino)
    return destino


def ler_carimbo_ocr(imagem, nome, com_vision, base):
    """O carimbo que é desenho, lido no recorte pelo glm-ocr e pelo Vision: cada campo vira uma linha com quem o leu —
    `confirmado` quando os dois leram o mesmo, `so_glm`/`so_vision` quando só um leu, `divergente` quando leram outra
    coisa (os dois valores ficam). Campo que ninguém leu não vira linha."""
    lida = ia.dupla_leitura(ia.ocr_da_pagina(imagem), imagem, com_vision)
    leituras = {leitor: campos_do_carimbo(texto, nome) if texto else {}
                for leitor, texto in (('glm_ocr', lida['texto']), ('vision', lida['texto_vision']))}
    linhas = []
    for campo in sorted(set(leituras['glm_ocr']) | set(leituras['vision'])):
        if campo in ('revisao_nome', 'arquivo_confere'):
            continue
        glm, vision = (str(leituras[l].get(campo) or '') for l in ('glm_ocr', 'vision'))
        if campo == 'revisoes':
            glm, vision = ('' if v == '[]' else v for v in (glm, vision))
        if not glm and not vision:
            continue
        status = ('confirmado' if normalizar(glm) == normalizar(vision) else 'divergente' if glm and vision
                  else 'so_glm' if glm else 'so_vision')
        linhas.append({**base, 'campo': campo, 'valor': glm if status != 'so_vision' else vision,
                       'valor_vision': vision if status == 'divergente' else '', 'status': status,
                       'erro': lida['erro'], 'erro_vision': lida['erro_vision']})
    return linhas


def linhas_do_carimbo_por_codigo(linha, base):
    """As linhas da família carimbo para o carimbo lido por código (texto real do PDF): leitor pdf, status codigo."""
    return [{**base, 'campo': c[len('carimbo_'):], 'valor': str(v), 'valor_vision': '', 'status': 'codigo', 'erro': '', 'erro_vision': ''}
            for c, v in linha.items() if c.startswith('carimbo_') and c not in ('carimbo_texto', 'carimbo_camada', 'carimbo_revisao_nome')
            and v not in ('', None, '[]')]


def familia(nome, texto):
    """Família pela primeira regra que casa: no nome, depois no código do desenho escrito no carimbo, e só então no texto
    sem os rótulos de tipo de linha (GAS GAS GAS… é a interferência desenhada, não a obra), de formulário e de existente;
    o grupo sai da família."""
    FAMILIAS = comum.configuracao('prancha')['familias']
    procurar = lambda alvo: next((f for f in FAMILIAS['ordem'] if re.search(FAMILIAS['padroes'][f], alvo)), '')
    codigos = ' '.join(re.findall(FAMILIAS['codigo_desenho'], texto))
    sem_tracejado = re.sub(FAMILIAS['rotulos_ignorados'], ' ', re.sub(r'\b(\w+)(?:\s+\1\b){2,}', ' ', texto))
    achada = procurar(Path(nome).stem) or procurar(codigos) or procurar(sem_tracejado)
    alvo = f'{Path(nome).stem}\n{texto}'
    return {'familia': achada or 'indefinida', 'grupo': FAMILIAS['grupo'].get(achada, ''), 'familia_origem': 'regra' if achada else '',
            'desenho': next((d for d, padrao in FAMILIAS['desenhos'].items() if re.search(padrao, alvo)), 'outro')}


def cadeias(triangulos):
    """Triângulos em sequência que dividem vértice formam uma faixa; a sequência que quebra abre outra."""
    faixas = []
    for pontos in triangulos:
        vertices = {(round(x, 1), round(y, 1)) for x, y in pontos}
        if faixas and vertices & faixas[-1][1]:
            faixas[-1] = (faixas[-1][0] + [pontos], vertices)
        else:
            faixas.append(([pontos], vertices))
    return [f[0] for f in faixas]


def centro(faixa):
    """Eixo da faixa: o ponto médio de cada par de bordas (o primeiro par de cada dois triângulos) e o do fim."""
    medio = lambda a, b: ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    return [medio(t[0], t[1]) for t in faixa[0::2]] + [medio(faixa[-1][1], faixa[-1][2])]


def comprimento_pt(vertices):
    return sum(math.dist(a, b) for a, b in zip(vertices, vertices[1:]))


def deflexoes(vertices):
    """Ângulo de cada dobra do eixo, em graus com sinal, a partir de `deflexao_minima_graus`."""
    MINIMA = comum.configuracao('prancha')['eixo']['deflexao_minima_graus']
    rumos = [math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) for a, b in zip(vertices, vertices[1:]) if math.dist(a, b) > 0.5]
    angulos = [(b - a + 180) % 360 - 180 for a, b in zip(rumos, rumos[1:])]
    return [round(a, 1) for a in angulos if abs(a) >= MINIMA]


def caminhos_na_cor(pagina, cores):
    """Pontos (x, y a partir do alto, em pt) de cada sub-caminho preenchido numa das cores, lidos no pdfium: a cor, o modo
    de preenchimento e os segmentos de cada objeto, com a matriz dele aplicada; cada moveto abre um sub-caminho."""
    import ctypes
    import pypdfium2.raw as raw
    altura, rgba, matriz = pagina.get_height(), [ctypes.c_uint() for _ in range(4)], raw.FS_MATRIX()
    modo, traco, x, y = ctypes.c_int(), ctypes.c_int(), ctypes.c_float(), ctypes.c_float()
    achados = []
    for objeto in pagina.get_objects(filter=[raw.FPDF_PAGEOBJ_PATH], max_depth=1):
        bruto = objeto.raw
        raw.FPDFPath_GetDrawMode(bruto, ctypes.byref(modo), ctypes.byref(traco))
        if not modo.value or not raw.FPDFPageObj_GetFillColor(bruto, *(ctypes.byref(c) for c in rgba)):
            continue
        cor = [c.value / 255 for c in rgba[:3]]
        if not any(max(abs(a - b) for a, b in zip(cor, alvo)) < 0.01 for alvo in cores):
            continue
        raw.FPDFPageObj_GetMatrix(bruto, ctypes.byref(matriz))
        pontos = []
        for indice in range(raw.FPDFPath_CountSegments(bruto)):  # o pdfium junta os triângulos da faixa num caminho só
            segmento = raw.FPDFPath_GetPathSegment(bruto, indice)
            if raw.FPDFPathSegment_GetType(segmento) == raw.FPDF_SEGMENT_MOVETO and pontos:
                achados.append(pontos)
                pontos = []
            raw.FPDFPathSegment_GetPoint(segmento, ctypes.byref(x), ctypes.byref(y))
            pontos.append((matriz.a * x.value + matriz.c * y.value + matriz.e, altura - (matriz.b * x.value + matriz.d * y.value + matriz.f)))
        achados.append(pontos)
    return achados


def camada_da_marca(objeto):
    """A camada (grupo de conteúdo opcional, marca OC) do objeto no pdfium; None sem marca. O nome sai do valor bruto: o
    GetParamStringValue perde o acento do UTF-16 que o CAD grava ('1ª ETAPA' virava '1\x00 ETAPA')."""
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


def comprimento_do_traco(objeto, matriz):
    """Comprimento em pt de papel dos sub-caminhos abertos de um caminho traçado (o preenchido não conta), com a matriz
    (a, b, c, d, e, f) aplicada; a curva de Bézier entra por 8 cordas."""
    import ctypes
    import pypdfium2.raw as raw
    modo, traco, x, y = ctypes.c_int(), ctypes.c_int(), ctypes.c_float(), ctypes.c_float()
    raw.FPDFPath_GetDrawMode(objeto, ctypes.byref(modo), ctypes.byref(traco))
    if not traco.value:
        return 0.0
    a, b, c, d, e, f = matriz
    total, trecho, pontos, fechado, bezier = 0.0, 0.0, [], False, []
    for indice in range(raw.FPDFPath_CountSegments(objeto)):
        segmento = raw.FPDFPath_GetPathSegment(objeto, indice)
        raw.FPDFPathSegment_GetPoint(segmento, ctypes.byref(x), ctypes.byref(y))
        ponto, tipo = (a * x.value + c * y.value + e, b * x.value + d * y.value + f), raw.FPDFPathSegment_GetType(segmento)
        if tipo == raw.FPDF_SEGMENT_MOVETO or not pontos:
            total, trecho, fechado, pontos = total + (0 if fechado else trecho), 0.0, False, [ponto]
            continue
        if tipo == raw.FPDF_SEGMENT_BEZIERTO:
            bezier.append(ponto)
            if len(bezier) < 3:
                continue
            p0, (p1, p2, p3), bezier = pontos[-1], bezier, []
            curva = [tuple((1 - t) ** 3 * u + 3 * (1 - t) ** 2 * t * v + 3 * (1 - t) * t ** 2 * w + t ** 3 * z
                           for u, v, w, z in zip(p0, p1, p2, p3)) for t in (i / 8 for i in range(1, 9))]
            trecho += comprimento_pt([p0, *curva])
        else:
            trecho += math.dist(pontos[-1], ponto)
        pontos.append(ponto)
        fechado = fechado or bool(raw.FPDFPathSegment_GetClose(segmento))
    return total + (0 if fechado else trecho)


def tracos_por_camada(pagina):
    """Comprimento em pt de papel dos traços abertos de cada camada da página; o conteúdo de formulário (XObject) entra
    com a camada do formulário, se não tem a própria, e com a matriz dele composta."""
    import ctypes
    import pypdfium2.raw as raw
    comprimentos, m = {}, raw.FS_MATRIX()
    compor = lambda f, g: (f[0] * g[0] + f[1] * g[2], f[0] * g[1] + f[1] * g[3], f[2] * g[0] + f[3] * g[2],
                           f[2] * g[1] + f[3] * g[3], f[4] * g[0] + f[5] * g[2] + g[4], f[4] * g[1] + f[5] * g[3] + g[5])
    def visitar(objeto, camada, pai, fundo):
        camada = camada_da_marca(objeto) or camada
        raw.FPDFPageObj_GetMatrix(objeto, ctypes.byref(m))
        matriz = compor((m.a, m.b, m.c, m.d, m.e, m.f), pai)
        tipo = raw.FPDFPageObj_GetType(objeto)
        if tipo == raw.FPDF_PAGEOBJ_FORM and fundo < 8:
            for indice in range(raw.FPDFFormObj_CountObjects(objeto)):
                visitar(raw.FPDFFormObj_GetObject(objeto, indice), camada, matriz, fundo + 1)
        elif tipo == raw.FPDF_PAGEOBJ_PATH and camada:
            comprimentos[camada] = comprimentos.get(camada, 0.0) + comprimento_do_traco(objeto, matriz)
    for indice in range(raw.FPDFPage_CountObjects(pagina.raw)):
        visitar(raw.FPDFPage_GetObject(pagina.raw, indice), None, (1, 0, 0, 1, 0, 0), 0)
    return comprimentos


def eixo(pagina, grupo='linear'):
    """O eixo desenhado, em mm de papel: a faixa mais longa na cor de eixo (conceitos/prancha.json → eixo.cores, com as
    deflexões); sem ela, na prancha linear, a soma dos traços abertos das camadas de tubo projetado (eixo.camadas_tubo,
    2v60), por camada. Na linear, tracos_camadas guarda o traço de toda camada (≥ 1 mm), para medir a regra."""
    EIXO = comum.configuracao('prancha')['eixo']
    triangulos = [p for p in caminhos_na_cor(pagina, EIXO['cores']) if 3 <= len(p) <= 5]
    melhor = max((centro(f) for f in cadeias(triangulos)), key=comprimento_pt, default=[])
    if len(melhor) >= 2:
        return {'eixo': 'faixa', 'eixo_mm': round(comprimento_pt(melhor) * MM_POR_PT, 2), 'eixo_vertices': len(melhor),
                'deflexoes': json.dumps(deflexoes(melhor)), 'eixo_camadas': '{}', 'tracos_camadas': '{}'}
    TUBO = EIXO['camadas_tubo']
    try:
        tracos = tracos_por_camada(pagina) if grupo == 'linear' else {}
    except Exception as falha:  # o erro fica no eixo, à vista: não pode virar 'não é prancha' no except do ler_prancha
        return {'eixo': 'erro', 'eixo_mm': None, 'eixo_vertices': 0, 'deflexoes': '[]', 'tracos_camadas': '{}',
                'eixo_camadas': json.dumps({'erro': f'{type(falha).__name__}: {falha}'[:200]}, ensure_ascii=False)}
    tubos = {c: round(pt * MM_POR_PT, 1) for c, pt in tracos.items()
             if re.search(TUBO['incluir'], c, re.I) and not re.search(TUBO['excluir'], c, re.I) and pt > 0}
    todas = json.dumps({c: round(pt * MM_POR_PT, 1) for c, pt in sorted(tracos.items(), key=lambda t: -t[1]) if pt * MM_POR_PT >= 1},
                       ensure_ascii=False)  # 2v65: toda camada, para medir antes de mudar a regra (a '1ª ETAPA' sozinha é tubo?)
    if not tubos:
        return {'eixo': 'nao_encontrado', 'eixo_mm': None, 'eixo_vertices': 0, 'deflexoes': '[]', 'eixo_camadas': '{}', 'tracos_camadas': todas}
    return {'eixo': 'camada', 'eixo_mm': round(sum(tubos.values()), 2), 'eixo_vertices': 0, 'deflexoes': '[]',
            'eixo_camadas': json.dumps(tubos, ensure_ascii=False), 'tracos_camadas': todas}


def inicios(total, lado, passo):
    """Onde começa cada fatia ao longo de um lado: de `passo` em `passo`, e a última encostada no fim."""
    return sorted({*range(0, max(total - lado, 0) + 1, passo), max(total - lado, 0)})


def plano_fatias(largura_pt, altura_pt):
    """Caixas (x0, y0, x1, y1) em pixels da folha renderizada a `dpi`, de até `lado_px`, com sobreposição."""
    FATIAS = comum.configuracao('prancha')['fatias']
    escala, lado = FATIAS['dpi'] / 72, FATIAS['lado_px']
    largura, altura, passo = round(largura_pt * escala), round(altura_pt * escala), round(lado * (1 - FATIAS['sobreposicao']))
    return [(x, y, min(x + lado, largura), min(y + lado, altura))
            for y in inicios(altura, lado, passo) for x in inicios(largura, lado, passo)]


def base_da_linha(documento, extrator, rodada):
    """O que toda linha leva: o documento do extrator (id, caminho, obra, versão do conteúdo) e quem a produziu."""
    return {'id': documento['id'], 'caminho': documento['caminho'], 'acervo': documento['acervo'], 'obra': documento['obra'],
            'versao_documento': documento['versao'], 'extrator': extrator, 'arquivo': documento['nome'], 'rodada': rodada}


def ler_prancha(documento, rodada):
    """Tarefa de código: o perfil do PDF entregue; na prancha, carimbo, família, eixo e o número de fatias. Uma linha em
    prancha (a IA vem depois, na vez da GPU)."""
    import pypdfium2 as pdfium
    marca = time.perf_counter()
    caminho = documento['arquivo_local']
    base = base_da_linha(documento, 'prancha', rodada)
    try:
        pdf = pdfium.PdfDocument(caminho)
        perfil = perfilar(pdf, caminho, documento['nome'])
        linha = {**base, **{k: v for k, v in perfil.items() if k not in ('texto', 'texto_folhas')}}
        linha['boletim_sondagem'] = e_boletim(pdf, documento['nome'], perfil['formato'])
        if linha['boletim_sondagem']:  # o boletim é lido pelo sondagem.py, não como prancha (é A4 quase sempre)
            perfil['e_prancha'] = linha['e_prancha'] = False
            linha['motivo'] = 'boletim de sondagem'
        if perfil['e_prancha']:
            pagina = pdf[0]
            linha.update(**ler_carimbo(pagina, documento['nome']), **familia(documento['nome'], perfil['texto_folhas']))
            linha.update(**eixo(pagina, linha.get('grupo')), fatias=len(plano_fatias(*pagina.get_size())))
        linha['camada'] = camada(perfil)
        pdf.close()
    except Exception as falha:  # PDF que o pdfium não abre não é prancha que se leia: fica o motivo, a fila segue
        perfil = {'e_prancha': False}
        linha = {**base, 'e_prancha': False, 'boletim_sondagem': False, 'motivo': f'erro ao abrir: {type(falha).__name__}: {falha}'[:300]}
    comum.gravar('prancha', [linha], [{**base, 'familia': 'prancha', 'segundos': round(time.perf_counter() - marca, 2),
                                       'e_prancha': perfil['e_prancha'], 'erro': ''}])
    if linha.get('carimbo_camada') == 'texto':
        comum.gravar('carimbo', linhas_do_carimbo_por_codigo(linha, {**base, 'leitor': 'pdf'}))
    if perfil['e_prancha']:
        reconferir(documento['id'], linha)
    return linha


def e_boletim(pdf, nome, formato):
    """O PDF é boletim de sondagem? Pelo texto das primeiras páginas (sondagem.json → reconhecer) ou, digitalizado, pelo nome."""
    import sondagem
    texto = '\n'.join(pdf[i].get_textpage().get_text_range() for i in range(min(len(pdf), sondagem.regras()['reconhecer']['paginas'])))
    return sondagem.e_boletim(nome, texto, formato)


def camada(perfil):
    """Por onde a folha se lê (pedido do Caio, 03/10: projeto vetorial vai ao código, digitalizado à IA): `texto` — o
    texto é texto, o código lê texto e geometria (pypdfium2, pdfplumber); `vetor` — o desenho é vetor mas o texto virou
    curva: a geometria pelo código, o texto pelo OCR; `imagem` — escaneada: tudo pelo OCR, sem geometria."""
    return {'vetorial_texto': 'texto', 'vetorial_curva': 'vetor', 'raster': 'imagem'}.get(perfil.get('classe'), '')


def reconferir(identificador, linha):
    """Prancha que a IA já leu: o eixo novo do código e a conferência refeita com as leituras gravadas da IA, sem chamar
    modelo (2v64: as 17 lidas até 27/09 ficaram 'sem_eixo', antes do eixo por camada). Sem leitura da IA, nada."""
    feita = comum.ler('prancha', [identificador])
    ia = next((l for l in (feita.to_dicts() if feita is not None else []) if l['id'] == identificador and l['extrator'] == 'prancha_ia'), None)
    if ia is None:
        return
    def do_documento(familia):
        tabela = comum.ler(familia, [identificador])
        return [l for l in (tabela.to_dicts() if tabela is not None else []) if l['id'] == identificador]
    EIXO = ('eixo', 'eixo_mm', 'eixo_vertices', 'deflexoes', 'eixo_camadas', 'tracos_camadas')
    novo = {**ia, **{c: linha.get(c) for c in EIXO}, 'diferenca_relativa': None}
    comum.gravar('prancha', [{**novo, **conferir(novo, do_documento('prancha_leitura'), do_documento('prancha_tabela'))}])


def para_decimal(texto):
    """'1.250,00' e '1250.00' viram Decimal('1250.00'); o que não é número vira None (como no extrator)."""
    texto = re.sub(r'[^\d.,\-]', '', texto or '')
    if ',' in texto:
        texto = texto.replace('.', '').replace(',', '.')
    elif texto.count('.') > 1:
        texto = texto.replace('.', '')
    try:
        return Decimal(texto) if texto else None
    except InvalidOperation:
        return None


def normalizar(valor):
    """Para comparar dois leitores: NFKC, maiúsculas, sem espaço, vírgula decimal como ponto."""
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', valor)).upper().replace(',', '.')


def achar(texto):
    """Os valores de cada padrão (conceitos/prancha.json → padroes) no texto, normalizados."""
    PADROES = {k: v for k, v in comum.configuracao('prancha')['padroes'].items() if not k.startswith('_')}
    texto = unicodedata.normalize('NFKC', texto or '')
    return {p: {normalizar(m.group(0)) for m in re.finditer(r, texto)} for p, r in PADROES.items() if re.search(r, texto)}


def alegacoes(lida, base):
    """Cada valor lido na fatia com quem o leu: confirmado (glm-ocr e Vision), so_glm, so_vision; um_leitor se um dos dois
    não leu a fatia. Fatia sem valor nenhum fica numa linha `vazia`, com os erros."""
    glm, vision = achar(lida['texto']), achar(lida['texto_vision'])
    dois = not lida['erro'] and not lida['erro_vision']
    extra = {'erro': lida['erro'], 'erro_vision': lida['erro_vision'], 'concordancia_ocr': lida['concordancia_ocr']}
    linhas = []
    for padrao in sorted(set(glm) | set(vision)):
        de_glm, de_vision = glm.get(padrao, set()), vision.get(padrao, set())
        for valor in sorted(de_glm | de_vision):
            status = ('um_leitor' if not dois else 'confirmado' if valor in de_glm and valor in de_vision
                      else 'so_glm' if valor in de_glm else 'so_vision')
            linhas.append({**base, **extra, 'padrao': padrao, 'valor': valor, 'status': status})
    return linhas or [{**base, **extra, 'padrao': '', 'valor': '', 'status': 'vazia'}]


def ler_fatias(caminho, pasta, com_vision, base, prazo):
    """A primeira página renderizada uma vez a `dpi`, cortada no plano de fatias; cada fatia pelos dois leitores."""
    import pypdfium2 as pdfium
    from PIL import Image
    FATIAS = comum.configuracao('prancha')['fatias']
    folha = pasta / 'folha.png'
    documento = pdfium.PdfDocument(caminho)
    plano = plano_fatias(documento[0].get_width(), documento[0].get_height())
    if not folha.exists():
        pasta.mkdir(parents=True, exist_ok=True)
        documento[0].render(scale=FATIAS['dpi'] / 72).to_pil().save(folha)
    documento.close()
    linhas = []
    with Image.open(folha) as imagem:
        for numero, caixa in enumerate(plano[:FATIAS['maximo_fatias']], 1):
            if time.monotonic() > prazo:  # o limite da prancha (operacao.json → limite_ia_s); o lido fica, o resto sai no motivo
                break
            destino = pasta / f'fatia{numero:02d}.png'
            if not destino.exists():
                imagem.crop(caixa).save(destino)
            lida = ia.dupla_leitura(ia.ocr_da_pagina(destino), destino, com_vision)
            linhas += alegacoes(lida, {**base, 'fatia': numero, 'caixa_px': json.dumps(caixa)})
    return linhas, len(plano)


def faixas(caminho, caixa, folha_pt, pasta):
    """A imagem colada na folha, renderizada na resolução dela, com largura até `lado_px`, em faixas horizontais de
    `faixa_altura_px` com sobreposição: a tabela inteira abortava o glm-ocr por repetição (T6, 26/09)."""
    import pypdfium2 as pdfium
    FATIAS = comum.configuracao('prancha')['fatias']
    x0, topo, x1, fundo, largura_px = caixa
    documento = pdfium.PdfDocument(caminho)
    imagem = documento[0].render(scale=max(largura_px / max(x1 - x0, 1), FATIAS['dpi'] / 72),
                                 crop=(x0, folha_pt[1] - fundo, folha_pt[0] - x1, topo)).to_pil()
    documento.close()
    imagem.thumbnail((FATIAS['lado_px'], 10 ** 6))
    altura = FATIAS['faixa_altura_px']
    pasta.mkdir(parents=True, exist_ok=True)
    destinos = []
    for numero, y in enumerate(inicios(imagem.height, altura, round(altura * (1 - FATIAS['sobreposicao']))), 1):
        destino = pasta / f'faixa{numero:02d}.png'
        imagem.crop((0, y, imagem.width, min(y + altura, imagem.height))).save(destino)
        destinos.append(destino)
    return destinos


def linhas_html(html):
    """Linhas da tabela que o glm-ocr devolve em HTML, cada célula sem marcação; a linha repetida (o laço do modelo) sai."""
    vistas, linhas = set(), []
    for linha in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S):
        celulas = [re.sub(r'<[^>]+>', '', c).strip() for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', linha, re.S)]
        if celulas and tuple(celulas) not in vistas:
            vistas.add(tuple(celulas))
            linhas.append(celulas)
    return linhas


def ler_tabela(imagem, com_vision, base):
    """Faixa de tabela: o glm-ocr em modo tabela, o Vision como texto; a linha é `confirmada` se todo número dela aparece
    também no que o Vision leu na mesma faixa, `pendente` se falta algum, `um_leitor` sem o Vision."""
    instrucao, _ = ia.ler_prompt('prancha_tabela', regras=False)
    try:
        html, erro = ia.ocr_glm(imagem, instrucao), ''
    except RuntimeError as falha:
        if ia.REPETICAO not in str(falha):
            raise
        html, erro = '', 'repetição: faixa sem tabela legível'
    vista = ia.dupla_leitura({'texto': '', 'erro': 'só o Vision'}, imagem, com_vision)
    do_vision = {normalizar(n) for n in re.findall(NUMERO, vista['texto_vision'])}
    linhas = []
    for numero, celulas in enumerate(linhas_html(html), 1):
        numeros = [c for c in celulas if re.fullmatch(NUMERO, c.strip())]
        faltam = [normalizar(c) for c in numeros if normalizar(c) not in do_vision]
        # 0v38: sem número nenhum a conferência era verdade vazia (Joinville 08/10: linhas [""] confirmadas)
        status = 'um_leitor' if vista['erro_vision'] else 'sem_numero' if not numeros else 'pendente' if faltam else 'confirmada'
        linhas.append({**base, 'linha': numero, 'celulas': json.dumps(celulas, ensure_ascii=False), 'status': status,
                       'nao_confirmados': ','.join(faltam), 'erro': erro})
    return linhas or [{**base, 'linha': 0, 'celulas': '[]', 'status': 'vazia', 'nao_confirmados': '', 'erro': erro or vista['erro_vision']}]


def imagens_da_folha(pagina, FATIAS, LIMITE):
    """O inventário das imagens da primeira página, soltas ou dentro de formulário (Form XObject: é como o CAD grava a
    tabela do Excel colada — 0v33, pedido da Giselle de 08/10, 'existem 3 tabelas e você leu só a primeira': só a de
    fora era vista). Cada uma com a caixa na folha (pt, de cima), os px, a fração da folha e se entra como tabela."""
    import pypdfium2.raw as raw
    folha_pt = pagina.get_size()
    inventario = []
    for imagem in pagina.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE], max_depth=FATIAS['profundidade_formularios']):
        (esquerda, baixo, direita, cima), (largura_px, altura_px) = limites(imagem), imagem.get_px_size()
        fracao = (direita - esquerda) * (cima - baixo) / (folha_pt[0] * folha_pt[1])
        motivo = ('pequena' if max(largura_px, altura_px) < FATIAS['imagem_minima_px'] else
                  'folha_escaneada' if fracao >= LIMITE else '')
        inventario.append({'imagem': len(inventario) + 1, 'nivel': imagem.level, 'onde': 'formulario' if imagem.level else 'solta',
                           'caixa_pt': [round(v, 1) for v in (esquerda, folha_pt[1] - cima, direita, folha_pt[1] - baixo)],
                           'px': [largura_px, altura_px], 'fracao_folha': round(fracao, 4), 'lida': not motivo, 'motivo': motivo})
    return inventario


def reler_no_ensaio(identificador):
    """No ensaio com `reler_com_glm` (conceitos/ensaios.json), o glm-ocr lê também o que a grade leu: o antes e o
    depois medidos na mesma execução (0v38). Fora dele, a imagem lida pela grade não vai ao glm-ocr."""
    partes = identificador.split('/')
    if len(partes) < 3 or partes[0] != '_ensaios':
        return False
    return bool(comum.configuracao('ensaios')['ensaios'].get(partes[1], {}).get('reler_com_glm'))


def ler_imagens(caminho, pasta, com_vision, base, prazo):
    """Cada imagem colada na primeira página (não a folha escaneada inteira), solta ou dentro de formulário, lida como
    tabela, faixa a faixa. Devolve (linhas, inventário com as faixas e as linhas de cada imagem)."""
    import pypdfium2 as pdfium
    FATIAS = comum.configuracao('prancha')['fatias']
    LIMITE = comum.configuracao('prancha')['classe']['fracao_imagem_raster']
    documento = pdfium.PdfDocument(caminho)
    pagina = documento[0]
    folha_pt = pagina.get_size()
    inventario = imagens_da_folha(pagina, FATIAS, LIMITE)
    documento.close()
    linhas, pela_grade = [], set() if reler_no_ensaio(base['id']) else tabela.lidas_pela_grade(base['id'])
    for item in inventario:
        if item['lida'] and item['imagem'] in pela_grade:  # 0v38: o ler_tabelas já leu pela grade; o glm-ocr não relê
            item.update(lida=False, motivo='lida_pela_grade')
        if not item['lida']:
            continue
        if time.monotonic() > prazo:
            item.update(lida=False, motivo='tempo')
            continue
        lidas, recortes = [], faixas(caminho, (*item['caixa_pt'], item['px'][0]), folha_pt, pasta / f"imagem{item['imagem']}")
        for faixa, destino in enumerate(recortes, 1):
            lidas += ler_tabela(destino, com_vision, {**base, 'imagem': item['imagem'], 'faixa': faixa})
        item.update(faixas=len(recortes), linhas=sum(l['status'] != 'vazia' for l in lidas))
        linhas += lidas
    return linhas, inventario


def conferir(linha, leituras, tabelas):
    """Escala da planta (a maior das confirmadas: o perfil tem a vertical menor), eixo em metros e o tubo da relação —
    a primeira quantidade com a faixa colorida; a soma dos tubos com o eixo por camada (a rede tem vários diâmetros), e
    os metros de cada camada de tubo (eixo_m_camadas), que valem mesmo sem a relação na folha (a A3 da OSE não a traz).
    Só entra valor confirmado pelos dois leitores; sem ele, a conferência diz o que faltou."""
    CONFERENCIA = comum.configuracao('prancha')['conferencia']
    escalas = sorted({int(l['valor'].split(':')[1].replace('.', '')) for l in leituras if l['padrao'] == 'escala' and l['status'] == 'confirmado'})
    tubos = [json.loads(t['celulas']) for t in tabelas if t['status'] == 'confirmada'
             and any(re.search(CONFERENCIA['tubo'], c) for c in json.loads(t['celulas']))]
    quantidades = [para_decimal(c[c.index(u) - 1]) for c in tubos for u in c if u.lower() == 'm' and c.index(u) > 0]
    resultado = {'escalas_confirmadas': json.dumps(escalas), 'tubo_relacao_m': str(quantidades[0]) if quantidades else '',
                 'eixo_m': None, 'eixo_m_camadas': '{}', 'conferencia': ''}
    if not linha.get('eixo_mm'):
        return {**resultado, 'conferencia': 'sem_eixo'}
    if not escalas:
        return {**resultado, 'conferencia': 'sem_escala_confirmada'}
    resultado['eixo_m'] = round(linha['eixo_mm'] * escalas[-1] / 1000, 2)
    resultado['eixo_m_camadas'] = json.dumps({c: round(mm * escalas[-1] / 1000, 1) for c, mm in json.loads(linha.get('eixo_camadas') or '{}').items()},
                                             ensure_ascii=False)  # a extensão por diâmetro: o quantitativo da rede, com ou sem relação
    if not quantidades or quantidades[0] is None:
        return {**resultado, 'conferencia': 'sem_tubo_confirmado'}
    alvo = sum(float(q) for q in quantidades if q is not None) if linha.get('eixo') == 'camada' else float(quantidades[0])
    resultado['tubo_relacao_m'] = str(round(alvo, 2)) if linha.get('eixo') == 'camada' else resultado['tubo_relacao_m']
    diferenca = abs(resultado['eixo_m'] - alvo) / max(alvo, 1e-9)
    return {**resultado, 'conferencia': 'fecha' if diferenca <= CONFERENCIA['tolerancia_relativa'] else 'diverge',
            'diferenca_relativa': round(diferenca, 4)}


def desempatar(texto):
    """Família sem regra que case: o qwen3 e o Apple FM (se instalado) escolhem entre as opções pelo texto do carimbo;
    vale só se todo motor chamado escolheu a mesma opção da lista — erro ou discordância deixa `indefinida`."""
    FAMILIAS = comum.configuracao('prancha')['familias']
    opcoes = FAMILIAS['ordem']
    prompt = ia.ler_prompt('prancha_familia')[0].replace('{opcoes}', ', '.join(opcoes)).replace('{texto}', texto[:3000])
    ESQUEMA = {'type': 'object', 'required': ['familia'],
               'properties': {'familia': {'type': 'string', 'enum': [*opcoes, 'indefinida']}}}
    motores = {'qwen3': lambda: ia.ollama(comum.configuracao('ia')['modelos']['qwen3'], prompt, ESQUEMA)}
    if ia.instalado('apple_fm_sdk'):
        motores['apple'] = lambda: ia.apple(prompt, ESQUEMA)
    votos = {}
    for motor, chamar in motores.items():
        try:
            votos[motor] = json.loads(chamar()[0]).get('familia', '')
        except (RuntimeError, ValueError, OSError) as falha:
            votos[motor] = f'erro: {falha}'[:120]
    validos = set(votos.values())
    escolhida = validos.pop() if len(validos) == 1 and set(votos.values()) <= set(opcoes) else 'indefinida'
    return {'familia': escolhida, 'grupo': FAMILIAS['grupo'].get(escolhida, ''), 'familia_votos': json.dumps(votos, ensure_ascii=False),
            'familia_origem': 'ia_concordante' if escolhida != 'indefinida' else 'ia_sem_acordo'}


def grade_lida(identificador):
    """As linhas que o ler_tabelas gravou (prancha_tabela, extrator tabelas) para este documento."""
    feita = comum.ler('prancha_tabela', [identificador])
    return [] if feita is None else [l for l in feita.to_dicts() if l['extrator'] == 'tabelas']


def ler_prancha_ia(documento, rodada):
    """Tarefa de IA: só na prancha que o ler_prancha achou (o ciclo confere antes). Fatias e imagens coladas pelos dois
    leitores, a conferência e, sem família por regra, o desempate. O resumo vai para prancha (extrator prancha_ia)."""
    marca, relogio = time.perf_counter(), time.monotonic()
    base = base_da_linha(documento, 'prancha_ia', rodada)
    feita = comum.ler('prancha', [documento['id']])
    linha = next(l for l in feita.to_dicts() if l['extrator'] == 'prancha')
    caminho = Path(documento['arquivo_local'])
    pasta, com_vision = comum.DADOS / 'recortes' / caminho.stem, ia.instalado('Vision')
    prazo = relogio + comum.configuracao('operacao')['limite_ia_s']
    if linha.get('carimbo_camada') == 'imagem':
        comum.gravar('carimbo', ler_carimbo_ocr(recorte_do_carimbo(caminho, pasta), documento['nome'], com_vision,
                                                {**base_da_linha(documento, 'carimbo_ia', rodada), 'leitor': 'glm_ocr+vision'}))
    tabelas, imagens = ler_imagens(caminho, pasta, com_vision, base, prazo)  # 0v38: a tabela antes das fatias (o prazo não a corta)
    leituras, planejadas = ler_fatias(caminho, pasta, com_vision, base, prazo)
    da_grade = [l for l in grade_lida(documento['id']) if l['linha']]  # a conferência eixo × tubo vê a tabela da grade também
    contagem = {s: sum(l['status'] == s for l in leituras) for s in ('confirmado', 'so_glm', 'so_vision', 'um_leitor')}
    resumo = {**linha, **base, **conferir(linha, leituras, tabelas + da_grade), 'fatias_lidas': len({l['fatia'] for l in leituras}),
              'fatias_planejadas': planejadas, 'com_vision': com_vision, **{f'valores_{s}': n for s, n in contagem.items()},
              'imagens_na_folha': json.dumps(imagens, ensure_ascii=False), 'imagens_lidas': sum(i['lida'] for i in imagens),
              'linhas_tabela': len(tabelas), 'linhas_tabela_confirmadas': sum(t['status'] == 'confirmada' for t in tabelas),
              'motivo': 'tempo: parou no limite da prancha (operacao.json → limite_ia_s)' if time.monotonic() > prazo else ''}
    if linha['familia'] == 'indefinida':
        resumo.update(desempatar(linha.get('carimbo_texto') or ''))
    comum.gravar('prancha_leitura', leituras)
    comum.gravar('prancha_tabela', tabelas)
    comum.gravar('prancha', [resumo], [{**base, 'familia': 'prancha', 'segundos': round(time.perf_counter() - marca, 2),
                                        'fatias': resumo['fatias_lidas'], 'confirmados': contagem['confirmado'], 'erro': ''}])
    return resumo
