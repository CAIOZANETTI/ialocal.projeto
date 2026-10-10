"""Lote: extrai as tabelas de cada prancha do PBES, mantendo estrutura -> prancha -> tabela -> linha (rastreabilidade).
Saída: saidas/<estrutura>/<codigo_arquivo>/{resumo_materiais,resumo_aco,tabela_armadura}.csv + prancha.json."""
import os, sys, json, time, glob, traceback
os.environ.setdefault('OMP_NUM_THREADS', '1'); os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import csv
import extrator_pbes as X

RAIZ = os.environ.get('PBES_BRUTO', os.path.expanduser('~/pbes_bruto'))   # os PDFs (nunca vão ao git)
SAIDA = os.environ.get('SAIDA', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'resultados'))

def gravar_csv(caminho, linhas, base):
    if not linhas: return
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    campos = list(base) + [k for k in dict.fromkeys(k for l in linhas for k in l) if k not in base]
    with open(caminho, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=campos, delimiter=';'); w.writeheader()
        for l in linhas: w.writerow({**base, **l})

def uma(pdf):
    estrutura = os.path.relpath(pdf, RAIZ).split(os.sep)[0]
    codigo = os.path.splitext(os.path.basename(pdf))[0]
    t0 = time.time()
    info = {'estrutura': estrutura, 'codigo_arquivo': codigo, 'caixas': [], 'erro': ''}
    base = {'estrutura': estrutura, 'codigo_arquivo': codigo, 'pagina': 1}
    try:
        pag, cs = X.caixas(pdf)
        mats, aco, arm, faixas, met = [], [], [], {}, []
        for k, (cx, rgb) in enumerate(cs):
            tipo, _ = X.classificar(rgb)
            info['caixas'].append({'n': k, 'tipo': tipo, 'caixa_pt': cx})
            if tipo == 'resumo_materiais':
                rows, ex = X.ler_resumo_materiais(rgb)
                mats += [{'tabela': k, 'caixa_pt': json.dumps(cx), **r} for r in rows if r['divisao'] or r['volume_txt'] or r['area_forma_txt']]
                faixas = X.ler_faixa_valor(pag, cx)
                if ex.get('erro'): info['caixas'][-1]['erro'] = ex['erro']
            elif tipo == 'resumo_aco':
                rows, ex = X.ler_resumo_aco(rgb)
                aco += [{'tabela': k, 'caixa_pt': json.dumps(cx), **r} for r in rows]
                for cl, v in ex.get('totais', {}).items():
                    aco.append({'tabela': k, 'caixa_pt': json.dumps(cx), 'classe': cl, 'peso_kg': v['peso_kg'], 'bit_txt': 'TOTAL', 'texto': v['texto']})
            elif tipo == 'resumo_metalico':
                rows, ex = X.ler_grade_simples(rgb)
                met += [{'tabela': k, 'caixa_pt': json.dumps(cx), 'y': l['y'], **{f'c{i}': c for i, c in enumerate(l['celulas'])}} for l in rows]
            elif tipo == 'armadura':
                rows, ex = X.ler_armadura(rgb)
                if ex.get('erro'): info['caixas'][-1]['erro'] = ex['erro']
                arm += [{'tabela': k, 'caixa_pt': json.dumps(cx), **r} for r in rows]
        for nome, v in faixas.items():
            mats.append({'tabela': -1, 'divisao': nome.upper(), 'volume_txt': v['texto'], 'volume_m3': v['valor_m3']})
        d = f'{SAIDA}/{estrutura}/{codigo}'
        gravar_csv(f'{d}/resumo_materiais.csv', mats, base)
        gravar_csv(f'{d}/resumo_aco.csv', aco, base)
        gravar_csv(f'{d}/tabela_armadura.csv', arm, base)
        gravar_csv(f'{d}/resumo_material_metalico.csv', met, base)
        info.update(n_resumo_materiais=len(mats), n_resumo_aco=len(aco), n_armadura=len(arm))
    except Exception as e:
        info['erro'] = f'{type(e).__name__}: {e}'; info['trace'] = traceback.format_exc()[-800:]
    info['segundos'] = round(time.time() - t0, 1)
    os.makedirs(f'{SAIDA}/{estrutura}/{codigo}', exist_ok=True)
    json.dump(info, open(f'{SAIDA}/{estrutura}/{codigo}/prancha.json', 'w'), ensure_ascii=False, indent=1)
    return info

if __name__ == '__main__':
    import multiprocessing as mp
    pdfs = sys.argv[1:] or sorted(glob.glob(f'{RAIZ}/*/*'))
    with mp.Pool(4) as p:
        for i, r in enumerate(p.imap_unordered(uma, pdfs), 1):
            print(f"[{i}/{len(pdfs)}] {r['estrutura']}/{r['codigo_arquivo'][:40]} {r['segundos']}s arm={r.get('n_armadura')} aco={r.get('n_resumo_aco')} mat={r.get('n_resumo_materiais')} {r['erro']}", flush=True)
