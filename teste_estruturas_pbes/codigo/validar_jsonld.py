"""Valida o JSON-LD: (1) toda chave está definida no @context (o pyld descarta termo indefinido em silêncio); (2) expande e vira RDF;
(3) as somas fecham: unidade = soma das pranchas; elementos = linhas; quantidades.jsonl = o que está nos documentos."""
import glob, json, os, sys
from pyld import jsonld
import rdflib

AQUI = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(AQUI, '..', 'jsonld')
ctx = json.load(open(os.path.join(OUT, 'contexto.jsonld')))['@context']
erros, triplas, docs = [], 0, 0

def chaves(o, caminho=''):
    if isinstance(o, dict):
        for k, v in o.items():
            if not k.startswith('@') and k not in ctx:
                erros.append(f'{caminho}: termo fora do @context: {k}')
            yield from chaves(v, caminho + '/' + k)
    elif isinstance(o, list):
        for x in o: yield from chaves(x, caminho)

for f in sorted(glob.glob(os.path.join(OUT, '**', '*.jsonld'), recursive=True)):
    if f.endswith('contexto.jsonld'): continue
    d = json.load(open(f)); docs += 1
    list(chaves(d, os.path.relpath(f, OUT)))
    base = 'file://' + os.path.abspath(f)
    exp = jsonld.expand(d, {'base': base, 'documentLoader': lambda url, opts=None: {'contentType': 'application/ld+json', 'contextUrl': None, 'documentUrl': url, 'document': json.load(open(os.path.join(os.path.dirname(os.path.abspath(f)), url.replace('file://', '').split('/')[-1]) if not url.startswith('file://') else url.replace('file://', '')))} if url.endswith('contexto.jsonld') else (_ for _ in ()).throw(Exception(url))})
    g = rdflib.Graph(); g.parse(data=json.dumps(exp), format='json-ld')
    triplas += len(g)

# somas
flat = [json.loads(l) for l in open(os.path.join(OUT, 'quantitativos.jsonl'), encoding='utf-8')]
n_doc = 0
for f in glob.glob(os.path.join(OUT, '*', '*-R?.jsonld')):
    d = json.load(open(f))
    n_doc += len(d['quantidades']) + sum(len(e['quantidades']) for e in d['elementos'])
    for e in d['elementos']:
        for q in e['quantidades']:
            if q['grandeza'] == 'aco':
                soma = sum(l['massaKg'] for l in e['linhasDeArmadura'] if l['bitolaMm'] == q['bitolaMm'])
                if abs(soma - q['valor']) > 0.06: erros.append(f"{d['codigoArquivo']} {e['codigo']} φ{q['bitolaMm']}: Σ linhas {soma:.1f} ≠ {q['valor']}")
if n_doc != len(flat): erros.append(f'quantitativos.jsonl tem {len(flat)}, os documentos {n_doc}')
for f in glob.glob(os.path.join(OUT, '*', '[A-Z][A-Z][A-Z][0-9][0-9].jsonld')):
    u = json.load(open(f))
    por_el = sum(q['valor'] for e in u['elementos'] for q in e['quantidades'] if q['grandeza'] == 'aco')
    if abs(por_el - u['totais']['acoKgSomaDosElementos']) > 0.2: erros.append(f"{u['codigo']}: Σ elementos {por_el} ≠ totais")
print(docs, 'documentos;', triplas, 'triplas RDF;', len(flat), 'quantidades em quantitativos.jsonl;', len(erros), 'erros')
for e in erros[:30]: print(' ', e)
sys.exit(1 if erros else 0)
