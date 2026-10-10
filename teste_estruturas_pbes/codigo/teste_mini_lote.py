"""Teste do código ATUAL do Mini (ialocal.projeto/codigo/tabela.py), sem alteração nenhuma, em pranchas do PBES.
Fluxo = o de tabela.ler_tabelas: malhas() -> e_tabela() -> ler() com os leitores do conceitos/tabela.json
(vision -> tesseract -> rapidocr; aqui o Vision não existe, então A = Tesseract e B = RapidOCR)."""
import os, sys, json, time, glob
os.environ.setdefault('OMP_THREAD_LIMIT', '1')
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, '..', '..', 'codigo'))   # o código do Mini, sem alteração
BRUTO = os.environ.get('PBES_BRUTO', os.path.expanduser('~/pbes_bruto'))
import pypdfium2 as pdfium, tabela
AMOSTRA = [
 'MOD_TRATAM_MICRO_AREIA_600Ls/002-SAA-0017-8820-PBES-DE-0000ACT01FORMA-R0.PDF',
 'MOD_TRATAM_MICRO_AREIA_600Ls/009-SAA-0017-8820-PBES-DE-0000ACT01ARMADURA-R0.PDF',
 'MOD_TRATAM_MICRO_AREIA_600Ls/020-SAA-0017-8820-PBES-DE-0000ACT01ARMADURA-R0.PDF',
 'MOD_TRATAM_MICRO_AREIA_360Ls/001-SAA-0017-8820-PBES-DE-0000ACT02FORMA-R0.PDF',
 'MOD_TRATAM_MICRO_AREIA_360Ls/004-SAA-0017-8820-PBES-DE-0000ACT02ARMADURA-R0.PDF',
 'MOD_TRATAM_FILTROS_NOVOS/008-SAA-0017-8820-PBES-DE-0000MOD01ARMADURA-R1.pdf',
 'BLOCOS_DE_APOIO_E_ANCORAGEM/003-SAA-0017-8820-PBES-DE-0000BLO01FORMARMAD-R0.PDF',
 'GUARITA/001-SAA-0017-8820-PBES-DE-0000POR01FORMA-R0.PDF',
 'GUARITA/002-SAA-0017-8820-PBES-DE-0000POR01ARMADURA-R0.PDF',
 'INTERLIGAÇÕES/001-SAA-0017-8820-PBES-DE-0000CXA03FORMARMAD-R0.PDF',
 'ABRIGO_BOMBAS_PRODS_QUIMICOS/001-SAA-0017-8820-PBES-DE-0000ABR0101FORMARMAD-R0.PDF',
 'REFORMA_EDIFIC_LODO/001-SAA-0017-8820-PBES-DE-0000ETL01FORMA-R0.PDF',
]
def uma(rel):
    pdf = os.path.join(BRUTO, rel)
    t0 = time.time(); r = {'arquivo': rel, 'caixas': [], 'itens_total': 0, 'erro': ''}
    try:
        nome_a, ler_a = tabela.leitor_a(); nome_b, ler_b = tabela.leitor_b()
        r.update(leitor_a=nome_a, leitor_b=nome_b)
        pag = pdfium.PdfDocument(pdf)[0]
        for caixa, rgb in tabela.malhas(pag, []):
            reg = {'caixa_pt': caixa, 'e_tabela': bool(tabela.e_tabela(rgb)), 'itens': 0, 'cabecalho': None, 'titulo': []}
            if reg['e_tabela']:
                lida = tabela.ler(rgb, ler_a, ler_b)
                reg.update(itens=len(lida['itens']), cabecalho=lida['cabecalho'], titulo=[t[:80] for t in lida['titulo']][:3], linhas_fora=lida['linhas_fora'])
                r['itens_total'] += reg['itens']
            r['caixas'].append(reg)
    except Exception as e:
        r['erro'] = f'{type(e).__name__}: {e}'
    r['segundos'] = round(time.time() - t0, 1)
    return r
def iou(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x1 - x0) * max(0, y1 - y0)
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u else 0


def localizacao(res):
    """As caixas que o malhas() do Mini achou x as tabelas-alvo que o extrator de referência localizou (IoU > 0,5)."""
    import csv
    linhas = []
    for r in res:
        est, arq = r['arquivo'].split('/')
        pj = json.load(open(os.path.join(AQUI, '..', 'resultados', est, os.path.splitext(arq)[0], 'prancha.json')))
        for c in pj['caixas']:
            if c['tipo'] in ('armadura', 'resumo_aco', 'resumo_materiais', 'resumo_metalico'):
                linhas.append({'estrutura': est, 'codigo_arquivo': os.path.splitext(arq)[0], 'tabela_alvo': c['tipo'], 'caixa_pt': json.dumps(c['caixa_pt']),
                               'achada_pelo_mini': any(iou(c['caixa_pt'], m['caixa_pt']) > 0.5 for m in r['caixas']),
                               'itens_lidos_pelo_mini': r['itens_total']})
    with open(os.path.join(AQUI, '..', 'resultados', 'consolidado', 'mini_localizacao.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0]), delimiter=';'); w.writeheader(); w.writerows(linhas)
    return linhas


if __name__ == '__main__':
    import multiprocessing as mp
    with mp.Pool(3) as p:
        res = []
        for r in p.imap_unordered(uma, AMOSTRA):
            res.append(r); print(r['arquivo'][:60], 'caixas', len(r['caixas']), 'itens', r['itens_total'], r['segundos'], 's', r['erro'], flush=True)
    os.makedirs(os.path.join(AQUI, '..', 'resultados', 'consolidado'), exist_ok=True)
    json.dump(sorted(res, key=lambda r: r['arquivo']), open(os.path.join(AQUI, '..', 'resultados', 'consolidado', 'resultado_codigo_do_mini.json'), 'w'), ensure_ascii=False, indent=1)
    localizacao(res)
