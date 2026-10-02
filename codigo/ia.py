"""A porta para os motores de IA do mini (MASTER-PLAN §5.4: só local): Ollama (qwen3, glm-ocr em localhost:11434), o
modelo do dispositivo da Apple (Foundation Models) e o OCR do macOS (Vision). Nenhum chama nuvem.

Toda resposta é congelada com a configuração inteira (§8.2): a mesma chave devolve a resposta guardada em
dados/congelamento.jsonl, sem chamar o modelo de novo. Prompts são arquivos em conceitos/prompts/ — o texto entra
na chave. O texto da prancha vai como dado, nunca como instrução. Trazido do modelos_ia.py do ialocal.extrator até a
2v75 (commit 35fc7e9), só com o que a prancha usa.
"""
import base64
import functools
import hashlib
import importlib.util
import json
import re
import sys
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / 'dados'
OLLAMA = 'http://localhost:11434'
REPETICAO = 'token repeat limit'  # o 500 do Ollama quando o modelo entra em laço (glm-ocr, ollama#18609)


@functools.cache
def configuracao(nome):
    """Um arquivo de conceitos/ (prancha, extratores, operacao), lido uma vez por execução."""
    return json.loads((RAIZ / 'conceitos' / f'{nome}.json').read_text())


def instalado(modulo):
    """O módulo existe neste python? (Vision e apple_fm_sdk só existem no macOS do mini)"""
    return modulo in sys.modules or importlib.util.find_spec(modulo) is not None


def ler_prompt(nome, regras=True):
    """O prompt com as regras comuns na frente (conceitos/prompts/_regras.txt: não inventar, vazio é resposta certa,
    copiar como está). O glm-ocr recebe só o pedido curto dele: é treinado nele, e texto longo o desvia."""
    pasta = RAIZ / 'conceitos' / 'prompts'
    return ((pasta / '_regras.txt').read_text() + '\n' if regras else '') + (pasta / f'{nome}.txt').read_text()


@functools.cache
def congelados():
    """Índice das respostas guardadas, lido uma vez por execução (regra 7.1: não varrer a cada chamada)."""
    arquivo = DADOS / 'congelamento.jsonl'
    if not arquivo.exists():
        return {}
    return {r['assinatura']: r for r in map(json.loads, arquivo.read_text().splitlines())}


def congelado(chave, chamar):
    """Resposta guardada para a mesma chave; senão chama e acrescenta ao JSONL (um arquivo que cresce por append)."""
    assinatura = hashlib.sha256(json.dumps(chave, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    guardado = congelados().get(assinatura)
    if guardado:
        return guardado['resposta'], {**guardado['meta'], 'congelado': True}
    marca = time.perf_counter()
    resposta, meta = chamar()
    meta = {**meta, 'segundos': round(time.perf_counter() - marca, 2), 'congelado': False}
    registro = {'assinatura': assinatura, 'chave': chave, 'resposta': resposta, 'meta': meta,
                'em': datetime.now().isoformat(timespec='seconds')}
    DADOS.mkdir(parents=True, exist_ok=True)
    with open(DADOS / 'congelamento.jsonl', 'a') as saida:
        saida.write(json.dumps(registro, ensure_ascii=False) + '\n')
    congelados()[assinatura] = registro
    return resposta, meta


def imagem_para_ia(caminho):
    """A imagem como vai ao modelo: o lado maior até `lado_max_px_ia` (o glm-ocr dava 500 com folha grande)."""
    import io
    from PIL import Image
    LADO = configuracao('extratores')['parametros']['lado_max_px_ia']
    with Image.open(caminho) as imagem:
        if max(imagem.size) <= LADO:
            return Path(caminho).read_bytes()
        reduzida = imagem.convert('RGB')
        reduzida.thumbnail((LADO, LADO))
        saida = io.BytesIO()
        reduzida.save(saida, format='PNG')
        return saida.getvalue()


@functools.cache
def modelos_ollama():
    """Nome → digest dos modelos baixados no Ollama local; vazio se o Ollama está fora do ar."""
    try:
        with urllib.request.urlopen(f'{OLLAMA}/api/tags', timeout=10) as resposta:
            return {m['name']: m['digest'] for m in json.load(resposta)['models']}
    except OSError:
        return {}


def ollama(modelo, prompt, esquema=None, imagens=(), parcial=False):
    """Resposta do Ollama local: temperatura 0, esquema JSON quando há, sem raciocínio visível. O digest do modelo
    entra na chave. `parcial`: a resposta vem em partes e o laço é cortado no fluxo; meta['fim'] diz como parou."""
    digest = modelos_ollama().get(modelo)
    if not digest:
        raise RuntimeError(f'Ollama sem o modelo {modelo} (fora do ar ou falta ollama pull)')
    corpo = {'model': modelo, 'prompt': prompt, 'stream': parcial, 'think': False,
             'options': {'temperature': 0, 'seed': 0, **configuracao('extratores')['opcoes_por_modelo'].get(modelo, {})},
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
                meta = {'motor': 'ollama', 'modelo': modelo, 'digest': digest[:12]}
                if parcial:
                    return em_partes(resposta, modelo, meta)
                inteira = json.load(resposta)
                return inteira['response'], {**meta, 'fim': inteira.get('done_reason')}
        except urllib.error.HTTPError as falha:
            raise RuntimeError(f'Ollama {falha.code} ({modelo}): {falha.read().decode(errors="replace")[:300]}') from falha
    return congelado(chave, chamar)


def em_partes(resposta, modelo, meta):
    """A resposta em partes (uma linha JSON cada): o texto e como parou — 'abortado' pela trava de repetição, 'laco'
    ou 'recomecou' quando o laço aparece no próprio fluxo (a conexão fecha e o Ollama deixa de gerar)."""
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
            meta = {**meta, 'fim': parte.get('done_reason'), 'tokens': parte.get('eval_count', numero)}
    return texto, meta


def laco_no_fluxo(texto):
    """'recomecou' se uma linha abre cerca depois da primeira (o fim da transcrição); 'laco' se as últimas linhas são a
    mesma, a cauda é pontilhado ou a janela final quase não se comprime (laço ≤ 0,04; texto de prancha ≥ 0,10)."""
    OCR = configuracao('extratores')['parametros']['ocr_glm']
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
    vai em faixas com sobreposição; todas no meio, o erro de repetição sobe (quem chama decide)."""
    modelo, OCR = configuracao('extratores')['modelos']['glm_ocr'], configuracao('extratores')['parametros']['ocr_glm']

    def ler(imagem):
        """O texto da transcrição terminada ('' é imagem em branco); None se parou no meio."""
        try:
            texto, meta = ollama(modelo, instrucao, imagens=[imagem], parcial=True)
        except RuntimeError as falha:
            if REPETICAO not in str(falha):
                raise
            return None
        linhas = texto.splitlines()
        linhas = linhas[1:] if linhas and linhas[0].strip().startswith('```') else linhas
        corte = next((n for n, linha in enumerate(linhas) if linha.strip().startswith('```')), None)
        texto = '\n'.join(linhas[:corte]).strip()
        if corte is not None or meta.get('fim') not in ('abortado', 'length', 'laco'):
            return texto
        cauda = texto[-40:].replace(' ', '')
        terminou = texto and len(set(cauda)) > 2 and not (len(linhas) >= 3 and linhas[-1] == linhas[-2] == linhas[-3])
        return texto if meta['fim'] == 'abortado' and terminou else None
    inteira = ler(caminho)
    if inteira is not None:
        return inteira
    textos = [t for t in (ler(faixa) for faixa in em_faixas(caminho, OCR['faixas'], OCR['sobreposicao'])) if t is not None]
    if not textos:
        raise RuntimeError(f'Ollama 500 ({modelo}): {REPETICAO} (a imagem e as faixas)')
    linhas = []
    for texto in textos:  # a sobreposição repete linhas no começo da faixa seguinte
        novas = texto.splitlines()
        vistas = {v.strip() for v in linhas[-len(novas):]}
        while novas and (novas[0].strip() in vistas or not novas[0].strip()):
            novas.pop(0)
        linhas += novas
    return '\n'.join(linhas)


def em_faixas(caminho, quantas, sobreposicao):
    """A imagem em `quantas` faixas horizontais com `sobreposicao` a mais para baixo, em dados/faixas_ocr/."""
    from PIL import Image
    pasta = DADOS / 'faixas_ocr'
    pasta.mkdir(parents=True, exist_ok=True)
    with Image.open(caminho) as imagem:
        altura = imagem.height / quantas
        codigo = hashlib.sha256(Path(caminho).read_bytes()).hexdigest()[:16]
        destinos = [pasta / f'{codigo}_{n}.png' for n in range(quantas)]
        for n, destino in enumerate(destinos):
            caixa = (0, round(n * altura), imagem.width, min(imagem.height, round((n + 1 + sobreposicao) * altura)))
            imagem.convert('RGB').crop(caixa).save(destino)
    return destinos


def apple(prompt, esquema=None):
    """O modelo do dispositivo da Apple (SystemLanguageModel). Com esquema, a geração guiada do próprio SDK
    (@fm.generable, um campo de texto por propriedade); se ela falha, o esquema vai no pedido e o JSON sai da resposta."""
    import asyncio
    import platform
    import apple_fm_sdk as fm
    modelo = fm.SystemLanguageModel()
    disponivel, motivo = modelo.is_available()
    if not disponivel:
        raise RuntimeError(f'Apple FM indisponível: {motivo}')
    chave = {'motor': 'apple', 'sdk': getattr(fm, '__version__', ''), 'prompt': prompt, 'esquema': esquema}

    def responder(texto, **opcoes):
        resposta = asyncio.run(fm.LanguageModelSession(model=modelo).respond(texto, **opcoes))
        return resposta.to_json() if hasattr(resposta, 'to_json') else str(resposta)

    def chamar():
        meta = {'motor': 'apple', 'modelo': 'SystemLanguageModel', 'versao': platform.mac_ver()[0]}
        if not esquema:
            return responder(prompt), meta
        try:
            classe = type('Campos', (), {'__annotations__': {campo: str for campo in esquema['properties']}})
            guiado = fm.generable('Campos lidos da prancha, como estão escritos')(classe)
            return responder(prompt, schema=guiado.generation_schema()), {**meta, 'esquema': 'generable'}
        except Exception as falha:
            pedido = f"{prompt}\n\nResponda só com um objeto JSON com as chaves {', '.join(esquema['properties'])}, todos os valores como texto."
            achado = re.search(r'\{.*\}', responder(pedido), re.S)
            if not achado:
                raise RuntimeError(f'Apple FM sem JSON (com esquema: {falha})') from falha
            return achado.group(0), {**meta, 'esquema': 'no prompt'}
    return congelado(chave, chamar)


def vision(caminho):
    """Texto da imagem pelo OCR do macOS (VNRecognizeTextRequest, modo preciso, pt-BR): no Neural Engine, sem modelo de
    linguagem — o leitor que confere o glm-ocr. Linhas de cima para baixo, da esquerda para a direita."""
    import objc
    import Vision
    from Foundation import NSURL
    with objc.autorelease_pool():
        pedido = Vision.VNRecognizeTextRequest.alloc().init()
        pedido.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        pedido.setRecognitionLanguages_(['pt-BR', 'en-US'])
        pedido.setUsesLanguageCorrection_(True)
        manipulador = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(caminho)), None)
        certo, erro = manipulador.performRequests_error_([pedido], None)
        if not certo:
            raise RuntimeError(f'Vision: {erro}')
        achados = sorted(pedido.results() or [], key=lambda o: (-round(o.boundingBox().origin.y, 2), o.boundingBox().origin.x))
        return '\n'.join(str(o.topCandidates_(1)[0].string()) for o in achados)
