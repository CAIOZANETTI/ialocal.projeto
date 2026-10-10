"""Acha tabelas pela geometria do PDF: linhas horizontais de mesma extensão empilhadas = linhas da tabela;
verticais dentro delas = colunas. Sem OCR, sem modelo: determinístico."""
import pymupdf
from collections import defaultdict

TOL = 1.5

def segmentos(pg):
    H, V = [], []
    for d in pg.get_drawings():
        for it in d['items']:
            if it[0] == 'l':
                a, b = it[1], it[2]
                segs = [(a.x, a.y, b.x, b.y)]
            elif it[0] == 're':
                r = it[1]
                segs = [(r.x0, r.y0, r.x1, r.y0), (r.x0, r.y1, r.x1, r.y1), (r.x0, r.y0, r.x0, r.y1), (r.x1, r.y0, r.x1, r.y1)]
            elif it[0] == 'qu':
                q = it[1].rect
                segs = [(q.x0, q.y0, q.x1, q.y0), (q.x0, q.y1, q.x1, q.y1), (q.x0, q.y0, q.x0, q.y1), (q.x1, q.y0, q.x1, q.y1)]
            else:
                continue
            for x0, y0, x1, y1 in segs:
                if abs(y1 - y0) < 0.3 and abs(x1 - x0) > 8:
                    H.append((min(x0, x1), max(x0, x1), (y0 + y1) / 2))
                elif abs(x1 - x0) < 0.3 and abs(y1 - y0) > 4:
                    V.append((min(y0, y1), max(y0, y1), (x0 + x1) / 2))
    return fundir(H), fundir(V)

def fundir(segs):
    """une segmentos colineares que se tocam (a linha da tabela costuma vir picada)."""
    por = defaultdict(list)
    for a, b, c in segs:
        por[round(c / TOL)].append((a, b, c))
    out = []
    for k in sorted(por):
        L = sorted(por[k])
        a, b, c = L[0]
        for a2, b2, c2 in L[1:]:
            if a2 <= b + TOL:
                b = max(b, b2)
            else:
                out.append((a, b, c)); a, b, c = a2, b2, c2
        out.append((a, b, c))
    return out

def tabelas(pg, min_linhas=3, max_passo=40, min_larg=60):
    """grupos de horizontais com o mesmo x0 e x1 e passo pequeno → caixa de tabela; colunas pelas verticais."""
    H, V = segmentos(pg)
    H = [h for h in H if h[1] - h[0] >= min_larg]
    grupos = defaultdict(list)
    for a, b, y in H:
        grupos[(round(a / 3), round(b / 3))].append((a, b, y))
    caixas = []
    for k, L in grupos.items():
        L.sort(key=lambda s: s[2])
        bloco = [L[0]]
        for s in L[1:]:
            if s[2] - bloco[-1][2] <= max_passo:
                bloco.append(s)
            else:
                if len(bloco) >= min_linhas: caixas.append(bloco)
                bloco = [s]
        if len(bloco) >= min_linhas: caixas.append(bloco)
    res = []
    for bl in caixas:
        x0 = min(s[0] for s in bl); x1 = max(s[1] for s in bl)
        ys = sorted({round(s[2], 1) for s in bl})
        y0, y1 = ys[0], ys[-1]
        cols = sorted({round(v[2], 1) for v in V if x0 - TOL <= v[2] <= x1 + TOL and v[0] <= y1 + TOL and v[1] >= y0 - TOL and (v[1] - v[0]) > 3})
        cols = dedup(cols)
        res.append(dict(bbox=(x0, y0, x1, y1), ys=dedup(ys), xs=cols))
    # descarta caixas contidas em outra (a mesma tabela vista por subconjunto)
    res.sort(key=lambda t: -(t['bbox'][2]-t['bbox'][0])*(t['bbox'][3]-t['bbox'][1]))
    final = []
    for t in res:
        if not any(dentro(t['bbox'], f['bbox']) for f in final):
            final.append(t)
    return final

def dedup(v, tol=2.0):
    out = []
    for x in v:
        if not out or x - out[-1] > tol: out.append(x)
    return out

def dentro(a, b, tol=3):
    return a[0] >= b[0]-tol and a[1] >= b[1]-tol and a[2] <= b[2]+tol and a[3] <= b[3]+tol
