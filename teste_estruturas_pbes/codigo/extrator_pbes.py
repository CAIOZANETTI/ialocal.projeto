"""Extrator de referência (Claude) das tabelas das pranchas estruturais TQS/Sanepar do PBES de Foz do Iguaçu.

Método (skill extrair-quantitativos-pdf): PDF vetorial sem texto -> render -> grade -> OCR (RapidOCR, uma coluna por vez)
-> linhas por y -> conferência física. Usa as funções de geometria do próprio Mini (ialocal.projeto/codigo/tabela.py),
SEM alterá-las, para a localização das caixas; a leitura das células é nossa (o Mini não lê este tipo de tabela).
"""
import os, re, sys, json, unicodedata
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'codigo'))   # o código do Mini, sem alteração
import numpy as np, cv2
import pypdfium2 as pdfium
import tabela as mini

OCR = None
def ocr(img):
    """RapidOCR -> [(cx, cy, h, texto, conf)] em px."""
    global OCR
    if OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        OCR = RapidOCR(); OCR.use_angle_cls = False
    entrada = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if img.ndim == 2 else img
    res, _ = OCR(entrada)
    out = []
    for caixa, t, c in (res or []):
        xs = [p[0] for p in caixa]; ys = [p[1] for p in caixa]
        out.append(((min(xs)+max(xs))/2, (min(ys)+max(ys))/2, max(ys)-min(ys), unicodedata.normalize('NFKC', t).strip(), float(c)))
    return out

def sa(t):
    return unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode().upper()

# --------------------------------------------------------------- localizar
def caixas(pdf_path):
    """Caixas de grade da folha (as do Mini, com a zona do carimbo liberada) -> [(caixa_pt, rgb400)]."""
    L = mini.regra()['localizar']
    L['carimbo'] = [2, 2, 2, 2]   # só configuração: o RESUMO AÇO fica na zona do carimbo
    L['malha_min_linhas'] = 2     # só configuração: a tabela de armadura tem poucas horizontais longas (títulos de elemento)
    pag = pdfium.PdfDocument(pdf_path)[0]
    return pag, mini.malhas(pag, [])

def classificar(rgb):
    """Tipo da caixa pelo OCR do topo: armadura | resumo_aco | resumo_materiais | outra."""
    h = rgb.shape[0]
    topo = rgb[:min(h, 520)]
    txt = sa(' '.join(t[3] for t in ocr(topo)))
    if 'RESUMO' in txt and 'MATERIAIS' in txt: return 'resumo_materiais', txt
    if 'RESUMO' in txt and 'ACO' in txt: return 'resumo_aco', txt
    if 'RESUMO' in txt and 'MATERIAL' in txt: return 'resumo_metalico', txt
    if 'POS' in txt and 'BIT' in txt and 'QUANT' in txt: return 'armadura', txt
    return 'outra', txt

# --------------------------------------------------------------- utilidades de grade
def verticais(rgb, frac=0.5):
    bw = mini.tinta(rgb)
    _, V = mini.linhas(bw, 'v', bw.shape[0] * frac)
    return [(a + b) // 2 for a, b in V]

def horizontais(rgb, frac=0.8):
    bw = mini.tinta(rgb)
    _, H = mini.linhas(bw, 'h', bw.shape[1] * frac)
    return [(a + b) // 2 for a, b in H]

def numero(t, tipo='int'):
    t = t.replace('O', '0').replace('o', '0').replace('I', '1').replace('l', '1').replace('|', '1').replace('S', '5').replace(' ', '')
    t = t.replace(',', '.')
    if tipo == 'int':
        t = re.sub(r'[^0-9]', '', t)
        return int(t) if t else None
    t = re.sub(r'[^0-9.]', '', t)
    try: return float(t)
    except ValueError: return None

def colunas_ocr(rgb, xs, y0, y1, margem=6):
    """OCR de cada faixa de coluna (entre verticais) separadamente -> {i: [(cy, texto)]} (cy relativo ao rgb)."""
    fx = [0] + list(xs) + [rgb.shape[1]]
    out = {}
    for i in range(len(fx) - 1):
        a, b = fx[i] + margem, fx[i + 1] - margem
        if b - a < 10: out[i] = []; continue
        faixa = cv2.copyMakeBorder(rgb[y0:y1, a:b], 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        out[i] = [(t[1] - 30 + y0, t[3], t[2], t[4]) for t in ocr(faixa)]
    return out

def juntar_linhas(cols, tol):
    """Agrupa os tokens das colunas em linhas pelo y -> [{y, 0:texto, 1:texto...}]."""
    todos = sorted([(cy, i, t, c) for i, ts in cols.items() for cy, t, h, c in ts])
    linhas = []
    for cy, i, t, c in todos:
        if linhas and abs(cy - linhas[-1]['y']) <= tol:
            L = linhas[-1]
            L[i] = (L.get(i, '') + ' ' + t).strip(); L['y'] = (L['y'] + cy) / 2
            L['conf'] = min(L.get('conf', 1), c)
        else:
            linhas.append({'y': cy, i: t, 'conf': c})
    return linhas

# --------------------------------------------------------------- leitor de célula (Tesseract)
import subprocess
def tess(cel, lista, psm=7):
    """Uma célula (cinza/RGB) -> texto lido pelo Tesseract com lista de caracteres. '' se nada."""
    if cel.ndim == 3: cel = cv2.cvtColor(cel, cv2.COLOR_RGB2GRAY)
    cel = cv2.copyMakeBorder(cel, 14, 14, 20, 20, cv2.BORDER_CONSTANT, value=255)
    ok, png = cv2.imencode('.png', cel)
    r = subprocess.run(['tesseract', '-', '-', '--psm', str(psm), '--dpi', '400', '-c', f'tessedit_char_whitelist={lista}'],
                       input=png.tobytes(), capture_output=True, timeout=60)
    return r.stdout.decode('utf8', 'replace').strip()

def faixas_de_tinta(perfil, vazio=6, minimo=14):
    """Intervalos (a, b) consecutivos onde o perfil > 0, juntando vazios menores que `vazio`."""
    on = np.where(perfil > 0)[0]
    grupos = []
    for p in on:
        if grupos and p - grupos[-1][1] <= vazio: grupos[-1][1] = int(p)
        else: grupos.append([int(p), int(p)])
    return [(a, b) for a, b in grupos if b - a >= minimo]

# --------------------------------------------------------------- armadura
RE_CLASSE = re.compile(r'^(50|60)[AB]?$')
def ler_armadura(rgb):
    """Uma caixa pode ter duas tabelas lado a lado (verticais do cabeçalho: 7 por tabela, a borda do meio é comum)."""
    H = horizontais(rgb, 0.8)
    if len(H) < 2: return [], {'erro': f'grade: {len(H)} horizontais'}
    zona = rgb[int(H[1] * 0.5):H[1] - 4]
    _, Vz = mini.linhas(mini.tinta(zona), 'v', zona.shape[0] * 0.8)
    V = [(a + b) // 2 for a, b in Vz]
    n = len(V)
    if n >= 12:
        pontos = V[0::6] if (n - 1) % 6 == 0 else None
        if pontos is None:     # tabelas separadas por um vão: corta no meio do maior intervalo entre verticais
            gaps = sorted(range(n - 1), key=lambda i: V[i + 1] - V[i], reverse=True)
            pontos = [V[0], (V[gaps[0]] + V[gaps[0] + 1]) // 2, V[-1]]
        saida, extra = [], {'sub_tabelas': len(pontos) - 1, 'dados': 0, 'titulos': 0}
        for i, (a, b) in enumerate(zip(pontos, pontos[1:])):
            sub = np.ascontiguousarray(rgb[:, max(0, a - 3):b + 4])
            r, ex = _ler_armadura_uma(sub)
            for l in r: l['sub_tabela'] = i
            saida += r; extra['dados'] += ex.get('dados', 0); extra['titulos'] += ex.get('titulos', 0)
            if ex.get('erro'): extra.setdefault('erro', ex['erro'])
        return saida, extra
    return _ler_armadura_uma(rgb)

def _ler_armadura_uma(rgb):
    """Tabela AÇO/POS/BIT/QUANT/COMPRIMENTO(UNIT,TOTAL).
    -> linhas [{elemento, classe, pos, bit_mm, quant, unit_cm|None, unit_txt, total_cm, y, leitura}] e extra."""
    H = horizontais(rgb, 0.8)
    if len(H) < 2: return [], {'erro': f'grade: {len(H)} horizontais'}
    zona = rgb[int(H[1] * 0.5):H[1] - 4]                       # 2ª linha do cabeçalho: todas as separações existem aqui
    _, Vz = mini.linhas(mini.tinta(zona), 'v', zona.shape[0] * 0.8)
    xs = [(a + b) // 2 for a, b in Vz if 0.05 * rgb.shape[1] < (a + b) / 2 < 0.97 * rgb.shape[1]]
    if len(xs) < 5: return [], {'erro': f'grade: {len(xs)} verticais no cabeçalho'}
    xs = xs[-5:]                                               # AÇO|POS, POS|BIT, BIT|QUANT, QUANT|UNIT, UNIT|TOTAL
    y_corpo = H[1] + 4
    bw = mini.tinta(rgb)
    # apaga as linhas da grade (verticais conhecidas, horizontais longas) para sobrar só texto
    for x in xs + [0, rgb.shape[1] - 1]: bw[:, max(0, x - 5):x + 6] = 0
    for y in H: bw[max(0, y - 4):y + 5, :] = 0
    bw[:, :22] = 0; bw[:, -22:] = 0
    # linhas de dado: tinta na coluna TOTAL (sempre preenchida)
    a, b = xs[4] + 8, rgb.shape[1] - 24
    dados = [(y0, y1) for y0, y1 in faixas_de_tinta(bw[:, a:b].sum(axis=1), 6, 14) if y0 > y_corpo]
    # linhas de título de elemento: tinta só nas colunas da esquerda e fora das faixas de dado
    esq = bw[:, 24:xs[2]].sum(axis=1).copy()
    for y0, y1 in dados: esq[max(0, y0 - 3):y1 + 4] = 0
    titulos = [(y0, y1) for y0, y1 in faixas_de_tinta(esq, 6, 14) if y0 > y_corpo]
    eventos = sorted([('t', y0, y1) for y0, y1 in titulos] + [('d', y0, y1) for y0, y1 in dados], key=lambda e: e[1])
    cinza = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    saida, elemento = [], ''
    lim = [24] + xs + [rgb.shape[1] - 24]
    tok = {}                                                  # 2º leitor: RapidOCR na tabela inteira, por y
    for cx, cy, h, t, c in ocr(rgb):
        tok.setdefault(round(cy / 20), []).append((cx, t))
    for tipo, y0, y1 in eventos:
        ym = (y0 + y1) // 2
        if tipo == 't':
            faixa = rgb[max(0, y0 - 6):y1 + 7, 24:rgb.shape[1] - 24]
            palavras = ocr(faixa)
            elemento = ' '.join(t[3] for t in sorted(palavras, key=lambda t: t[0])).strip() or elemento
            continue
        cel = lambda i, lista: tess(cinza[max(0, y0 - 5):y1 + 6, lim[i] + 4:lim[i + 1] - 4], lista)
        classe = cel(0, '0123456789AB')
        pos = cel(1, '0123456789')
        bit = cel(2, '0123456789.')
        quant = cel(3, '0123456789')
        unit = cel(4, '0123456789CORVA-')
        total = cel(5, '0123456789')
        valida = bool(re.fullmatch(r'\d+', total) and re.fullmatch(r'\d+', quant) and unit and re.fullmatch(r'\d+\.?\d*', bit or 'x'))
        saida.append({'elemento': elemento, 'classe': classe, 'pos': pos, 'bit_mm': bit, 'quant': quant, 'unit_txt': unit,
                      'total_cm': total, 'y': ym, 'valida': valida})
    return saida, {'colunas': 6, 'xs': xs, 'dados': len(dados), 'titulos': len(titulos)}

# --------------------------------------------------------------- resumo dos materiais / lastro / enchimento
def num_br(t):
    """'0,86' | '11.48' | '1.234,5' | '--' -> float | None (vírgula e ponto são decimais; só 2 casas aqui)."""
    t = (t or '').replace(' ', '')
    if not re.search(r'\d', t): return None
    t = t.replace(',', '.')
    t = re.sub(r'[^0-9.]', '', t)
    if t.count('.') > 1: t = t.replace('.', '', t.count('.') - 1)
    try: return float(t)
    except ValueError: return None

def ler_resumo_materiais(rgb):
    """RESUMO DOS MATERIAIS: DIVISÃO | ÁREA DE FORMAS (m2) | VOLUME DE CONCRETO (m3), com a linha TOTAL."""
    H = horizontais(rgb, 0.8)
    zona = rgb[int(H[2] * 0.3):H[2] - 3] if len(H) >= 3 else rgb[:300]
    _, Vz = mini.linhas(mini.tinta(zona), 'v', max(20, zona.shape[0] * 0.6))
    xs = [(a + b) // 2 for a, b in Vz if 0.1 * rgb.shape[1] < (a + b) / 2 < 0.95 * rgb.shape[1]]
    if len(xs) < 2 or len(H) < 3: return [], {'erro': f'grade: {len(xs)} verticais, {len(H)} horizontais'}
    xs = xs[:2]
    y_corpo = H[2] + 4
    bw = mini.tinta(rgb)
    for x in xs + [0, rgb.shape[1] - 1]: bw[:, max(0, x - 5):x + 6] = 0
    for y in H: bw[max(0, y - 4):y + 5, :] = 0
    bw[:, :22] = 0; bw[:, -22:] = 0
    ink = bw[:, 24:rgb.shape[1] - 24].sum(axis=1)
    cinza = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    lim = [24, xs[0], xs[1], rgb.shape[1] - 24]
    out = []
    # linhas da tabela: entre as horizontais do corpo; só linhas com tinta
    ys = [y for y in H if y >= H[2] - 3]
    for ya, yb in zip(ys, ys[1:]):
        if yb - ya < 25: continue
        if bw[ya + 4:yb - 3, 24:rgb.shape[1] - 24].sum() == 0: continue
        banda = rgb[ya + 4:yb - 3, lim[0]:lim[1] - 4]
        nome = tess(cinza[ya + 4:yb - 3, lim[0]:lim[1] - 4], 'ABCDEFGHIJKLMNOPQRSTUVWXYZÇÃÕÉÊÁÍÓÚ/-+().0123456789 ')
        a = tess(cinza[ya + 4:yb - 3, lim[1] + 6:lim[2] - 6], '0123456789.,-')
        v = tess(cinza[ya + 4:yb - 3, lim[2] + 6:lim[3] - 4], '0123456789.,-')
        out.append({'divisao': nome, 'area_forma_txt': a, 'volume_txt': v, 'area_forma_m2': num_br(a), 'volume_m3': num_br(v), 'y': (ya + yb) // 2})
    return out, {'xs': xs}

def ler_faixa_valor(pag, caixa_resumo):
    """LASTRO DE CONCRETO SIMPLES / ENCHIMENTO: barras de 1 linha logo acima do RESUMO DOS MATERIAIS (até 520 pt)."""
    W, Hh = pag.get_size()
    x0, y0, x1, y1 = caixa_resumo
    topo = max(0, y0 - 520)
    x0 = x0 - 255   # a barra cobre a coluna toda: DET. GENÉRICO (esquerda) + RESUMO (direita)
    rgb = np.array(pag.render(scale=300 / 72, crop=(x0, Hh - y0 + 2, W - x1 - 2, topo)).to_pil().convert('RGB'))
    toks = sorted(ocr(rgb), key=lambda t: t[1])
    linhas = []
    for cx, cy, h, t, c in toks:
        if linhas and abs(cy - linhas[-1]['y']) < h * 0.8:
            linhas[-1]['t'].append((cx, t)); linhas[-1]['y'] = (linhas[-1]['y'] + cy) / 2
        else:
            linhas.append({'y': cy, 't': [(cx, t)]})
    achados = {}
    for L in linhas:
        txt = ' '.join(t for _, t in sorted(L['t']))
        s = sa(txt).replace(' ', '')
        for chave, rx in (('lastro', 'LASTRO'), ('enchimento', 'ENCHIMENTO')):
            if rx in s:
                m = re.findall(r'(\d+[.,]\d+)', txt.replace(' ', ''))
                achados[chave] = {'texto': txt, 'valor_m3': num_br(m[-1]) if m else None}
    if 'lastro' not in achados or 'enchimento' not in achados:      # 2º leitor: Tesseract na faixa inteira
        cinza = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        txt = tess(cinza, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,/ ', psm=6)
        for ln in txt.splitlines():
            s = sa(ln).replace(' ', '')
            for chave, rx in (('lastro', 'LASTRO'), ('enchimento', 'ENCHIMENTO')):
                if rx in s and chave not in achados:
                    m = re.findall(r'(\d+[.,]\d+)', ln.replace(' ', ''))
                    achados[chave] = {'texto': ln, 'valor_m3': num_br(m[-1]) if m else None, 'leitor': 'tesseract'}
    return achados

# --------------------------------------------------------------- resumo aço
MASSA = {5.0: 0.154, 6.3: 0.245, 8.0: 0.395, 10.0: 0.617, 12.5: 0.963, 16.0: 1.578, 20.0: 2.466, 25.0: 3.853}   # NBR 7480, kg/m
def bitola_pela_massa(comp_m, peso_kg):
    """Bitola cujo kg/m mais se aproxima de peso/comprimento (reparo quando o OCR perde o dígito da bitola)."""
    if not comp_m or not peso_kg: return None
    r = peso_kg / comp_m
    b = min(MASSA, key=lambda k: abs(MASSA[k] - r))
    return b if abs(MASSA[b] - r) / MASSA[b] < 0.06 else None

def ler_resumo_aco(rgb):
    """RESUMO AÇO CA 50-60: linhas {classe, bit_mm, comp_m, peso_kg} e 'Peso Total <classe> = N kg'."""
    H = horizontais(rgb, 0.8)
    zona_ok = rgb
    _, Vz = mini.linhas(mini.tinta(rgb), 'v', rgb.shape[0] * 0.4)
    xs = [(a + b) // 2 for a, b in Vz if 0.05 * rgb.shape[1] < (a + b) / 2 < 0.97 * rgb.shape[1]]
    toks = ocr(rgb)
    y_hdr = max([t[1] for t in toks if t[3].startswith('(') and sa(t[3]).strip('() ') in ('KG', 'M', 'MM')] or [0])
    bw = mini.tinta(rgb)
    for x in xs + [0, rgb.shape[1] - 1]: bw[:, max(0, x - 5):x + 6] = 0
    for y in H: bw[max(0, y - 4):y + 5, :] = 0
    bw[:, :22] = 0; bw[:, -22:] = 0
    bandas = [(a, b) for a, b in faixas_de_tinta(bw.sum(axis=1), 6, 14) if a > y_hdr + 15]
    cinza = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    lim = [24] + xs[:3] + [rgb.shape[1] - 24] if len(xs) >= 3 else None
    linhas, totais = [], {}
    for a, b in bandas:
        faixa = rgb[max(0, a - 5):b + 6, 24:rgb.shape[1] - 24]
        txt = ' '.join(t[3] for t in sorted(ocr(faixa), key=lambda t: t[0]))
        if 'PESO' in sa(txt) or 'TOTAL' in sa(txt):
            cls = re.search(r'(50|60)\s*[AB]', sa(txt))
            val = re.findall(r'(\d[\d.]*)\s*KG', sa(txt).replace(' ', ' '))
            nums = re.findall(r'\d+', sa(txt).split('=')[-1]) if '=' in txt else re.findall(r'\d+', txt)
            totais[cls.group(0).replace(' ', '') if cls else '?'] = {'texto': txt, 'peso_kg': int(nums[-1]) if nums else None}
            continue
        if lim is None: continue
        cel = lambda i, lista: tess(cinza[max(0, a - 5):b + 6, lim[i] + 4:lim[i + 1] - 4], lista)
        linhas.append({'classe': cel(0, '0123456789AB'), 'bit_txt': cel(1, '0123456789.'), 'comp_txt': cel(2, '0123456789'),
                       'peso_txt': cel(3, '0123456789')})
    for L in linhas:
        L['comp_m'] = float(L['comp_txt']) if L['comp_txt'] else None
        L['peso_kg'] = float(L['peso_txt']) if L['peso_txt'] else None
        try: L['bit_mm'] = float(L['bit_txt']) if L['bit_txt'] else None
        except ValueError: L['bit_mm'] = None
        pela_massa = bitola_pela_massa(L['comp_m'], L['peso_kg'])
        L['bit_fisica'] = pela_massa
        L['bit_reparada'] = L['bit_mm'] not in MASSA and pela_massa is not None
        if L['bit_reparada'] or (L['bit_mm'] in MASSA and pela_massa and L['bit_mm'] != pela_massa):
            L['bit_lida_antes'] = L['bit_mm']; L['bit_mm'] = pela_massa
    return linhas, {'verticais': xs, 'totais': totais}


# --------------------------------------------------------------- tabela de grade completa (estrutura metálica)
def ler_grade_simples(rgb):
    """Tabela com todas as linhas e colunas desenhadas: [[texto da célula]] por linha (Tesseract, sem lista fechada)."""
    H = horizontais(rgb, 0.8)
    bw = mini.tinta(rgb)
    _, V = mini.linhas(bw, 'v', rgb.shape[0] * 0.5)
    xs = [(a + b) // 2 for a, b in V]
    cinza = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    linhas = []
    for ya, yb in zip(H, H[1:]):
        if yb - ya < 25: continue
        cel = []
        for xa, xb in zip(xs, xs[1:]):
            if xb - xa < 12: continue
            cel.append(tess(cinza[ya + 4:yb - 3, xa + 4:xb - 3], '0123456789.,ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-/\u00d8\u00ba\u00b0\u00b2\u00b3 ()xX*:'))
        linhas.append({'y': (ya + yb) // 2, 'celulas': cel})
    return linhas, {'verticais': xs}
