"""A rodada do projeto: lê o que o extrator entregou e extrai cada prancha, primeiro por código, depois pela IA local.

    .venv/bin/python codigo/ciclo.py rodada     # o que o launchd roda a cada 5 min; sai sozinha (rodada_max_s)
    .venv/bin/python codigo/ciclo.py status     # só regrava saidas/status.json

Ordem (decisão do Caio de 26/09, que veio do extrator): todo o código antes (ler_prancha: é prancha?, carimbo,
família, eixo), depois a IA (ler_prancha_ia), uma prancha por vez na vez da GPU que o maestro dá (cliente_gpu.py,
prioridade 7: atrás dos documentos do extrator). Refaz sozinho a leitura feita com código anterior à versão que a
declara em `muda` (codigo/versoes.jsonl) e a de documento cujo conteúdo mudou. Falha volta na rodada seguinte até
`tentativas` vezes por versão do código. O andamento sai em saidas/status.json, no formato comum que o maestro lê.
"""
import fcntl
import json
import sys
import time
import traceback
from collections import Counter

import polars as pl

import cliente_gpu
import comum
import entrega
import prancha

TAREFAS = {'ler_prancha': 'prancha', 'ler_prancha_ia': 'prancha_ia'}  # tarefa → extrator da linha em prancha.parquet
FALHAS = comum.DADOS / 'falhas.jsonl'


def numero(versao):
    return tuple(map(int, versao.split('v')))


def vigentes():
    """Tarefa → a última versão que a declara em muda: leitura com código anterior a ela é refeita."""
    return {t: max((v['versao'] for v in comum.versoes() if t in v.get('muda', [])), key=numero, default='0v0') for t in TAREFAS}


def falhas_agora():
    """(id, versão do documento, tarefa) → quantas vezes falhou com o código desta versão."""
    if not FALHAS.exists():
        return Counter()
    versao = comum.codigo()['versao_codigo']
    return Counter((f['id'], f['versao'], f['tarefa']) for f in map(json.loads, FALHAS.read_text().splitlines())
                   if f['versao_codigo'] == versao)


def situacao(documentos):
    """Cada documento entregue em uma situação: codigo (falta o código), ia (prancha esperando a IA), feito (não é
    prancha, ou as duas leituras em dia) ou falhou (passou das tentativas com este código)."""
    tabela, VIGENTE = comum.ler('prancha'), vigentes()
    linhas = {} if tabela is None else {(l['id'], l['extrator']): l for l in tabela.to_dicts()}
    falhas, TENTATIVAS = falhas_agora(), comum.configuracao('operacao')['tentativas']
    em_dia = lambda d, extrator: (l := linhas.get((d['id'], extrator))) is not None and l['versao_documento'] == d['versao'] \
        and numero(l['versao_codigo']) >= numero(VIGENTE[next(t for t, e in TAREFAS.items() if e == extrator)])
    estados = {}
    for documento in documentos:
        if not em_dia(documento, 'prancha'):
            tarefa = 'ler_prancha'
        elif linhas[(documento['id'], 'prancha')]['e_prancha'] and not em_dia(documento, 'prancha_ia'):
            tarefa = 'ler_prancha_ia'
        else:
            estados[documento['id']] = 'feito'
            continue
        esgotou = falhas[(documento['id'], documento['versao'], tarefa)] >= TENTATIVAS
        estados[documento['id']] = 'falhou' if esgotou else 'codigo' if tarefa == 'ler_prancha' else 'ia'
    return estados


def executar(tarefa, documento, rodada):
    """Uma leitura; a falha fica em dados/falhas.jsonl com o erro e a rodada segue."""
    marca = time.perf_counter()
    try:
        getattr(prancha, tarefa)(documento, rodada)
        erro = ''
    except Exception as falha:
        erro = f'{type(falha).__name__}: {falha}'[:500]
        comum.anexar(FALHAS, json.dumps({'em': comum.agora(), 'id': documento['id'], 'versao': documento['versao'],
                                         'tarefa': tarefa, **comum.codigo(), 'erro': erro,
                                         'rastro': traceback.format_exc()[-1500:]}, ensure_ascii=False) + '\n')
    print(f"{time.strftime('%d/%m %H:%M:%S')}  {tarefa:<15} {documento['caminho'][-70:]:<70} "
          f"{time.perf_counter() - marca:6.1f} s {'FALHOU ' + erro[:80] if erro else ''}", flush=True)


def publicar(documentos):
    """pranchas.csv, prancha_leituras.csv e prancha_tabelas.csv: todas as obras em saida/_sistema/projeto/ e cada obra em
    saida/<acervo>/<obra>/projeto/ (ao lado de extrator/, revisor/ e contexto/). Só quando alguma tabela mudou desde a
    última publicação."""
    DRIVE, marca = comum.configuracao('operacao')['drive'], comum.DADOS / '.publicado'
    FAMILIAS = {'prancha': 'pranchas.csv', 'prancha_leitura': 'prancha_leituras.csv', 'prancha_tabela': 'prancha_tabelas.csv'}
    mudou = max(((comum.DADOS / f'{f}.parquet').stat().st_mtime for f in FAMILIAS if (comum.DADOS / f'{f}.parquet').exists()), default=0)
    if not mudou or (marca.exists() and marca.stat().st_mtime >= mudou):
        return
    marca.touch()
    obra_de = pl.DataFrame([{'id': d['id'], 'acervo_atual': d['acervo'], 'obra_atual': d['obra']} for d in documentos]
                           or {'id': [], 'acervo_atual': [], 'obra_atual': []}, schema={'id': pl.Utf8, 'acervo_atual': pl.Utf8, 'obra_atual': pl.Utf8})
    for familia, nome in FAMILIAS.items():
        tabela = comum.ler(familia)
        if tabela is None:
            continue
        tabela = tabela.join(obra_de, on='id', how='inner')  # a obra de agora: o Caio pode ter renomeado (obras.csv do extrator)
        comum.publicar(tabela.drop('acervo_atual', 'obra_atual'), f"{DRIVE['sistema']}/{nome}")
        for (acervo, obra), grupo in tabela.group_by('acervo_atual', 'obra_atual'):
            comum.publicar(grupo.drop('acervo_atual', 'obra_atual'), f"{acervo}/{obra}/{DRIVE['etapa']}/{nome}")


def status(documentos, ultima=None):
    """saidas/status.json no formato comum dos repositórios (o do revisor): o maestro o lê pelo cadastro."""
    estados = situacao(documentos)
    contagem = Counter(estados.values())
    tabela = comum.ler('prancha')
    ia = [] if tabela is None else tabela.filter(pl.col('extrator') == 'prancha_ia').to_dicts()
    pranchas = 0 if tabela is None else tabela.filter((pl.col('extrator') == 'prancha') & pl.col('e_prancha').fill_null(False)).height
    motivo = (f"{contagem['falhou']} leitura(s) falharam {comum.configuracao('operacao')['tentativas']} vezes com este código "
              '(dados/falhas.jsonl)') if contagem['falhou'] else '' if documentos else 'nada entregue pelo extrator ainda'
    comum.gravar_no_lugar(comum.SAIDAS / 'status.json', json.dumps({
        'repo': 'ialocal.projeto', 'versao': comum.codigo()['versao_codigo'], 'commit': comum.codigo()['commit'],
        'gerado_em': comum.agora(), 'saude': 'atenção' if motivo else 'ok', 'motivo': motivo, 'usa_gpu': True,
        'progresso': {'feito': contagem['feito'], 'total': len(documentos)},
        'fila': {'codigo': contagem['codigo'], 'ia': contagem['ia'], 'na_fila': contagem['codigo'] + contagem['ia'],
                 'falhou': contagem['falhou']},
        'pranchas': {'reconhecidas': pranchas, 'lidas_pela_ia': len(ia),
                     'conferencia': dict(Counter(l.get('conferencia') or 'sem' for l in ia))},
        'por_obra': por_obra(documentos, estados, tabela),
        'ultima_rodada': ultima, 'precisa_do_caio': []}, ensure_ascii=False, indent=1))


def por_obra(documentos, estados, tabela):
    """acervo/obra (a pasta da obra no extrator e no Drive) → candidatas feitas e o total, pranchas reconhecidas e os
    arquivos e bytes publicados em saidas/<acervo>/<obra>/projeto/: a tela 8 do maestro (ETAPAS DA OBRA) lê daqui."""
    reconhecidas = set() if tabela is None else set(tabela.filter((pl.col('extrator') == 'prancha') & pl.col('e_prancha').fill_null(False))['id'])
    obras = {}
    for documento in documentos:
        obra = obras.setdefault(f"{documento['acervo']}/{documento['obra']}", {'feito': 0, 'total': 0, 'pranchas': 0})
        obra['total'] += 1
        obra['feito'] += estados[documento['id']] == 'feito'
        obra['pranchas'] += documento['id'] in reconhecidas
    for chave, obra in obras.items():
        publicados = [a for a in (comum.SAIDAS / chave / comum.configuracao('operacao')['drive']['etapa']).glob('*.csv')]
        obra.update(arquivos=len(publicados), bytes=sum(a.stat().st_size for a in publicados))
    return obras


def rodada():
    """Código em todos os pendentes, depois a IA prancha a prancha na vez da GPU; publica a cada publicar_a_cada_s e no
    fim. Uma rodada por vez (trava em dados/rodada.lock): a de 5 min seguinte sai na hora se a anterior ainda roda."""
    OPERACAO = comum.configuracao('operacao')
    comum.DADOS.mkdir(parents=True, exist_ok=True)
    trava = open(comum.DADOS / 'rodada.lock', 'w')
    try:
        fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    inicio, publicado, rodada_em = time.monotonic(), time.monotonic(), comum.agora()
    feitas = Counter()
    documentos = entrega.documentos()

    def seguir():
        nonlocal publicado
        if time.monotonic() - publicado > OPERACAO['publicar_a_cada_s']:
            publicar(documentos)
            status(documentos, {'inicio': rodada_em, 'em_curso': True, **feitas})
            publicado = time.monotonic()
        return time.monotonic() - inicio < OPERACAO['rodada_max_s']

    estados = situacao(documentos)
    for documento in [d for d in documentos if estados[d['id']] == 'codigo']:
        if not seguir():
            break
        executar('ler_prancha', documento, rodada_em)
        feitas['codigo'] += 1
    estados = situacao(documentos)
    fila = [d for d in documentos if estados[d['id']] == 'ia']
    publicar(documentos)  # o código terminou: o maestro vê o andamento já, não só depois da espera pela vez e da primeira prancha
    status(documentos, {'inicio': rodada_em, 'em_curso': True, **feitas})
    publicado = time.monotonic()
    if fila and seguir():
        GPU = OPERACAO['gpu']
        print(f"{time.strftime('%d/%m %H:%M:%S')}  pedindo a vez da GPU ao maestro (prioridade {GPU['prioridade']}): "
              f"{len(fila)} pranchas para a IA", flush=True)
        with cliente_gpu.vez_da_gpu('ialocal.projeto', str(comum.DADOS / 'gpu'), GPU['prioridade'], GPU['modelo'], 'prancha') as vez:
            for documento in fila:
                if not vez.minha() or not seguir():  # alguém mais importante espera, ou a rodada acabou: a próxima pede de novo
                    break
                executar('ler_prancha_ia', documento, rodada_em)
                feitas['ia'] += 1
    publicar(documentos)
    status(documentos, {'inicio': rodada_em, 'fim': comum.agora(), **feitas})


if __name__ == '__main__':
    if sys.argv[1:2] == ['status']:
        status(entrega.documentos())
    else:
        rodada()
