"""Roda o leitor nos recortes com uma largura máxima (simula o thumbnail de 1.100 px da produção) e grava CSVs no formato da revisão."""
import sys, csv, json, time, pathlib, cv2
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import tabela_raster as tr
largura, saida = int(sys.argv[1]), pathlib.Path(sys.argv[2]); saida.mkdir(exist_ok=True)
ids = [t['tabela_id'] for t in json.load(open('saida/tabelas.json')) if t['tabela'] and t['n_itens']]
cols = ['linha','secao','item','codigo','descricao','quantidade','etapa1','etapa2','unidade','riscado']
tempos = {}
for tid in ids:
    rgb = cv2.cvtColor(cv2.imread(f'saida/recortes/{tid}.png'), cv2.COLOR_BGR2RGB)
    if largura and rgb.shape[1] > largura:
        f = largura / rgb.shape[1]; rgb = cv2.resize(rgb, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    a = time.time(); r = tr.ler(rgb, tid); tempos[tid] = round(time.time() - a, 2)
    with open(saida / f'{tid}.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter=';', extrasaction='ignore'); w.writeheader()
        for n, it in enumerate(r['itens'], 1):
            w.writerow(dict(linha=n, secao=it['secao'], item=it.get('item',''), codigo=it.get('codigo',''), descricao=it.get('descricao',''),
                            quantidade=it.get('quantidade',''), etapa1=it.get('etapa1',''), etapa2=it.get('etapa2',''),
                            unidade=it.get('unidade_norm') or it.get('unidade',''), riscado=','.join(it['riscado'])))
json.dump(tempos, open(saida / 'tempos.json', 'w'))
print(largura, sum(tempos.values()))
