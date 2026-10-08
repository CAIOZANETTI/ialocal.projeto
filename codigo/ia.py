"""A única porta do projeto para os modelos: os do mini (§5.4) — Ollama (glm-ocr, qwen3), o Vision do macOS e o modelo
do dispositivo da Apple — e, na exceção do MASTER-PLAN §5.6 (só este repositório, com prazo), os agentes do catálogo
da NVIDIA (nvidia(); conceitos/agentes.json). Toda resposta é congelada com a configuração inteira (§8.2): a mesma
chave devolve a resposta guardada em dados/congelamento.jsonl, sem chamar o modelo de novo.

Copiado de ialocal.extrator/codigo/modelos_ia.py e extracao.py (2v93) só no que a prancha usa: cópia, não import —
cada repositório roda sozinho. O texto da prancha vai como dado, nunca como instrução (princípio 10).
"""
import base64
import functools
import hashlib
import importlib.util
import io
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime
from pathlib import Path

import cliente_gpu
import comum
import tempo

CONGELAMENTO = comum.DADOS / 'congelamento.jsonl'
REFAZER = False  # a bancada com --refazer: chama de novo e regrava, para medir o tempo nas mesmas condições
CHAMADAS = threading.local()  # o meta de cada resposta (guardada ou nova) desta thread: quem mede soma o tempo útil
OLLAMA = 'http://localhost:11434'
REPETICAO = 'token repeat limit'  # o 500 do Ollama quando o modelo entra em laço (glm-ocr, ollama#18609)


def ler_prompt(nome, regras=True):
    """O prompt com as regras comuns na frente (conceitos/prompts/_regras.txt: não inventar, vazio é resposta certa);
    o glm-ocr recebe só o pedido curto dele. O hash do texto entra na chave de congelamento."""
    pasta = comum.RAIZ / 'conceitos' / 'prompts'
    texto = ((pasta / '_regras.txt').read_text() + '\n' if regras else '') + (pasta / f'{nome}.txt').read_text()
    return texto, hashlib.sha256(texto.encode()).hexdigest()[:16]


@functools.cache
def congelados():
    if not CONGELAMENTO.exists():
        return {}
    return {r['assinatura']: r for r in map(json.loads, CONGELAMENTO.read_text().splitlines())}


def congelado(chave, chamar, refazer=False):
    """Resposta guardada para a mesma chave; senão chama e acrescenta ao JSONL (a nova fica no lugar da guardada).
    `refazer`: chama de novo só esta (a falha guardada de um agente, agentes.ler_com_agente)."""
    assinatura = hashlib.sha256(json.dumps(chave, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    guardado = None if REFAZER or refazer else congelados().get(assinatura)
    if guardado:
        meta = {**guardado['meta'], 'congelado': True}
        anotar(meta)
        return guardado['resposta'], meta
    marca = time.perf_counter()
    resposta, meta = chamar()
    meta = {**meta, 'segundos': round(time.perf_counter() - marca, 2), 'congelado': False}
    anotar(meta)
    registro = {'assinatura': assinatura, 'chave': chave, 'resposta': resposta, 'meta': meta,
                'em': datetime.now().isoformat(timespec='seconds')}
    comum.anexar(CONGELAMENTO, json.dumps(registro, ensure_ascii=False) + '\n')
    congelados()[assinatura] = registro
    return resposta, meta


def anotar(meta):
    """Guarda o meta da resposta para quem mede e dá o sinal de vida da vez da GPU (maestro 0v66): cada resposta de
    modelo é um avanço de verdade; sem vez, não faz nada."""
    cliente_gpu.avancei()
    tempo.chamada(meta)
    if not hasattr(CHAMADAS, 'lista'):
        CHAMADAS.lista = []
    CHAMADAS.lista.append(meta)


def medir():
    """Zera a lista desta thread; quem mede chama antes e lê CHAMADAS.lista depois (uma leitura pode ser várias
    chamadas: as faixas do glm-ocr)."""
    CHAMADAS.lista = []
    return CHAMADAS.lista


def instalado(modulo):
    """O pacote está no python do .venv? (sem importar: o Vision e o apple_fm_sdk só existem no macOS)"""
    try:
        return modulo in sys.modules or importlib.util.find_spec(modulo) is not None
    except ValueError:
        return modulo in sys.modules


def imagem_para_ia(caminho, lado=None):
    """A imagem como vai ao modelo: o lado maior até `lado` (sem ele, lado_max_px_ia de conceitos/ia.json)."""
    from PIL import Image
    LADO = lado or comum.configuracao('ia')['lado_max_px_ia']
    with Image.open(caminho) as imagem:
        if max(imagem.size) <= LADO:
            return Path(caminho).read_bytes()
        reduzida = imagem.convert('RGB')
        reduzida.thumbnail((LADO, LADO))
        saida = io.BytesIO()
        reduzida.save(saida, format='PNG')
        return saida.getvalue()


@functools.cache
def versao_ollama():
    try:
        with urllib.request.urlopen(f'{OLLAMA}/api/version', timeout=10) as resposta:
            return json.load(resposta)['version']
    except OSError:
        return ''


def ollama(modelo, prompt, esquema=None, imagens=(), parcial=False):
    """Resposta do Ollama local: temperatura 0, esquema JSON quando há, sem raciocínio visível. O digest do modelo
    entra na chave. `parcial`: a resposta vem em partes e, abortada pela trava de repetição, o texto até ali volta
    com meta['fim'] = 'abortado'."""
    with urllib.request.urlopen(f'{OLLAMA}/api/tags', timeout=10) as resposta:
        digest = next(m['digest'] for m in json.load(resposta)['models'] if m['name'] == modelo)
    corpo = {'model': modelo, 'prompt': prompt, 'stream': parcial, 'think': False,
             'options': {'temperature': 0, 'seed': 0, **comum.configuracao('ia')['opcoes_por_modelo'].get(modelo, {})},
             'images': [base64.b64encode(imagem_para_ia(i)).decode() for i in imagens]}
    if esquema:
        corpo['format'] = esquema
    chave = {'motor': 'ollama', 'modelo': modelo, 'digest': digest, 'prompt': prompt, 'esquema': esquema,
             'imagens': [hashlib.sha256(Path(i).read_bytes()).hexdigest() for i in imagens], 'opcoes': corpo['options']}

    def chamar():
        pedido = urllib.request.Request(f'{OLLAMA}/api/generate', data=json.dumps(corpo).encode(),
                                        headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(pedido, timeout=900) as resposta:
                meta = {'motor': 'ollama', 'modelo': modelo, 'digest': digest[:12], 'versao': versao_ollama()}
                if parcial:
                    return em_partes(resposta, modelo, meta)
                inteira = json.load(resposta)
                return inteira['response'], {**meta, 'fim': inteira.get('done_reason'), **tempos_do_ollama(inteira)}
        except urllib.error.HTTPError as falha:
            raise RuntimeError(f'Ollama {falha.code} ({modelo}): {falha.read().decode(errors="replace")[:300]}') from falha
    return congelado(chave, chamar)


def chave_nvidia():
    """A chave da API da NVIDIA: a variável NVIDIA_API_KEY ou o arquivo de agentes.json → chave; '' se não há."""
    if os.environ.get('NVIDIA_API_KEY', '').strip():
        return os.environ['NVIDIA_API_KEY'].strip()
    arquivo = Path(os.path.expanduser(comum.configuracao('agentes')['chave']))
    return arquivo.read_text().strip() if arquivo.exists() else ''


RITMO, RITMO_TRAVA = {}, threading.Lock()


def esperar_vez(provedor, por_minuto):
    """Um pedido ao mesmo provedor a cada 60/por_minuto s, entre todas as threads e todos os modelos dele: o limite
    da conta é um só (a NVIDIA mostra 40/min para a macminicaio). Devolve quanto esperou."""
    with RITMO_TRAVA:
        trava, ultimo = RITMO.setdefault(provedor, (threading.Lock(), [0.0]))
    with trava:
        espera = max(0.0, ultimo[0] + 60 / por_minuto - time.monotonic())
        if espera:
            time.sleep(espera)
        ultimo[0] = time.monotonic()
    return espera


def nvidia(modelo, pedido, imagens=(), opcoes=None, lado_max_px=2048, timeout_s=300, provedor='nvidia', refazer=False):
    """Resposta de um modelo do catálogo da NVIDIA (API no formato OpenAI): `pedido` é o texto, as imagens vão como data
    URI. Devolve o JSON {'texto', 'ferramentas'} (o content e os argumentos das tool_calls; o raciocínio fica de fora,
    menos os 300 primeiros caracteres dele no meta quando o content vem vazio: o diagnóstico da resposta vazia).
    429, 5xx, timeout e queda de rede tentam de novo (agentes.json → tentativas); outro 4xx sobe na hora. A chave da API
    não entra na chave do congelamento; o remoto não tem digest: o modelo e os tokens que a resposta diz vão ao meta.
    O tempo separa o modelo do plano: segundos_util (a tentativa que deu certo), segundos_espera (o ritmo do provedor
    e as esperas entre tentativas) e segundos_falhas (as tentativas que falharam)."""
    AGENTES = comum.configuracao('agentes')
    POR_MINUTO = AGENTES['provedores'][provedor]['por_minuto']
    partes = ([{'type': 'text', 'text': pedido}] if pedido else []) + [
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(imagem_para_ia(i, lado_max_px)).decode()}}
        for i in imagens]
    corpo = {'model': modelo, 'messages': [{'role': 'user', 'content': partes}], 'temperature': 0, **(opcoes or {})}
    chave = {'motor': 'nvidia', 'modelo': modelo, 'pedido': pedido, 'opcoes': opcoes or {}, 'lado_max_px': lado_max_px,
             'imagens': [hashlib.sha256(Path(i).read_bytes()).hexdigest() for i in imagens]}

    def chamar():
        envio = urllib.request.Request(AGENTES['endpoint'], data=json.dumps(corpo).encode(), headers={
            'Content-Type': 'application/json', 'Accept': 'application/json', 'Authorization': f'Bearer {chave_nvidia()}'})
        motivos = []  # por que cada tentativa anterior falhou: 429 (o limite), 5xx (o servidor) ou sem resposta
        espera_total = falhas_total = 0.0
        for tentativa in range(AGENTES['tentativas'] + 1):
            espera_total += esperar_vez(provedor, POR_MINUTO)
            inicio = time.perf_counter()
            try:
                with urllib.request.urlopen(envio, timeout=timeout_s) as resposta:
                    inteira = json.load(resposta)
                util = time.perf_counter() - inicio
                break
            except urllib.error.HTTPError as falha:
                falhas_total += time.perf_counter() - inicio
                motivo = f'NVIDIA {falha.code} ({modelo}): {falha.read().decode(errors="replace")[:600]}'
                if (falha.code != 429 and falha.code < 500) or tentativa == AGENTES['tentativas']:
                    raise RuntimeError(motivo) from falha
                motivos.append(str(falha.code))
                pedida = falha.headers.get('Retry-After', '')
                espera = float(pedida) if re.fullmatch(r'\d+(?:\.\d+)?', pedida.strip()) else AGENTES['espera_s'] * 2 ** tentativa
            except (urllib.error.URLError, TimeoutError, ConnectionError) as falha:
                falhas_total += time.perf_counter() - inicio
                if tentativa == AGENTES['tentativas']:
                    raise RuntimeError(f'NVIDIA sem resposta ({modelo}): {falha}') from falha
                motivos.append(type(falha).__name__)
                espera = AGENTES['espera_s'] * 2 ** tentativa
            pausa = min(espera, AGENTES['espera_max_s']) + random.random() * min(1, AGENTES['espera_s'])
            time.sleep(pausa)
            espera_total += pausa
        escolha, uso = inteira['choices'][0], inteira.get('usage') or {}
        mensagem = escolha.get('message') or {}
        raciocinio = mensagem.get('reasoning_content') or mensagem.get('reasoning') or ''
        resposta = {'texto': mensagem.get('content') or '',
                    'ferramentas': [c['function']['arguments'] for c in mensagem.get('tool_calls') or []]}
        return json.dumps(resposta, ensure_ascii=False), {
            'motor': 'nvidia', 'modelo': inteira.get('model') or modelo, 'fim': escolha.get('finish_reason'),
            'tokens_entrada': uso.get('prompt_tokens'), 'tokens_saida': uso.get('completion_tokens'), 'tentativas': tentativa + 1, 'motivos': motivos,
            'caracteres_raciocinio': len(raciocinio), **({'raciocinio_sem_resposta': raciocinio[:300]} if not (mensagem.get('content') or '').strip() else {}), 'segundos_util': round(util, 2), 'segundos_espera': round(espera_total, 2), 'segundos_falhas': round(falhas_total, 2)}
    return congelado(chave, chamar, refazer)


def em_partes(resposta, modelo, meta):
    """O texto em partes e como parou; a cada linha completa o laço é procurado no próprio fluxo e a leitura para ali."""
    texto = ''
    for numero, parte in enumerate(map(json.loads, resposta), 1):
        if 'error' in parte and REPETICAO in parte['error']:
            return texto, {**meta, 'fim': 'abortado', 'tokens': numero}
        if 'error' in parte:
            raise RuntimeError(f"Ollama 500 ({modelo}): {parte['error'][:300]}")
        texto += parte.get('response', '')
        if ('\n' in parte.get('response', '') or numero % 32 == 0) and (laco := laco_no_fluxo(texto)):
            return texto, {**meta, 'fim': laco, 'tokens': numero}
        if parte.get('done'):
            meta = {**meta, 'fim': parte.get('done_reason'), 'tokens': parte.get('eval_count', numero), **tempos_do_ollama(parte)}
    return texto, meta


def tempos_do_ollama(fim):
    """0v32: o que o próprio Ollama diz que gastou (a última parte da resposta, em ns): carregar o modelo, ler o prompt
    (com a imagem) e gerar, com os tokens de cada lado. A resposta abortada pela trava de laço não tem."""
    segundos = lambda campo: round(fim[campo] / 1e9, 3) if isinstance(fim.get(campo), (int, float)) else None
    tempos = {'ollama_total_s': segundos('total_duration'), 'carregar_s': segundos('load_duration'),
              'prompt_s': segundos('prompt_eval_duration'), 'gerar_s': segundos('eval_duration'),
              'tokens_entrada': fim.get('prompt_eval_count'), 'tokens_saida': fim.get('eval_count')}
    return {k: v for k, v in tempos.items() if v is not None}


def laco_no_fluxo(texto):
    """'recomecou' se uma linha completa abre cerca depois da primeira; 'laco' se as últimas linhas são a mesma, a
    cauda é pontilhado ou a janela final quase não se comprime (laço ≤ 0,04; prancha, tabela e cotas ≥ 0,10)."""
    OCR = comum.configuracao('ia')['ocr_glm']
    completas = texto.split('\n')[:-1]
    if any(linha.strip().startswith('```') for linha in completas[1:]):
        return 'recomecou'
    ultimas = [linha.strip() for linha in completas[-OCR['linhas_iguais_laco']:]]
    cauda = texto[-OCR['cauda_laco']:].replace(' ', '').replace('\n', '')
    janela = texto[-OCR['janela_laco']:].encode()
    if (len(ultimas) == OCR['linhas_iguais_laco'] and ultimas[0] and len(set(ultimas)) == 1) or \
            (len(texto) >= OCR['cauda_laco'] and len(set(cauda)) <= 2) or \
            (len(janela) >= OCR['janela_laco'] and len(zlib.compress(janela)) < OCR['compressao_laco'] * len(janela)):
        return 'laco'
    return ''


def ocr_glm(caminho, instrucao):
    """O glm-ocr numa imagem. Abortada depois de terminar a transcrição, o texto até ali vale; parada no meio, a imagem
    vai em faixas com sobreposição. Todas no meio, o erro de repetição sobe (quem chama decide)."""
    modelo, OCR = comum.configuracao('ia')['modelos']['glm_ocr'], comum.configuracao('ia')['ocr_glm']

    def ler(imagem):
        try:
            texto, meta = ollama(modelo, instrucao, imagens=[imagem], parcial=True)
        except RuntimeError as falha:
            if REPETICAO not in str(falha):
                raise
            return None
        texto, recomecou = cortar_laco(texto)
        if recomecou or meta.get('fim') not in ('abortado', 'length', 'laco'):
            return texto
        return texto if meta['fim'] == 'abortado' and not fim_em_laco(texto) else None
    inteira = ler(caminho)
    if inteira is not None:
        return inteira
    textos = [t for t in (ler(faixa) for faixa in em_faixas(caminho, OCR['faixas'], OCR['sobreposicao'])) if t is not None]
    if not textos:
        raise RuntimeError(f'Ollama 500 ({modelo}): prediction aborted, {REPETICAO} reached (a imagem e as faixas)')
    return juntar(textos)


def fim_em_laco(texto):
    linhas = [linha.strip() for linha in texto.strip().splitlines()]
    cauda = texto.strip()[-40:].replace(' ', '')
    return not linhas or len(set(cauda)) <= 2 or (len(linhas) >= 3 and linhas[-1] == linhas[-2] == linhas[-3])


def cortar_laco(texto):
    """A transcrição até onde o glm-ocr recomeça (abre outra cerca '```'), e se recomeçou."""
    linhas = texto.splitlines()
    if linhas and linhas[0].strip().startswith('```'):
        linhas = linhas[1:]
    corte = next((n for n, linha in enumerate(linhas) if linha.strip().startswith('```')), None)
    return '\n'.join(linhas[:corte]).strip(), corte is not None


def em_faixas(caminho, quantas, sobreposicao):
    """A imagem em `quantas` faixas horizontais com `sobreposicao` a mais para baixo, em PNG em dados/faixas_ocr/."""
    from PIL import Image
    pasta = comum.DADOS / 'faixas_ocr'
    pasta.mkdir(parents=True, exist_ok=True)
    with Image.open(caminho) as imagem:
        altura = imagem.height / quantas
        caixas = [(0, round(n * altura), imagem.width, min(imagem.height, round((n + 1 + sobreposicao) * altura)))
                  for n in range(quantas)]
        codigo = hashlib.sha256(Path(caminho).read_bytes()).hexdigest()[:16]
        destinos = [pasta / f'{codigo}_{n}.png' for n in range(quantas)]
        for caixa, destino in zip(caixas, destinos):
            imagem.convert('RGB').crop(caixa).save(destino)
    return destinos


def juntar(textos):
    """O texto das faixas na ordem, sem as linhas que a sobreposição repetiu."""
    linhas = []
    for texto in textos:
        novas = texto.splitlines()
        vistas = {v.strip() for v in linhas[-len(novas):]}
        while novas and (novas[0].strip() in vistas or not novas[0].strip()):
            novas.pop(0)
        linhas += novas
    return '\n'.join(linhas)


def ler_com_glm_ocr(caminho):
    return {'texto': ocr_glm(caminho, ler_prompt('imagem_ocr', regras=False)[0])}


VISION = [sys.executable, str(Path(__file__).resolve()), 'vision']  # o Vision num processo à parte (os testes trocam)
VISION_CELULAS = [sys.executable, str(Path(__file__).resolve()), 'celulas']


def ler_com_vision(caminho):
    """Texto da imagem pelo OCR do macOS (Vision, modo preciso, pt-BR): o segundo leitor, de natureza diferente. Roda
    num processo à parte, com prazo (ia.json → vision_timeout_s): em 04/10 o Vision travou 11 h dentro de
    performRequests (VNCRImageReaderDetector) e a rodada segurou a vez da GPU o tempo todo, com a GPU parada e a fila
    inteira esperando. Travado, o processo é encerrado e o erro sobe — quem chama segue com o outro leitor."""
    PRAZO = comum.configuracao('ia').get('vision_timeout_s', 120)
    try:
        feito = subprocess.run([*VISION, str(caminho)], capture_output=True, text=True, timeout=PRAZO)
    except subprocess.TimeoutExpired as falha:
        raise RuntimeError(f'Vision travou: passou de {PRAZO} s em {Path(caminho).name} (processo encerrado)') from falha
    if feito.returncode != 0:
        raise RuntimeError(f'Vision: {feito.stderr.strip()[-300:]}')
    cliente_gpu.avancei()
    lido = json.loads(feito.stdout)
    return {'texto': lido['texto'], 'palavras': lido.get('palavras', [])}


def recortar_celulas(imagem, caixas, pasta, ampliar=4, margem=12):
    """Cada caixa (0 a 1, origem em cima) da imagem num PNG à parte, sobre fundo branco, com margem e ampliado: o
    algarismo sozinho que o Vision pulou na tabela inteira vira texto grande no meio do recorte."""
    from PIL import Image
    pasta.mkdir(parents=True, exist_ok=True)
    original = Image.open(imagem).convert('RGBA')
    fundo = Image.new('RGBA', original.size, 'white')
    fundo.alpha_composite(original)
    folha, largura, altura = fundo.convert('RGB'), original.width, original.height
    destinos = []
    for n, (x0, y0, x1, y1) in enumerate(caixas):
        caixa = (max(0, int(x0 * largura)), max(0, int(y0 * altura)), min(largura, int(x1 * largura) + 1), min(altura, int(y1 * altura) + 1))
        recorte = sem_tracos(folha.crop(caixa), (y1 - y0) * altura / 1.5)
        moldura = Image.new('RGB', (recorte.width + 2 * margem, recorte.height + 2 * margem), 'white')
        moldura.paste(recorte, (margem, margem))
        destino = pasta / f'{Path(imagem).stem}_celula{n:02d}.png'
        moldura.resize((moldura.width * ampliar, moldura.height * ampliar), Image.Resampling.LANCZOS).save(destino)
        destinos.append(destino)
    return destinos


def sem_tracos(recorte, altura_texto, escuro=128):
    """Apaga os traços da grade que entram no recorte da célula (o OCR lê '|' e '[' neles): a coluna de pixels com uma
    corrida escura mais alta que 1,15 × a altura do texto e a linha com uma corrida mais larga que 3 × ela. O traço de
    um algarismo não chega a isso."""
    cinza = recorte.convert('L')
    largura, altura = cinza.size
    pixels = cinza.load()

    def corrida(valores):
        maior = atual = 0
        for valor in valores:
            atual = atual + 1 if valor < escuro else 0
            maior = max(maior, atual)
        return maior
    colunas = [x for x in range(largura) if corrida(pixels[x, y] for y in range(altura)) > 1.15 * altura_texto]
    linhas = [y for y in range(altura) if corrida(pixels[x, y] for x in range(largura)) > 3 * altura_texto]
    limpo = recorte.copy()
    branco = limpo.load()
    for x in colunas:
        for y in range(altura):
            branco[x, y] = (255, 255, 255)
    for y in linhas:
        for x in range(largura):
            branco[x, y] = (255, 255, 255)
    return limpo


def ler_celulas(imagem, caixas, pasta):
    """O texto de cada célula (caixas de 0 a 1) pelo Vision, sem a correção de idioma (ela troca e some com algarismo
    solto), todas num processo só, com o prazo do Vision. Uma lista de textos na ordem das caixas."""
    if not caixas:
        return []
    caminhos = recortar_celulas(imagem, caixas, pasta)
    PRAZO = comum.configuracao('ia').get('vision_timeout_s', 120)
    try:
        feito = subprocess.run([*VISION_CELULAS, *map(str, caminhos)], capture_output=True, text=True, timeout=PRAZO)
    except subprocess.TimeoutExpired as falha:
        raise RuntimeError(f'Vision travou nas células de {Path(imagem).name} (processo encerrado)') from falha
    if feito.returncode != 0:
        raise RuntimeError(f'Vision: {feito.stderr.strip()[-300:]}')
    return json.loads(feito.stdout)['textos']


def vision_neste_processo(caminho, correcao=True):
    """O Vision de fato (chamado pelo processo à parte de ler_com_vision; sem correção de idioma, pelo de ler_celulas)."""
    import Vision
    import objc
    from Foundation import NSURL
    with objc.autorelease_pool():
        pedido = Vision.VNRecognizeTextRequest.alloc().init()
        pedido.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        pedido.setRecognitionLanguages_(['pt-BR', 'en-US'])
        pedido.setUsesLanguageCorrection_(correcao)
        manipulador = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(caminho)), None)
        certo, erro = manipulador.performRequests_error_([pedido], None)
        if not certo:
            raise RuntimeError(f'Vision: {erro}')
        achados = sorted(pedido.results() or [], key=lambda o: (-round(o.boundingBox().origin.y, 2), o.boundingBox().origin.x))
        linhas = [(str(o.topCandidates_(1)[0].string()), o.topCandidates_(1)[0], o.boundingBox()) for o in achados]
        return {'texto': '\n'.join(texto for texto, _, _ in linhas),
                'palavras': [p for texto, candidato, caixa in linhas for p in palavras_do_vision(texto, candidato, caixa)]}


def caixa_de_cima(x, y, largura, altura):
    """A caixa do Vision (origem embaixo à esquerda, de 0 a 1) com a origem em cima à esquerda, como a grade usa."""
    return {'x0': round(x, 5), 'y0': round(1 - y - altura, 5), 'x1': round(x + largura, 5), 'y1': round(1 - y, 5)}


def palavras_do_vision(texto, candidato, caixa_linha):
    """Cada palavra da linha que o Vision leu, com a caixa dela (codigo/grade.py monta a tabela por elas): a caixa que
    o Vision dá para o trecho (boundingBoxForRange); se não dá, ou devolve a linha inteira para cada palavra (acontece
    em algumas versões do macOS), a fatia da caixa da linha na proporção dos caracteres."""
    trechos = list(re.finditer(r'\S+', texto))
    x, y = caixa_linha.origin.x, caixa_linha.origin.y
    largura, altura = caixa_linha.size.width, caixa_linha.size.height
    palavras = []
    for trecho in trechos:
        caixa = None
        try:
            retangulo, _ = candidato.boundingBoxForRange_error_((trecho.start(), trecho.end() - trecho.start()), None)
            caixa = retangulo.boundingBox() if retangulo is not None else None
        except Exception:  # pyobjc sem o método ou trecho fora: a proporção basta
            caixa = None
        if caixa is not None and (len(trechos) == 1 or caixa.size.width < 0.95 * largura):
            palavras.append({'texto': trecho.group(), **caixa_de_cima(caixa.origin.x, caixa.origin.y, caixa.size.width, caixa.size.height)})
        else:
            inicio, fim = trecho.start() / max(len(texto), 1), trecho.end() / max(len(texto), 1)
            palavras.append({'texto': trecho.group(), **caixa_de_cima(x + largura * inicio, y, largura * (fim - inicio), altura)})
    return palavras


def concordancia(texto_a, texto_b):
    """Jaccard das palavras de dois leitores; 1,0 = mesmas palavras."""
    palavras_a, palavras_b = set(re.findall(r'\w+', texto_a.lower())), set(re.findall(r'\w+', texto_b.lower()))
    if not palavras_a and not palavras_b:
        return 1.0
    return len(palavras_a & palavras_b) / len(palavras_a | palavras_b)


def ocr_da_pagina(imagem):
    """Texto pelo glm-ocr; em repetição (recorte em branco ou só ruído) fica sem texto e com o motivo."""
    try:
        return {'texto': ler_com_glm_ocr(imagem)['texto'], 'erro': ''}
    except RuntimeError as falha:
        if REPETICAO not in str(falha):
            raise
        return {'texto': '', 'erro': 'repetição: recorte sem texto legível'}


def dupla_leitura(lida, imagem, com_vision=True):
    """A leitura do glm-ocr mais a do Vision do mesmo recorte e a concordância, quando os dois leram."""
    try:
        vision, erro_vision = (ler_com_vision(imagem)['texto'], '') if com_vision else ('', 'só o glm-ocr')
    except ImportError:
        vision, erro_vision = '', 'Vision ausente: .venv/bin/pip install pyobjc-framework-Vision'
    except RuntimeError as falha:
        vision, erro_vision = '', str(falha)[:300]
    comparavel = not erro_vision and not lida['erro']
    return {**lida, 'texto_vision': vision, 'erro_vision': erro_vision,
            'concordancia_ocr': round(concordancia(lida['texto'], vision), 3) if comparavel else None}


def apple(prompt, esquema=None):
    """Modelo do dispositivo da Apple, com o esquema montado pelo próprio SDK (@fm.generable); se a geração guiada
    falha, o esquema vai no pedido e o JSON é tirado da resposta. Importado aqui: só existe no macOS."""
    import asyncio
    import platform
    import apple_fm_sdk as fm
    modelo = fm.SystemLanguageModel()
    disponivel, motivo = modelo.is_available()
    if not disponivel:
        raise RuntimeError(f'Apple FM indisponível: {motivo}')
    chave = {'motor': 'apple', 'sdk': getattr(fm, '__version__', ''), 'prompt': prompt, 'esquema': esquema, 'guiada': 'generable'}

    def responder(texto, **opcoes):
        resposta = asyncio.run(fm.LanguageModelSession(model=modelo).respond(texto, **opcoes))
        return resposta.to_json() if hasattr(resposta, 'to_json') else str(resposta)

    def chamar():
        meta = {'motor': 'apple', 'modelo': 'SystemLanguageModel', 'versao': platform.mac_ver()[0]}
        classe = type('CamposDoDocumento', (), {'__annotations__': {campo: str for campo in esquema['properties']}})
        try:
            return responder(prompt, schema=fm.generable('Campos lidos, como estão escritos')(classe).generation_schema()), meta
        except Exception as falha:
            pedido = f"{prompt}\n\nResponda só com um objeto JSON com as chaves {', '.join(esquema['properties'])}, todos os valores como texto."
            achado = re.search(r'\{.*\}', responder(pedido), re.S)
            if not achado:
                raise RuntimeError(f'Apple FM sem esquema não devolveu JSON (com esquema: {falha})') from falha
            return achado.group(0), {**meta, 'esquema': 'no prompt'}
    return congelado(chave, chamar)


if __name__ == '__main__' and sys.argv[1:2] == ['vision']:
    print(json.dumps(vision_neste_processo(sys.argv[2]), ensure_ascii=False))
if __name__ == '__main__' and sys.argv[1:2] == ['celulas']:
    print(json.dumps({'textos': [' '.join(vision_neste_processo(c, correcao=False)['texto'].split()) for c in sys.argv[2:]]}, ensure_ascii=False))
