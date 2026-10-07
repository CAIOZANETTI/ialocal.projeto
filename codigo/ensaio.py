"""O ensaio do projeto: um conjunto pequeno e fixo de PDFs reais (conceitos/ensaios.json, no máximo 10) rodado de ponta
a ponta no mini — todo o código primeiro, depois a IA na vez da GPU pedida ao maestro — com o registro de como foi: o
que cada documento deu, quanto tempo cada tarefa levou, o que falhou e o que mudou desde a execução anterior do mesmo
ensaio. É a prova do ciclo de lições (notas/plano_inventario_roteamento.md): muda o código por PR, roda o mesmo ensaio,
compara.

    .venv/bin/python codigo/ensaio.py rodar foz_10                  # espera a rodada em curso, pede a vez e roda
    .venv/bin/python codigo/ensaio.py rodar foz_10 --prioridade 6   # outra prioridade na vez da GPU
    .venv/bin/python codigo/ensaio.py rodar foz_10 --sortear        # esquece a lista gravada e sorteia de novo
    .venv/bin/python codigo/ensaio.py lista foz_10                  # só mostra o que entraria, sem rodar

Pelo maestro, sem terminal: conceitos/ensaios.json → pedido {ensaio, id}. A rodada (a cada 5 min) roda o ensaio pedido
uma vez por id, antes do trabalho de sempre; para rodar de novo, um PR troca o id.

FONTES — a primeira que der PDF vale: `drive` (os PDFs soltos da pasta da entrada no Drive, pelo rclone; só lê) ou
`entrega` (os que o extrator já tirou dos zips e entregou ao projeto, da obra que casa com o padrão).
LISTA — a do conceito, se houver; senão a gravada em dados/ensaios/<nome>/lista.json na primeira execução; senão o
sorteio: primeiro os nomes que casam com `preferir` (até a metade), o resto pelo sha1 do caminho. O mesmo ensaio lê
sempre os mesmos PDFs: é o que torna a comparação entre execuções justa.
SEMPRE RODA — o ensaio é teste: lê tudo de novo a cada execução, sem olhar o que já está em dia. A resposta de modelo
igual vem do congelamento (dados/congelamento.jsonl): repetir um ensaio sem mudar nada custa o código, não a GPU.

SAÍDA — dados/ensaios/<nome>/execucoes.jsonl (uma linha por execução, com as falhas) e dados/ensaios/ensaios.parquet (uma
linha por execução × documento); saidas/ensaios.csv e saidas/ensaios_execucoes.csv, e no Drive
saida/_sistema/projeto/ (o ialocal.dados leva ao GitHub). As falhas viram lições de operação (licoes.py).
Os documentos do ensaio ficam nas tabelas de sempre com acervo `_ensaios` e obra = o nome do ensaio; a rodada não os
publica por obra.
"""
import fcntl
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import polars as pl

import ciclo
import cliente_gpu
import comum
import entrega
import licoes

COMPARAR = ('e_prancha', 'boletim_sondagem', 'formato', 'classe', 'familia', 'desenho', 'carimbo_camada', 'carimbo_numero_desenho',
            'eixo', 'eixo_mm', 'eixo_m', 'conferencia', 'fatias_lidas', 'valores_confirmado', 'linhas_tabela_confirmadas',
            'carimbo_campos', 'sondagem_campos', 'erros')
DA_PRANCHA = ('paginas', 'formato', 'classe', 'camada', 'e_prancha', 'boletim_sondagem', 'motivo', 'familia', 'familia_origem',
              'desenho', 'carimbo_camada', 'carimbo_numero_desenho', 'carimbo_revisao_vigente', 'eixo', 'eixo_mm', 'eixo_m',
              'conferencia', 'diferenca_relativa', 'fatias_lidas', 'fatias_planejadas', 'valores_confirmado', 'valores_so_glm',
              'valores_so_vision', 'linhas_tabela', 'linhas_tabela_confirmadas')


def pasta():
    """dados/ensaios/ (lida a cada chamada: os testes trocam comum.DADOS)."""
    return comum.DADOS / 'ensaios'


def regras():
    return comum.configuracao('ensaios')


def sha1(texto):
    return hashlib.sha1(texto.encode()).hexdigest()


def escolher(caminhos, regra):
    """O sorteio: os que casam com `preferir`, até a metade do máximo, e o resto pelo sha1 do caminho, até o máximo."""
    preferir = regra.get('preferir') or r'(?!x)x'
    preferidos = sorted((c for c in caminhos if re.search(preferir, c)), key=sha1)[:regra['maximo'] // 2]
    resto = sorted((c for c in caminhos if c not in preferidos), key=sha1)
    return (preferidos + resto)[:regra['maximo']]


def listar_drive(fonte):
    """Os caminhos dos PDFs da pasta do Drive (recursivo, só metadados) e o erro do rclone ('' se listou)."""
    try:
        feito = subprocess.run(['rclone', 'lsjson', '-R', '--files-only', '--include', '*.{pdf,PDF}', fonte['caminho']],
                               capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as falha:
        return [], f'rclone: {type(falha).__name__}: {falha}'[:200]
    if feito.returncode != 0:
        return [], f"rclone lsjson saiu com {feito.returncode}: {feito.stderr.strip()[-200:]}"
    try:
        return sorted(item['Path'] for item in json.loads(feito.stdout or '[]')), ''
    except (ValueError, KeyError, TypeError) as falha:
        return [], f'rclone lsjson: resposta sem JSON ({falha})'[:200]


def baixar_drive(fonte, caminhos, destino):
    """Os PDFs escolhidos, do Drive para dados/ensaios/<nome>/pdfs/ (só os que faltam); caminho → arquivo local."""
    faltam = [c for c in caminhos if not (destino / c).exists()]
    if faltam:
        destino.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as lista:
            lista.write('\n'.join(faltam) + '\n')
        try:
            subprocess.run(['rclone', 'copy', fonte['caminho'], str(destino), '--files-from-raw', lista.name, '--no-traverse'],
                           capture_output=True, timeout=1800)
        finally:
            Path(lista.name).unlink(missing_ok=True)
    return {c: destino / c for c in caminhos if (destino / c).exists()}


def da_entrega(fonte):
    """caminho → arquivo local dos PDFs que o extrator entregou ao projeto, da obra que casa com fonte['obra']."""
    return {d['caminho']: Path(d['arquivo_local']) for d in entrega.do_extrator()
            if re.search(fonte['obra'], f"{d['acervo']}/{d['obra']}")}


def montar(nome, sortear=False):
    """Os PDFs do ensaio: (fonte usada, {caminho: arquivo local}, avisos). A lista do conceito vale; senão a gravada;
    senão o sorteio, gravado para as próximas execuções."""
    regra, local = regras()['ensaios'][nome], pasta() / nome
    gravada = local / 'lista.json'
    fixa = regra.get('lista') or (json.loads(gravada.read_text())['caminhos'] if gravada.exists() and not sortear else [])
    avisos = []
    for fonte in regra['fontes']:
        if fonte['tipo'] == 'drive':
            caminhos, erro = listar_drive(fonte)
            if erro:
                avisos.append(f"drive {fonte['caminho']}: {erro}")
            escolhidos = [c for c in fixa if c in caminhos] if fixa else escolher(caminhos, regra)
            locais = baixar_drive(fonte, escolhidos, local / 'pdfs') if escolhidos else {}
        else:
            disponiveis = da_entrega(fonte)
            escolhidos = [c for c in fixa if c in disponiveis] if fixa else escolher(sorted(disponiveis), regra)
            locais = {c: disponiveis[c] for c in escolhidos}
        if locais:
            if not fixa or sortear:
                local.mkdir(parents=True, exist_ok=True)
                comum.gravar_no_lugar(gravada, json.dumps({'fonte': fonte, 'caminhos': list(locais), 'em': comum.agora()},
                                                          ensure_ascii=False, indent=1))
            faltando = [c for c in fixa if c not in locais]
            if faltando:
                avisos.append(f'{len(faltando)} PDF(s) da lista não estão mais na fonte: {", ".join(faltando[:3])}')
            return fonte, locais, avisos
        avisos.append(f"fonte {fonte['tipo']} sem PDF")
    return None, {}, avisos


def documento(nome, caminho, local):
    """O documento no formato da entrega, com acervo _ensaios: as tarefas de sempre o leem sem saber que é ensaio."""
    return {'id': f'_ensaios/{nome}/{caminho}', 'caminho': caminho, 'nome': Path(caminho).name, 'acervo': '_ensaios', 'obra': nome,
            'versao': hashlib.sha256(Path(local).read_bytes()).hexdigest()[:16], 'arquivo_local': str(local)}


def linhas_de(ids):
    """(id, extrator) → linha, das famílias que decidem a próxima tarefa (prancha, sondagem)."""
    linhas = {}
    for familia in ('prancha', 'sondagem'):
        tabela = comum.ler(familia, ids)
        linhas.update({} if tabela is None else {(l['id'], l['extrator']): l for l in tabela.to_dicts()})
    return linhas


def avancar(documento, feitas, execucao, so_codigo):
    """Roda as tarefas do documento enquanto a próxima for de código (so_codigo) ou de IA; cada uma uma vez nesta
    execução. Devolve as que rodou: [{tarefa, segundos, erro}]."""
    rodadas = []
    while True:
        linhas = linhas_de([documento['id']])
        try:
            tarefa = ciclo.proxima_tarefa(documento, linhas, lambda d, t: t in feitas)
        except KeyError:  # a tarefa anterior falhou e não deixou a linha de que a próxima depende
            return rodadas
        if tarefa is None or tarefa in feitas or tarefa.endswith('_ia') == so_codigo:
            return rodadas
        marca = time.perf_counter()
        erro = ciclo.executar(tarefa, documento, execucao)
        feitas.add(tarefa)
        rodadas.append({'tarefa': tarefa, 'segundos': round(time.perf_counter() - marca, 2), 'erro': erro})
        if erro:
            return rodadas


def contar(familia, ids, status=None):
    """Linhas da família por id (só as do status, se dado)."""
    tabela = comum.ler(familia, ids)
    if tabela is None:
        return {}
    if status and 'status' in tabela.columns:
        tabela = tabela.filter(pl.col('status').is_in(list(status)))
    return dict(tabela.group_by('id').len().iter_rows())


def resultado(nome, execucao, fonte, documentos, tarefas):
    """Uma linha por documento: o que a leitura deu (a linha da IA, se houver; senão a do código), as contagens e o tempo."""
    ids = [d['id'] for d in documentos]
    pranchas = comum.ler('prancha', ids)
    por_id = {}
    for l in (pranchas.to_dicts() if pranchas is not None else []):
        if l['extrator'] == 'prancha_ia' or l['id'] not in por_id:
            por_id[l['id']] = l
    carimbo, sondagem = contar('carimbo', ids, ('codigo', 'confirmado')), contar('sondagem_campo', ids)
    linhas = []
    for d in documentos:
        lida, feitas = por_id.get(d['id'], {}), tarefas.get(d['id'], [])
        linhas.append({'ensaio': nome, 'execucao': execucao, **comum.codigo(), 'fonte': fonte['tipo'] if fonte else '',
                       'arquivo': d['nome'], 'caminho': d['caminho'], 'versao_documento': d['versao'],
                       **{c: None if lida.get(c) is None else str(lida.get(c)) for c in DA_PRANCHA},
                       'carimbo_campos': carimbo.get(d['id'], 0), 'sondagem_campos': sondagem.get(d['id'], 0),
                       'tarefas': ','.join(t['tarefa'] for t in feitas),
                       'segundos_codigo': round(sum(t['segundos'] for t in feitas if not t['tarefa'].endswith('_ia')), 2),
                       'segundos_ia': round(sum(t['segundos'] for t in feitas if t['tarefa'].endswith('_ia')), 2),
                       'erros': ' | '.join(f"{t['tarefa']}: {t['erro']}" for t in feitas if t['erro'])[:500]})
    return linhas


def comparar(linhas, anteriores):
    """Cada linha com o que mudou contra a execução anterior do mesmo ensaio (mesmo caminho): 'novo', '' ou os campos."""
    antes = {l['caminho']: l for l in anteriores}
    for l in linhas:
        velha = antes.get(l['caminho'])
        l['mudou'] = 'novo' if velha is None else ','.join(c for c in COMPARAR if str(velha.get(c)) != str(l.get(c)))
    return linhas


def gravar(nome, linhas, resumo):
    """dados/ensaios/ensaios.parquet (todas as execuções), execucoes.jsonl do ensaio, os CSVs em saidas/ e o Drive."""
    pasta().mkdir(parents=True, exist_ok=True)
    destino = pasta() / 'ensaios.parquet'
    nova = pl.DataFrame(linhas, infer_schema_length=None)
    tabela = pl.concat([pl.read_parquet(destino), nova], how='diagonal_relaxed') if destino.exists() else nova
    tabela.write_parquet(destino)
    comum.anexar(pasta() / nome / 'execucoes.jsonl', json.dumps(resumo, ensure_ascii=False) + '\n')
    execucoes = pl.DataFrame([{**{k: v for k, v in r.items() if k != 'falhas'}, 'falhas': len(r.get('falhas', [])),
                               'conferencia': json.dumps(r.get('conferencia', {}), ensure_ascii=False),
                               'fonte': json.dumps(r.get('fonte', {}), ensure_ascii=False), 'avisos': ' | '.join(r.get('avisos', []))}
                              for e in sorted(pasta().glob('*/execucoes.jsonl')) for r in map(json.loads, e.read_text().splitlines())],
                             infer_schema_length=None)
    SISTEMA = comum.configuracao('operacao')['drive']['sistema']
    for quadro, arquivo in ((tabela, 'ensaios.csv'), (execucoes, 'ensaios_execucoes.csv')):
        local = comum.SAIDAS / arquivo
        local.parent.mkdir(parents=True, exist_ok=True)
        quadro.write_csv(local, separator=';', include_bom=True)
        try:
            comum.publicar(quadro, f'{SISTEMA}/{arquivo}')
        except (OSError, subprocess.CalledProcessError) as falha:  # sem rclone (fora do mini) o CSV local basta
            print(f'Drive: {arquivo} não publicado ({type(falha).__name__})')


def rodar(nome, prioridade=None, sortear=False, pedido=''):
    """Uma execução do ensaio (quem chama segura a trava da rodada). Devolve o resumo."""
    regra = regras()['ensaios'][nome]
    prioridade = regra['prioridade'] if prioridade is None else prioridade
    inicio, execucao = time.monotonic(), comum.agora()
    prazo = inicio + regra['limite_s']
    fonte, locais, avisos = montar(nome, sortear)
    documentos = [documento(nome, c, l) for c, l in locais.items()]
    print(f"{time.strftime('%d/%m %H:%M:%S')}  ensaio {nome}: {len(documentos)} PDF(s) de {fonte['tipo'] if fonte else 'nenhuma fonte'}"
          + (f" ({'; '.join(avisos)})" if avisos else ''), flush=True)
    feitas, tarefas, interrompido = {d['id']: set() for d in documentos}, {d['id']: [] for d in documentos}, ''
    for d in documentos:  # 1) todo o código, sem a vez da GPU (o boletim: ler_prancha e ler_sondagem na mesma volta)
        tarefas[d['id']] += avancar(d, feitas[d['id']], execucao, so_codigo=True)

    def precisa_de_ia(d):
        if any(t['erro'] for t in tarefas[d['id']]) or ciclo.em_quarentena(d):
            return False
        try:
            proxima = ciclo.proxima_tarefa(d, linhas_de([d['id']]), lambda x, t: t in feitas[d['id']])
        except KeyError:
            return False
        return proxima is not None and proxima.endswith('_ia')
    fila = [d for d in documentos if precisa_de_ia(d)]
    espera = 0.0
    while fila and not interrompido:  # 2) a IA, na vez da GPU; devolvida a vez no meio, pede de novo
        if time.monotonic() > prazo:
            interrompido = f"limite do ensaio ({regra['limite_s']} s): {len(fila)} documento(s) sem a IA"
            break
        print(f"{time.strftime('%d/%m %H:%M:%S')}  ensaio {nome}: pedindo a vez da GPU ao maestro (prioridade {prioridade}) "
              f"para {len(fila)} documento(s)", flush=True)
        pedido_em = time.monotonic()
        with cliente_gpu.vez_da_gpu('ialocal.projeto', str(comum.DADOS / 'gpu'), prioridade,
                                    comum.configuracao('operacao')['gpu']['modelo'], 'ensaio') as vez:
            espera += time.monotonic() - pedido_em
            for d in list(fila):
                if not vez.minha() or time.monotonic() > prazo:
                    break
                vez.avancei(d['id'])
                tarefas[d['id']] += avancar(d, feitas[d['id']], execucao, so_codigo=False)
                vez.contar('documentos')
                fila.remove(d)
    linhas = comparar(resultado(nome, execucao, fonte, documentos, tarefas), anteriores(nome))
    falhas = [{'arquivo': d['nome'], 'caminho': d['caminho'], 'tarefa': t['tarefa'], 'erro': t['erro']}
              for d in documentos for t in tarefas[d['id']] if t['erro']]
    resumo = {'ensaio': nome, 'execucao': execucao, 'pedido': pedido, **comum.codigo(), 'fonte': fonte or {}, 'prioridade': prioridade,
              'documentos': len(documentos), 'pranchas': sum(l['e_prancha'] == 'True' for l in linhas),
              'boletins': sum(l['boletim_sondagem'] == 'True' for l in linhas),
              'conferencia': {c: sum((l['conferencia'] or '') == c for l in linhas) for c in sorted({l['conferencia'] or '' for l in linhas})},
              'com_erro': len({f['caminho'] for f in falhas}), 'mudaram': sum(bool(l['mudou']) and l['mudou'] != 'novo' for l in linhas),
              'segundos': round(time.monotonic() - inicio, 1), 'espera_gpu_s': round(espera, 1), 'interrompido': interrompido,
              'avisos': avisos, 'falhas': falhas, 'fim': comum.agora()}
    if documentos:
        gravar(nome, linhas, resumo)
        licoes.gerar()
    else:  # sem PDF nenhum: a execução fica registrada (o pedido não volta a cada 5 min) e o motivo, nos avisos
        comum.anexar(pasta() / nome / 'execucoes.jsonl', json.dumps(resumo, ensure_ascii=False) + '\n')
    print(f"{time.strftime('%d/%m %H:%M:%S')}  ensaio {nome}: {resumo['documentos']} documento(s), {resumo['pranchas']} prancha(s), "
          f"{resumo['boletins']} boletim(ns), {resumo['com_erro']} com erro, {resumo['mudaram']} mudaram desde a execução anterior; "
          f"{resumo['segundos']} s ({resumo['espera_gpu_s']} s esperando a GPU){'; ' + interrompido if interrompido else ''}", flush=True)
    return resumo


def anteriores(nome):
    """As linhas da última execução gravada deste ensaio (para comparar), ou []."""
    destino = pasta() / 'ensaios.parquet'
    if not destino.exists():
        return []
    tabela = pl.read_parquet(destino).filter(pl.col('ensaio') == nome)
    if not tabela.height:
        return []
    return tabela.filter(pl.col('execucao') == tabela['execucao'].max()).to_dicts()


def executados(nome):
    """Os ids de pedido que já rodaram neste ensaio."""
    arquivo = pasta() / nome / 'execucoes.jsonl'
    return {json.loads(l).get('pedido') for l in arquivo.read_text().splitlines()} if arquivo.exists() else set()


def pendente():
    """O pedido de conceitos/ensaios.json ainda não executado: (nome, id) ou None."""
    pedido = regras().get('pedido') or {}
    nome, identificador = pedido.get('ensaio'), pedido.get('id')
    if not nome or not identificador or nome not in regras()['ensaios'] or identificador in executados(nome):
        return None
    return nome, identificador


def do_pedido():
    """Chamado pela rodada (que já segura a trava): roda o ensaio pedido, se houver. Uma falha não derruba a rodada."""
    pedido = pendente()
    if pedido is None:
        return None
    try:
        return rodar(pedido[0], pedido=pedido[1])
    except Exception as falha:  # o ensaio é teste: falhou, registra e a rodada de sempre segue
        comum.anexar(pasta() / pedido[0] / 'execucoes.jsonl', json.dumps({
            'ensaio': pedido[0], 'execucao': comum.agora(), 'pedido': pedido[1], **comum.codigo(), 'fonte': {}, 'documentos': 0,
            'conferencia': {}, 'avisos': [], 'falhas': [{'arquivo': '', 'caminho': '', 'tarefa': 'ensaio', 'erro': f'{type(falha).__name__}: {falha}'[:500]}],
            'interrompido': 'erro no ensaio'}, ensure_ascii=False) + '\n')
        print(f'ensaio {pedido[0]} falhou: {type(falha).__name__}: {falha}', flush=True)
        return None


def ultimo():
    """O resumo da última execução de qualquer ensaio, sem as falhas (para o status.json), ou None."""
    linhas = [json.loads(l) for e in pasta().glob('*/execucoes.jsonl') for l in e.read_text().splitlines()] if pasta().exists() else []
    if not linhas:
        return None
    feito = max(linhas, key=lambda r: r['execucao'])
    return {**{k: v for k, v in feito.items() if k not in ('falhas', 'fonte')}, 'falhas': len(feito.get('falhas', []))}


def principal(argumentos):
    comando, resto = (argumentos[0] if argumentos else ''), argumentos[1:]
    nomes = [r for r in resto if not r.startswith('--') and not r.isdigit()]
    nome = nomes[0] if nomes else (regras().get('pedido') or {}).get('ensaio')
    if comando not in ('rodar', 'lista') or nome not in regras()['ensaios']:
        print(__doc__)
        print(f"ensaios: {', '.join(regras()['ensaios'])}")
        return
    if comando == 'lista':
        fonte, locais, avisos = montar(nome, '--sortear' in resto)
        print(f"fonte: {json.dumps(fonte, ensure_ascii=False)}" + (f"  ({'; '.join(avisos)})" if avisos else ''))
        for caminho, local in locais.items():
            print(f'  {caminho}  →  {local}')
        return
    prioridade = int(resto[resto.index('--prioridade') + 1]) if '--prioridade' in resto else None
    comum.DADOS.mkdir(parents=True, exist_ok=True)
    with open(comum.DADOS / 'rodada.lock', 'w') as trava:  # a rodada e o ensaio não leem ao mesmo tempo
        try:
            fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('uma rodada está em curso: o ensaio espera ela terminar', flush=True)
            fcntl.flock(trava, fcntl.LOCK_EX)
        rodar(nome, prioridade, '--sortear' in resto)


if __name__ == '__main__':
    principal(sys.argv[1:])
