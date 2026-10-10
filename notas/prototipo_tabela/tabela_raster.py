"""Tabela de material (imagem colada ou malha vetorial rasterizada): grade pelas linhas do raster, texto pelo
Tesseract (uma passada na tabela + releitura das células numéricas com lista de caracteres), palavra → célula pela
geometria. Determinístico: mesma imagem, mesma saída."""
import cv2, numpy as np, subprocess, io, csv, re, unicodedata
import vocabulario

UNIDADES = {'KG/M': 'kg/m', 'UN.': 'un', 'UD': 'un', 'BARRAS': 'barras', 'BARRA': 'barras', 'BR': 'barras', 'BARAS': 'barras', 'PC': 'pç', 'PÇ': 'pç', 'PCS': 'pç', 'M': 'm', 'KG': 'kg', 'CJ': 'cj', 'UN': 'un', 'UND': 'un', 'M2': 'm²',
            'M²': 'm²', 'M3': 'm³', 'M³': 'm³', 'VB': 'vb', 'L': 'l', 'GL': 'gl', 'JG': 'jg', 'PAR': 'par', 'T': 't'}

def tinta(rgb, limiar=140):
    """escuro e sem cor: o fundo roxo/azul da 2ª etapa não vira tinta."""
    r = rgb.astype(np.int16)
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    sat = r.max(axis=2) - r.min(axis=2)
    return ((g < limiar) & ((sat < 70) | (g < 70))).astype(np.uint8) * 255

def linhas(bw, eixo, comp):
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (int(comp), 1) if eixo == 'h' else (1, int(comp)))
    m = cv2.morphologyEx(bw, cv2.MORPH_OPEN, k)
    perfil = m.sum(axis=1 if eixo == 'h' else 0) / 255
    grupos = []
    for p in np.where(perfil > 0)[0]:
        if grupos and p - grupos[-1][-1] <= 3: grupos[-1].append(p)
        else: grupos.append([p])
    return m, [(g[0], g[-1]) for g in grupos]

def e_tabela(rgb):
    bw = tinta(rgb); h, w = bw.shape
    _, H = linhas(bw, 'h', w * 0.5)
    claro = (cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY) > 200).mean()
    return len(H) >= 4 and claro > 0.6

def tesseract(img, psm=6, extra=()):
    ok, png = cv2.imencode('.png', img)
    r = subprocess.run(['tesseract', '-', '-', '-l', 'por', '--psm', str(psm), '--dpi', '400', *extra, 'tsv'],
                       input=png.tobytes(), capture_output=True)
    out = []
    for row in csv.DictReader(io.StringIO(r.stdout.decode('utf8', 'replace')), delimiter='\t', quoting=csv.QUOTE_NONE):
        t = (row.get('text') or '').strip()
        if t and float(row['conf']) >= 0:
            out.append(dict(t=t, x=int(row['left']), y=int(row['top']), w=int(row['width']), h=int(row['height']),
                            c=float(row['conf']), lin=(row['block_num'], row['par_num'], row['line_num'])))
    return out

def sem_acento(s):
    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().upper()

CAMPOS = [('item', r'^(N|NO|N°|Nº|ITEM)$'), ('codigo', r'ESPECIF|COD'), ('descricao', r'DESCRI|DISCRIM'),
          ('etapa1', r'^1.{0,3}ETAPA'), ('etapa2', r'^2.{0,3}ETAPA'), ('quantidade', r'^QT|QUANT'), ('unidade', r'^UN')]
NUMERICOS = {'etapa1', 'etapa2', 'quantidade'}

def campo_do_cabecalho(txt):
    n = sem_acento(txt).replace(' ', '').replace('/', '').replace('.', '')
    for k, rx in CAMPOS:
        if re.search(rx, n): return k
    return None

def ler(rgb, nome=''):
    bw = tinta(rgb)
    h, w = bw.shape
    _, H0 = linhas(bw, 'h', w * 0.25)
    y0s = [(a + b) // 2 for a, b in H0]
    alt = [b - a for a, b in zip(y0s, y0s[1:]) if b - a >= 12]
    passo0 = np.median(alt) if alt else 60
    if passo0 < 45:  # letra pequena (imagem a ~200 dpi): amplia até a linha ter ~60 px
        f = min(3.0, 60 / passo0)
        rgb = cv2.resize(rgb, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
        bw = tinta(rgb); h, w = bw.shape
    mh, H = linhas(bw, 'h', w * 0.25)
    ys = [(a + b) // 2 for a, b in H]
    alturas = [b - a for a, b in zip(ys, ys[1:]) if b - a >= 25]
    passo = int(np.median(alturas)) if alturas else 60
    mv, _ = linhas(bw, 'v', max(0.7 * passo, 20))
    faixas, grade = [], mh.copy()
    for y0, y1 in zip(ys, ys[1:]):
        if y1 - y0 < 25: continue
        col = mv[y0 + 3:y1 - 3, :].sum(axis=0) / 255 >= (y1 - y0 - 8) * 0.9
        xs = []
        for x in np.where(col)[0]:
            if xs and x - xs[-1][-1] <= 3: xs[-1].append(x)
            else: xs.append([x])
        for g in xs: grade[y0:y1 + 1, max(0, g[0] - 1):g[-1] + 2] = 255
        xs = [int(np.mean(g)) for g in xs]
        if len(xs) >= 2: faixas.append((y0, y1, xs))
    limpa = np.where(bw > 0, 0, 255).astype(np.uint8)
    limpa[cv2.dilate(grade, np.ones((3, 3), np.uint8)) > 0] = 255
    pal = tesseract(limpa)
    linhas_tab = []
    for y0, y1, xs in faixas:
        celulas = []
        for x0, x1 in zip(xs, xs[1:]):
            if x1 - x0 < max(12, 0.012 * w): continue  # moldura dupla
            ws = [p for p in pal if x0 <= p['x'] + p['w'] / 2 < x1 and y0 <= p['y'] + p['h'] / 2 < y1]
            celulas.append(dict(x0=x0, x1=x1, y0=y0, y1=y1, ws=ws, linhas=sublinhas(ws),
                                riscado=False, colorido=fundo_colorido(rgb, x0, x1, y0, y1),
                                conf=min([p['c'] for p in ws], default=None)))
        if celulas: linhas_tab.append(dict(y0=y0, y1=y1, celulas=celulas))
    return montar(linhas_tab, w, limpa, nome)

def sublinhas(ws):
    por = {}
    for p in ws: por.setdefault(p['lin'], []).append(p)
    L = sorted(por.values(), key=lambda s: np.mean([q['y'] for q in s]))
    # o Tesseract às vezes parte a mesma linha visual em duas: junta pela altura
    out = []
    for s in L:
        ymed = np.mean([q['y'] + q['h'] / 2 for q in s])
        if out and abs(ymed - out[-1][0]) < 0.5 * np.median([q['h'] for q in s]):
            out[-1][1].extend(s)
        else:
            out.append([ymed, list(s)])
    return [' '.join(q['t'] for q in sorted(s, key=lambda q: q['x'])) for _, s in out]

LISTAS = {'num': '0123456789,.-', 'codigo': '0123456789-', 'item': '0123456789*S/Nabc-', 'unidade': 'PÇpçMmKkGgCJjUuNnLlVBb²³23'}

_RAPID = None
def rapid():
    global _RAPID
    if _RAPID is None:
        from rapidocr_onnxruntime import RapidOCR
        _RAPID = RapidOCR()
    return _RAPID

FILTRO = {'num': r'[^0-9,./\- ]', 'codigo': r'[^0-9\-]', 'item': r'[^0-9*SNa-c/\-]', 'unidade': r'[^A-Za-zÇç²³23/]'}

def reler_coluna(limpa, cels, tipo):
    """as células de uma coluna empilhadas numa faixa, lidas pelo RapidOCR (PP-OCR): segundo leitor, de natureza
    diferente do Tesseract, forte em algarismo. Uma chamada por coluna."""
    pedacos, faixas, y = [], [], 0
    larg = max(c['x1'] - c['x0'] for c in cels) + 40
    for c in cels:
        rec = limpa[c['y0'] + 3:c['y1'] - 2, c['x0'] + 4:c['x1'] - 3]
        rec = cv2.copyMakeBorder(rec, 14, 14, 20, larg - rec.shape[1] - 20, cv2.BORDER_CONSTANT, value=255)
        pedacos.append(rec); faixas.append((y, y + rec.shape[0])); y += rec.shape[0]
    if not pedacos: return []
    faixa = cv2.cvtColor(np.vstack(pedacos), cv2.COLOR_GRAY2BGR)
    r, _ = rapid()(faixa, use_cls=False)
    ws = []
    for caixa, txt, conf in (r or []):
        xs = [p[0] for p in caixa]; ys_ = [p[1] for p in caixa]
        t = re.sub(FILTRO[tipo], '', txt.replace('O', '0') if tipo in ('num', 'codigo') else txt).strip()
        if tipo == 'unidade': t = txt.strip()
        if t: ws.append(dict(t=t, x=min(xs), y=min(ys_), w=max(xs) - min(xs), h=max(ys_) - min(ys_), c=conf * 100, lin=(0, 0, len(ws))))
    out = []
    for (a, b), c in zip(faixas, cels):
        dentro = sorted([w for w in ws if a <= w['y'] + w['h'] / 2 < b], key=lambda w: w['y'])
        linhas_ = []
        for w_ in dentro:
            if linhas_ and abs(w_['y'] - linhas_[-1][-1]['y']) < w_['h'] * 0.6: linhas_[-1].append(w_)
            else: linhas_.append([w_])
        out.append([' '.join(q['t'] for q in sorted(L, key=lambda q: q['x'])) for L in linhas_])
    return out

NUM_OK = re.compile(r'^\d{1,5}([.,]\d{1,4})?$|^-$')

def juntar(prim, rel, campo):
    """duas leituras da mesma célula (tabela inteira × célula com lista de caracteres): igual → confirmada;
    diferente → fica a que tem a forma esperada, marcada divergente."""
    if prim == rel: return prim, 'confirmada'
    forma = (lambda t: bool(NUM_OK.match(t.replace(' ', '')))) if campo != 'codigo' else (lambda t: bool(re.fullmatch(r'\d{3,6}|-', t)))
    if campo == 'item': forma = lambda t: bool(re.fullmatch(r'\*?\d{1,3}[a-z]?|S/N', t))
    if campo == 'unidade': forma = lambda t: unidade(t) is not None
    ok_p = prim and all(forma(t) for t in prim)
    ok_r = rel and all(forma(t) for t in rel)
    if ok_r and not ok_p: return rel, 'releitura'
    if ok_p and not ok_r: return prim, 'primeira'
    if ok_r and ok_p:   # as duas com forma válida e diferentes: no código fica o Tesseract (o PP-OCR às vezes gira a palavra 180°), no número o PP-OCR
        return (prim if campo in ('codigo', 'unidade') else rel), 'divergente'
    return (rel or prim), 'divergente'

def numero(s):
    s = s.strip().replace(' ', '')
    if re.fullmatch(r'-+', s) or not s: return None
    s2 = s.replace('.', '').replace(',', '.') if re.search(r',\d', s) else s
    try: return float(s2)
    except ValueError: return None

def unidade(s):
    k = sem_acento(s).replace('.', '').strip()
    k = {'PC': 'PC', 'PG': 'PC', 'PE': 'PC', 'OC': 'PC', 'BE': 'PC', 'PO': 'PC', 'PS': 'PC', '5D': 'PC', '3D': 'PC', 'P¢': 'PC', 'PQ': 'PC',
         'KG': 'KG', 'K G': 'KG', 'KA': 'KG', 'K9': 'KG', 'KQ': 'KG', 'CI': 'CJ', 'C)': 'CJ', 'MO': 'M', 'RN': 'M'}.get(k, k)
    return UNIDADES.get(k)

def alinhar(ln, cab_x):
    """linha com células mescladas ou partidas: cada célula vai para a coluna do cabeçalho com maior sobreposição em x."""
    novas = [None] * len(cab_x)
    for c in ln['celulas']:
        sob = [max(0, min(c['x1'], b) - max(c['x0'], a)) for a, b in cab_x]
        i = int(np.argmax(sob))
        if sob[i] <= 0: continue
        if novas[i] is None: novas[i] = dict(c)
        else:
            n = novas[i]; n['x0'] = min(n['x0'], c['x0']); n['x1'] = max(n['x1'], c['x1'])
            n['linhas'] = n['linhas'] + c['linhas']; n['ws'] = n['ws'] + c['ws']
            n['riscado'] = n['riscado'] or c['riscado']; n['colorido'] = n['colorido'] or c['colorido']
    if sum(1 for n in novas if n) < 2: return None
    y0, y1 = ln['y0'], ln['y1']
    for i, n in enumerate(novas):
        if n is None: novas[i] = dict(x0=cab_x[i][0], x1=cab_x[i][1], y0=y0, y1=y1, ws=[], linhas=[], riscado=False, colorido=False, conf=None)
    return dict(y0=y0, y1=y1, celulas=novas)

def decimal(t):
    """o PP-OCR lê a vírgula como ponto: no quantitativo brasileiro, ponto seguido de 1 a 3 algarismos no fim é a vírgula."""
    return re.sub(r'^(\d+)\.(\d{1,4})$', r'\1,\2', t.strip())

def empilhar(reg):
    """'02 - 20,06' numa linha só com unidade empilhada (pç / kg): são dois valores, como na célula de duas linhas."""
    n_un = len([u for u in reg.get('unidade_norm', '').split(' / ') if u])
    for c in NUMERICOS:
        v = reg.get(c, '')
        if n_un == 2 and v and '/' not in v:
            m = re.fullmatch(r'\D*(\d+)\s*[-–—]+\s*(\d+[.,]\d+)\D*', v)
            if m: reg[c] = f'{m.group(1)} / {decimal(m.group(2))}'

def inferir_papeis(linhas_item):
    """coluna sem rótulo legível (cabeçalho pequeno ou borrado): o papel sai do conteúdo. À esquerda do código e curta
    = item; numérica depois da descrição = quantidade; curta e alfabética no fim = unidade; 4-6 algarismos = código."""
    if not linhas_item: return linhas_item
    cab = list(linhas_item[0][1])
    if all(cab) and 'unidade' in cab and ('quantidade' in cab or 'etapa1' in cab): return linhas_item
    n = len(cab)
    cols = [[' '.join(ln['celulas'][i]['linhas']) for _, _, ln in linhas_item] for i in range(n)]
    def frac(i, rx):
        v = [t for t in cols[i] if t.strip()]
        return sum(bool(re.fullmatch(rx, t.strip())) for t in v) / max(1, len(v)) if v else 0
    vazias = lambda i: sum(1 for t in cols[i] if not t.strip()) / len(cols[i])
    idesc = cab.index('descricao') if 'descricao' in cab else None
    iun = cab.index('unidade') if 'unidade' in cab else None
    for i in range(n):
        if cab[i] or vazias(i) > 0.9: continue
        if idesc is not None and iun is not None and idesc < i < iun:   # ordem fixa da relação Sanepar
            cab[i] = 'quantidade' if not any(c in cab for c in ('quantidade', 'etapa1')) else ('etapa2' if 'etapa1' in cab and 'etapa2' not in cab else None)
            if cab[i]: continue
        if frac(i, r'\d{4,6}|-') > 0.6 and 'codigo' not in cab: cab[i] = 'codigo'
        elif idesc is not None and i < idesc and frac(i, r'\*?\s?\d{1,3}[a-c]?|S/?N|.{1,4}') > 0.6 and 'item' not in cab: cab[i] = 'item'
        elif idesc is not None and i > idesc and frac(i, r'[A-Za-zÇç²³/ ]{1,6}') > 0.6 and 'unidade' not in cab: cab[i] = 'unidade'
        elif idesc is not None and i > idesc and frac(i, r'[\d.,/ -]+') > 0.5:
            cab[i] = 'quantidade' if 'quantidade' not in cab and 'etapa1' not in cab else ('etapa2' if 'etapa1' in cab and 'etapa2' not in cab else None)
    # código colado no começo da descrição (coluna sem traço próprio no cabeçalho)
    if 'codigo' not in cab and idesc is not None:
        if sum(bool(re.match(r'^\s*(\d{4,6}|-)\s', ' '.join(ln['celulas'][idesc]['linhas']))) for _, _, ln in linhas_item) > 0.6 * len(linhas_item):
            for _, _, ln in linhas_item:
                c = ln['celulas'][idesc]
                if c['linhas']:
                    m = re.match(r'^\s*(\d{4,6}|-)\s+(.*)$', c['linhas'][0])
                    if m: c['codigo_colado'] = m.group(1); c['linhas'] = [m.group(2)] + c['linhas'][1:]
    return [(sec, cab, ln) for sec, _, ln in linhas_item]

def montar(linhas_tab, w, limpa, nome):
    cab, secao, titulo, outras = None, '', [], 0
    linhas_item = []
    for ln in linhas_tab:
        cs = ln['celulas']
        larga = max(c['x1'] - c['x0'] for c in cs) > 0.6 * w
        if len(cs) == 1 or (len(cs) <= 3 and larga):
            t = ' '.join(' '.join(c['linhas']) for c in cs).strip()
            if t:
                if cab is None: titulo.append(t)
                else: secao = t
            continue
        campos = [campo_do_cabecalho(' '.join(c['linhas'])) for c in cs]
        brutos = [sem_acento(' '.join(c['linhas'])) for c in cs]
        n_etapa = 0
        for i, b in enumerate(brutos):
            if 'ETAPA' in b.replace(' ', ''):
                n_etapa += 1; campos[i] = f'etapa{n_etapa}'
        if 'descricao' in campos and sum(1 for k in campos if k) >= 3:
            cab = campos; cab_x = [(c['x0'], c['x1']) for c in cs]; continue
        if cab is None:
            outras += 1; continue
        if len(cs) != len(cab):
            ln = alinhar(ln, cab_x)
            if ln is None: outras += 1; continue
        linhas_item.append((secao, cab, ln))
    linhas_item = inferir_papeis(linhas_item)
    # releitura em lote por (cabeçalho, coluna)
    rel = {}
    grupos = {}
    for k, (sec, cb, ln) in enumerate(linhas_item):
        for i, campo in enumerate(cb):
            if campo in NUMERICOS or campo in ('codigo', 'item', 'unidade'):
                grupos.setdefault((tuple(cb), i, campo), []).append((k, ln['celulas'][i]))
    for (cb, i, campo), L in grupos.items():
        tipo = 'num' if campo in NUMERICOS else campo
        res = reler_coluna(limpa, [c for _, c in L], tipo)
        for (k, _), r in zip(L, res): rel[(k, i)] = r
    itens = []
    for k, (sec, cb, ln) in enumerate(linhas_item):
        reg = {'secao': sec, 'linha_y': [int(ln['y0']), int(ln['y1'])], 'riscado': [], 'colorido': [], 'estado': {}}
        for i, (campo, c) in enumerate(zip(cb, ln['celulas'])):
            if not campo: continue
            txt = c['linhas']
            if (k, i) in rel:
                txt, est = juntar(txt, rel[(k, i)], campo)
                reg['estado'][campo] = est
            if campo in NUMERICOS: txt = [decimal(t) for t in txt]
            reg[campo] = ' / '.join(txt)
            if campo == 'descricao':
                if c.get('codigo_colado'): reg['codigo'] = c['codigo_colado']
                reg['descricao_ocr'] = reg[campo]
                reg[campo], tr = vocabulario.corrigir(reg[campo])
                if tr: reg['correcoes'] = tr
            if c['riscado']: reg['riscado'].append(campo)
            if c['colorido']: reg['colorido'].append(campo)
            if campo == 'unidade':
                reg['unidade_norm'] = ' / '.join(unidade(t) or t.lower() or '?' for t in txt)
            if campo in NUMERICOS:
                reg[campo + '_valor'] = [numero(t) for t in txt]
        empilhar(reg)
        reg['conf_min'] = min([c['conf'] for c in ln['celulas'] if c['conf'] is not None], default=None)
        if reg.get('descricao') or reg.get('codigo'):
            itens.append(reg)
    return dict(nome=nome, titulo=titulo, cabecalho=cab, itens=itens, linhas_fora=outras)

def risco(bw, x0, x1, y0, y1, ws):
    """valor riscado: traço horizontal (contínuo ou tracejado) com mais de 40 % da célula, passando pela altura do
    texto — o separador pç/kg fica ENTRE as linhas de texto e não conta."""
    cel = bw[y0 + 5:y1 - 4, x0 + 6:x1 - 5]
    if cel.size == 0 or cel.shape[1] < 30: return False
    fech = cv2.morphologyEx(cel, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 1)))
    lin = cv2.morphologyEx(fech, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (int(cel.shape[1] * 0.4), 1)))
    rows = np.where(lin.sum(axis=1) > 0)[0]
    if not len(rows): return False
    texto = (cel > 0).sum(axis=1) > 0
    for r in rows:
        # texto acima e abaixo do traço, colado nele: o traço corta a palavra
        if r >= 4 and r + 4 < len(texto) and texto[r - 4] and texto[r + 4]:
            a = cel[r - 4, :].astype(bool) & ~lin[r, :].astype(bool)
            b = cel[r + 4, :].astype(bool)
            if a.sum() > 3 and b.sum() > 3: return True
    return False

def fundo_colorido(rgb, x0, x1, y0, y1):
    r = rgb[y0 + 4:y1 - 4, x0 + 4:x1 - 4].reshape(-1, 3).astype(int)
    if not len(r): return False
    return ((r.max(axis=1) - r.min(axis=1)) > 60).mean() > 0.4
