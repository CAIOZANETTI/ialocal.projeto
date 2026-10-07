"""As lições do projeto: cada falha que a bancada mediu, uma linha com classe, gravidade e destino da correção
(conceitos/licoes.json). É o começo do ciclo de lições (notas/plano_inventario_roteamento.md): o mini roda o ensaio, as
lições sobem ao Drive (saida/_sistema/projeto/licoes_projeto.csv) e, pelo ialocal.dados, ao GitHub; a IA de fora lê,
propõe o PR (regra em JSON, função Python com teste), o Caio faz o merge e o mini roda o mesmo ensaio de novo.

De onde sai cada classe:
    bancada_<conjunto>.parquet, linha de leitor     errada → leitura_errada · inventada → invencao · faltou → omissao
    bancada_<conjunto>.parquet, linha de curadoria  confirmada e errada ou inventada → confirmou_errado
    bancada_chamadas_<conjunto>.parquet             erro depois das tentativas → operacao
    dados/ensaios/<nome>/execucoes.jsonl            a última execução de cada ensaio: tarefa que falhou → operacao
                                                    (conjunto ensaio:<nome>, recorte = o caminho do PDF, leitor = a tarefa)
O Vision, sem estrutura de tabela, não dá lição de linha (é medido pela presença).

codigo_acertou diz se o leitor só de código (grade.py) leu certo a mesma chave do mesmo recorte: é o caso em que o
modelo nem precisava ter sido chamado — a catraca da IA para o código.

PROGRESSO — cada geração é comparada com a anterior: novas (não estavam) e resolvidas (estavam e sumiram). Só conta como
resolvida a lição cujo recorte e leitor foram medidos de novo nesta geração: no --rapido os modelos leem só a amostra, e
a lição de fora da amostra não sumiu, só não foi medida. Uma linha por geração em dados/licoes_historico.jsonl.
"""
import hashlib
import json
import subprocess

import polars as pl

import comum

CONJUNTOS = ('tabelas', 'controle', 'sondagem')
CLASSE_DO_RESULTADO = {'errada': 'leitura_errada', 'inventada': 'invencao', 'faltou': 'omissao'}
COLUNAS = ['id', 'conjunto', 'recorte', 'leitor', 'chave', 'classe', 'gravidade', 'lido', 'esperado', 'codigo_acertou',
           'situacao', 'estagio', 'origem', 'destino']
HISTORICO = 'licoes_historico.jsonl'


def regras():
    return comum.configuracao('licoes')


def identificador(conjunto, recorte, leitor, chave, classe):
    """Estável entre gerações: a mesma falha no mesmo recorte tem o mesmo id (é como se sabe que foi resolvida)."""
    return hashlib.sha1('|'.join((conjunto, recorte, leitor, chave, classe)).encode()).hexdigest()[:12]


def situacao(conjunto, tipo, classe=''):
    """confirmada onde a referência é gabarito (licoes.json → situacao) e na falha de operação (é fato, não leitura);
    provável onde a referência é a concordância de dois leitores."""
    CONFIRMADA = regras()['situacao']['confirmada']
    return 'confirmada' if classe == 'operacao' or conjunto in CONFIRMADA or f'{conjunto}:{tipo}' in CONFIRMADA else 'provavel'


def linha(conjunto, tipo, recorte, leitor, chave, classe, lido='', esperado='', codigo_acertou=None):
    CLASSE = regras()['classes'][classe]
    return {'id': identificador(conjunto, recorte, leitor, chave, classe), 'conjunto': conjunto, 'recorte': recorte,
            'leitor': leitor, 'chave': chave, 'classe': classe, 'gravidade': CLASSE['gravidade'], 'lido': lido,
            'esperado': esperado, 'codigo_acertou': codigo_acertou, 'situacao': situacao(conjunto, tipo, classe),
            'estagio': 'observacao', 'origem': conjunto.split(':')[0] if ':' in conjunto else 'bancada', 'destino': CLASSE['destino']}


def das_medidas(tabela, chamadas=None):
    """As lições de uma bancada (as linhas de bancada_<conjunto>.parquet) e das chamadas (bancada_chamadas_*), na ordem
    da gravidade. Função pura: a tabela entra, a lista sai."""
    linhas = tabela.to_dicts()
    certas_do_codigo = {(l['conjunto'], l['recorte'], l['chave']) for l in linhas
                        if l['leitor'] == 'codigo' and l['tipo'] != 'curadoria' and l['resultado'] == 'certa'}
    medidos_pelo_codigo = {(l['conjunto'], l['recorte']) for l in linhas if l['leitor'] == 'codigo' and l['tipo'] != 'curadoria'}
    licoes = []
    for l in linhas:
        if l['tipo'] == 'curadoria':
            if l['status'] == 'confirmada' and l['resultado'] in ('errada', 'inventada'):
                licoes.append(linha(l['conjunto'], l['tipo'], l['recorte'], l['leitor'], l['chave'], 'confirmou_errado',
                                    l['lido'] or '', l['esperado'] or ''))
            continue
        classe = CLASSE_DO_RESULTADO.get(l['resultado'] or '')
        if classe is None:  # certa, ou o Vision (sem estrutura: resultado vazio)
            continue
        acertou = ((l['conjunto'], l['recorte'], l['chave']) in certas_do_codigo
                   if (l['conjunto'], l['recorte']) in medidos_pelo_codigo and l['leitor'] != 'codigo' else None)
        licoes.append(linha(l['conjunto'], l['tipo'], l['recorte'], l['leitor'], l['chave'], classe, l['lido'] or '',
                            l['esperado'] or '', acertou))
    for c in (chamadas.to_dicts() if chamadas is not None else []):
        if c.get('erro'):
            licoes.append(linha(c['conjunto'], '', c['recorte'], c['leitor'], '', 'operacao', c['erro'][:300]))
    unicas = {l['id']: l for l in licoes}  # a mesma chave lida duas vezes no mesmo recorte é uma lição só
    ordem = {'alta': 0, 'media': 1, 'baixa': 2}
    return sorted(unicas.values(), key=lambda l: (ordem[l['gravidade']], l['classe'], l['conjunto'], l['leitor'], l['recorte'], l['chave']))


def dos_ensaios(execucoes):
    """As falhas da última execução de cada ensaio (as linhas de execucoes.jsonl), como lições de operação; e os
    conjuntos (ensaio:<nome>) que rodaram — o ensaio lê sempre a lista inteira, então toda lição anterior dele foi medida
    de novo."""
    ultimas = {}
    for e in execucoes:
        if e['execucao'] >= ultimas.get(e['ensaio'], {}).get('execucao', ''):
            ultimas[e['ensaio']] = e
    licoes = [linha(f"ensaio:{e['ensaio']}", '', f['caminho'], f['tarefa'], '', 'operacao', f['erro'][:300])
              for e in ultimas.values() for f in e.get('falhas', [])]
    return licoes, {f"ensaio:{nome}" for nome in ultimas}


def ler_ensaios():
    pasta = comum.DADOS / 'ensaios'
    return [json.loads(l) for e in sorted(pasta.glob('*/execucoes.jsonl')) for l in e.read_text().splitlines()] if pasta.exists() else []


def progresso(anteriores, atuais, medidos):
    """novas e resolvidas contra a geração anterior; resolvida só se o recorte × leitor dela foi medido agora."""
    antes, agora = {l['id']: l for l in anteriores}, {l['id'] for l in atuais}
    resolvidas = [i for i, l in antes.items() if i not in agora
                  and (l['conjunto'], l['recorte'], l['leitor']) in medidos]
    return {'novas': len(agora - set(antes)), 'resolvidas': len(resolvidas), 'continuam': len(agora & set(antes))}


def ler_bancada():
    """(tabela, chamadas) de todos os conjuntos medidos, ou (None, None)."""
    partes = [pl.read_parquet(p) for c in CONJUNTOS if (p := comum.DADOS / f'bancada_{c}.parquet').exists()]
    chamadas = [pl.read_parquet(p) for c in CONJUNTOS if (p := comum.DADOS / f'bancada_chamadas_{c}.parquet').exists()]
    return (pl.concat(partes, how='diagonal_relaxed') if partes else None,
            pl.concat(chamadas, how='diagonal_relaxed') if chamadas else None)


def gerar(publicar=True):
    """As lições da bancada atual e da última execução de cada ensaio: dados/licoes.parquet (a geração),
    saidas/licoes_projeto.csv (e o Drive), uma linha de progresso em dados/licoes_historico.jsonl. Devolve o resumo da
    geração, ou None sem bancada e sem ensaio."""
    tabela, chamadas = ler_bancada()
    do_ensaio, ensaios_rodados = dos_ensaios(ler_ensaios())
    if tabela is None and not do_ensaio:
        return None
    atuais = (das_medidas(tabela, chamadas) if tabela is not None else []) + do_ensaio
    destino = comum.DADOS / 'licoes.parquet'
    anteriores = pl.read_parquet(destino).to_dicts() if destino.exists() else []
    medidos = {(l['conjunto'], l['recorte'], l['leitor']) for l in (tabela.to_dicts() if tabela is not None else [])}
    medidos |= {(c['conjunto'], c['recorte'], c['leitor']) for c in (chamadas.to_dicts() if chamadas is not None else [])}
    medidos |= {(l['conjunto'], l['recorte'], l['leitor']) for l in anteriores if l['conjunto'] in ensaios_rodados}
    resumo = {'em': comum.agora(), **comum.codigo(), 'licoes': len(atuais), **progresso(anteriores, atuais, medidos),
              'por_classe': {c: sum(l['classe'] == c for l in atuais) for c in regras()['classes']},
              'codigo_acertou': sum(l['codigo_acertou'] is True for l in atuais)}
    saida = pl.DataFrame(atuais, schema={c: pl.Boolean if c == 'codigo_acertou' else pl.Utf8 for c in COLUNAS}).with_columns(
        **{c: pl.lit(v) for c, v in comum.codigo().items()})
    comum.DADOS.mkdir(parents=True, exist_ok=True)
    saida.write_parquet(destino)
    comum.anexar(comum.DADOS / HISTORICO, json.dumps(resumo, ensure_ascii=False) + '\n')
    local = comum.SAIDAS / 'licoes_projeto.csv'
    local.parent.mkdir(parents=True, exist_ok=True)
    saida.write_csv(local, separator=';', include_bom=True)
    if publicar:
        try:
            comum.publicar(saida, f"{comum.configuracao('operacao')['drive']['sistema']}/licoes_projeto.csv")
        except (OSError, subprocess.CalledProcessError) as falha:  # sem rclone (fora do mini) o CSV local basta
            print(f'Drive: lições não publicadas ({type(falha).__name__})')
    classes = ', '.join(f'{n} {c}' for c, n in resumo['por_classe'].items() if n)
    print(f"lições: {resumo['licoes']} ({classes or 'nenhuma'}); {resumo['novas']} novas, {resumo['resolvidas']} resolvidas "
          f"desde a geração anterior; em {resumo['codigo_acertou']} o código já acertava o que o modelo errou", flush=True)
    return resumo


if __name__ == '__main__':
    gerar()
