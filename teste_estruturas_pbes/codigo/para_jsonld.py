"""CSV do extrator -> JSON-LD: obra -> estrutura -> unidade construtiva -> prancha -> elemento -> quantidade, com a evidência de cada número.

    python3 para_jsonld.py            # lê ../resultados e ../gabarito, escreve ../jsonld

Saídas (CSV continua sendo a fonte; o JSON-LD é a forma de entrega, a que o orçamento consome):
    jsonld/contexto.jsonld                       o @context (vocabulário civil:, termos fechados)
    jsonld/obra.jsonld                           a obra: estruturas, unidades, totais, cobertura, alertas
    jsonld/<estrutura>/<UNIDADE>.jsonld          a unidade construtiva: elementos somados entre folhas, totais, pranchas
    jsonld/<estrutura>/<codigo_arquivo>.jsonld   a prancha: tabelas, elementos, linhas de armadura, quantidades, evidências
    jsonld/quantitativos.jsonl                   uma quantidade por linha, com a chave para o orçamento
"""
import json, os, re, sys, unicodedata, datetime, collections
import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import conferir as C

RES = os.path.join(AQUI, '..', 'resultados')
OUT = os.path.join(AQUI, '..', 'jsonld')
C.SAIDA = RES
NS = 'https://ialocal.dev/civil/v1#'          # espaço de nomes provisório: troca no F0 do repositório novo
OBRA_ID = 'urn:ialocal:civil:eta-vila-c-foz-pbes'
OBRA = {'nome': 'ETA Vila C — Projeto Básico Estrutural (PBES)', 'localidade': 'Foz do Iguaçu - PR', 'contratante': 'SANEPAR',
        'fase': 'PBES', 'sistema': 'Sistema de Abastecimento de Água', 'ordemDeServico': '359534'}
EXTRATOR = {'nome': 'ialocal.projeto-civil', 'versao': '0.0.1-teste-pbes', 'leitores': ['tesseract 5.3.4 (psm 7, lista de caracteres por coluna)',
            'rapidocr_onnxruntime (texto e localização)', 'geometria: ialocal.projeto/codigo/tabela.py (sem alteração)']}
GRANDEZAS = {'concreto': 'm³', 'forma': 'm²', 'lastro': 'm³', 'enchimento': 'm³', 'aco': 'kg'}


def slug(t):
    t = unicodedata.normalize('NFKD', t or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', t).strip('-')


def n(x, casas=2):
    return None if x is None or (isinstance(x, float) and pd.isna(x)) else round(float(x), casas)


# ------------------------------------------------------------------ elementos
def elemento(nome):
    """'PAR3=PAR6 (X2)' -> codigo PAR3, equivalentes [PAR3, PAR6], multiplicidade 2, tipo parede. O OCR troca 1 por O: PAR1O -> PAR10."""
    bruto = (nome or '').strip()
    up = re.sub(r'(?<=\d)O|O(?=\d)', '0', bruto.upper())
    mult = re.search(r'\(?\s*X\s*(\d+)\s*\)?|\b(\d+)\s*X\b', up)
    ids = re.findall(r'\b(?:PAR|VA|VT|VE|V|PL|BL|P|LF|S)\s*\d+', up)
    ids = [re.sub(r'\s+', '', i) for i in ids]
    if ids:
        pref = ids[0].rstrip('0123456789')
        tipo = {'PAR': 'parede', 'V': 'viga', 'VA': 'viga', 'VT': 'viga', 'VE': 'viga', 'P': 'pilar', 'PL': 'pilar', 'BL': 'bloco', 'LF': 'laje', 'S': 'parede'}.get(pref, 'elemento')
        return {'codigo': ids[0], 'tipo': tipo, 'equivalentes': ids, 'multiplicidade': int(mult.group(1) or mult.group(2)) if mult else 1, 'nomeLido': bruto}
    tipo = 'laje' if 'LAJE' in up else 'bloco' if 'BLOCO' in up else 'escada' if 'ESCADA' in up else 'detalhe' if 'DETALHE' in up else 'grupo'
    cod = slug(re.sub(r'^ARMADURA\s+(D[AEO]S?)\s+', '', up)).upper() or 'SEM-NOME'
    if cod == 'CONJUNTO': tipo = 'conjunto'      # folha de caixa única: a tabela de armadura não tem título de elemento
    return {'codigo': cod, 'tipo': tipo, 'equivalentes': [cod], 'multiplicidade': 1, 'nomeLido': bruto}


def evid(prancha_id, tabela, caixas, estado, reparo=None, nivel=None):
    e = {'@type': 'Evidencia', 'prancha': {'@id': prancha_id}, 'tabela': tabela, 'caixaPt': caixas, 'estado': estado}
    if reparo: e['reparo'] = reparo
    if nivel: e['verificacao'] = nivel
    return e


def quant(grandeza, valor, unidade, evidencia, chave, **extra):
    q = {'@type': 'Quantidade', 'grandeza': grandeza, 'valor': valor, 'unidade': unidade, 'evidencia': evidencia, 'chaveOrcamento': chave}
    q.update({k: v for k, v in extra.items() if v is not None})
    return q


def prancha_doc(info, reg, g, arm, mat, aco, estrut_id, unid):
    est, cod = info['estrutura'], info['codigo_arquivo']
    pid = f"{OBRA_ID}:p:{cod}"
    caixas = collections.defaultdict(list)
    for c in info['caixas']: caixas[c['tipo']].append(c['caixa_pt'])
    consenso = reg.get('aco_consenso')
    nivel_aco = {'nivel': 'prancha', 'consenso': consenso, 'fontes': ['tabelas de armadura', 'RESUMO AÇO (linhas)', 'Peso Total impresso']} if consenso else None
    rev = re.search(r'-R(\d)$', cod).group(1)
    doc = {'@context': '../contexto.jsonld', '@id': pid, '@type': 'Prancha', 'codigoArquivo': cod, 'revisao': f'R{rev}',
           'tipo': reg['tipo'], 'folha': g['folha'] if g else None, 'conteudo': g.get('conteudo') if g else None,
           'estrutura': est, 'unidadeConstrutiva': {'@id': unid}, 'obra': {'@id': OBRA_ID}, 'pagina': 1,
           'extrator': EXTRATOR, 'segundos': info['segundos']}
    tabelas, quantidades, elementos = [], [], []
    for k, t in enumerate(info['caixas']):
        if t['tipo'] != 'outra':
            tabelas.append({'@type': 'Tabela', 'tipo': t['tipo'], 'caixaPt': t['caixa_pt'], 'ordem': k})
    doc['tabelas'] = tabelas
    chave = lambda *p: '/'.join([unid.rsplit(':', 1)[-1], *p])
    uc = unid.rsplit(':', 1)[-1]
    # ---- divisões (forma/concreto): a granularidade do projeto é a divisão (blocos, lajes, paredes, vigas, pilares), não a parede
    if not mat.empty:
        for _, r in mat.iterrows():
            nome = r['divisao'].strip()
            if not nome or r['tabela'] == '-1' or nome.upper().startswith('TOTAL'): continue
            qs = []
            if r['area_forma_m2'] != '': qs.append(quant('forma', n(C.f(r['area_forma_m2'])), 'm²', evid(pid, 'resumo_materiais', caixas['resumo_materiais'], 'lido'), chave(slug(nome), 'forma')))
            if r['volume_m3'] != '': qs.append(quant('concreto', n(C.f(r['volume_m3'])), 'm³', evid(pid, 'resumo_materiais', caixas['resumo_materiais'], 'lido'), chave(slug(nome), 'concreto')))
            if qs: elementos.append({'@id': f'{pid}:e:{slug(nome)}', '@type': 'Elemento', 'codigo': slug(nome).upper(), 'tipo': 'divisao', 'nomeLido': nome, 'quantidades': qs})
        for k in ('concreto', 'forma', 'lastro', 'enchimento'):
            v = reg.get(k + '_m3' if k != 'forma' else 'forma_m2')
            if v is not None and not pd.isna(v):
                ref = reg.get('resumo_' + (k + '_m3' if k != 'forma' else 'forma_m2'))
                estado = 'confirmado' if ref is not None and not pd.isna(ref) and abs(v - ref) <= C.TOL_VOL else ('lido' if ref is None or pd.isna(ref) else 'divergente')
                quantidades.append(quant(k, n(v), GRANDEZAS[k], evid(pid, 'resumo_materiais' if k in ('concreto', 'forma') else 'barra_' + k, caixas['resumo_materiais'], estado),
                                         chave('total', k), escopo='prancha', resumoGeral=n(ref) if ref is not None and not pd.isna(ref) else None))
    # ---- armadura: elementos com linhas, aço por bitola
    if not arm.empty:
        ok = arm[arm['valida_peso']]
        ordem = list(dict.fromkeys(zip(ok['sub_tabela'] if 'sub_tabela' in ok else [''] * len(ok), ok['elemento'])))
        for sub, nome in ordem:
            m = (ok['elemento'] == nome) & ((ok['sub_tabela'] == sub) if 'sub_tabela' in ok else True)
            sub_df = ok[m]
            el = elemento(nome)
            linhas = []
            for _, r in sub_df.iterrows():
                rep = r['reparo'] or None
                estado = 'suspeito' if (rep or '').startswith('SUSPEITO') else ('reparado' if rep else 'lido')
                linhas.append({'@type': 'LinhaArmadura', 'posicao': int(r['pos']), 'bitolaMm': n(r['bit_mm'], 1), 'classeAco': 'CA-60' if r['bit_mm'] == 5.0 else 'CA-50',
                               'quantidadeBarras': None if pd.isna(r['quant']) else int(r['quant']),
                               'comprimentoUnitarioCm': None if pd.isna(r['unit_cm']) else int(r['unit_cm']),
                               'comprimentoUnitarioTipo': 'numerico' if not pd.isna(r['unit_cm']) else ('corrida' if 'CORR' in r['unit_txt'].upper() else 'variavel'),
                               'comprimentoTotalCm': int(r['total_cm']), 'massaKg': n(r['peso_kg'], 3),
                               'posicaoLidaPeloOcr': r['pos_lida'] or None, 'posicaoReindexada': bool(r['pos_reindexada']),
                               'confereQuantXUnit': None if pd.isna(r['confere_quant_x_unit']) else bool(r['confere_quant_x_unit']),
                               'evidencia': evid(pid, 'armadura', caixas['armadura'], estado, rep)})
            qs = []
            for b, sb in sub_df.groupby('bit_mm'):
                qs.append(quant('aco', n(sb['peso_kg'].sum(), 1), 'kg', evid(pid, 'armadura', caixas['armadura'], 'lido', nivel=nivel_aco), chave(el['codigo'], 'aco', 'CA-60' if b == 5.0 else 'CA-50', f'{b:g}'),
                                classeAco='CA-60' if b == 5.0 else 'CA-50', bitolaMm=n(b, 1), comprimentoM=n(sb['comp_m'].sum(), 2), linhasDeArmadura=int(len(sb))))
            elementos.append({'@id': f"{pid}:e:{slug(el['codigo'])}-{sub if sub != '' else 0}", '@type': 'Elemento', **{k: v for k, v in el.items()},
                              'grupoDeTabela': None if sub == '' else int(sub), 'linhasDeArmadura': linhas, 'quantidades': qs,
                              'massaTotalKg': n(sum(q['valor'] for q in qs), 1)})
    doc['elementos'] = elementos
    # ---- aço total da prancha (consenso de 3 fontes)
    if reg.get('aco_adotado_kg') is not None and not pd.isna(reg['aco_adotado_kg']):
        ref = reg.get('resumo_aco_total_kg')
        ref = None if ref is None or pd.isna(ref) else float(ref)
        estado = 'sem_consenso' if consenso == 'sem consenso' else 'confirmado'
        quantidades.append(quant('aco', n(reg['aco_adotado_kg'], 0), 'kg', evid(pid, 'armadura+resumo_aco', caixas['armadura'] + caixas['resumo_aco'], estado, nivel=nivel_aco),
                                 chave('total', 'aco'), escopo='prancha', resumoGeral=ref,
                                 diferencaParaResumoKg=None if ref is None else n(reg['aco_adotado_kg'] - ref, 0)))
    doc['quantidades'] = quantidades
    alertas = []
    if reg['nota']: alertas.append({'@type': 'Alerta', 'classe': 'revisao', 'texto': reg['nota']})
    if 'ETL01FORMA' in cod: alertas.append({'@type': 'Alerta', 'classe': 'arquivo_diferente_da_linha', 'texto': 'estrutura metálica (RESUMO DO MATERIAL, ≈1404 kg); a linha de mesmo nome no resumo geral é de concreto'})
    for _, r in (arm[arm['reparo'].str.startswith('SUSPEITO')].iterrows() if not arm.empty else []):
        alertas.append({'@type': 'Alerta', 'classe': 'celula_suspeita', 'texto': f"{r['elemento']} pos {int(r['pos'])}: {r['reparo']}"})
    doc['alertas'] = alertas
    doc['conferenciaComResumoGeral'] = {'linhaNoResumo': g['ordem'] if g else None, 'aco': {'extraidoKg': n(reg.get('aco_adotado_kg'), 0), 'resumoGeralKg': n(reg.get('resumo_aco_total_kg'), 0),
                                        'somaDasTabelasKg': n(reg.get('aco_tabelas_kg'), 0), 'consenso': consenso}}
    return doc


def main():
    gab_rows = C.GAB['linhas']
    gab, gab_base = {}, {}
    for r in gab_rows:
        gab.setdefault(r['arquivo'], []).append(r); gab_base.setdefault(C.sem_revisao(r['arquivo']), []).append(r)
    conf = pd.read_csv(os.path.join(RES, 'consolidado', 'conferencia_por_prancha.csv'), sep=';')
    conf = {r['codigo_arquivo']: r.to_dict() for _, r in conf.iterrows()}
    os.makedirs(OUT, exist_ok=True)
    ctx = contexto()
    json.dump(ctx, open(os.path.join(OUT, 'contexto.jsonld'), 'w'), ensure_ascii=False, indent=1)
    por_unidade = collections.OrderedDict()
    flat = []
    import glob
    for pj in sorted(glob.glob(os.path.join(RES, '*', '*', 'prancha.json'))):
        info = json.load(open(pj)); est, cod = info['estrutura'], info['codigo_arquivo']
        reg = conf[cod]
        for k, v in list(reg.items()):
            if isinstance(v, float) and pd.isna(v): reg[k] = None
        g = None
        cands = gab.get(cod) or gab_base.get(C.sem_revisao(cod))
        if cands:
            rad = lambda t: {w[:7] for w in re.findall(r'[A-ZÇÃÕÉÊÁÍÓÚ]{5,}', (t or '').upper().replace('_', ' '))}
            g = cands[0] if len(cands) == 1 else max(cands, key=lambda l: len(rad(l.get('unidade_construtiva')) & rad(est)))
        m = re.search(r'0000([A-Z]{3})(\d{2,4})', cod)
        ucod = m.group(1) + m.group(2)[:2]
        unome = g['unidade_construtiva'] if g else est.replace('_', ' ').title()
        unid = f"{OBRA_ID}:u:{ucod}"
        arm = C.tratar_armadura(C.ler(est, cod, 'tabela_armadura'))
        mat, aco = C.ler(est, cod, 'resumo_materiais'), C.ler(est, cod, 'resumo_aco')
        doc = prancha_doc(info, reg, g, arm, mat, aco, f'{OBRA_ID}:s:{slug(est)}', unid)
        d = os.path.join(OUT, est); os.makedirs(d, exist_ok=True)
        json.dump(doc, open(os.path.join(d, cod + '.jsonld'), 'w'), ensure_ascii=False, indent=1)
        u = por_unidade.setdefault(unid, {'estrutura': est, 'codigo': ucod, 'nome': unome, 'nomeVemDe': 'relacao de desenhos' if g else 'pasta do Drive', 'pranchas': [], 'elem': collections.OrderedDict(), 'tot': collections.Counter()})
        u['pranchas'].append({'@id': doc['@id'], 'codigoArquivo': cod, 'folha': doc['folha'], 'tipo': doc['tipo']})
        for el in doc['elementos']:
            key = (el['tipo'], el['codigo'])
            slot = u['elem'].setdefault(key, {'tipo': el['tipo'], 'codigo': el['codigo'], 'equivalentes': el.get('equivalentes'), 'fontes': [], 'aco': collections.Counter(), 'forma': 0.0, 'concreto': 0.0})
            slot['fontes'].append({'@id': el['@id'], 'codigoArquivo': cod})
            for q in el['quantidades']:
                if q['grandeza'] == 'aco': slot['aco'][(q['classeAco'], q['bitolaMm'])] += q['valor']
                else: slot[q['grandeza']] += q['valor']
        for q in doc['quantidades']:
            if q['grandeza'] != 'aco' or q['escopo'] == 'prancha':
                u['tot'][q['grandeza']] += q['valor']
            flat.append({'@id': f"{doc['@id']}#{q['chaveOrcamento']}", 'obra': OBRA_ID, 'estrutura': est, 'unidadeConstrutiva': ucod, 'unidadeNome': unome, 'prancha': cod, 'folha': doc['folha'],
                         'elemento': None, 'grandeza': q['grandeza'], 'valor': q['valor'], 'unidade': q['unidade'], 'estado': q['evidencia']['estado'], 'chaveOrcamento': q['chaveOrcamento'], 'escopo': 'prancha'})
        for el in doc['elementos']:
            for q in el['quantidades']:
                flat.append({'@id': f"{el['@id']}#{q['chaveOrcamento']}", 'obra': OBRA_ID, 'estrutura': est, 'unidadeConstrutiva': ucod, 'unidadeNome': unome, 'prancha': cod, 'folha': doc['folha'],
                             'elemento': el['codigo'], 'elementoTipo': el['tipo'], 'grandeza': q['grandeza'], 'classeAco': q.get('classeAco'), 'bitolaMm': q.get('bitolaMm'), 'valor': q['valor'],
                             'unidade': q['unidade'], 'estado': q['evidencia']['estado'], 'verificacao': (q['evidencia'].get('verificacao') or {}).get('nivel'),
                             'chaveOrcamento': q['chaveOrcamento'], 'escopo': 'elemento'})
    # ---- unidades
    unidades_obra = []
    for unid, u in por_unidade.items():
        elems = []
        for (tipo, cod), e in u['elem'].items():
            qs = [quant('aco', n(v, 1), 'kg', {'@type': 'Evidencia', 'estado': 'somado_entre_folhas', 'prancha': [{'@id': f['@id'].rsplit(':e:', 1)[0]} for f in e['fontes']]},
                        f"{u['codigo']}/{cod}/aco/{cl}/{b:g}", classeAco=cl, bitolaMm=b) for (cl, b), v in sorted(e['aco'].items())]
            if e['forma']: qs.append(quant('forma', n(e['forma']), 'm²', {'@type': 'Evidencia', 'estado': 'somado_entre_folhas'}, f"{u['codigo']}/{cod}/forma"))
            if e['concreto']: qs.append(quant('concreto', n(e['concreto']), 'm³', {'@type': 'Evidencia', 'estado': 'somado_entre_folhas'}, f"{u['codigo']}/{cod}/concreto"))
            elems.append({'@id': f"{unid}:e:{slug(cod)}", '@type': 'Elemento', 'codigo': cod, 'tipo': tipo, 'equivalentes': e['equivalentes'], 'foiLidoEm': e['fontes'], 'quantidades': qs})
        aco_total = sum(q['valor'] for el in elems for q in el['quantidades'] if q['grandeza'] == 'aco')
        doc = {'@context': '../contexto.jsonld', '@id': unid, '@type': 'UnidadeConstrutiva', 'codigo': u['codigo'], 'nome': u['nome'], 'nomeVemDe': u['nomeVemDe'],
               'estrutura': u['estrutura'], 'obra': {'@id': OBRA_ID}, 'pranchas': u['pranchas'], 'elementos': elems,
               'totais': {'@type': 'Totais', 'concretoM3': n(u['tot']['concreto']), 'formaM2': n(u['tot']['forma']), 'lastroM3': n(u['tot']['lastro']), 'enchimentoM3': n(u['tot']['enchimento']),
                          'acoKgSomaDosElementos': n(aco_total, 1), 'acoKgPorPrancha': n(u['tot']['aco'], 0)}}
        json.dump(doc, open(os.path.join(OUT, u['estrutura'], u['codigo'] + '.jsonld'), 'w'), ensure_ascii=False, indent=1)
        unidades_obra.append({'@id': unid, 'codigo': u['codigo'], 'nome': u['nome'], 'estrutura': u['estrutura'], 'pranchas': len(u['pranchas']), 'totais': doc['totais']})
    cob = pd.read_csv(os.path.join(RES, 'consolidado', 'cobertura_resumo_x_pasta.csv'), sep=';')
    cobv = cob['pdf_na_pasta'].str.replace(r' \(sem linha.*', '', regex=True).value_counts().to_dict()
    obra = {'@context': 'contexto.jsonld', '@id': OBRA_ID, '@type': 'Obra', **OBRA, 'geradoEm': datetime.date(2026, 10, 10).isoformat(), 'extrator': EXTRATOR,
            'unidades': unidades_obra,
            'cobertura': {'@type': 'Cobertura', 'linhasNoResumoGeral': len(gab_rows), 'pdfsNaPasta': int(len(conf)), 'comPdfExato': cobv.get('sim', 0), 'comPdfOutraRevisao': cobv.get('sim (outra revisão)', 0),
                          'semPdfNaPasta': cobv.get('não', 0), 'pdfsSemLinhaNoResumo': int(cob['pdf_na_pasta'].str.contains('sem linha').sum())},
            'alertas': [{'@type': 'Alerta', 'classe': 'arquivo_diferente_da_linha', 'texto': 'REFORMA_EDIFIC_LODO/…ETL01FORMA-R0 é estrutura metálica; a linha do resumo geral de mesmo nome é de concreto'},
                        {'@type': 'Alerta', 'classe': 'nome_duplicado_no_resumo', 'texto': 'CXA01 e CXA02 aparecem duas vezes no resumo geral, em unidades construtivas diferentes'},
                        {'@type': 'Alerta', 'classe': 'revisao', 'texto': 'MOD01 001 e 008: PDF em R1, resumo geral em R0'}]}
    json.dump(obra, open(os.path.join(OUT, 'obra.jsonld'), 'w'), ensure_ascii=False, indent=1)
    with open(os.path.join(OUT, 'quantitativos.jsonl'), 'w', encoding='utf-8') as f:
        for r in flat: f.write(json.dumps({k: v for k, v in r.items() if v is not None}, ensure_ascii=False) + '\n')
    print(len(flat), 'quantidades;', len(por_unidade), 'unidades;', len(conf), 'pranchas')


def contexto():
    t = lambda nome, **kw: {'@id': 'civil:' + nome, **kw}
    c = {'@version': 1.1, 'civil': NS, 'xsd': 'http://www.w3.org/2001/XMLSchema#', 'prov': 'http://www.w3.org/ns/prov#', 'schema': 'https://schema.org/',
         'Obra': 'civil:Obra', 'UnidadeConstrutiva': 'civil:UnidadeConstrutiva', 'Prancha': 'civil:Prancha', 'Tabela': 'civil:Tabela', 'Elemento': 'civil:Elemento',
         'LinhaArmadura': 'civil:LinhaArmadura', 'Quantidade': 'civil:Quantidade', 'Evidencia': 'prov:Entity', 'Alerta': 'civil:Alerta', 'Cobertura': 'civil:Cobertura',
         'Totais': 'civil:Totais'}
    for nome in ('nome', 'localidade', 'contratante', 'fase', 'sistema', 'ordemDeServico', 'geradoEm', 'codigo', 'nomeVemDe', 'estrutura', 'codigoArquivo', 'revisao', 'tipo', 'folha',
                 'conteudo', 'pagina', 'segundos', 'nomeLido', 'multiplicidade', 'grupoDeTabela', 'posicao', 'classeAco', 'comprimentoUnitarioTipo', 'posicaoLidaPeloOcr',
                 'grandeza', 'unidade', 'chaveOrcamento', 'escopo', 'estado', 'reparo', 'texto', 'classe', 'consenso', 'nivel', 'versao', 'leitores', 'equivalentes', 'tabela'):
        c[nome] = 'civil:' + nome
    for nome in ('valor', 'bitolaMm', 'quantidadeBarras', 'comprimentoUnitarioCm', 'comprimentoTotalCm', 'massaKg', 'massaTotalKg', 'comprimentoM', 'resumoGeral', 'diferencaParaResumoKg',
                 'concretoM3', 'formaM2', 'lastroM3', 'enchimentoM3', 'acoKgSomaDosElementos', 'acoKgPorPrancha', 'linhasDeArmadura', 'linhaNoResumo', 'extraidoKg', 'resumoGeralKg',
                 'somaDasTabelasKg', 'linhasNoResumoGeral', 'pdfsNaPasta', 'comPdfExato', 'comPdfOutraRevisao', 'semPdfNaPasta', 'pdfsSemLinhaNoResumo', 'ordem'):
        c[nome] = {'@id': 'civil:' + nome, '@type': 'xsd:decimal' if nome in ('valor', 'massaKg', 'massaTotalKg', 'comprimentoM', 'resumoGeral', 'diferencaParaResumoKg', 'concretoM3', 'formaM2', 'lastroM3', 'enchimentoM3', 'acoKgSomaDosElementos', 'acoKgPorPrancha', 'bitolaMm', 'extraidoKg', 'resumoGeralKg', 'somaDasTabelasKg') else 'xsd:integer'}
    for nome in ('posicaoReindexada', 'confereQuantXUnit'):
        c[nome] = {'@id': 'civil:' + nome, '@type': 'xsd:boolean'}
    c['caixaPt'] = {'@id': 'civil:caixaPt', '@type': '@json'}
    for nome, alvo in (('obra', 'civil:daObra'), ('unidadeConstrutiva', 'civil:daUnidadeConstrutiva'), ('prancha', 'prov:wasDerivedFrom'), ('foiLidoEm', 'prov:wasDerivedFrom')):
        c[nome] = {'@id': alvo, '@type': '@id'}
    for nome, alvo in (('unidades', 'civil:temUnidade'), ('pranchas', 'civil:temPrancha'), ('tabelas', 'civil:temTabela'), ('elementos', 'civil:temElemento'),
                       ('linhasDeArmadura', 'civil:temLinhaDeArmadura'), ('quantidades', 'civil:temQuantidade'), ('alertas', 'civil:temAlerta')):
        c[nome] = {'@id': alvo, '@container': '@set'}
    c['evidencia'] = 'prov:wasGeneratedBy'
    for nome in ('extrator', 'cobertura', 'totais', 'conferenciaComResumoGeral', 'aco', 'verificacao'):
        c[nome] = 'civil:' + nome
    c['fontes'] = 'civil:fontes'
    return {'@context': c}


if __name__ == '__main__':
    main()
