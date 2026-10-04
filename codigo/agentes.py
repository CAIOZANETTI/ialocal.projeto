"""Os agentes externos (notas/plano_agentes_nvidia.md; exceção do MASTER-PLAN §5.6): modelos gratuitos do catálogo da
NVIDIA que leem os mesmos recortes que o glm-ocr e o Vision, em paralelo, fora da vez da GPU (a inferência é remota).
Cada agente devolve a leitura no formato dos leitores locais — texto, linhas de tabela e, no parse, as caixas — para os
padrões do código (prancha.json, sondagem.json) acharem os valores. Agente é leitor candidato: quem diz o que é
confirmado é a curadoria em Python, e confirmado continua exigindo uma testemunha que não gera texto.

    .venv/bin/python codigo/agentes.py sondar              # F1: a imagem da sonda (agentes.json → sonda) a cada agente
    .venv/bin/python codigo/agentes.py sondar <imagem>…    # outras imagens (a tabela de Cambé com o nome dela é medida)
"""
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import comum
import ia
import prancha

REGISTRO = comum.DADOS / 'agentes.jsonl'
SONDA = comum.DADOS / 'agentes_sonda.jsonl'
CAMBE = comum.RAIZ / 'amostras' / 'tabelas' / '216_cambe' / 'CÓDIGO;Nº;DISCRIMINAÇÃO;QUANT.;UND..txt'


def configuracao():
    return comum.configuracao('agentes')


def permitido(obra=None):
    """'' se o agente pode ser chamado; senão o motivo: desligado, fora do prazo da exceção, sem chave ou obra fora da
    lista. Quem chama não chama e grava o motivo."""
    AGENTES = configuracao()
    if not AGENTES['ligado']:
        return 'agentes desligados (agentes.json → ligado)'
    if date.today().isoformat() > AGENTES['prazo_fim']:
        return f"fora do prazo da exceção (MASTER-PLAN §5.6, até {AGENTES['prazo_fim']})"
    if not ia.chave_nvidia():
        return f"sem a chave da NVIDIA ({AGENTES['chave']} ou NVIDIA_API_KEY)"
    if obra is not None and '*' not in AGENTES['obras_permitidas'] and obra not in AGENTES['obras_permitidas']:
        return f'obra fora de agentes.json → obras_permitidas: {obra}'
    return ''


def sem_cerca(texto):
    """O conteúdo sem o raciocínio que vaza (<think>…</think>) e sem a cerca de código em volta (```html … ```)."""
    texto = re.sub(r'<think>.*?</think>', '', texto or '', flags=re.S).strip()
    achado = re.fullmatch(r'```[\w-]*\n?(.*?)\n?```', texto, re.S)
    return achado.group(1).strip() if achado else texto


def linhas_da_tabela(texto):
    """As linhas de uma tabela como o modelo a escreveu — HTML, LaTeX (tabular) ou markdown com barras —, cada célula
    sem marcação; a linha repetida sai (como no linhas_html do glm-ocr)."""
    if re.search(r'<tr', texto, re.I):
        return prancha.linhas_html(texto)
    if '\\begin{tabular}' in texto or ('&' in texto and '\\\\' in texto):
        corpo = re.sub(r'\\(?:begin|end)\{tabular\}(?:\{[^}]*\})?|\\hline|\\toprule|\\midrule|\\bottomrule', '', texto)
        corpo = re.sub(r'\\multi(?:column|row)\{[^}]*\}\{[^}]*\}\{([^}]*)\}', r'\1', corpo)
        brutas = [[c.strip() for c in linha.split('&')] for linha in corpo.split('\\\\')]
    else:
        brutas = [[c.strip() for c in linha.strip().strip('|').split('|')] for linha in texto.splitlines()
                  if '|' in linha and not re.fullmatch(r'[\s|:\-]+', linha)]
    vistas, linhas = set(), []
    for celulas in brutas:
        if any(celulas) and tuple(celulas) not in vistas:
            vistas.add(tuple(celulas))
            linhas.append(celulas)
    return linhas


MARCAS = re.compile(r'<x_([\d.]+)><y_([\d.]+)>(.*?)<x_([\d.]+)><y_([\d.]+)><class_([^>]+)>', re.S)


def elementos_do_parse(resposta):
    """Os elementos que o Nemotron Parse leu: {'classe', 'texto', 'caixa' (x0, y0, x1, y1 de 0 a 1) ou None}. A resposta
    vem nos argumentos da ferramenta (JSON: lista de {'bbox', 'text', 'type'}, às vezes dentro de outra lista) ou no
    texto com as marcas <x_><y_>…<class_>; sem nenhum dos dois, o texto inteiro é um elemento sem caixa."""
    elementos = []
    for argumentos in resposta['ferramentas']:
        achados = json.loads(argumentos) if isinstance(argumentos, str) else argumentos
        while isinstance(achados, list) and len(achados) == 1 and isinstance(achados[0], list):
            achados = achados[0]
        for item in achados if isinstance(achados, list) else [achados]:
            caixa = item.get('bbox') or {}
            elementos.append({'classe': item.get('type', ''), 'texto': item.get('text', ''),
                              'caixa': tuple(caixa[k] for k in ('xmin', 'ymin', 'xmax', 'ymax')) if caixa else None})
    if not elementos and MARCAS.search(resposta['texto']):
        elementos = [{'classe': m.group(6), 'texto': m.group(3).strip(),
                      'caixa': tuple(float(m.group(i)) for i in (1, 2, 4, 5))} for m in MARCAS.finditer(resposta['texto'])]
    if not elementos and resposta['texto'].strip():
        elementos = [{'classe': 'Text', 'texto': sem_cerca(resposta['texto']), 'caixa': None}]
    return elementos


def ler_com_kimi(nome, imagem, modo):
    """Um VLM do catálogo (o Kimi K3 ou um reserva do mesmo tipo): transcreve o recorte (modo texto) ou a tabela em HTML
    (modo tabela), com as regras comuns na frente do pedido."""
    AGENTE = configuracao()['agentes'][nome]
    pedido = ia.ler_prompt(AGENTE['prompt'][modo])[0]
    bruta, meta = ia.nvidia(AGENTE['modelo'], pedido, [imagem], {'max_tokens': AGENTE['max_tokens']},
                            AGENTE['lado_max_px'], AGENTE['timeout_s'], AGENTE['por_minuto'])
    conteudo = sem_cerca(json.loads(bruta)['texto'])
    linhas = linhas_da_tabela(conteudo) if modo == 'tabela' else []
    texto = '\n'.join(' '.join(celulas) for celulas in linhas) if linhas else conteudo
    return {'texto': texto, 'linhas': linhas, 'caixas': [], 'meta': meta}


def ler_com_parse(nome, imagem, modo):
    """O Nemotron Parse: o texto de cada elemento com a caixa e a classe; as tabelas que ele achou viram linhas (em
    qualquer modo: o parse não recebe pedido, só a ferramenta ou as marcas de controle)."""
    AGENTE = configuracao()['agentes'][nome]
    opcoes = {'max_tokens': AGENTE['max_tokens']} if AGENTE.get('max_tokens') else {}
    if AGENTE.get('ferramenta'):
        opcoes['tools'] = [{'type': 'function', 'function': {'name': AGENTE['ferramenta']}}]
    bruta, meta = ia.nvidia(AGENTE['modelo'], AGENTE.get('controle', ''), [imagem], opcoes,
                            AGENTE['lado_max_px'], AGENTE['timeout_s'], AGENTE['por_minuto'])
    elementos = elementos_do_parse(json.loads(bruta))
    linhas = [l for e in elementos if e['classe'].lower() == 'table' or '<tr' in e['texto'] for l in linhas_da_tabela(e['texto'])]
    return {'texto': '\n'.join(e['texto'] for e in elementos), 'linhas': linhas,
            'caixas': [{'classe': e['classe'], 'caixa': e['caixa'], 'texto': e['texto'][:200]} for e in elementos], 'meta': meta}


LEITORES = {'vlm': ler_com_kimi, 'parser': ler_com_parse}


def ler_com_agente(nome, imagem, modo='texto', obra=None):
    """Um recorte por um agente; nunca sobe erro: falha (do agente ou da permissão) vira leitura vazia com o motivo, e a
    leitura segue com os outros. Toda chamada fica em dados/agentes.jsonl (o registro da exceção §5.6)."""
    marca = time.perf_counter()
    motivo = permitido(obra)
    if motivo:
        return {'texto': '', 'linhas': [], 'caixas': [], 'meta': {}, 'erro': motivo, 'segundos': 0.0}
    AGENTE = configuracao()['agentes'][nome]
    try:
        lida = {**LEITORES[AGENTE['tipo']](nome, imagem, modo), 'erro': ''}
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as falha:
        lida = {'texto': '', 'linhas': [], 'caixas': [], 'meta': {}, 'erro': f'{type(falha).__name__}: {falha}'[:800]}
    lida['segundos'] = round(time.perf_counter() - marca, 2)
    comum.anexar(REGISTRO, json.dumps({
        'em': comum.agora(), 'agente': nome, 'modelo': AGENTE['modelo'], 'modelo_devolvido': lida['meta'].get('modelo', ''),
        'recorte': Path(imagem).name, 'obra': obra or '', 'modo': modo, 'congelado': lida['meta'].get('congelado'),
        'segundos': lida['segundos'], 'tokens_entrada': lida['meta'].get('tokens_entrada'),
        'tokens_saida': lida['meta'].get('tokens_saida'), 'erro': lida['erro'], **comum.codigo()}, ensure_ascii=False) + '\n')
    return lida


def em_paralelo(recortes, nomes=None, modo='texto', obra=None, progresso=False):
    """Cada recorte por cada agente ao mesmo tempo, `simultaneas` pedidos por agente (e o ritmo por_minuto do ia.nvidia);
    devolve as leituras à medida que chegam, com o agente e o recorte. Falha de um não para os outros. `progresso`:
    uma linha na tela por leitura que volta (a bancada)."""
    AGENTES = configuracao()['agentes']
    nomes = list(nomes or AGENTES)
    ia.congelados()  # carregado antes das threads: todas acrescentam no mesmo dicionário
    filas = {nome: ThreadPoolExecutor(max_workers=AGENTES[nome]['simultaneas'], thread_name_prefix=nome) for nome in nomes}
    terminou = False
    try:
        pedidos = {filas[nome].submit(ler_com_agente, nome, recorte, modo, obra): (nome, recorte) for recorte in recortes for nome in nomes}
        for numero, feito in enumerate(as_completed(pedidos), 1):
            nome, recorte = pedidos[feito]
            lida = {'agente': nome, 'recorte': str(recorte), **feito.result()}
            if progresso:
                print(f"{numero:>4}/{len(pedidos)}  {nome:<6} {Path(recorte).name[:34]:<34} {lida['segundos']:6.1f} s  "
                      f"{'congelado' if lida['meta'].get('congelado') else '':<9} linhas {len(lida['linhas']):>3}"
                      + (f"  tentativas {lida['meta']['tentativas']} ({','.join(lida['meta'].get('motivos', []))})"
                         if lida['meta'].get('tentativas', 1) > 1 else '') + (f"  ERRO {lida['erro'][:100]}" if lida['erro'] else ''), flush=True)
            yield lida
        terminou = True
    finally:  # Ctrl+C ou erro: não espera as chamadas em curso (o que já voltou está congelado)
        for fila in filas.values():
            fila.shutdown(wait=terminou, cancel_futures=not terminou)


def gabarito_cambe():
    """'TABELA 01' (o nome da imagem em maiúsculas) → as linhas transcritas pelo Caio: {'codigo', 'quant', 'und', 'linha'}."""
    tabelas, atual = {}, None
    for linha in CAMBE.read_text(encoding='utf-8-sig').splitlines():
        if re.match(r'TABELA\s', linha):
            atual = tabelas.setdefault(linha.strip().upper(), [])
        elif atual is not None and re.match(r'\d', linha):
            celulas = linha.split(';')
            atual.append({'codigo': celulas[0], 'quant': celulas[3], 'und': celulas[4], 'linha': celulas})
    return tabelas


def placar_tabela(linhas, gabarito):
    """Linhas lidas × gabarito, pelo código: achadas (o código está numa linha lida), certas (na mesma linha, também a
    quantidade e a unidade) e inventadas (linha lida que começa por um código que o gabarito não tem)."""
    unidade = lambda u: prancha.normalizar(u).rstrip('.')
    por_codigo = {}
    for celulas in linhas:
        for celula in celulas:
            por_codigo.setdefault(celula.strip(), []).append({prancha.normalizar(c) for c in celulas} | {unidade(c) for c in celulas})
    achadas = [g for g in gabarito if g['codigo'] in por_codigo]
    certas = [g for g in achadas if any(prancha.normalizar(g['quant']) in lida and unidade(g['und']) in lida for lida in por_codigo[g['codigo']])]
    codigos = {g['codigo'] for g in gabarito}
    inventadas = [c for c in linhas if c and re.fullmatch(r'\d{4,6}', c[0].strip()) and c[0].strip() not in codigos]
    return {'gabarito': len(gabarito), 'achadas': len(achadas), 'certas': len(certas), 'inventadas': len(inventadas),
            'lidas': len(linhas)}


def sondar(imagens=None):
    """F1: cada imagem a cada agente, em paralelo, no modo tabela; a resposta inteira vai a dados/agentes_sonda.jsonl
    (é ela que diz o formato que a API devolve) e a tela mostra tempo, tokens e, na tabela de Cambé, o placar."""
    AGENTES = configuracao()
    motivo = permitido()
    if motivo:
        print(f'sonda parada: {motivo}')
        return []
    imagens = [Path(i) for i in imagens or [comum.RAIZ / AGENTES['sonda']]]
    gabaritos = gabarito_cambe()
    resultados = []
    for lida in em_paralelo(imagens, modo='tabela'):
        gabarito = gabaritos.get(Path(lida['recorte']).stem.upper())
        placar = placar_tabela(lida['linhas'], gabarito) if gabarito else {}
        resultado = {'em': comum.agora(), **{k: v for k, v in lida.items() if k != 'caixas'},
                     'caixas': lida['caixas'][:50], 'placar': placar}
        comum.anexar(SONDA, json.dumps(resultado, ensure_ascii=False, default=str) + '\n')
        resultados.append(resultado)
        meta = lida['meta']
        print(f"{lida['agente']:<6} {Path(lida['recorte']).name[:30]:<30} {lida['segundos']:7.1f} s  "
              f"{meta.get('modelo', '')[:28]:<28} tokens {meta.get('tokens_entrada')}/{meta.get('tokens_saida')}  "
              f"linhas {len(lida['linhas'])}  caixas {len(lida['caixas'])}"
              + (f"  Cambé: {placar['certas']}/{placar['gabarito']} certas, {placar['inventadas']} inventadas" if placar else '')
              + (f"  ERRO {lida['erro'][:400]}" if lida['erro'] else ''), flush=True)
    return resultados


def sair_no_ctrl_c(funcao, *argumentos):
    """Roda a função; no Ctrl+C sai na hora, sem esperar as chamadas em curso (as threads do urllib só voltariam no
    timeout). O que já voltou está no congelamento: a próxima rodada continua dali."""
    import os
    try:
        return funcao(*argumentos)
    except KeyboardInterrupt:
        print('\ninterrompido: o que já voltou está congelado (dados/congelamento.jsonl); a próxima rodada continua dali', flush=True)
        os._exit(130)


if __name__ == '__main__':
    if sys.argv[1:2] == ['sondar']:
        sair_no_ctrl_c(sondar, sys.argv[2:])
    else:
        print(__doc__)
