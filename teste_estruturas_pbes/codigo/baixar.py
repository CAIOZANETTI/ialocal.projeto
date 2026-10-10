import sys, os, subprocess, concurrent.futures as cf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from manifesto_drive import ESTRUTURAS
RAIZ = os.environ.get('PBES_BRUTO', os.path.expanduser('~/pbes_bruto'))
def uma(t):
    est, fid, nome = t
    d = f'{RAIZ}/{est}'; os.makedirs(d, exist_ok=True)
    dest = f'{d}/{nome}'
    if os.path.exists(dest) and open(dest,'rb').read(5) == b'%PDF-': return est, nome, 'ja'
    r = subprocess.run(['curl','-sS','-L','--retry','3','-o',dest,'-w','%{http_code}',f'https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t'],capture_output=True,text=True)
    ok = os.path.exists(dest) and open(dest,'rb').read(5) == b'%PDF-'
    return est, nome, ('ok %d' % os.path.getsize(dest)) if ok else 'FALHA ' + r.stdout + r.stderr[:80]
tarefas = [(e, i, n) for e, fs in ESTRUTURAS.items() for i, n in fs.items()]
with cf.ThreadPoolExecutor(6) as ex:
    res = list(ex.map(uma, tarefas))
falhas = [r for r in res if r[2].startswith('FALHA')]
print(len(res), 'arquivos;', len(falhas), 'falhas'); [print(f) for f in falhas]
