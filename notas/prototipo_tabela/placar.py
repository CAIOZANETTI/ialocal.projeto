"""Placar de uma extração contra o gabarito: linha a linha (alinhadas pela ordem e pelo item+código), campo a campo."""
import csv, sys, re, json, pathlib, difflib, unicodedata
CAMPOS = ['item', 'codigo', 'quantidade', 'etapa1', 'etapa2', 'unidade', 'riscado']

def norm(campo, v):
    v = (v or '').strip()
    if campo in ('quantidade', 'etapa1', 'etapa2'):
        return ' / '.join(x.strip().replace(' ', '') for x in v.split('/')) if v else ''
    if campo == 'unidade':
        return v.lower().replace('pc', 'pç').replace(' ', '')
    if campo == 'riscado':
        return ','.join(sorted(x for x in v.split(',') if x and x != 'descricao'))
    return v.replace(' ', '')

def desc(v):
    v = unicodedata.normalize('NFKD', (v or '').replace(' / ', ' ')).encode('ascii', 'ignore').decode().upper()
    return re.sub(r'\s+', ' ', v).strip()

def ler(p):
    return list(csv.DictReader(open(p, encoding='utf-8-sig'), delimiter=';'))

def comparar(ext, gab):
    chave = lambda r: (norm('item', r.get('item')) + '|' + norm('codigo', r.get('codigo')))
    sm = difflib.SequenceMatcher(None, [chave(r) for r in ext], [chave(r) for r in gab], autojunk=False)
    pares, faltou, inventou = [], 0, 0
    # alinhamento pela ordem: blocos iguais + substituições 1:1
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op == 'equal' or (op == 'replace' and a1 - a0 == b1 - b0):
            pares += list(zip(ext[a0:a1], gab[b0:b1]))
        else:
            n = min(a1 - a0, b1 - b0)
            pares += list(zip(ext[a0:a0 + n], gab[b0:b0 + n]))
            faltou += max(0, (b1 - b0) - n); inventou += max(0, (a1 - a0) - n)
    res = {c: [0, 0] for c in CAMPOS + ['descricao']}
    erros = []
    for e, g in pares:
        for c in CAMPOS:
            if c not in g: continue
            if norm(c, g[c]) == '' and norm(c, e.get(c)) == '': continue
            ok = norm(c, e.get(c)) == norm(c, g[c])
            res[c][0] += ok; res[c][1] += 1
            if not ok: erros.append((c, e.get(c), g[c], g.get('item'), g.get('codigo')))
        r = difflib.SequenceMatcher(None, desc(e.get('descricao')), desc(g.get('descricao'))).ratio()
        res['descricao'][0] += r; res['descricao'][1] += 1
    linha_ok = sum(all(norm(c, e.get(c)) == norm(c, g.get(c)) for c in CAMPOS if c in g and c != 'riscado') for e, g in pares)
    return dict(linhas_gab=len(gab), linhas_ext=len(ext), pareadas=len(pares), faltou=faltou, inventou=inventou,
                linhas_certas=linha_ok, campos=res, erros=erros)

if __name__ == '__main__':
    ext_dir, gab_dir = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    tot = {c: [0, 0] for c in CAMPOS + ['descricao']}; T = dict(linhas_gab=0, linhas_certas=0, faltou=0, inventou=0)
    por_tab = {}
    for g in sorted(gab_dir.glob('gab_*.csv')):
        tid = g.stem[4:]
        e = ext_dir / f'{tid}.csv'
        if not e.exists(): continue
        r = comparar(ler(e), ler(g)); por_tab[tid] = r
        for c in tot: tot[c][0] += r['campos'][c][0]; tot[c][1] += r['campos'][c][1]
        for k in T: T[k] += r[k]
        print(f"{tid:12} gab={r['linhas_gab']:3} ext={r['linhas_ext']:3} certas={r['linhas_certas']:3} faltou={r['faltou']} inventou={r['inventou']}  " +
              ' '.join(f"{c}={r['campos'][c][0]:.0f}/{r['campos'][c][1]}" for c in CAMPOS if r['campos'][c][1]))
    print('TOTAL', T, {c: (round(a / b, 3) if b else None) for c, (a, b) in tot.items()})
    if len(sys.argv) > 3:
        json.dump(dict(total=T, campos={c: dict(certos=a, total=b, taxa=round(a / b, 4) if b else None) for c, (a, b) in tot.items()},
                       tabelas={k: {kk: vv for kk, vv in v.items() if kk != 'erros'} | {'erros': v['erros'][:50]} for k, v in por_tab.items()}),
                  open(sys.argv[3], 'w'), ensure_ascii=False, indent=1)
