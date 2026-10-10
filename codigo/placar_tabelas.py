"""Placar das tabelas de material contra um gabarito (0v38): linha a linha, campo a campo, e o tempo.

    .venv/bin/python codigo/placar_tabelas.py pasta <pasta_de_pdfs> [gabarito.csv]   # roda o ler_tabelas (sem gravar) e compara
    .venv/bin/python codigo/placar_tabelas.py ensaio foz_pbhi                         # compara o que o ensaio gravou

O gabarito (amostras/tabelas/211_foz_pbhi/gabarito.csv: 661 linhas da ETA Vila C) tem uma linha por item com
tabela_id, arquivo, item, codigo, descricao, quantidade, etapa1, etapa2, unidade. Cada tabela do gabarito é casada com
a tabela extraída do mesmo arquivo que mais divide (item, código) com ela; as linhas, pela ordem (difflib). No ensaio,
as duas saídas são medidas: a do glm-ocr em faixas (extrator prancha_ia) e a da grade (extrator tabelas) — o antes e o
depois na mesma execução. Resultado: saidas/placar_tabelas.csv (uma linha por execução × extrator) e o Drive.
"""
import csv
import difflib
import json
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import comum
import tabela

CAMPOS = ['item', 'codigo', 'quantidade', 'etapa1', 'etapa2', 'unidade']
ESSENCIAIS = ['codigo', 'quantidade', 'etapa1', 'etapa2', 'unidade']
GABARITO = comum.RAIZ / 'amostras' / 'tabelas' / '211_foz_pbhi' / 'gabarito.csv'


def chave_arquivo(nome):
    """O nome do PDF sem acento e sem caixa: 'INTERLIGAÇOES' no Drive e 'INTERLIGACOES' no gabarito são o mesmo."""
    return unicodedata.normalize('NFKD', Path(nome).name).encode('ascii', 'ignore').decode().upper()


def norm(campo, valor):
    v = (valor or '').strip()
    if campo in ('quantidade', 'etapa1', 'etapa2'):
        return ' / '.join(tabela.decimal(x.strip().replace(' ', '')) for x in v.split('/')) if v else ''
    if campo == 'unidade':
        return ' / '.join((tabela.unidade(x.strip()) or x.strip().lower()) for x in v.split(' / ')) if v else ''
    return v.replace(' ', '')


def descricao(v):
    v = unicodedata.normalize('NFKD', (v or '').replace(' / ', ' ')).encode('ascii', 'ignore').decode().upper()
    return re.sub(r'\s+', ' ', v).strip()


def chave(r):
    return norm('item', r.get('item')) + '|' + norm('codigo', r.get('codigo'))


def comparar(extraidas, gabarito):
    """Duas listas de linhas (dicts com os CAMPOS e descricao) da mesma tabela → contagens."""
    sm = difflib.SequenceMatcher(None, [chave(r) for r in extraidas], [chave(r) for r in gabarito], autojunk=False)
    pares, faltou, sobrou = [], 0, 0
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        n = min(a1 - a0, b1 - b0)
        pares += list(zip(extraidas[a0:a0 + n], gabarito[b0:b0 + n]))
        faltou += (b1 - b0) - n
        sobrou += (a1 - a0) - n
    campos = {c: [0, 0] for c in CAMPOS}
    certas = essenciais = 0
    semelhanca = 0.0
    erros = []
    for e, g in pares:
        for c in CAMPOS:
            if not norm(c, g.get(c)) and not norm(c, e.get(c)):
                continue
            ok = norm(c, e.get(c)) == norm(c, g.get(c))
            campos[c][0] += ok
            campos[c][1] += 1
            if not ok and len(erros) < 40:
                erros.append({'campo': c, 'lido': e.get(c, ''), 'certo': g.get(c, ''), 'item': g.get('item', ''), 'codigo': g.get('codigo', '')})
        certas += all(norm(c, e.get(c)) == norm(c, g.get(c)) for c in CAMPOS)
        essenciais += all(norm(c, e.get(c)) == norm(c, g.get(c)) for c in ESSENCIAIS)
        semelhanca += difflib.SequenceMatcher(None, descricao(e.get('descricao')), descricao(g.get('descricao'))).ratio()
    return {'linhas_gabarito': len(gabarito), 'linhas_extraidas': len(extraidas), 'faltou': faltou, 'sobrou': sobrou,
            'linhas_certas': certas, 'essenciais_certos': essenciais, 'descricao_semelhanca': semelhanca,
            'campos': campos, 'erros': erros}


def ler_gabarito(caminho=None):
    """{arquivo normalizado: {tabela_id: [linhas]}}."""
    saida = {}
    with open(caminho or GABARITO, encoding='utf-8-sig') as entrada:
        for linha in csv.DictReader(entrada, delimiter=';'):
            saida.setdefault(chave_arquivo(linha['arquivo']), {}).setdefault(linha['tabela_id'], []).append(linha)
    return saida


def casar(gabaritos, extraidas):
    """Cada tabela do gabarito ↔ a extraída do mesmo arquivo que mais divide (item, código); uma extraída só serve uma vez."""
    pares, usadas = [], set()
    candidatos = sorted(((len({chave(r) for r in g} & {chave(r) for r in e}), gid, eid)
                         for gid, g in gabaritos.items() for eid, e in extraidas.items()), reverse=True)
    casadas = {}
    for comuns, gid, eid in candidatos:
        if comuns and gid not in casadas and eid not in usadas:
            casadas[gid] = eid
            usadas.add(eid)
    for gid, g in gabaritos.items():
        pares.append((gid, g, extraidas.get(casadas.get(gid), [])))
    return pares


def somar(resultados):
    total = {'tabelas': len(resultados), 'linhas_gabarito': 0, 'linhas_extraidas': 0, 'faltou': 0, 'sobrou': 0, 'linhas_certas': 0,
             'essenciais_certos': 0, 'descricao_semelhanca': 0.0, 'campos': {c: [0, 0] for c in CAMPOS}}
    for r in resultados:
        for k in ('linhas_gabarito', 'linhas_extraidas', 'faltou', 'sobrou', 'linhas_certas', 'essenciais_certos', 'descricao_semelhanca'):
            total[k] += r[k]
        for c in CAMPOS:
            total['campos'][c][0] += r['campos'][c][0]
            total['campos'][c][1] += r['campos'][c][1]
    n = max(total['linhas_gabarito'], 1)
    total['descricao_semelhanca'] = round(total['descricao_semelhanca'] / n, 3)
    total['acerto_linhas'] = round(total['linhas_certas'] / n, 3)
    total['acerto_essencial'] = round(total['essenciais_certos'] / n, 3)
    total['campos'] = {c: round(a / b, 3) if b else None for c, (a, b) in total['campos'].items()}
    return total


def medir(extraidas_por_arquivo, gabarito):
    """{arquivo normalizado: {id da tabela: [linhas]}} × gabarito → (total, por tabela)."""
    por_tabela = []
    for arquivo, gabs in gabarito.items():
        if arquivo not in extraidas_por_arquivo:
            continue
        for gid, g, e in casar(gabs, extraidas_por_arquivo[arquivo]):
            por_tabela.append({'tabela_id': gid, **comparar(e, g)})
    return somar(por_tabela), por_tabela


# ---------------------------------------------------------------- de prancha_tabela (as duas saídas) para linhas
def itens_de_celulas(linhas):
    """As linhas de uma tabela em prancha_tabela (celulas em lista, a 1ª com DESCRI é o cabeçalho) → dicts com os CAMPOS:
    vale para a grade (cabeçalho canônico na linha 0) e para o glm-ocr (cabeçalho onde ele aparecer)."""
    celulas = [json.loads(l['celulas']) if isinstance(l.get('celulas'), str) else (l.get('celulas') or []) for l in linhas]
    cab, saida = None, []
    for cs in celulas:
        if not cs:
            continue
        campos = [tabela.campo_do_cabecalho(c) for c in cs]
        etapas = 0
        for i, c in enumerate(cs):
            if 'ETAPA' in tabela.sem_acento(c).replace(' ', ''):
                etapas += 1
                campos[i] = f'etapa{etapas}'
        if 'descricao' in campos:
            cab = campos
            continue
        if cab is None or len(cs) != len(cab):
            continue
        saida.append({c: v for c, v in zip(cab, cs) if c})
    return saida


def do_ensaio(nome, execucao=''):
    """O que o ensaio gravou em prancha_tabela (documentos _ensaios/<nome>/…), medido por extrator. Grava e publica."""
    import polars as pl
    regra_ = comum.configuracao('ensaios')['ensaios'][nome]
    gabarito = ler_gabarito(comum.RAIZ / regra_['gabarito'])
    lidas = comum.ler('prancha_tabela')
    if lidas is None:
        return {}
    lidas = lidas.filter(pl.col('id').str.starts_with(f'_ensaios/{nome}/'))
    resultado = {}
    for extrator in sorted(set(lidas['extrator'].to_list())):
        por_arquivo = {}
        grupos = {}
        for l in lidas.filter(pl.col('extrator') == extrator).to_dicts():
            if l.get('status') == 'vazia':
                continue
            grupos.setdefault((chave_arquivo(l['arquivo']), l['imagem']), []).append(l)
        for (arquivo, imagem), ls in grupos.items():
            ls.sort(key=lambda l: (l.get('faixa') or 0, l.get('linha') or 0))
            por_arquivo.setdefault(arquivo, {})[imagem] = itens_de_celulas(ls)
        total, por_tabela = medir(por_arquivo, gabarito)
        resultado[extrator] = total
        gravar([{'ensaio': nome, 'execucao': execucao, **comum.codigo(), 'extrator': extrator, **plano(total)}],
               por_tabela, nome, extrator)
    return resultado


def plano(total):
    """O total numa linha só (CSV)."""
    return {**{k: v for k, v in total.items() if k != 'campos'}, **{f'campo_{c}': v for c, v in total['campos'].items()}}


def gravar(linhas, por_tabela, nome, extrator):
    import polars as pl
    destino = comum.DADOS / 'placar_tabelas.parquet'
    novas = pl.DataFrame(linhas, infer_schema_length=None)
    tudo = pl.concat([pl.read_parquet(destino), novas], how='diagonal_relaxed') if destino.exists() else novas
    destino.parent.mkdir(parents=True, exist_ok=True)
    tudo.write_parquet(destino)
    detalhe = comum.DADOS / 'placar_tabelas' / f'{nome}_{extrator}.json'
    detalhe.parent.mkdir(parents=True, exist_ok=True)
    detalhe.write_text(json.dumps(por_tabela, ensure_ascii=False, indent=1))
    SISTEMA = comum.configuracao('operacao')['drive']['sistema']
    try:
        comum.publicar(tudo, f'{SISTEMA}/placar_tabelas.csv')
    except (OSError, subprocess.CalledProcessError) as falha:  # fora do mini, sem rclone: o CSV local basta
        print(f'Drive: placar_tabelas.csv não publicado ({type(falha).__name__})')


def da_pasta(pasta, gabarito=None):
    """Roda a leitura de produção (tabela.imagens/malhas/ler, sem gravar) nos PDFs da pasta e mede."""
    import pypdfium2 as pdfium
    gabarito = ler_gabarito(gabarito)
    por_arquivo, tempos = {}, {}
    _, ler_a = tabela.leitor_a()
    _, ler_b = tabela.leitor_b()
    for pdf in sorted(Path(pasta).glob('*.pdf')):
        if chave_arquivo(pdf.name) not in gabarito:
            continue
        marca = time.perf_counter()
        documento = pdfium.PdfDocument(pdf)
        pagina = documento[0]
        achadas = tabela.imagens(pagina)
        candidatas = [(f'i{n}', rgb) for n, _, rgb, _ in achadas if rgb is not None]
        candidatas += [(f'v{k}', rgb) for k, (_, rgb) in enumerate(tabela.malhas(pagina, [c for _, c, _, _ in achadas]))]
        for nome, rgb in candidatas:
            if tabela.e_tabela(rgb):
                lida = tabela.ler(rgb, ler_a, ler_b)
                if lida['itens']:
                    por_arquivo.setdefault(chave_arquivo(pdf.name), {})[nome] = lida['itens']
        documento.close()
        tempos[pdf.name] = round(time.perf_counter() - marca, 1)
        print(f'{pdf.name[:60]:60} {tempos[pdf.name]:6.1f} s', flush=True)
    total, por_tabela = medir(por_arquivo, gabarito)
    total['segundos'] = round(sum(tempos.values()), 1)
    return total, por_tabela, tempos


if __name__ == '__main__':
    if sys.argv[1] == 'pasta':
        total, por_tabela, tempos = da_pasta(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
        print(json.dumps(total, ensure_ascii=False, indent=1))
        if len(sys.argv) > 4:
            Path(sys.argv[4]).write_text(json.dumps({'total': total, 'tabelas': por_tabela, 'tempos': tempos}, ensure_ascii=False, indent=1))
    elif sys.argv[1] == 'ensaio':
        print(json.dumps(do_ensaio(sys.argv[2]), ensure_ascii=False, indent=1))
