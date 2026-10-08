"""A velocidade do pedido (0v32, Caio 08/10: "a última tarefa gastou 9 minutos; preciso saber todos os tempos — quando
recebeu, entrou, a fila… maestro > projeto > ollama > python, tudo"). Um cronômetro por execução do pedido:

    marcos      os instantes da execução (recebido no web, pego pelo projeto, fim do código, GPU pedida e concedida,
                fim da IA, entrega, resultado gravado), cada um com o tempo desde o início e desde o anterior
    funções     as de conceitos/operacao.json → pedidos.velocidade.funcoes, embrulhadas só durante o pedido: chamadas,
                segundos (com as que ela chama), proprio_s (sem elas), máximo e erros, cada uma na sua camada
    chamadas    o meta de cada resposta de modelo (ia.anotar): no Ollama, o carregar, o ler o prompt e o gerar, com os
                tokens (os tempos que o próprio Ollama devolve no fim da resposta)

    with tempo.cronometrar(['ia.ollama', 'prancha.ler_fatias']) as cronometro:
        tempo.marco('pego_pelo_projeto')
        ...
    resultado['velocidade'] = cronometro.velocidade()

Fora de um cronômetro, marco e chamada não fazem nada: a rodada de sempre não paga nada por isso.
"""
import functools
import importlib
import sys
import threading
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ATUAL = None  # o cronômetro em curso (um pedido por vez: pedido.trava)
CAMADAS = {  # camada → o que é, na ordem do caminho do pedido
    'email_ate_o_web': 'do Date: do e-mail de quem pediu até o web guardar o pedido (o Gmail, a leitura do IMAP a cada minuto)',
    'fila_ate_o_projeto': 'do e-mail guardado pelo web até o projeto pegar o pedido (o launchd a cada minuto, a trava de um pedido por vez)',
    'maestro_fila_gpu': 'esperando a vez da GPU no maestro (cliente_gpu.vez_da_gpu)',
    'ollama': 'o Ollama local respondendo (glm-ocr, gemma, qwen): carregar o modelo, ler o prompt e a imagem, gerar',
    'vision': 'o Vision do macOS, num processo à parte',
    'apple_fm': 'o modelo da Apple no aparelho',
    'agentes_web': 'os agentes de fora (NVIDIA): a fila deles e a resposta',
    'python': 'o código: pypdfium2, pdfminer, geometria, recortes, conferência, gravar os CSVs e a entrega',
}


def agora():
    return datetime.now().astimezone().replace(tzinfo=None)


def em_texto(momento):
    return momento.isoformat(timespec='milliseconds')


class Cronometro:
    def __init__(self, camadas_das_funcoes):
        self.camada_de = camadas_das_funcoes
        self.funcoes, self.marcos, self.chamadas = {}, [], []
        self.documento = ''
        self.trava, self.local = threading.Lock(), threading.local()
        self.nao_achadas = []

    def pilha(self):
        if not hasattr(self.local, 'pilha'):
            self.local.pilha = []
        return self.local.pilha

    def embrulhar(self, nome, original):
        @functools.wraps(original)
        def medido(*args, **kwargs):
            pilha = self.pilha()
            pilha.append(0.0)
            marca, erro = time.perf_counter(), False
            try:
                return original(*args, **kwargs)
            except BaseException:
                erro = True
                raise
            finally:
                gasto, filhos = time.perf_counter() - marca, pilha.pop()
                if pilha:
                    pilha[-1] += gasto
                with self.trava:
                    soma = self.funcoes.setdefault(nome, {'funcao': nome, 'camada': self.camada_de.get(nome, 'python'), 'chamadas': 0,
                                                          'segundos': 0.0, 'proprio_s': 0.0, 'maximo_s': 0.0, 'erros': 0})
                    soma['chamadas'] += 1
                    soma['segundos'] += gasto
                    soma['proprio_s'] += max(0.0, gasto - filhos)
                    soma['maximo_s'] = max(soma['maximo_s'], gasto)
                    soma['erros'] += erro
        return medido

    def marco(self, nome, em=None, quem='projeto'):
        self.marcos.append({'marco': nome, 'quem': quem, 'em': em or agora()})

    def chamada(self, meta):
        with self.trava:
            self.chamadas.append({**meta, 'documento': self.documento})

    def velocidade(self, espera_gpu_s=0.0):
        """A seção velocidade do resultado.json."""
        marcos = sorted(self.marcos, key=lambda m: m['em'])
        inicio = marcos[0]['em'] if marcos else agora()
        linha, anterior = [], inicio
        for m in marcos:
            linha.append({'marco': m['marco'], 'quem': m['quem'], 'em': em_texto(m['em']),
                          'desde_inicio_s': round((m['em'] - inicio).total_seconds(), 2),
                          'desde_anterior_s': round((m['em'] - anterior).total_seconds(), 2)})
            anterior = m['em']
        quando = {m['marco']: m['em'] for m in marcos}
        total = round((marcos[-1]['em'] - inicio).total_seconds(), 2) if marcos else 0.0
        por_funcao = sorted(({**f, 'segundos': round(f['segundos'], 3), 'proprio_s': round(f['proprio_s'], 3),
                              'maximo_s': round(f['maximo_s'], 3), 'media_s': round(f['segundos'] / f['chamadas'], 3)}
                             for f in self.funcoes.values()), key=lambda f: -f['proprio_s'])
        modelos = self.ollama()
        camadas = self.por_camada(quando, total, espera_gpu_s, por_funcao)
        return {'total_s': total, 'de': linha[0]['marco'] if linha else '', 'ate': linha[-1]['marco'] if linha else '',
                'linha_do_tempo': linha, 'por_camada': camadas, 'por_funcao': por_funcao, 'ollama': modelos,
                'gargalo': gargalo(camadas, modelos, total), 'nao_medidas': self.nao_achadas}

    def por_camada(self, quando, total, espera_gpu_s, por_funcao):
        """O total partido nas camadas: a fila até o projeto e a da GPU pelos marcos; o Ollama, o Vision, a Apple e os
        agentes pelas funções embrulhadas (o tempo delas, com o que chamam); o python é o resto."""
        entre = lambda a, b: (quando[b] - quando[a]).total_seconds() if {a, b} <= set(quando) else 0.0
        motores = {c: sum(f['segundos'] for f in por_funcao if f['funcao'] == self.raiz(c))  # a função que fala com o motor
                   for c in ('ollama', 'vision', 'apple_fm', 'agentes_web')}
        valores = {'email_ate_o_web': max(0.0, entre('enviado_por_quem_pediu', 'recebido_no_web')),
                   'fila_ate_o_projeto': max(0.0, entre('recebido_no_web', 'pego_pelo_projeto')), 'maestro_fila_gpu': espera_gpu_s, **motores}
        valores['python'] = max(0.0, total - sum(valores.values()))
        return [{'camada': c, 'segundos': round(valores[c], 2), 'pct': round(100 * valores[c] / total, 1) if total else 0.0, 'o_que': CAMADAS[c]}
                for c in CAMADAS if valores.get(c) or c == 'python']

    def raiz(self, camada):
        """A função que mede a camada inteira (a mais de baixo, a que fala com o motor)."""
        return {'ollama': 'ia.ollama', 'vision': 'ia.ler_com_vision', 'apple_fm': 'ia.apple', 'agentes_web': 'ia.nvidia'}[camada]

    def ollama(self):
        """Por modelo: as chamadas (as do congelamento não gastam), os segundos de relógio e os que o Ollama diz que
        gastou carregando, lendo o prompt e gerando; os tokens e a velocidade; como cada resposta terminou; as 5 mais
        lentas."""
        modelos = {}
        for c in self.chamadas:
            if c.get('motor') != 'ollama':
                continue
            m = modelos.setdefault(c.get('modelo', '?'), {'modelo': c.get('modelo', '?'), 'chamadas': 0, 'congeladas': 0, 'segundos': 0.0,
                                                          'carregar_s': 0.0, 'prompt_s': 0.0, 'gerar_s': 0.0,
                                                          'tokens_entrada': 0, 'tokens_saida': 0, 'fins': Counter()})
            m['chamadas'] += 1
            if c.get('congelado'):
                m['congeladas'] += 1
                continue
            m['segundos'] += c.get('segundos') or 0
            for campo in ('carregar_s', 'prompt_s', 'gerar_s'):
                m[campo] += c.get(campo) or 0
            m['tokens_entrada'] += c.get('tokens_entrada') or 0
            m['tokens_saida'] += c.get('tokens_saida') or c.get('tokens') or 0
            m['fins'][str(c.get('fim'))] += 1
        for m in modelos.values():
            for campo in ('segundos', 'carregar_s', 'prompt_s', 'gerar_s'):
                m[campo] = round(m[campo], 2)
            m['tokens_por_s'] = round(m['tokens_saida'] / m['gerar_s'], 1) if m['gerar_s'] else None
            m['fins'] = dict(m['fins'])
        lentas = sorted((c for c in self.chamadas if c.get('motor') == 'ollama' and not c.get('congelado')), key=lambda c: -(c.get('segundos') or 0))[:5]
        return {'modelos': sorted(modelos.values(), key=lambda m: -m['segundos']),
                'lentas': [{k: c.get(k) for k in ('modelo', 'documento', 'segundos', 'carregar_s', 'prompt_s', 'gerar_s', 'tokens_entrada', 'tokens_saida', 'fim')}
                           for c in lentas]}


def gargalo(camadas, ollama, total):
    """Uma frase: onde foi o tempo."""
    if not total or not camadas:
        return ''
    maior = max(camadas, key=lambda c: c['segundos'])
    frase = f"{maior['camada']}: {maior['segundos']} s de {total} s ({maior['pct']}%)"
    if maior['camada'] == 'ollama' and ollama['modelos']:
        m = ollama['modelos'][0]
        fins = ', '.join(f'{n} {fim}' for fim, n in m['fins'].items())
        frase += (f" — {m['modelo']} em {m['chamadas'] - m['congeladas']} chamada(s): carregar {m['carregar_s']} s, prompt "
                  f"{m['prompt_s']} s, gerar {m['gerar_s']} s ({m['tokens_saida']} tokens, {m['tokens_por_s']} tokens/s); fim: {fins}")
    return frase


@contextmanager
def cronometrar(funcoes):
    """Embrulha as funções ('modulo.funcao' ou {'funcao': ..., 'camada': ...}) enquanto dura o bloco e devolve o
    cronômetro. A que não existe fica em nao_medidas (o nome mudou no código: a lista em operacao.json fica velha)."""
    global ATUAL
    nomes = [f if isinstance(f, str) else f['funcao'] for f in funcoes]
    camadas = {f['funcao']: f['camada'] for f in funcoes if isinstance(f, dict) and f.get('camada')}
    cronometro, trocadas = Cronometro({**{'ia.ollama': 'ollama', 'ia.ler_com_vision': 'vision', 'ia.apple': 'apple_fm', 'ia.nvidia': 'agentes_web'}, **camadas}), []
    for nome in nomes:
        modulo_nome, _, funcao = nome.rpartition('.')
        try:
            modulo = modulo_de(modulo_nome)
            original = getattr(modulo, funcao)
        except (ImportError, AttributeError, ValueError):
            cronometro.nao_achadas.append(nome)
            continue
        setattr(modulo, funcao, cronometro.embrulhar(nome, original))
        trocadas.append((modulo, funcao, original))
    ATUAL = cronometro
    try:
        yield cronometro
    finally:
        ATUAL = None
        for modulo, funcao, original in reversed(trocadas):
            setattr(modulo, funcao, original)


def modulo_de(nome):
    """O módulo carregado com esse nome; o script em curso (python codigo/pedido.py) é o __main__, não um segundo pedido."""
    principal = sys.modules.get('__main__')
    if getattr(principal, '__file__', None) and Path(principal.__file__).stem == nome:
        return principal
    return sys.modules.get(nome) or importlib.import_module(nome)


def marco(nome, em=None, quem='projeto'):
    if ATUAL is not None:
        ATUAL.marco(nome, em, quem)


def chamada(meta):
    if ATUAL is not None:
        ATUAL.chamada(meta)


def documento(nome):
    """O documento em curso: vai em cada chamada de modelo (as mais lentas dizem de que prancha eram)."""
    if ATUAL is not None:
        ATUAL.documento = nome
