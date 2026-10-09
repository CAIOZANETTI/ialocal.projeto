"""Laço: cada PDF → tabelas (imagem embutida ou malha vetorial) → JSON e CSV com rastro (arquivo, página, origem,
caixa em pt na folha, tempo)."""
import sys, json, time, pathlib, csv
import pymupdf, cv2, numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import tabela_raster as tr, grade_vetor as gv

def no_carimbo(b, W, H):
    return b[0] > 0.70 * W and b[1] > 0.70 * H

def tabelas_da_pagina(doc, pg):
    W, H = pg.rect.width, pg.rect.height
    out = []
    for info in pg.get_image_info(xrefs=True):
        b = info['bbox']
        if info['width'] < 400 or (b[2]-b[0])*(b[3]-b[1]) > 0.5 * W * H: continue
        pix = pymupdf.Pixmap(doc, info['xref'])
        if pix.alpha or pix.n > 3: pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        rgb = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3].copy()
        out.append(('imagem', tuple(b), rgb))
    for t in gv.tabelas(pg):
        b = t['bbox']
        if no_carimbo(b, W, H) or len(t['ys']) < 5 or (b[2]-b[0]) < 120: continue
        if any(gv.dentro(b, o[1]) for o in out): continue
        clip = pymupdf.Rect(b[0]-3, b[1]-3, b[2]+3, b[3]+3)
        pix = pg.get_pixmap(matrix=pymupdf.Matrix(400/72, 400/72), clip=clip)
        rgb = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3].copy()
        out.append(('vetor', tuple(b), rgb))
    return out

def main(pasta, saida):
    saida = pathlib.Path(saida); saida.mkdir(parents=True, exist_ok=True)
    (saida / 'recortes').mkdir(exist_ok=True)
    todas, linhas = [], []
    for p in sorted(pathlib.Path(pasta).glob('*.pdf')):
        doc = pymupdf.open(p)
        for ip, pg in enumerate(doc):
            t0 = time.time()
            cands = tabelas_da_pagina(doc, pg)
            for k, (origem, b, rgb) in enumerate(cands):
                a = time.time()
                if not tr.e_tabela(rgb):
                    todas.append(dict(arquivo=p.name, pagina=ip+1, origem=origem, bbox_pt=[round(x,1) for x in b], tabela=False, tempo_s=round(time.time()-a,2)))
                    continue
                r = tr.ler(rgb, f'{p.stem}_p{ip+1}_{k}')
                tid = f'{p.name[:4].strip("-")}_p{ip+1}_t{k}'
                cv2.imwrite(str(saida/'recortes'/f'{tid}.png'), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
                todas.append(dict(arquivo=p.name, pagina=ip+1, tabela_id=tid, origem=origem, bbox_pt=[round(x,1) for x in b], tabela=True,
                                  titulo=r['titulo'], cabecalho=r['cabecalho'], n_itens=len(r['itens']), linhas_fora=r['linhas_fora'],
                                  tempo_s=round(time.time()-a,2), px=list(rgb.shape[:2])))
                for n, it in enumerate(r['itens']):
                    linhas.append(dict(arquivo=p.name, pagina=ip+1, tabela_id=tid, origem=origem, linha=n+1,
                                       titulo=' | '.join(r['titulo']), secao=it['secao'], item=it.get('item',''), codigo=it.get('codigo',''),
                                       descricao=it.get('descricao',''), quantidade=it.get('quantidade',''), etapa1=it.get('etapa1',''),
                                       etapa2=it.get('etapa2',''), unidade=it.get('unidade_norm') or it.get('unidade',''),
                                       riscado=','.join(it['riscado']), colorido=','.join(it['colorido']),
                                       divergente=','.join(k for k,v in it['estado'].items() if v=='divergente'),
                                       correcoes=';'.join(f'{a}>{b}' for a,b in it.get('correcoes',[])),
                                       conf_min=round(it['conf_min'],1) if it['conf_min'] is not None else '', linha_y=it['linha_y']))
            print(f'{p.name[:50]:50} p{ip+1} {len(cands)} cand. {time.time()-t0:5.1f}s', flush=True)
    json.dump(todas, open(saida/'tabelas.json','w'), ensure_ascii=False, indent=1)
    with open(saida/'itens.csv','w',newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()), delimiter=';'); w.writeheader(); w.writerows(linhas)
    print('tabelas', sum(1 for t in todas if t['tabela']), 'itens', len(linhas))

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
