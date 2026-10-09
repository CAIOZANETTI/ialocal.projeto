"""O catálogo das referências do orçamento e a conferência das tabelas de projeto: cada linha (código, descrição,
unidade) de uma tabela de prancha — "3875 | CURVA FD JE 2GS BB 90 DN150 | pç" — é procurada no catálogo único das bases
(Padrão GEL, SINAPI, SICRO, Sanepar, Sienge, equipamentos) que o ialocal.orcamento monta.

O conhecimento vem do ialocal.orcamento (desde a 0v35): lá o engenheiro edita os dicionários (padrões de texto, abreviaturas,
sinônimos, palavras vazias, unidades, etiquetas técnicas) e o servidor monta o catálogo; aqui chegam a cópia do
dicionário em conceitos/catalogo.json (pelo git, é público) e o catalogo.parquet em dados/catalogo/ (fora do git: tem
os preços de compra da GEL e de licitação, que mudam a cada versão das bases). A conta é a mesma de lá (motor/catalogo.py, motor 0.15.0): 1º pelo código,
com a descrição confirmando; 2º pela descrição normalizada, pela unidade (mesma grandeza) e pelas etiquetas fortes
(DN, PN, fck, material, junta, classe).

    .venv/bin/python codigo/catalogo.py instalar ~/Downloads/catalogo_gel_2026-10-09.zip   # o zip de Referências › Conferir lista
    .venv/bin/python codigo/catalogo.py conferir tabela.csv     # código;descrição;unidade (; , ou tabulação) → tabela_conferida.csv
    .venv/bin/python codigo/catalogo.py normalizar "Reg. gaveta FºFº DN 150"
    .venv/bin/python codigo/catalogo.py dicionario <conceitos.json do orçamento ou o zip>   # atualiza conceitos/catalogo.json (por PR)
"""
import csv
import functools
import json
import math
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

import comum

RAIZ = Path(__file__).resolve().parent.parent
DICIONARIO = RAIZ / 'conceitos' / 'catalogo.json'
SITUACOES = ('código confere', 'pela descrição', 'revisar', 'código diverge', 'não achado')


@functools.cache
def dic():
    return json.loads(DICIONARIO.read_text())


def _cat():
    return dic()['catalogo']


# ---------------------------------------------------------------- unidades (unidades_medida.yaml do orçamento)
def _grafia(u):
    """NFKD (m² vira m2, pç vira pc), sem acento, minúscula, sem espaço, sem o ponto final (UN. = UN)."""
    return unicodedata.normalize('NFKD', str(u or '')).encode('ascii', 'ignore').decode().lower().replace(' ', '').rstrip('.')


@functools.cache
def _sinonimos_unid():
    return {_grafia(k): v for k, v in dic()['unidades_medida']['sinonimos'].items()}


def unidade(u):
    """{codigo, simbolo, grandeza, base, fator, conhecida}: "M3", "m³" e "m3" dão m3; "pç", "UN." e "PC" dão un."""
    g = _grafia(u)
    c = _sinonimos_unid().get(g, g)
    x = dic()['unidades_medida']['canonicas'].get(c)
    if not x:
        return {'codigo': c, 'simbolo': c, 'grandeza': 'desconhecida', 'base': c, 'fator': 1, 'conhecida': False}
    return {'codigo': c, 'simbolo': x[0], 'grandeza': x[2], 'base': x[3], 'fator': x[4], 'conhecida': True}


# ---------------------------------------------------------------- etiquetas técnicas (tags_tecnicas.yaml do orçamento)
def etiquetas(texto):
    """DN, PN, DE, fck, material, junta, classe, vazão, altura… da descrição: o primeiro padrão que casa vale; "se" exige
    outra expressão no texto e "senao" a proíbe; "ordem: texto" pega o que aparece primeiro (o material do item)."""
    t = unicodedata.normalize('NFD', str(texto or '')).encode('ascii', 'ignore').decode().upper()
    tags = {}
    for tg in dic()['tags_tecnicas']:
        achados = [(pd, m) for pd in tg['padroes'] if (m := re.search(pd['re'], t))
                   and ('se' not in pd or re.search(pd['se'], t)) and ('senao' not in pd or not re.search(pd['senao'], t))]
        if tg.get('ordem') == 'texto':
            achados.sort(key=lambda x: x[1].start())
        for pd, m in achados[:1]:
            if 'valor' in pd:
                tags[tg['k']] = pd['valor']
            elif 'formato' in pd:
                tags[tg['k']] = pd['formato'].replace('{}', m.group(1))
            else:
                v = float(m.group(1).replace(',', '.')) * pd.get('fator', 1)
                tags[tg['k']] = int(v) if v == int(v) else round(v, 2)
    return tags


# ---------------------------------------------------------------- texto (catalogo.yaml do orçamento)
def _maiusculas(texto):
    t = re.sub('[ØøΦφ]', ' DIAMETRO ', str(texto or ''))
    return unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode().upper()


def _palavras(t):
    return re.findall(r'\d+(?:[./]\d+)*[A-Z0-9]*|[A-Z0-9]+', t)


@functools.cache
def _padroes():
    return [(re.compile(p['re']), p['por']) for p in _cat()['padroes_texto']]


def _sem_sinonimo(texto):
    t = _maiusculas(texto)
    for rx, por in _padroes():
        t = rx.sub(por, t)
    ab = _cat()['abreviaturas']
    return ' '.join(ab.get(w, w) for w in _palavras(t))


@functools.cache
def _sinonimos():
    mapa = {}
    for canon, grafias in _cat()['sinonimos'].items():
        c = _sem_sinonimo(canon)
        for g in [canon, *grafias]:
            mapa.setdefault(_sem_sinonimo(g), c)
    alt = '|'.join(re.escape(g) for g in sorted(mapa, key=len, reverse=True))
    return re.compile(rf'(?<![A-Z0-9./])(?:{alt})(?![A-Z0-9./])'), mapa


def normalizar(texto):
    """A forma comparável: "Reg. gaveta FºFº DN 150" e "REGISTRO DE GAVETA, FERRO FUNDIDO DUCTIL, DN150" dão
    "REGISTRO GAVETA FERRO FUNDIDO DUCTIL DN150". Só compara: o texto original não muda."""
    rx, mapa = _sinonimos()
    vazias = set(_cat()['palavras_vazias'])
    return ' '.join(w for w in rx.sub(lambda m: mapa[m.group(0)], _sem_sinonimo(texto)).split() if w not in vazias)


# ---------------------------------------------------------------- índice e conferência
def _chave_codigo(c):
    c = re.sub(r'\s+', '', str(c or '')).upper()
    return c.lstrip('0') or c


def indexar(linhas):
    """Linhas do catalogo.parquet → o peso de cada palavra (raridade), as linhas por palavra e por código."""
    por_palavra, por_codigo = {}, {}
    for i, ln in enumerate(linhas):
        if isinstance(ln.get('tags'), str):
            ln['tags'] = json.loads(ln['tags'] or '{}')
        ln.setdefault('forma', normalizar(ln.get('desc')))
        for w in set(ln['forma'].split()):
            por_palavra.setdefault(w, []).append(i)
        if ln.get('codigo'):
            por_codigo.setdefault(_chave_codigo(ln['codigo']), []).append(i)
    n = max(len(linhas), 1)
    return {'linhas': linhas, 'peso': {w: math.log(1 + n / len(ids)) for w, ids in por_palavra.items()},
            'por_palavra': por_palavra, 'por_codigo': por_codigo, 'peso_novo': math.log(1 + n)}


def _semelhanca(a, b, idx):
    pa, pb = set(a.split()), set(b.split())
    if not pa or not pb:
        return 0.0
    p = lambda ws: sum(idx['peso'].get(w, idx['peso_novo']) for w in ws)
    comum = p(pa & pb)
    return 0.5 * comum / p(pa) + 0.5 * 2 * comum / (p(pa) + p(pb))


def _nota_unidade(u_proj, ln):
    if not u_proj or not ln.get('unid_cod'):
        return 0.5, None
    a = unidade(u_proj)
    if a['codigo'] == ln['unid_cod']:
        return 1.0, ('ok', f"unidade {a['simbolo']}")
    if a['conhecida'] and a['base'] == unidade(ln['unid_cod'])['base']:
        return 0.7, ('aviso', f"unidade {ln.get('unid_simbolo')} (converte de {a['simbolo']})")
    return 0.0, ('erro', f"unidade {ln.get('unid_simbolo') or ln.get('unid')} ≠ {a['simbolo']}")


def _nota_etiquetas(t_proj, t_cand):
    comuns = [k for k in _cat()['conferencia']['etiquetas_fortes'] if k in t_proj and k in t_cand]
    if not comuns:
        return 0.5, []
    igual = lambda x, y: abs(x - y) <= 0.01 * max(abs(x), abs(y), 1) if isinstance(x, (int, float)) and isinstance(y, (int, float)) else x == y
    dif = [k for k in comuns if not igual(t_proj[k], t_cand[k])]
    return (0.0 if dif else 1.0), [('erro', f'{k} {t_cand[k]} ≠ {t_proj[k]}') for k in dif] + [('ok', f'{k} {t_proj[k]}') for k in comuns if k not in dif]


def pontuar(item, ln, idx):
    """Nota 0 a 1 de uma linha do catálogo para o item {codigo, descricao, unidade}, com os motivos."""
    pesos = _cat()['conferencia']
    tx = _semelhanca(item['_forma'], ln['forma'], idx)
    un, mu = _nota_unidade(item.get('unidade'), ln)
    et, me = _nota_etiquetas(item['_tags'], ln.get('tags') or {})
    nota = pesos['peso_texto'] * tx + pesos['peso_unidade'] * un + pesos['peso_etiquetas'] * et
    motivos = [('ok' if tx >= 0.8 else 'aviso' if tx >= 0.5 else 'erro', f'descrição {round(tx * 100)}% semelhante'), *([mu] if mu else []), *me]
    return {**{k: ln.get(k) for k in ('fonte', 'tipo', 'codigo', 'desc', 'unid', 'preco', 'preco_des', 'ref')},
            'nota': round(nota, 3), 'texto': round(tx, 3), 'motivos': [{'nivel': a, 'texto': b} for a, b in motivos]}


def _por_texto(forma, idx, limite=400):
    soma = {}
    for w in sorted(set(forma.split()), key=lambda w: -idx['peso'].get(w, 0))[:8]:
        ids = idx['por_palavra'].get(w, [])
        if len(ids) <= 20000:  # palavra comum demais não separa candidatos
            for i in ids:
                soma[i] = soma.get(i, 0) + idx['peso'][w]
    return sorted(soma, key=lambda i: -soma[i])[:limite]


def conferir_item(item, idx, fonte=None):
    """{codigo, descricao, unidade} → {situacao, melhor, candidatos}; situações em SITUACOES."""
    cf = _cat()['conferencia']
    item = {**item, '_forma': normalizar(item.get('descricao')), '_tags': etiquetas(item.get('descricao'))}
    fonte = (fonte or item.get('fonte') or '').lower() or None
    da_fonte = lambda i: not fonte or idx['linhas'][i].get('fonte') == fonte
    por_cod = [i for i in idx['por_codigo'].get(_chave_codigo(item.get('codigo')), []) if da_fonte(i)] if item.get('codigo') else []
    cod = sorted((pontuar(item, idx['linhas'][i], idx) for i in por_cod), key=lambda c: -c['nota'])
    if cod and (not item['_forma'] or cod[0]['nota'] >= cf['revisar']):
        return {'situacao': 'código confere', 'melhor': cod[0], 'candidatos': cod[:cf['candidatos']]}
    txt = sorted((pontuar(item, idx['linhas'][i], idx) for i in _por_texto(item['_forma'], idx) if da_fonte(i)),
                 key=lambda c: (-c['nota'], len(c['desc'] or '')))[:cf['candidatos']]
    if cod:
        return {'situacao': 'código diverge', 'melhor': cod[0], 'candidatos': cod[:2] + txt}
    if not txt or txt[0]['nota'] < cf['revisar']:
        return {'situacao': 'não achado', 'melhor': None, 'candidatos': txt}
    return {'situacao': 'pela descrição' if txt[0]['nota'] >= cf['aceita'] else 'revisar', 'melhor': txt[0], 'candidatos': txt}


def conferir(itens, idx, fonte=None):
    out = [{**conferir_item(it, idx, fonte), 'linha': n + 1, **{k: it.get(k, '') for k in ('codigo', 'descricao', 'unidade')}}
           for n, it in enumerate(itens)]
    return {'itens': out, 'resumo': {s: sum(x['situacao'] == s for x in out) for s in SITUACOES if any(x['situacao'] == s for x in out)}}


# ---------------------------------------------------------------- tabelas de prancha: qual coluna é o quê
COLUNAS = {'codigo': r'^(COD|ESPECIF|SEQ|N.? ?ESTOQUE|ITEM SAM|SAM)', 'descricao': r'^(DESCRI|DISCRIMINA|ESPECIFICACAO|MATERIA)',
           'unidade': r'^(UN|UND|UNID)\b'}


def colunas_da_tabela(cabecalho):
    """O índice das colunas código, descrição e unidade pelo cabeçalho ("ESPECIF/COD SAM", "DISCRIMINAÇÃO", "UND."); None
    para a que não tem rótulo conhecido."""
    rot = [_maiusculas(c).strip() for c in cabecalho]
    return {k: next((i for i, c in enumerate(rot) if re.search(rx, c)), None) for k, rx in COLUNAS.items()}


def itens_da_tabela(linhas):
    """Linhas de células (a primeira é o cabeçalho) → itens {codigo, descricao, unidade}; sem cabeçalho reconhecido,
    nenhum item (a tabela não é lista de material)."""
    if not linhas:
        return []
    col = colunas_da_tabela(linhas[0])
    if col['descricao'] is None:
        return []
    pega = lambda c, k: c[col[k]].strip() if col[k] is not None and col[k] < len(c) else ''
    return [{'codigo': pega(c, 'codigo'), 'descricao': pega(c, 'descricao'), 'unidade': pega(c, 'unidade')}
            for c in linhas[1:] if pega(c, 'descricao')]


def conferir_tabelas(linhas_tabela, idx):
    """As linhas de prancha_tabela (id, imagem, faixa, linha, celulas, status) → uma linha por item de lista de material:
    cada imagem é uma tabela; o cabeçalho é a primeira linha em que se reconhece a coluna de descrição (a linha do
    título, "RETORNO LODO EEE FLOTOFILTRO", fica antes dele); tabela sem cabeçalho de lista não entra."""
    grupos = {}
    for l in linhas_tabela:
        if l.get('status') != 'vazia':
            grupos.setdefault((l.get('id'), l.get('imagem')), []).append(l)
    saida = []
    for (doc, imagem), ls in grupos.items():
        celulas = [json.loads(l['celulas']) if isinstance(l.get('celulas'), str) else (l.get('celulas') or [])
                   for l in sorted(ls, key=lambda l: (l.get('faixa') or 0, l.get('linha') or 0))]
        inicio = next((i for i, c in enumerate(celulas) if colunas_da_tabela(c)['descricao'] is not None), None)
        itens = itens_da_tabela(celulas[inicio:]) if inicio is not None else []
        for x in conferir(itens, idx)['itens']:
            m = x['melhor'] or {}
            saida.append({'id': doc, 'imagem': imagem, 'linha': x['linha'], 'codigo': x['codigo'], 'descricao': x['descricao'],
                          'unidade': x['unidade'], 'situacao': x['situacao'], 'fonte': m.get('fonte'), 'codigo_ref': m.get('codigo'),
                          'descricao_ref': m.get('desc'), 'unidade_ref': m.get('unid'), 'preco': m.get('preco'), 'nota': m.get('nota'),
                          'motivos': ' · '.join(i['texto'] for i in m.get('motivos', []))})
    return saida


# ---------------------------------------------------------------- o catálogo em dados/catalogo
def pasta():
    return comum.DADOS / 'catalogo'


def instalar(zip_):
    """O zip do orçamento (Referências › Conferir lista › Baixar catálogo) → dados/catalogo/ (catalogo.parquet, os
    dicionários em Parquet e o meta.json). Avisa quando o dicionário do zip é outro que o de conceitos/catalogo.json."""
    pasta().mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_) as z:
        for nome in z.namelist():
            if nome.endswith('.parquet') or nome == 'meta.json':
                (pasta() / nome).write_bytes(z.read(nome))
        lido = json.loads(z.read('motor/conceitos.json')) if 'motor/conceitos.json' in z.namelist() else None
    meta = json.loads((pasta() / 'meta.json').read_text()) if (pasta() / 'meta.json').exists() else {}
    if lido and lido.get('catalogo') != _cat():
        print('atenção: o dicionário do zip é outro que conferir conceitos/catalogo.json — rodar: codigo/catalogo.py dicionario', zip_)
    carregar.cache_clear()
    return meta


@functools.cache
def carregar():
    """O índice do dados/catalogo/catalogo.parquet; None quando o catálogo não foi instalado."""
    arq = pasta() / 'catalogo.parquet'
    if not arq.exists():
        return None
    import polars as pl

    return indexar(pl.read_parquet(arq).to_dicts())


def dicionario(origem):
    """conceitos/catalogo.json a partir do conceitos.json do orçamento (o arquivo ou o zip do catálogo, que o leva)."""
    origem = Path(origem)
    if origem.suffix == '.zip':
        with zipfile.ZipFile(origem) as z:
            c = json.loads(z.read('motor/conceitos.json'))
            meta = json.loads(z.read('meta.json')) if 'meta.json' in z.namelist() else {}
    else:
        c, meta = json.loads(origem.read_text()), {}
    anterior = json.loads(DICIONARIO.read_text()) if DICIONARIO.exists() else {}
    novo = {'_o_que': anterior.get('_o_que', ''),
            'origem': {'repositorio': 'CAIOZANETTI/ialocal.orcamento', 'catalogo': meta.get('assinatura'),
                       'arquivos': {k: v for k, v in c['origem'].items() if k in ('catalogo.yaml', 'unidades_medida.yaml', 'tags_tecnicas.yaml', 'busca_composicoes.yaml')}},
            'catalogo': c['catalogo'], 'unidades_medida': c['unidades_medida'], 'tags_tecnicas': c['tags_tecnicas'],
            'grupos_servico': c['busca_composicoes']['termos']}
    DICIONARIO.write_text(json.dumps(novo, ensure_ascii=False, indent=1) + '\n')
    dic.cache_clear()
    return novo


def _ler_csv(arq):
    texto = Path(arq).read_text(encoding='utf-8-sig')
    primeira = texto.splitlines()[0] if texto.strip() else ''
    sep = '\t' if '\t' in primeira else ';' if primeira.count(';') >= primeira.count(',') else ','
    return [r for r in csv.reader(texto.splitlines(), delimiter=sep) if any(c.strip() for c in r)]


def conferir_csv(arq, idx=None):
    """A tabela (com cabeçalho) → <nome>_conferida.csv ao lado; devolve o resumo."""
    idx = idx or carregar()
    if idx is None:
        raise SystemExit('catálogo não instalado: codigo/catalogo.py instalar <zip do orçamento>')
    itens = itens_da_tabela(_ler_csv(arq))
    r = conferir(itens, idx)
    saida = Path(arq).with_name(Path(arq).stem + '_conferida.csv')
    with open(saida, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['linha', 'codigo', 'descricao', 'unidade', 'situacao', 'fonte', 'codigo_ref', 'descricao_ref', 'unidade_ref', 'preco', 'nota', 'motivos'])
        for x in r['itens']:
            m = x['melhor'] or {}
            w.writerow([x['linha'], x['codigo'], x['descricao'], x['unidade'], x['situacao'], m.get('fonte'), m.get('codigo'), m.get('desc'),
                        m.get('unid'), m.get('preco'), m.get('nota'), ' · '.join(i['texto'] for i in m.get('motivos', []))])
    return r['resumo'], saida


if __name__ == '__main__':
    comando, *args = sys.argv[1:] or ['ajuda']
    if comando == 'instalar':
        print(json.dumps(instalar(args[0]), ensure_ascii=False))
    elif comando == 'conferir':
        resumo, saida = conferir_csv(args[0])
        print(json.dumps(resumo, ensure_ascii=False), '→', saida)
    elif comando == 'normalizar':
        print(normalizar(' '.join(args)), json.dumps(etiquetas(' '.join(args)), ensure_ascii=False))
    elif comando == 'dicionario':
        print(json.dumps(dicionario(args[0])['origem'], ensure_ascii=False))
    else:
        print(__doc__)
