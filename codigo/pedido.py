"""O pedido do Caio por e-mail (0v27, pedido do Caio de 08/10: "eu te mando um e-mail com o projeto anexado, você
extrai e me responde mostrando o que extraiu, quais ferramentas usou e quanto tempo levou; eu valido ou digo por que
não; a gente ajusta o código e roda de novo — é prioridade máxima").

O ialocal.web guarda cada e-mail do Caio com PDF anexado em ~/dados/ialocal.web/saidas/pedidos/<pedido>/ (anexos/,
corpo.txt, meta.json) e cada resposta dele no mesmo fio em validacoes/<recebido>.json; o projeto só lê. Cada PDF é
lido de ponta a ponta como no ensaio — todo o código primeiro, depois a IA na vez da GPU pedida ao maestro com a
prioridade do Caio (operacao.json → pedidos.prioridade = 0: o dono da vez devolve na hora, de dia e de noite) — e o
resultado vai para saidas/pedidos/<pedido>/<execução>/: resultado.json, resultado.txt (o corpo do e-mail) e os CSVs do
que foi extraído. O web manda o resultado.txt no mesmo fio, com os CSVs anexos.

Quando roda (pendentes):
    primeira leitura   o pedido chegou e não tem execução
    refazer            o Caio respondeu "refazer" depois da última execução
    código novo        o Caio recusou (no todo ou num item) e o commit do código mudou desde a última execução: o
                       ajuste foi feito e o mini roda de novo sozinho (operacao.json → pedidos.refazer_recusados)

O placar das validações (aceito/recusado por item × execução × commit) sai em saidas/pedidos.csv e no Drive
(_sistema/projeto/pedidos.csv): é o que diz, ao longo do dia, qual algoritmo funcionou melhor em cada item.

    .venv/bin/python codigo/pedido.py vigiar        # o launchd (a cada minuto e quando a pasta do web muda): os pendentes, um por vez
    .venv/bin/python codigo/pedido.py rodar <id>    # roda (de novo) um pedido à mão
    .venv/bin/python codigo/pedido.py lista         # os pedidos, as execuções e as validações
"""
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import polars as pl

import cliente_gpu
import comum
import ensaio
import ia

ITENS = ('carimbo', 'tabelas', 'tracado', 'texto', 'sondagem')  # o que o Caio valida, um por um (o web usa os mesmos)
NOMES = {'carimbo': 'CARIMBO', 'tabelas': 'TABELAS', 'tracado': 'TRAÇADO (eixo)', 'texto': 'TEXTO DA FOLHA (fatias)',
         'sondagem': 'BOLETIM DE SONDAGEM'}
FERRAMENTAS = {'ler_prancha': 'código: pypdfium2 + pdfminer (perfil, carimbo de texto real, família, eixo pela geometria)',
               'ler_prancha_ia': 'IA local: glm-ocr (Ollama) × Vision (macOS) nas fatias, nas tabelas coladas e no carimbo desenhado',
               'ler_sondagem': 'código: pdfplumber/pypdfium2 (boletim com texto real)',
               'ler_sondagem_ia': 'IA local: glm-ocr × Vision (boletim digitalizado)'}
MOSTRAR = 15  # linhas de tabela e valores por documento no corpo do e-mail; o resto vai nos CSVs anexos


def regra():
    return comum.configuracao('operacao')['pedidos']


def entrada():
    """A pasta onde o web guarda os pedidos (PROJETO_PEDIDOS passa na frente: os testes)."""
    return Path(os.environ.get('PROJETO_PEDIDOS') or os.path.expanduser(regra()['pasta']))


def saida():
    return comum.SAIDAS / 'pedidos'


def instante(texto):
    """O ISO do web (com fuso) e o do projeto (sem) na mesma régua: a hora local, sem fuso."""
    momento = datetime.fromisoformat(str(texto))
    return momento.astimezone().replace(tzinfo=None) if momento.tzinfo else momento


def ler(arquivo):
    try:
        return json.loads(Path(arquivo).read_text())
    except (OSError, ValueError):
        return None


def pedidos():
    """Os pedidos guardados pelo web, do mais antigo ao mais novo: o meta.json (escrito por último: pedido sem ele
    ainda está chegando) e as validações."""
    lista = []
    for meta in entrada().glob('*/meta.json'):
        dados = ler(meta)
        if dados and dados.get('tipo', 'projeto') in regra()['tipos']:  # os outros tipos (memorial, livro…) são de outro leitor
            validacoes = sorted(filter(None, map(ler, meta.parent.glob('validacoes/*.json'))), key=lambda v: instante(v['recebido_em']))
            lista.append({**dados, 'id': meta.parent.name, 'pasta': meta.parent, 'validacoes': validacoes})
    return sorted(lista, key=lambda p: instante(p['recebido_em']))


def execucoes(identificador):
    """As execuções gravadas do pedido, da primeira à última (o resultado.json de cada uma)."""
    return sorted(filter(None, map(ler, (saida() / identificador).glob('e*/resultado.json'))), key=lambda e: e['n'])


def julga(validacao, execucao, seguinte=None):
    """A validação é sobre esta execução: a que o web anotou (a última cujo resultado ele mandou no fio) ou, sem a
    anotação, a que terminou antes dela e antes da seguinte começar."""
    if validacao.get('execucao'):
        return validacao['execucao'] == execucao['execucao']
    quando = instante(validacao['recebido_em'])
    return quando > instante(execucao['fim']) and (seguinte is None or quando < instante(seguinte['inicio']))


def recusou(validacao):
    return validacao.get('veredito') == 'recusado' or any(i.get('veredito') == 'recusado' for i in (validacao.get('itens') or {}).values())


def motivo_para_rodar(pedido, feitas, commit):
    """Por que o pedido roda agora ('' se não roda): a primeira leitura, o Caio pediu para refazer, ou recusou e o
    código mudou desde a última execução."""
    if not feitas:
        return 'primeira leitura'
    ultima = feitas[-1]
    depois = [v for v in pedido['validacoes'] if julga(v, ultima)]
    if any(v.get('refazer') for v in depois):
        return 'você pediu para refazer'
    if regra()['refazer_recusados'] and commit and ultima.get('commit') != commit and any(recusou(v) for v in depois):
        return f"código novo ({ultima.get('commit') or '?'} → {commit}) depois da sua recusa"
    return ''


def pendentes():
    """[(pedido, motivo)] dos que rodam agora, na ordem de chegada."""
    commit = comum.codigo()['commit']
    return [(p, motivo) for p in pedidos() if (motivo := motivo_para_rodar(p, execucoes(p['id']), commit))]


def ativo():
    """O pedido em curso neste momento ({pedido, pid, desde}) ou None: a rodada de sempre cede a ele."""
    estado = ler(comum.DADOS / 'pedido_ativo.json')
    if not estado:
        return None
    try:
        os.kill(estado['pid'], 0)
    except (OSError, KeyError, TypeError):
        return None
    return estado


@contextmanager
def trava():
    """Um pedido por vez (dados/pedido.lock), à parte da trava da rodada: o pedido não espera a rodada de 50 min."""
    comum.DADOS.mkdir(parents=True, exist_ok=True)
    with open(comum.DADOS / 'pedido.lock', 'w') as arquivo:
        try:
            fcntl.flock(arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


def documentos(pedido):
    """Os PDFs anexos como documentos da rodada (acervo _pedidos, obra = o pedido). Cada um é copiado para
    dados/pedidos/<pedido>/ com o hash no nome: os recortes (dados/recortes/<nome>) não se misturam com os de outra
    prancha de mesmo nome."""
    lista = []
    for anexo in sorted(pedido['pasta'].glob('anexos/*')):
        if anexo.suffix.lower() != '.pdf':
            continue
        versao = hashlib.sha256(anexo.read_bytes()).hexdigest()[:16]
        local = comum.DADOS / 'pedidos' / pedido['id'] / f'{versao}_{anexo.name}'
        if not local.exists():
            local.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(anexo, local)
        lista.append({'id': f"_pedidos/{pedido['id']}/{anexo.name}", 'caminho': f"_pedidos/{pedido['id']}/{anexo.name}",
                      'nome': anexo.name, 'acervo': '_pedidos', 'obra': pedido['id'], 'versao': versao, 'arquivo_local': str(local),
                      'bytes': anexo.stat().st_size})
    return lista


@contextmanager
def cronometro_do_vision():
    """Quantas vezes o Vision foi chamado e quanto levou (ele roda num processo à parte, fora do congelamento)."""
    original, medida = ia.ler_com_vision, {'chamadas': 0, 'segundos': 0.0, 'erros': 0}

    def medido(caminho):
        marca = time.perf_counter()
        try:
            return original(caminho)
        except Exception:
            medida['erros'] += 1
            raise
        finally:
            medida['chamadas'] += 1
            medida['segundos'] += time.perf_counter() - marca
    ia.ler_com_vision = medido
    try:
        yield medida
    finally:
        ia.ler_com_vision = original


def rodar(pedido, motivo='à mão'):
    """Uma execução do pedido (quem chama segura a trava). Grava e devolve o resultado; uma falha vira resultado com o
    erro (o Caio fica sabendo pelo mesmo fio e o pedido não volta a cada minuto)."""
    feitas = execucoes(pedido['id'])
    n = (feitas[-1]['n'] + 1) if feitas else 1
    pasta = saida() / pedido['id'] / f'e{n}'
    inicio, marca = comum.agora(), time.monotonic()
    comum.gravar_no_lugar(comum.DADOS / 'pedido_ativo.json', json.dumps({'pedido': pedido['id'], 'pid': os.getpid(), 'desde': inicio}))
    print(f"{time.strftime('%d/%m %H:%M:%S')}  pedido {pedido['id']} (e{n}): {motivo}", flush=True)
    status()
    base = {'pedido': pedido['id'], 'execucao': f'e{n}', 'n': n, 'motivo': motivo, 'assunto': pedido.get('assunto', ''),
            'inicio': inicio, **comum.codigo()}
    try:
        resultado = {**base, **executar(pedido, pasta, inicio, marca)}
    except Exception as falha:
        resultado = {**base, 'documentos': [], 'ferramentas': [], 'itens': {}, 'segundos': round(time.monotonic() - marca, 1),
                     'espera_gpu_s': 0, 'anexos': [], 'erro': f'{type(falha).__name__}: {falha}'[:500],
                     'rastro': traceback.format_exc()[-1500:]}
    resultado['fim'] = comum.agora()
    resultado['texto'] = texto(resultado, feitas[-1] if feitas else None)
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / 'resultado.txt').write_text(resultado['texto'])
    comum.gravar_no_lugar(pasta / 'resultado.json', json.dumps(resultado, ensure_ascii=False, indent=1))  # por último: o web espera por ele
    (comum.DADOS / 'pedido_ativo.json').unlink(missing_ok=True)
    status()
    print(f"{time.strftime('%d/%m %H:%M:%S')}  pedido {pedido['id']} (e{n}): {len(resultado['documentos'])} documento(s) em "
          f"{resultado['segundos']} s{' · ERRO ' + resultado['erro'] if resultado.get('erro') else ''}", flush=True)
    return resultado


def executar(pedido, pasta, execucao, marca):
    """O código em todos, depois a IA na vez da GPU com a prioridade do Caio; o que cada documento deu, por item, com
    a ferramenta e o tempo."""
    REGRA = regra()
    lista = documentos(pedido)
    for d in lista:  # o pedido é teste: lê tudo de novo, com os recortes do zero (o código pode ter mudado o recorte)
        shutil.rmtree(comum.DADOS / 'recortes' / Path(d['arquivo_local']).stem, ignore_errors=True)
    feitas, tarefas = {d['id']: set() for d in lista}, {d['id']: [] for d in lista}
    chamadas = ia.medir()
    for d in lista:
        tarefas[d['id']] += ensaio.avancar(d, feitas[d['id']], execucao, so_codigo=True)

    def precisa_de_ia(d):
        if any(t['erro'] for t in tarefas[d['id']]):
            return False
        try:
            proxima = ensaio.ciclo.proxima_tarefa(d, ensaio.linhas_de([d['id']]), lambda x, t: t in feitas[d['id']])
        except KeyError:
            return False
        return proxima is not None and proxima.endswith('_ia')
    fila, espera, interrompido = [d for d in lista if precisa_de_ia(d)], 0.0, ''
    with cronometro_do_vision() as vision:
        while fila:
            if time.monotonic() - marca > REGRA['limite_s']:
                interrompido = f"limite do pedido ({REGRA['limite_s']} s): {len(fila)} documento(s) sem a IA"
                break
            print(f"{time.strftime('%d/%m %H:%M:%S')}  pedido {pedido['id']}: pedindo a vez da GPU (prioridade {REGRA['prioridade']}, a do Caio) "
                  f"para {len(fila)} documento(s)", flush=True)
            pedido_em = time.monotonic()
            with cliente_gpu.vez_da_gpu('ialocal.projeto', str(comum.DADOS / 'gpu'), REGRA['prioridade'],
                                        comum.configuracao('operacao')['gpu']['modelo'], 'pedido') as vez:
                espera += time.monotonic() - pedido_em
                for d in list(fila):
                    if not vez.minha():
                        break
                    vez.avancei(d['id'])
                    tarefas[d['id']] += ensaio.avancar(d, feitas[d['id']], execucao, so_codigo=False)
                    vez.contar('documentos')
                    fila.remove(d)
    pasta.mkdir(parents=True, exist_ok=True)
    return {'documentos': [documento_lido(d, tarefas[d['id']]) for d in lista], 'ferramentas': ferramentas(tarefas, list(chamadas), vision),
            'itens': itens(lista), 'segundos': round(time.monotonic() - marca, 1), 'espera_gpu_s': round(espera, 1),
            'interrompido': interrompido, 'anexos': exportar(lista, pasta), 'erro': ''}


def ferramentas(tarefas, chamadas, vision):
    """O tempo de cada tarefa (somado nos documentos) com a ferramenta dela, e o de cada modelo chamado."""
    por_tarefa = {}
    for feitas in tarefas.values():
        for t in feitas:
            soma = por_tarefa.setdefault(t['tarefa'], {'tarefa': t['tarefa'], 'ferramenta': FERRAMENTAS.get(t['tarefa'], t['tarefa']),
                                                       'documentos': 0, 'segundos': 0.0, 'erros': 0})
            soma['documentos'] += 1
            soma['segundos'] = round(soma['segundos'] + t['segundos'], 2)
            soma['erros'] += bool(t['erro'])
    modelos, WEB = {}, set(regra()['motores_web'])
    for meta in chamadas:
        nome = f"{meta.get('motor', '?')}:{meta.get('modelo', '?')}"
        onde = 'web' if meta.get('motor') in WEB else 'local'
        soma = modelos.setdefault(nome, {'modelo': nome, 'onde': onde, 'chamadas': 0, 'segundos': 0.0, 'do_congelamento': 0,
                                         'versao': ' '.join(filter(None, (meta.get('digest'), meta.get('versao')))),
                                         'servidor': ia.OLLAMA if meta.get('motor') == 'ollama' else ''})
        soma['chamadas'] += 1
        soma['segundos'] = round(soma['segundos'] + (0 if meta.get('congelado') else meta.get('segundos') or 0), 2)
        soma['do_congelamento'] += bool(meta.get('congelado'))
    if vision['chamadas']:
        modelos['vision'] = {'modelo': 'vision:macOS', 'onde': 'local', 'versao': '', 'servidor': '', 'chamadas': vision['chamadas'], 'segundos': round(vision['segundos'], 2),
                             'do_congelamento': 0, 'erros': vision['erros']}
    return list(por_tarefa.values()) + [{**m, 'tarefa': 'modelo'} for m in modelos.values()]


def linhas(familia, ids):
    tabela = comum.ler(familia, ids)
    return [] if tabela is None else tabela.to_dicts()


def documento_lido(d, feitas):
    """A linha da prancha (a da IA, se houver) com o tempo de cada tarefa deste documento."""
    pranchas = linhas('prancha', [d['id']])
    codigo_ = next((l for l in pranchas if l['extrator'] == 'prancha'), {})
    linha = next((l for l in pranchas if l['extrator'] == 'prancha_ia'), codigo_)
    linha = {**linha, 'motivo': ' · '.join(filter(None, dict.fromkeys((codigo_.get('motivo'), linha.get('motivo')))))}
    campos = ('paginas', 'formato', 'classe', 'camada', 'e_prancha', 'boletim_sondagem', 'motivo', 'familia', 'familia_origem', 'grupo',
              'desenho', 'carimbo_camada', 'eixo', 'eixo_mm', 'eixo_vertices', 'deflexoes', 'eixo_camadas', 'escalas_confirmadas',
              'eixo_m', 'eixo_m_camadas', 'tubo_relacao_m', 'conferencia', 'diferenca_relativa', 'fatias_lidas', 'fatias_planejadas',
              'valores_confirmado', 'valores_so_glm', 'valores_so_vision', 'linhas_tabela', 'linhas_tabela_confirmadas')
    return {'id': d['id'], 'arquivo': d['nome'], 'bytes': d['bytes'], **{c: linha.get(c) for c in campos},
            'tarefas': [{k: t[k] for k in ('tarefa', 'segundos', 'erro')} for t in feitas]}


def itens(lista):
    """O que saiu de cada item validável, por documento: carimbo (campo, valor, leitor, status), tabelas (linhas),
    traçado (da linha da prancha), texto (valores por status e padrão) e sondagem (campos e N-SPT)."""
    ids = [d['id'] for d in lista]
    por = lambda familia: {i: [l for l in linhas(familia, ids) if l['id'] == i] for i in ids}
    carimbo, tabela, leitura, campo, spt = (por(f) for f in ('carimbo', 'prancha_tabela', 'prancha_leitura', 'sondagem_campo', 'sondagem_spt'))
    saida_ = {}
    for i in ids:
        saida_[i] = {
            'carimbo': [{k: l.get(k) for k in ('campo', 'valor', 'valor_vision', 'leitor', 'status')} for l in carimbo[i]],
            'tabelas': [{'imagem': l.get('imagem'), 'faixa': l.get('faixa'), 'linha': l.get('linha'), 'celulas': json.loads(l.get('celulas') or '[]'),
                         'status': l.get('status'), 'nao_confirmados': l.get('nao_confirmados')} for l in tabela[i] if l.get('status') != 'vazia'],
            'texto': dict(Counter(f"{l.get('padrao')}|{l.get('status')}" for l in leitura[i] if l.get('valor'))),
            'texto_exemplos': [{k: l.get(k) for k in ('fatia', 'padrao', 'valor', 'status')} for l in leitura[i] if l.get('valor')][:200],
            'sondagem': [{k: l.get(k) for k in ('pagina', 'furo', 'campo', 'valor', 'valor_vision', 'leitor', 'status')} for l in campo[i]],
            'spt': [{k: l.get(k) for k in ('furo', 'profundidade_m', 'golpes', 'nspt', 'nspt_vision', 'status')} for l in spt[i]]}
    return saida_


def exportar(lista, pasta):
    """Os CSVs do que foi extraído (;, UTF-8 com BOM, como os do Drive), só das famílias com linha: os anexos do e-mail."""
    ids, feitos = [d['id'] for d in lista], []
    for familia, nome in (('prancha', 'pranchas.csv'), ('carimbo', 'carimbos.csv'), ('prancha_tabela', 'tabelas.csv'),
                          ('prancha_leitura', 'leituras.csv'), ('sondagem_campo', 'sondagens.csv'), ('sondagem_spt', 'sondagem_spt.csv'),
                          ('sondagem_camada', 'sondagem_camadas.csv')):
        tabela = comum.ler(familia, ids)
        if tabela is not None and tabela.height:
            tabela.write_csv(pasta / nome, separator=';', include_bom=True)
            feitos.append(nome)
    return feitos


def segundos(s):
    s = float(s or 0)
    return f'{s:.1f} s'.replace('.', ',') if s < 90 else f'{int(s // 60)} min {int(s % 60):02d} s'


def texto(resultado, anterior):
    """O corpo do e-mail de resposta: o que saiu de cada documento, item a item, as ferramentas e o tempo, o que mudou
    desde a execução anterior e como validar."""
    partes = [f"Pedido {resultado['pedido']} · execução {resultado['execucao']} ({resultado['motivo']}) · código "
              f"{resultado['versao_codigo']} ({resultado['commit'] or 'sem commit'})", '']
    if resultado.get('erro'):
        partes += [f"A extração FALHOU: {resultado['erro']}", '', 'O rastro está no mini em saidas/pedidos/'
                   f"{resultado['pedido']}/{resultado['execucao']}/resultado.json. Responda \"refazer\" depois da correção.", '']
    if not resultado.get('erro') and not resultado['documentos']:
        partes += ['Nenhum PDF anexo neste pedido: nada a extrair.', '']
    for numero, d in enumerate(resultado['documentos'], 1):
        partes += documento_em_texto(numero, d, resultado['itens'].get(d['id'], {}))
    partes += ['FERRAMENTAS E TEMPO']
    for f in resultado['ferramentas']:
        if f['tarefa'] == 'modelo':
            congelado = f" ({f['do_congelamento']} do congelamento, sem custo)" if f.get('do_congelamento') else ''
            onde = 'IA WEB' if f.get('onde') == 'web' else 'IA local'
            versao = f" [{f['versao']}{' em ' + f['servidor'] if f.get('servidor') else ''}]" if f.get('versao') or f.get('servidor') else ''
            partes.append(f"  · {onde} {f['modelo']}{versao}: {f['chamadas']} chamada(s), {segundos(f['segundos'])}{congelado}")
        else:
            partes.append(f"  {f['tarefa']:<16} {segundos(f['segundos']):>12}  {f['ferramenta']}"
                          + (f" — {f['erros']} erro(s)" if f['erros'] else ''))
    if not any(f['tarefa'] == 'modelo' for f in resultado['ferramentas']):
        partes.append('  · nenhuma IA chamada: tudo saiu por código')
    partes += [f"  espera pela vez da GPU: {segundos(resultado['espera_gpu_s'])}",
               f"  TOTAL: {segundos(resultado['segundos'])}" + (f" — {resultado['interrompido']}" if resultado.get('interrompido') else ''), '']
    if anterior:
        partes += mudancas(resultado, anterior) + ['']
    if resultado.get('anexos'):
        partes += [f"Anexos: {', '.join(resultado['anexos'])} (tudo o que foi extraído, linha a linha, com o leitor e o status).", '']
    partes += ['PARA VALIDAR — responda este e-mail, uma linha por item (o que não disser fica sem avaliação):',
               '  ok                                  tudo certo',
               '  carimbo: ok',
               '  tabelas: não, faltou a tabela de materiais',
               '  traçado: não, o eixo tem 540 m',
               '  texto: ok        sondagem: ok',
               '  refazer                             roda de novo agora, com o código atual',
               'Com uma recusa, quando o código mudar (o ajuste feito pelo Claude e aprovado), o mini roda de novo sozinho e '
               'responde aqui com o que mudou.']
    return '\n'.join(partes) + '\n'


def documento_em_texto(numero, d, it):
    tamanho = (f"{d['bytes'] / 1e6:.1f} MB" if d['bytes'] >= 1e6 else f"{d['bytes'] / 1e3:.0f} kB").replace('.', ',')
    paginas = f"{d['paginas']} página(s)" if d.get('paginas') else 'páginas: ?'
    linhas_ = [f"{numero}) {d['arquivo']} — {tamanho}, {paginas}, {d.get('formato') or 'formato ?'}"
               + (' (a leitura olha só a página 1)' if (d.get('paginas') or 1) > 1 else '')]
    tipo = 'boletim de sondagem' if d.get('boletim_sondagem') else 'prancha' if d.get('e_prancha') else 'não é prancha'
    linhas_.append(f"   O que é: {tipo} ({d.get('motivo') or 'sem motivo'}) · classe {d.get('classe') or '?'}, camada de leitura {d.get('camada') or '?'}")
    if d.get('e_prancha'):
        linhas_.append(f"   Família: {d.get('familia') or '?'} ({d.get('familia_origem') or '?'}) · desenho: {d.get('desenho') or '?'}")
    erros = [f"{t['tarefa']}: {t['erro']}" for t in d['tarefas'] if t['erro']]
    linhas_ += [f'   ERRO {e}' for e in erros]
    linhas_.append('   Tempo: ' + ' · '.join(f"{t['tarefa']} {segundos(t['segundos'])}" for t in d['tarefas']))
    if d.get('e_prancha'):
        linhas_ += carimbo_em_texto(d, it.get('carimbo', [])) + tabelas_em_texto(it.get('tabelas', [])) + tracado_em_texto(d) \
            + texto_da_folha(d, it)
    if d.get('boletim_sondagem'):
        linhas_ += sondagem_em_texto(it)
    return linhas_ + ['']


def carimbo_em_texto(d, campos):
    leitores = sorted({c['leitor'] for c in campos if c.get('leitor')})
    como = {'texto': 'pelo código (texto real do PDF, região do carimbo)', 'imagem': 'pela IA (recorte do carimbo: glm-ocr × Vision)'}
    cabeca = f"   CARIMBO — {como.get(d.get('carimbo_camada'), d.get('carimbo_camada') or 'não lido')}; leitor(es): {', '.join(leitores) or '—'}"
    if not campos:
        return [cabeca, '     nenhum campo lido']
    contagem = Counter(c['status'] for c in campos)
    corpo = [f"     {c['campo']}: {c['valor']}" + (f" (Vision: {c['valor_vision']})" if c.get('valor_vision') else '') + f"  [{c['status']}]"
             for c in campos if c['campo'] != 'revisoes']
    return [cabeca + f" · {', '.join(f'{n} {s}' for s, n in contagem.items())}", *corpo]


def tabelas_em_texto(tabelas):
    if not tabelas:
        return ['   TABELAS — nenhuma tabela colada como imagem na folha (a tabela em texto/vetor ainda não é lida como tabela)']
    contagem = Counter(t['status'] for t in tabelas)
    imagens = len({t['imagem'] for t in tabelas})
    corpo = [f"     {' | '.join(t['celulas'])}  [{t['status']}{': falta ' + t['nao_confirmados'] if t.get('nao_confirmados') else ''}]"
             for t in tabelas[:MOSTRAR]]
    return [f"   TABELAS — glm-ocr (modo tabela) × Vision: {imagens} imagem(ns), {len(tabelas)} linha(s): "
            f"{', '.join(f'{n} {s}' for s, n in contagem.items())}", *corpo] + \
        ([f'     … mais {len(tabelas) - MOSTRAR} linha(s) em tabelas.csv'] if len(tabelas) > MOSTRAR else [])


def tracado_em_texto(d):
    metodo = {'faixa': 'pelo código, a faixa colorida do eixo na geometria do PDF', 'camada': 'pelo código, a soma dos traços das camadas de tubo do CAD',
              'nao_encontrado': 'não encontrado (sem faixa colorida nem camada de tubo)', 'erro': 'erro na leitura da geometria'}
    linhas_ = [f"   TRAÇADO — {metodo.get(d.get('eixo'), d.get('eixo') or 'não lido')}"]
    if d.get('eixo_mm'):
        deflexoes = json.loads(d.get('deflexoes') or '[]')
        linhas_.append(f"     {d['eixo_mm']} mm de papel, {d.get('eixo_vertices') or 0} vértice(s)"
                       + (f", deflexões {', '.join(f'{x}°' for x in deflexoes)}" if deflexoes else ''))
        camadas = json.loads(d.get('eixo_camadas') or '{}')
        linhas_ += [f'     camada {c}: {mm} mm' for c, mm in list(camadas.items())[:8]]
    escalas = json.loads(d.get('escalas_confirmadas') or '[]')
    linhas_.append(f"     escala confirmada: {', '.join(f'1:{e}' for e in escalas) or '—'} → eixo "
                   f"{str(d['eixo_m']) + ' m' if d.get('eixo_m') is not None else '—'} · tubo da relação: {str(d['tubo_relacao_m']) + ' m' if d.get('tubo_relacao_m') else '—'} · "
                   f"conferência: {d.get('conferencia') or '—'}" + (f" (diferença {d['diferenca_relativa']:.1%})" if d.get('diferenca_relativa') else ''))
    return linhas_


def texto_da_folha(d, it):
    if d.get('fatias_planejadas') is None:
        return ['   TEXTO DA FOLHA — a IA não leu as fatias (sem a vez da GPU ou erro)']
    exemplos = Counter(f"{e['padrao']} {e['valor']}" for e in it.get('texto_exemplos', []) if e['status'] == 'confirmado')
    return [f"   TEXTO DA FOLHA — glm-ocr × Vision em {d.get('fatias_lidas')} de {d.get('fatias_planejadas')} fatia(s): "
            f"{d.get('valores_confirmado') or 0} confirmados, {d.get('valores_so_glm') or 0} só glm-ocr, {d.get('valores_so_vision') or 0} só Vision",
            *(f'     {valor}' for valor, _ in exemplos.most_common(MOSTRAR))]


def sondagem_em_texto(it):
    campos, spt = it.get('sondagem', []), it.get('spt', [])
    leitores = sorted({c['leitor'] for c in campos if c.get('leitor')})
    return [f"   BOLETIM DE SONDAGEM — leitor(es): {', '.join(leitores) or '—'}; {len(campos)} campo(s), {len(spt)} metro(s) de N-SPT",
            *(f"     {c['furo'] or ''} {c['campo']}: {c['valor']}  [{c['status']}]" for c in campos[:MOSTRAR]),
            *(f"     {s['furo'] or ''} {s['profundidade_m']} m: N-SPT {s['nspt']}  [{s['status']}]" for s in spt[:MOSTRAR])]


def mudancas(resultado, anterior):
    """O que mudou desde a execução anterior do mesmo pedido, documento a documento, e o tempo."""
    antes = {d['arquivo']: d for d in anterior.get('documentos', [])}
    linhas_ = [f"COMPARADO COM A EXECUÇÃO {anterior['execucao']} ({anterior.get('commit') or '?'}, {segundos(anterior.get('segundos'))}):"]
    for d in resultado['documentos']:
        velho = antes.get(d['arquivo'])
        if velho is None:
            linhas_.append(f"  {d['arquivo']}: novo")
            continue
        mudou = [f"{c} {velho.get(c)} → {d.get(c)}" for c in ensaio.COMPARAR if c in d and str(velho.get(c)) != str(d.get(c))]
        linhas_.append(f"  {d['arquivo']}: " + ('; '.join(mudou) if mudou else 'nada mudou na prancha'))
    return linhas_


def placar():
    """Uma linha por execução × item com o veredito do Caio (a validação mais nova depois daquela execução e antes da
    seguinte): saidas/pedidos.csv e o Drive. É o placar de qual algoritmo funcionou."""
    linhas_ = []
    for p in pedidos():
        feitas = execucoes(p['id'])
        for k, e in enumerate(feitas):
            dela = [v for v in p['validacoes'] if julga(v, e, feitas[k + 1] if k + 1 < len(feitas) else None)]
            ultima = dela[-1] if dela else {}
            usados = '; '.join(f"{f['tarefa'] if f['tarefa'] != 'modelo' else f['modelo']} {f['segundos']} s" for f in e.get('ferramentas', []))
            for item in ('geral', *ITENS):
                juizo = {'veredito': ultima.get('veredito'), 'motivo': ultima.get('motivo')} if item == 'geral' else (ultima.get('itens') or {}).get(item, {})
                linhas_.append({'pedido': p['id'], 'assunto': p.get('assunto', ''), 'execucao': e['execucao'], 'inicio': e['inicio'],
                                'versao_codigo': e.get('versao_codigo'), 'commit': e.get('commit'), 'documentos': len(e.get('documentos', [])),
                                'segundos': e.get('segundos'), 'espera_gpu_s': e.get('espera_gpu_s'), 'ferramentas': usados,
                                'erro': e.get('erro', ''), 'item': item, 'veredito': juizo.get('veredito') or '', 'motivo': juizo.get('motivo') or ''})
    if linhas_:
        tabela = pl.DataFrame(linhas_, infer_schema_length=None)
        destino = comum.SAIDAS / 'pedidos.csv'
        destino.parent.mkdir(parents=True, exist_ok=True)
        tabela.write_csv(destino, separator=';', include_bom=True)
        try:
            comum.publicar(tabela, f"{comum.configuracao('operacao')['drive']['sistema']}/pedidos.csv")
        except (OSError, subprocess.CalledProcessError) as falha:  # sem rclone (fora do mini) o CSV local basta
            print(f'Drive: pedidos.csv não publicado ({type(falha).__name__})')
    return linhas_


CODIGO_DO_ITEM = {
    'carimbo': 'codigo/prancha.py (ler_carimbo, campos_do_carimbo, campo_por_ancora, ler_carimbo_ocr) e conceitos/prancha.json → carimbo '
               '(regiao, campos, ancoras, revisoes)',
    'tabelas': 'codigo/prancha.py (ler_imagens, faixas, ler_tabela, linhas_html), codigo/grade.py (a tabela pelas caixas do Vision) e '
               'conceitos/prompts/prancha_tabela.txt',
    'tracado': 'codigo/prancha.py (eixo, caminhos_na_cor, tracos_por_camada, conferir) e conceitos/prancha.json → eixo (cores, camadas_tubo) '
               'e conferencia',
    'texto': 'codigo/prancha.py (plano_fatias, ler_fatias, alegacoes) e conceitos/prancha.json → fatias e padroes',
    'sondagem': 'codigo/sondagem.py (ler_sondagem, ler_sondagem_ia) e conceitos/sondagem.json'}


def prompt_de_correcao(pedido, execucao, validacao):
    """O prompt para o Claude corrigir o código pela recusa: o pedido, o que saiu em cada item recusado, o motivo de
    quem validou, as ferramentas e IAs usadas, onde mexer e como provar. Vai ao e-mail de quem validou e fica em
    saidas/pedidos/<pedido>/<execução>/."""
    recusados = {k: i for k, i in (validacao.get('itens') or {}).items() if i.get('veredito') == 'recusado'}
    if not recusados and validacao.get('veredito') == 'recusado':
        recusados = {'geral': {'veredito': 'recusado', 'motivo': validacao.get('motivo') or ''}}
    partes = [f"# Correção da extração · pedido {pedido['id']} · execução {execucao['execucao']}", '',
              f"Repositório CAIOZANETTI/ialocal.projeto, código {execucao.get('versao_codigo')} (commit {execucao.get('commit') or '?'}). "
              f"{validacao.get('de') or 'Quem validou'} recusou a extração de \"{pedido.get('assunto', '')}\" em "
              f"{validacao['recebido_em'][:16].replace('T', ' ')}.", '',
              '## O que foi recusado e por quê', '']
    for item, juizo in recusados.items():
        partes += [f"- **{NOMES.get(item, item)}**: {juizo.get('motivo') or '(sem motivo escrito)'}",
                   f"  - onde mexer: {CODIGO_DO_ITEM.get(item, 'ver notas/saidas_e_rastro.md')}"]
    if validacao.get('texto'):
        partes += ['', 'Resposta inteira de quem validou:', '', *(f'> {l}' for l in validacao['texto'].strip().splitlines()[:40])]
    partes += ['', '## O que o mini extraiu (o resultado recusado)', '', '```', execucao.get('texto', '').split('PARA VALIDAR')[0].strip(), '```', '',
               '## Ferramentas e IAs usadas', '']
    for f in execucao.get('ferramentas', []):
        partes.append(f"- {f.get('onde', 'código') if f['tarefa'] == 'modelo' else 'código/tarefa'} · "
                      f"{f['modelo'] if f['tarefa'] == 'modelo' else f['tarefa'] + ' — ' + f['ferramenta']}: {f['segundos']} s")
    partes += ['', '## Como corrigir', '',
               f"1. Os PDFs estão no mini em ~/dados/ialocal.web/saidas/pedidos/{pedido['id']}/anexos/ e os CSVs do que saiu em "
               f"~/dados/ialocal.projeto/saidas/pedidos/{pedido['id']}/{execucao['execucao']}/ (anexos deste e-mail).",
               '2. Ache a causa no código do item (acima); prefira mudar a regra em conceitos/*.json quando for rótulo, padrão ou cor.',
               '3. Escreva um teste em codigo/testes.py com o caso recusado (o PDF sintético que o reproduz) e rode .venv/bin/python codigo/testes.py.',
               '4. Nova linha em codigo/versoes.jsonl (muda: as tarefas cuja leitura mudou) e o PR. Aprovado, o mini puxa a main e roda o pedido '
               'de novo sozinho (o commit mudou e houve recusa); o resultado novo volta no mesmo fio, com o que mudou.']
    return '\n'.join(partes) + '\n'


def correcoes():
    """Para cada validação com recusa ainda sem prompt: o correcao_<recebido>.md na pasta da execução que ela julgou
    (a última que terminou antes dela). Devolve quantos escreveu."""
    escritos = 0
    for p in pedidos():
        feitas = execucoes(p['id'])
        for v in p['validacoes']:
            julgada = [e for k, e in enumerate(feitas) if julga(v, e, feitas[k + 1] if k + 1 < len(feitas) else None)]
            if not recusou(v) or not julgada:
                continue
            destino = saida() / p['id'] / julgada[-1]['execucao'] / f"correcao_{instante(v['recebido_em']):%Y%m%dT%H%M%S}.md"
            if not destino.exists():
                comum.gravar_no_lugar(destino, prompt_de_correcao(p, julgada[-1], v))
                escritos += 1
    return escritos


def resumo():
    """O bloco pedido do status.json: o em curso (o maestro pausa os pesados enquanto ele roda), os na fila e o placar."""
    agora_, lista = ativo(), pedidos()
    fila = [p['id'] for p, _ in pendentes()] if lista else []
    vereditos = Counter()
    for p in lista:
        for v in p['validacoes']:
            vereditos[v.get('veredito') or 'sem_veredito'] += 1
    return {'ativo': bool(agora_ or fila), 'id': (agora_ or {}).get('pedido') or (fila[0] if fila else ''),
            'desde': (agora_ or {}).get('desde', ''), 'na_fila': len(fila), 'recebidos': len(lista), 'validacoes': dict(vereditos)}


def status():
    """O status.json de novo, com o bloco pedido: de dia a rodada não roda (o maestro a tira do launchd) e é por aqui
    que o maestro sabe que há pedido em curso (e pausa os pesados de noite). Falha aqui não para o pedido."""
    try:
        import entrega
        ensaio.ciclo.status(entrega.documentos())
    except Exception as falha:
        print(f'status não regravado: {type(falha).__name__}: {falha}', flush=True)


def vigiar():
    """Os pedidos pendentes, um por vez, até não sobrar nenhum (o que chega no meio entra na mesma volta); calado
    quando não há nada."""
    with trava() as minha:
        if not minha:
            return
        rodados = correcoes()
        while fila := pendentes():
            pedido, motivo = fila[0]
            rodar(pedido, motivo)
            rodados += 1
        if rodados:
            placar()


def lista():
    for p in pedidos():
        print(f"{p['id']}  {p.get('assunto', '')[:60]}  ({len(list(p['pasta'].glob('anexos/*')))} anexo(s), de {p.get('de')})")
        for e in execucoes(p['id']):
            print(f"   {e['execucao']}  {e['inicio'][:16]}  {e.get('commit')}  {segundos(e.get('segundos'))}  {len(e.get('documentos', []))} doc  "
                  f"{e.get('motivo')}{'  ERRO ' + e['erro'] if e.get('erro') else ''}")
        for v in p['validacoes']:
            itens_ = ', '.join(f"{k} {i.get('veredito')}" for k, i in (v.get('itens') or {}).items())
            print(f"   validação {v['recebido_em'][:16]}: {v.get('veredito') or '—'}{' (refazer)' if v.get('refazer') else ''} {itens_}")


def principal(argumentos):
    comando = argumentos[0] if argumentos else 'vigiar'
    if comando == 'vigiar':
        return vigiar()
    if comando == 'lista':
        return lista()
    if comando == 'rodar' and argumentos[1:]:
        alvo = next((p for p in pedidos() if p['id'] == argumentos[1]), None)
        if alvo is None:
            sys.exit(f'pedido {argumentos[1]} não está em {entrada()}')
        with trava() as minha:
            if not minha:
                sys.exit('outro pedido está rodando: tente quando ele terminar')
            rodar(alvo, 'à mão')
            placar()
        return
    print(__doc__)


if __name__ == '__main__':
    principal(sys.argv[1:])
