"""A rodada do projeto: lê o que o extrator entregou e extrai cada prancha, primeiro por código, depois pela IA local.

    .venv/bin/python codigo/ciclo.py rodada     # o que o launchd roda a cada 5 min; sai sozinha (rodada_max_s)
    .venv/bin/python codigo/ciclo.py status     # só regrava saidas/status.json

Ordem (decisão do Caio de 26/09, que veio do extrator): todo o código antes (ler_prancha: é prancha ou boletim?,
camada, carimbo, família, eixo; ler_sondagem: as páginas com texto do boletim), depois a IA (ler_sondagem_ia nas
páginas digitalizadas do boletim, ler_prancha_ia), um documento por vez na vez da GPU que o maestro dá (cliente_gpu.py,
prioridade 7: atrás dos documentos do extrator). Refaz sozinho a leitura feita com código anterior à versão que a
declara em `muda` (codigo/versoes.jsonl) e a de documento cujo conteúdo mudou. Falha volta na rodada seguinte até
`tentativas` vezes por versão do código. O andamento sai em saidas/status.json, no formato comum que o maestro lê.
"""
import fcntl
import json
import os
import sys
import time
import traceback
from collections import Counter

import polars as pl

import cliente_gpu
import comum
import entrega
import pedido
import prancha
import rastro
import respostas
import sondagem
import tabela

TAREFAS = {'ler_prancha': ('prancha', 'prancha'), 'ler_prancha_ia': ('prancha', 'prancha_ia'),  # tarefa → (família, extrator
           'ler_sondagem': ('sondagem', 'sondagem'), 'ler_sondagem_ia': ('sondagem', 'sondagem_ia'),  # do resumo dela)
           'ler_tabelas': ('prancha', 'tabelas')}  # 0v38: a tabela pela grade, código antes da IA (tabela.py)
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
    """id → a tarefa que falta (ler_prancha, ler_sondagem, ler_sondagem_ia, ler_prancha_ia), `feito` ou `falhou` (passou
    das tentativas com este código). O ler_prancha vem antes de tudo: é ele que diz se a folha é prancha, boletim de
    sondagem ou nenhum dos dois."""
    VIGENTE, linhas = vigentes(), {}
    for familia in {f for f, _ in TAREFAS.values()}:
        tabela = comum.ler(familia)
        linhas.update({} if tabela is None else {(l['id'], l['extrator']): l for l in tabela.to_dicts()})
    falhas, TENTATIVAS = falhas_agora(), comum.configuracao('operacao')['tentativas']
    em_dia = lambda d, tarefa: (l := linhas.get((d['id'], TAREFAS[tarefa][1]))) is not None and l['versao_documento'] == d['versao'] \
        and numero(l['versao_codigo']) >= numero(VIGENTE[tarefa])
    estados = {}
    for documento in documentos:
        tarefa = proxima_tarefa(documento, linhas, em_dia)
        if tarefa is None:
            estados[documento['id']] = 'feito'
            continue
        estados[documento['id']] = 'falhou' if falhas[(documento['id'], documento['versao'], tarefa)] >= TENTATIVAS \
            or (tarefa.endswith('_ia') and em_quarentena(documento)) else tarefa
    return estados


def bancada_esperando(pasta=None):
    """A bancada (bancada.py, tarefa 'bancada') do próprio repositório pediu a vez da GPU e está viva: a rodada cede
    entre um documento e outro, sem esperar o fim do pedaço (04/10: a bancada esperou 40 min a rodada de prioridade 7,
    porque a vez só volta no fim do pedaço de 20 min e cada prancha leva até 20)."""
    for arquivo in (pasta or comum.DADOS / 'gpu' / 'pedidos').glob('*.json'):
        try:
            pedido = json.loads(arquivo.read_text())
            if pedido.get('tarefa') == 'bancada' and pedido.get('pid') != os.getpid():
                os.kill(pedido['pid'], 0)
                return True
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return False


def em_quarentena(documento):
    """O documento que travou a IA tantas vezes (o vigia do maestro encerrou a rodada parada nele; operacao.json →
    gpu.quarentena_travamentos) fica de fora da fila de IA: uma tentativa a mais depois do primeiro travamento, e só."""
    return cliente_gpu.travamentos('ialocal.projeto', documento['id']) >= comum.configuracao('operacao')['gpu']['quarentena_travamentos']


def fase(estado):
    """codigo, ia, feito ou falhou: a tarefa que falta pela natureza dela."""
    return estado if estado in ('feito', 'falhou') else 'ia' if estado.endswith('_ia') else 'codigo'


def proxima_tarefa(documento, linhas, em_dia):
    """A tarefa que falta: ler_prancha; no boletim, ler_sondagem e, com página digitalizada, ler_sondagem_ia; na
    prancha, ler_prancha_ia. None se está tudo em dia."""
    if not em_dia(documento, 'ler_prancha'):
        return 'ler_prancha'
    perfil = linhas[(documento['id'], 'prancha')]
    if perfil.get('boletim_sondagem'):
        if not em_dia(documento, 'ler_sondagem'):
            return 'ler_sondagem'
        digitalizadas = json.loads(linhas[(documento['id'], 'sondagem')].get('paginas_ocr') or '[]')
        return 'ler_sondagem_ia' if digitalizadas and not em_dia(documento, 'ler_sondagem_ia') else None
    if perfil['e_prancha'] and not em_dia(documento, 'ler_tabelas'):
        return 'ler_tabelas'
    return 'ler_prancha_ia' if perfil['e_prancha'] and not em_dia(documento, 'ler_prancha_ia') else None


def executar(tarefa, documento, rodada):
    """Uma leitura; a falha fica em dados/falhas.jsonl com o erro e a rodada segue. Devolve o erro ('' se leu)."""
    marca = time.perf_counter()
    try:
        getattr(sondagem if 'sondagem' in tarefa else tabela if tarefa == 'ler_tabelas' else prancha, tarefa)(documento, rodada)
        erro = ''
    except Exception as falha:
        erro = f'{type(falha).__name__}: {falha}'[:500]
        comum.anexar(FALHAS, json.dumps({'em': comum.agora(), 'id': documento['id'], 'versao': documento['versao'],
                                         'tarefa': tarefa, **comum.codigo(), 'erro': erro,
                                         'rastro': traceback.format_exc()[-1500:]}, ensure_ascii=False) + '\n')
    print(f"{time.strftime('%d/%m %H:%M:%S')}  {tarefa:<15} {documento['caminho'][-70:]:<70} "
          f"{time.perf_counter() - marca:6.1f} s {'FALHOU ' + erro[:80] if erro else ''}", flush=True)
    return erro


def publicar(documentos):
    """pranchas.csv, prancha_leituras.csv, prancha_tabelas.csv… e rastro.csv (a vista de quem leu o quê): todas as obras em saida/_sistema/projeto/ e cada obra em
    saida/<acervo>/<obra>/projeto/ (ao lado de extrator/, revisor/ e contexto/). Só quando alguma tabela mudou desde a
    última publicação."""
    DRIVE, marca = comum.configuracao('operacao')['drive'], comum.DADOS / '.publicado'
    FAMILIAS = {'prancha': 'pranchas.csv', 'prancha_leitura': 'prancha_leituras.csv', 'prancha_tabela': 'prancha_tabelas.csv',
                'carimbo': 'carimbos.csv', 'sondagem_campo': 'sondagens.csv', 'sondagem_spt': 'sondagem_spt.csv',
                'sondagem_camada': 'sondagem_camadas.csv'}
    mudou = max(((comum.DADOS / f'{f}.parquet').stat().st_mtime for f in FAMILIAS if (comum.DADOS / f'{f}.parquet').exists()), default=0)
    if not mudou or (marca.exists() and marca.stat().st_mtime >= mudou):
        return
    marca.touch()
    rastro.gerar()  # a vista única de quem leu o quê, refeita só quando alguma família mudou
    FAMILIAS['rastro'] = 'rastro.csv'
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
    contagem, tarefas = Counter(fase(e) for e in estados.values()), Counter(estados.values())
    tabela, boletins = comum.ler('prancha'), comum.ler('sondagem_campo')
    if tabela is not None:  # os documentos dos ensaios (acervo _ensaios) não contam como acervo
        tabela = tabela.filter(~pl.col('id').str.starts_with('_ensaios/'))
    if boletins is not None:
        boletins = boletins.filter(~pl.col('id').str.starts_with('_ensaios/'))
    ia = [] if tabela is None else tabela.filter(pl.col('extrator') == 'prancha_ia').to_dicts()
    pranchas = 0 if tabela is None else tabela.filter((pl.col('extrator') == 'prancha') & pl.col('e_prancha').fill_null(False)).height
    quarentena = [d['caminho'] for d in documentos if estados[d['id']] == 'falhou' and em_quarentena(d)]
    motivo = (f"{contagem['falhou']} leitura(s) falharam {comum.configuracao('operacao')['tentativas']} vezes com este código "
              '(dados/falhas.jsonl)' + (f"; {len(quarentena)} em quarentena (travaram a IA: o maestro encerrou a rodada parada nelas)"
                                        if quarentena else '')) if contagem['falhou'] else '' if documentos else 'nada entregue pelo extrator ainda'
    comum.gravar_no_lugar(comum.SAIDAS / 'status.json', json.dumps({
        'repo': 'ialocal.projeto', 'versao': comum.codigo()['versao_codigo'], 'commit': comum.codigo()['commit'],
        'gerado_em': comum.agora(), 'saude': 'atenção' if motivo else 'ok', 'motivo': motivo, 'usa_gpu': True,
        'progresso': {'feito': contagem['feito'], 'total': len(documentos)},
        'fila': {'codigo': contagem['codigo'], 'ia': contagem['ia'], 'na_fila': contagem['codigo'] + contagem['ia'],
                 'falhou': contagem['falhou'], 'por_tarefa': {t: n for t, n in tarefas.items() if t not in ('feito', 'falhou')}},
        'pranchas': {'reconhecidas': pranchas, 'lidas_pela_ia': len(ia),
                     'conferencia': dict(Counter(l.get('conferencia') or 'sem' for l in ia))},
        'sondagens': {'boletins': 0 if tabela is None else tabela.filter(pl.col('boletim_sondagem').fill_null(False)).height
                      if 'boletim_sondagem' in tabela.columns else 0,
                      'furos': 0 if boletins is None else boletins.filter(pl.col('campo') == 'furo')['valor'].n_unique()},
        'por_obra': por_obra(documentos, estados, tabela),
        'quarentena': quarentena,
        'ensaio': {'ultimo': ensaio_ultimo(), 'pendente': ensaio_pendente()},
        'pedido': pedido.resumo(),
        'ultima_rodada': ultima, **pedidos_ao_caio(documentos, estados)}, ensure_ascii=False, indent=1))


def ensaio_ultimo():
    import ensaio
    return ensaio.ultimo()


def ensaio_pendente():
    import ensaio
    pedido = ensaio.pendente()
    return '/'.join(pedido) if pedido else ''


def pedidos_ao_caio(documentos, estados):
    """As demandas abertas de conceitos/demandas.json ainda sem resposta: quantas (precisa_do_caio, o número que o
    maestro conta) e quais (demandas: id, título e texto), que o maestro põe na caixa de avisos e o ialocal.web manda
    por e-mail. E os resultados das respondidas (respostas.py), que seguem o mesmo caminho até o Caio."""
    respondidas, resultados = respostas.situacao(estados, documentos)
    abertas = [{c: d[c] for c in ('id', 'titulo', 'texto')} for d in comum.configuracao('demandas')['demandas']
               if d['aberta'] and d['id'] not in respondidas]
    return {'precisa_do_caio': len(abertas), 'demandas': abertas, 'resultados': resultados}


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
    import ensaio
    ensaio.do_pedido()  # o ensaio pedido em conceitos/ensaios.json (uma vez por id), antes do trabalho de sempre
    inicio, publicado, rodada_em = time.monotonic(), time.monotonic(), comum.agora()
    feitas = Counter()
    documentos = entrega.documentos()

    def seguir():
        nonlocal publicado
        if time.monotonic() - publicado > OPERACAO['publicar_a_cada_s']:
            publicar(documentos)
            status(documentos, {'inicio': rodada_em, 'em_curso': True, **feitas})
            publicado = time.monotonic()
        if pedido.ativo():  # 0v27: o pedido do Caio por e-mail roda agora; a rodada sai e a próxima continua
            print(f"{time.strftime('%d/%m %H:%M:%S')}  pedido do Caio em curso: a rodada cede", flush=True)
            return False
        return time.monotonic() - inicio < OPERACAO['rodada_max_s']

    for _ in range(2):  # ler_prancha diz o que a folha é; no boletim, o ler_sondagem vem na segunda passada
        estados = situacao(documentos)
        for documento in [d for d in documentos if fase(estados[d['id']]) == 'codigo']:
            if not seguir():
                break
            executar(estados[documento['id']], documento, rodada_em)
            feitas['codigo'] += 1
    estados = situacao(documentos)
    fila = sorted((d for d in documentos if fase(estados[d['id']]) == 'ia'), key=lambda d: estados[d['id']] != 'ler_sondagem_ia')
    publicar(documentos)  # o código terminou: o maestro vê o andamento já, não só depois da espera pela vez e da primeira prancha
    status(documentos, {'inicio': rodada_em, 'em_curso': True, **feitas})
    publicado = time.monotonic()
    if fila and seguir():
        GPU = OPERACAO['gpu']
        print(f"{time.strftime('%d/%m %H:%M:%S')}  pedindo a vez da GPU ao maestro (prioridade {GPU['prioridade']}): "
              f"{len(fila)} documentos para a IA ({', '.join(f'{n} {t}' for t, n in Counter(estados[d['id']] for d in fila).items())})", flush=True)
        with cliente_gpu.vez_da_gpu('ialocal.projeto', str(comum.DADOS / 'gpu'), GPU['prioridade'], GPU['modelo'], 'prancha') as vez:
            for documento in fila:
                if not vez.minha() or not seguir():  # alguém mais importante espera, ou a rodada acabou: a próxima pede de novo
                    break
                if bancada_esperando():
                    print(f"{time.strftime('%d/%m %H:%M:%S')}  a bancada pediu a vez da GPU: a rodada cede (a próxima continua)", flush=True)
                    break
                vez.avancei(documento['id'])  # o item em curso: travado aqui, o vigia do maestro encerra e o registra
                executar(estados[documento['id']], documento, rodada_em)
                feitas['ia'] += 1
    publicar(documentos)
    status(documentos, {'inicio': rodada_em, 'fim': comum.agora(), **feitas})


if __name__ == '__main__':
    if sys.argv[1:2] == ['status']:
        status(entrega.documentos())
    else:
        rodada()
