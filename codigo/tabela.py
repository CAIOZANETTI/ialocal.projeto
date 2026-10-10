"""Tabela de material pela grade (0v38; notas/plano_tabelas_deterministicas.md; regras em conceitos/tabela.json).

A relação de materiais da Sanepar tem linhas desenhadas: a geometria diz onde está cada célula, sem modelo. O OCR só
lê o conteúdo de cada caixa, e dois leitores de natureza diferente leem as células curtas:

    PDF ─► localizar ─► é tabela? ─► pixels nativos ─► grade ─► células ─► leitor A + leitor B ─► regras ─► linha
           imagem colada (pdfium) e malha vetorial (folha renderizada), sem thumbnail; foto e mapa não vão ao OCR

Leitor A: a tabela inteira uma vez, com caixa por palavra (Vision no mini; Tesseract fora dele). Leitor B: PP-OCR
(RapidOCR, ONNX, CPU) nas colunas curtas empilhadas, uma chamada por coluna. Os dois iguais: `confirmada`; senão a
célula vai em `nao_confirmados` e a linha fica `divergente`; sem o B, `um_leitor`. Mesma imagem, mesma saída.

ler_tabelas(documento, rodada) é a tarefa de código do ciclo (depois do ler_prancha, sem a vez da GPU): grava em
prancha_tabela (extrator `tabelas`: linha 0 = cabeçalho, as outras = itens) e um resumo em prancha (extrator `tabelas`).
"""
import csv
import io
import itertools
import json
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
from pathlib import Path

import comum
import ia


def disponivel():
    """A grade precisa do OpenCV e do numpy (codigo/requisitos.txt); sem eles, a tabela segue pelo caminho antigo."""
    return ia.instalado('cv2') and ia.instalado('numpy')


def regra():
    return comum.configuracao('tabela')


def sem_acento(texto):
    return unicodedata.normalize('NFKD', texto or '').encode('ascii', 'ignore').decode().upper()


# ---------------------------------------------------------------- geometria
def tinta(rgb):
    """Escuro e sem cor: o fundo roxo da 2ª etapa não é tinta."""
    import cv2
    import numpy as np
    G = regra()['grade']
    cinza = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    r = rgb.astype(np.int16)
    saturacao = r.max(axis=2) - r.min(axis=2)
    return ((cinza < G['tinta_limiar']) & ((saturacao < G['tinta_saturacao_max']) | (cinza < 70))).astype(np.uint8) * 255


def linhas(bw, eixo, comprimento):
    """Máscara e posições (início, fim) das linhas longas num eixo, por abertura morfológica."""
    import cv2
    import numpy as np
    nucleo = cv2.getStructuringElement(cv2.MORPH_RECT, (max(2, int(comprimento)), 1) if eixo == 'h' else (1, max(2, int(comprimento))))
    mascara = cv2.morphologyEx(bw, cv2.MORPH_OPEN, nucleo)
    perfil = mascara.sum(axis=1 if eixo == 'h' else 0)
    grupos = []
    for p in np.where(perfil > 0)[0]:
        if grupos and p - grupos[-1][-1] <= 3:
            grupos[-1].append(int(p))
        else:
            grupos.append([int(p)])
    return mascara, [(g[0], g[-1]) for g in grupos]


def e_tabela(rgb):
    """Pelo menos 4 horizontais de meia largura e a imagem quase toda clara: foto, mapa e render não passam."""
    import cv2
    G = regra()['grade']
    bw = tinta(rgb)
    _, horizontais = linhas(bw, 'h', bw.shape[1] * 0.5)
    clara = (cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY) > 200).mean()
    return len(horizontais) >= G['e_tabela_min_horizontais'] and clara > G['e_tabela_fracao_clara']


def passo_tipico(bw):
    import numpy as np
    _, H = linhas(bw, 'h', bw.shape[1] * regra()['grade']['horizontal_fracao'])
    ys = [(a + b) // 2 for a, b in H]
    alturas = [b - a for a, b in zip(ys, ys[1:]) if b - a >= 12]
    return float(np.median(alturas)) if alturas else 60.0


def grade(rgb):
    """(rgb talvez ampliado, faixas [(y0, y1, [x das verticais])], imagem limpa sem a grade, em cinza)."""
    import cv2
    import numpy as np
    G = regra()['grade']
    passo = passo_tipico(tinta(rgb))
    if passo < G['ampliar_abaixo_px']:
        f = min(G['ampliar_max'], G['linha_alvo_px'] / passo)
        rgb = cv2.resize(rgb, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    bw = tinta(rgb)
    largura = bw.shape[1]
    mh, H = linhas(bw, 'h', largura * G['horizontal_fracao'])
    ys = [(a + b) // 2 for a, b in H]
    alturas = [b - a for a, b in zip(ys, ys[1:]) if b - a >= G['linha_minima_px']]
    passo = float(np.median(alturas)) if alturas else 60.0
    mv, _ = linhas(bw, 'v', max(G['vertical_fracao_da_linha'] * passo, 20))
    faixas, mascara = [], mh.copy()
    for y0, y1 in zip(ys, ys[1:]):
        if y1 - y0 < G['linha_minima_px']:
            continue
        coluna = mv[y0 + 3:y1 - 3, :].sum(axis=0) / 255 >= (y1 - y0 - 8) * 0.9
        grupos = []
        for x in np.where(coluna)[0]:
            if grupos and x - grupos[-1][-1] <= 3:
                grupos[-1].append(int(x))
            else:
                grupos.append([int(x)])
        for g in grupos:
            mascara[y0:y1 + 1, max(0, g[0] - 1):g[-1] + 2] = 255
        xs = [int(sum(g) / len(g)) for g in grupos]
        if len(xs) >= 2:
            faixas.append((y0, y1, xs))
    # o OCR lê em cinza (o traço fino do 'pç' some na binarização: 004_t9), com o fundo colorido e a grade em branco
    limpa = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    r = rgb.astype(np.int16)
    limpa[((r.max(axis=2) - r.min(axis=2)) >= G['tinta_saturacao_max']) & (limpa >= 70)] = 255
    limpa[cv2.dilate(mascara, np.ones((3, 3), np.uint8)) > 0] = 255
    return rgb, faixas, limpa


def fundo_colorido(rgb, x0, x1, y0, y1):
    r = rgb[y0 + 4:y1 - 4, x0 + 4:x1 - 4].reshape(-1, 3).astype(int)
    return bool(len(r)) and ((r.max(axis=1) - r.min(axis=1)) > 60).mean() > 0.4


# ---------------------------------------------------------------- leitores
def png(imagem):
    import cv2
    return cv2.imencode('.png', imagem)[1].tobytes()


def tesseract(imagem, psm=6, extra=()):
    """Palavras com caixa em px: {t, x, y, w, h, c, lin}."""
    feito = subprocess.run(['tesseract', '-', '-', '-l', 'por', '--psm', str(psm), '--dpi', '400', *extra, 'tsv'],
                           input=png(imagem), capture_output=True, timeout=300)
    palavras = []
    for row in csv.DictReader(io.StringIO(feito.stdout.decode('utf8', 'replace')), delimiter='\t', quoting=csv.QUOTE_NONE):
        t = (row.get('text') or '').strip()
        if t and float(row['conf']) >= 0:
            palavras.append({'t': t, 'x': int(row['left']), 'y': int(row['top']), 'w': int(row['width']), 'h': int(row['height']),
                             'c': float(row['conf']), 'lin': (row['block_num'], row['par_num'], row['line_num'])})
    return palavras


_RAPID = []


def rapid():
    if not _RAPID:
        from rapidocr_onnxruntime import RapidOCR
        motor = RapidOCR()
        motor.use_angle_cls = False  # o argumento use_cls da chamada é ignorado na 1.2.x: desliga no motor
        _RAPID.append(motor)
    return _RAPID[0]


def rapidocr(imagem):
    """PP-OCR sem o classificador de ângulo; caixas em px, uma por trecho de texto."""
    import cv2
    entrada = cv2.cvtColor(imagem, cv2.COLOR_GRAY2BGR) if imagem.ndim == 2 else imagem
    resultado, _ = rapid()(entrada)
    palavras = []
    for n, (caixa, texto, conf) in enumerate(resultado or []):
        xs, ys = [p[0] for p in caixa], [p[1] for p in caixa]
        palavras.append({'t': texto.strip(), 'x': min(xs), 'y': min(ys), 'w': max(xs) - min(xs), 'h': max(ys) - min(ys),
                         'c': float(conf) * 100, 'lin': (n,)})
    return [p for p in palavras if p['t']]


def vision(imagem):
    """O Vision do mini (processo à parte, com prazo): as caixas de 0 a 1 viram px."""
    altura, largura = imagem.shape[:2]
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False, dir=comum.DADOS if comum.DADOS.exists() else None) as arquivo:
        arquivo.write(png(imagem))
    try:
        lido = ia.ler_com_vision(arquivo.name)
    finally:
        Path(arquivo.name).unlink(missing_ok=True)
    return [{'t': p['texto'], 'x': p['x0'] * largura, 'y': p['y0'] * altura, 'w': (p['x1'] - p['x0']) * largura,
             'h': (p['y1'] - p['y0']) * altura, 'c': 100.0, 'lin': (n,)} for n, p in enumerate(lido.get('palavras', []))]


LEITORES = {'vision': (lambda: ia.instalado('Vision'), vision), 'tesseract': (lambda: bool(shutil.which('tesseract')), tesseract),
            'rapidocr': (lambda: ia.instalado('rapidocr_onnxruntime'), rapidocr)}


def leitor_a():
    """O primeiro leitor A disponível (conceitos/tabela.json → leitores.a): (nome, função) ou (None, None)."""
    for nome in regra()['leitores']['a']:
        existe, ler = LEITORES[nome]
        if existe():
            return nome, ler
    return None, None


def leitor_b():
    nome = regra()['leitores']['b']
    existe, ler = LEITORES[nome]
    return (nome, ler) if existe() else (None, None)


def sublinhas(palavras):
    """As palavras de uma célula em linhas de texto, de cima para baixo (o '01' sobre '5,26' são duas)."""
    import numpy as np
    por = {}
    for p in palavras:
        por.setdefault(p['lin'], []).append(p)
    saida = []
    for grupo in sorted(por.values(), key=lambda s: np.mean([q['y'] for q in s])):
        meio = np.mean([q['y'] + q['h'] / 2 for q in grupo])
        if saida and abs(meio - saida[-1][0]) < 0.5 * np.median([q['h'] for q in grupo]):
            saida[-1][1].extend(grupo)
        else:
            saida.append([meio, list(grupo)])
    return [' '.join(q['t'] for q in sorted(g, key=lambda q: q['x'])) for _, g in saida]


FILTRO = {'num': r'[^0-9,./\- ]', 'codigo': r'[^0-9\-]', 'item': r'[^0-9*A-Za-c/\-]'}


def reler_coluna(limpa, celulas, tipo, ler):
    """As células de uma coluna empilhadas numa faixa só, lidas por `ler` (leitor B) de uma vez: lista de sublinhas."""
    import cv2
    import numpy as np
    if not celulas:
        return []
    largura = max(c['x1'] - c['x0'] for c in celulas) + 40
    pedacos, faixas, y = [], [], 0
    for c in celulas:
        recorte = limpa[c['y0'] + 3:c['y1'] - 2, c['x0'] + 4:c['x1'] - 3]
        recorte = cv2.copyMakeBorder(recorte, 14, 14, 20, largura - recorte.shape[1] - 20, cv2.BORDER_CONSTANT, value=255)
        pedacos.append(recorte)
        faixas.append((y, y + recorte.shape[0]))
        y += recorte.shape[0]
    palavras = []
    for p in ler(np.vstack(pedacos)):
        t = p['t']
        if tipo in ('num', 'codigo'):
            t = re.sub(FILTRO[tipo], '', t.replace('O', '0'))
        elif tipo == 'item':
            t = re.sub(FILTRO['item'], '', t)
        if t.strip():
            palavras.append({**p, 't': t.strip()})
    saida = []
    for (a, b), c in zip(faixas, celulas):
        dentro = sorted([p for p in palavras if a <= p['y'] + p['h'] / 2 < b], key=lambda p: p['y'])
        grupos = []
        for p in dentro:
            if grupos and abs(p['y'] - grupos[-1][-1]['y']) < p['h'] * 0.6:
                grupos[-1].append(p)
            else:
                grupos.append([p])
        saida.append([' '.join(q['t'] for q in sorted(g, key=lambda q: q['x'])) for g in grupos])
    return saida


# ---------------------------------------------------------------- regras de domínio (funções puras, testadas)
def unidade(texto):
    R = regra()['regras']
    chave = sem_acento(texto).replace('.', '').strip() if texto else ''
    chave = R['unidades_confusas'].get(chave, chave)
    return R['unidades'].get(chave) or R['unidades'].get(sem_acento(texto or '').strip())


def numero(texto):
    """'1,50' → 1.5; '1.234,5' → 1234.5; '-' ou vazio → None."""
    s = (texto or '').strip().replace(' ', '')
    if not s or re.fullmatch(r'-+', s):
        return None
    s = s.replace('.', '').replace(',', '.') if re.search(r',\d', s) else s
    try:
        return float(s)
    except ValueError:
        return None


def decimal(texto):
    """O PP-OCR lê a vírgula como ponto: ponto seguido de 1 a 4 algarismos no fim é a vírgula do quantitativo."""
    return re.sub(r'^(\d+)\.(\d{1,4})$', r'\1,\2', (texto or '').strip())


def empilhar(registro):
    """'02 - 20,06' numa linha só com a unidade empilhada (pç / kg) são dois valores, como na célula de duas linhas."""
    unidades = [u for u in registro.get('unidade', '').split(' / ') if u]
    for campo in ('quantidade', 'etapa1', 'etapa2'):
        valor = registro.get(campo, '')
        if valor and '/' not in valor and (len(unidades) == 2 or re.search(r'\d\s*[-–—]+\s*\d+[.,]\d', valor)):
            achado = re.fullmatch(r'\D*(\d+)\s*[-–—+]+\s*(\d+[.,]\d+)\D*', valor)
            if achado:
                registro[campo] = f'{achado.group(1)} / {decimal(achado.group(2))}'
    return registro


def item_sem_numero(texto):
    return 'S/N' if texto.strip().upper().replace(' ', '') in {s.replace(' ', '') for s in regra()['regras']['sem_numero']} else texto


def _candidatos(corpo):
    CONF = regra()['regras']['confusoes']
    opcoes = [c if c.isdigit() else CONF.get(c, '') for c in corpo]
    if any(not o for o in opcoes) or len(corpo) > 5:
        return set()
    return {''.join(p) for p in itertools.product(*opcoes)}


PN_DN = re.compile(r'\b(PN|DN|BN|DBN)\s?([0-9OoDQIl|iZzSsBGbgqAdT]{1,5})\b')


def vocabulario(texto):
    """PN e DN pelo vocabulário fechado: muda só se a confusão leva a UM valor da série. (texto, [(lido, novo)])."""
    R, trocas = regra()['regras'], []

    def trocar(achado):
        prefixo = 'PN' if achado.group(1) == 'PN' else 'DN'
        serie, corpo = set(R['pn'] if prefixo == 'PN' else R['dn']), achado.group(2)
        if corpo in serie and achado.group(1) == prefixo:
            return achado.group(0)
        validos = ({corpo} & serie) or (_candidatos(corpo) & serie)
        if len(validos) != 1:
            return achado.group(0)
        novo = f"{prefixo}{' ' if ' ' in achado.group(0) else ''}{validos.pop()}"
        if novo != achado.group(0):
            trocas.append((achado.group(0), novo))
        return novo
    return PN_DN.sub(trocar, texto), trocas


NUMERO_OK = re.compile(r'^\d{1,5}([.,]\d{1,4})?$|^-$')


def forma(campo, texto):
    if campo == 'codigo':
        return bool(re.fullmatch(r'\d{3,6}|-', texto))
    if campo == 'item':
        return bool(re.fullmatch(r'\*{0,2}[A-Z]{0,2}\d{1,3}[a-zA-Z]?|S/N', texto))
    if campo == 'unidade':
        return unidade(texto) is not None
    return bool(NUMERO_OK.match(texto.replace(' ', '')))


def normal(campo, texto):
    """A forma comparável de uma leitura: o que os dois leitores escrevem diferente sem ler diferente."""
    t = (texto or '').strip().strip('|[]').strip()
    if campo in ('quantidade', 'etapa1', 'etapa2'):
        return decimal(t.replace(' ', ''))
    if campo == 'item':
        return item_sem_numero(t.replace(' ', ''))
    if campo == 'codigo':
        return t.replace(' ', '')
    if campo == 'unidade':
        return unidade(t) or t.lower()
    return t


def juntar(campo, a, b):
    """Duas leituras da mesma célula (listas de sublinhas) → (sublinhas, estado): confirmada (as duas iguais), so_a ou
    so_b (só uma com a forma esperada), divergente (as duas válidas e diferentes), um_leitor (sem o leitor B)."""
    a = [normal(campo, t) for t in a if normal(campo, t)]
    if b is None:
        return a, 'um_leitor'
    b = [normal(campo, t) for t in b if normal(campo, t)]
    if a == b:
        return a, 'confirmada'
    ok_a = bool(a) and all(forma(campo, t) for t in a)
    ok_b = bool(b) and all(forma(campo, t) for t in b)
    if ok_b and not ok_a:
        return b, 'so_b'
    if ok_a and not ok_b:
        return a, 'so_a'
    if ok_a and ok_b:
        return (a if campo in regra()['leitores']['preferir_a'] else b), 'divergente'
    return (b or a), 'divergente'


# ---------------------------------------------------------------- montar a tabela
def campo_do_cabecalho(texto):
    C = regra()['cabecalho']
    n = sem_acento(texto).replace(' ', '').replace('/', '').replace('.', '')
    for campo in ('item', 'codigo', 'descricao', 'quantidade', 'unidade'):
        if re.search(C[campo], n):
            return campo
    return None


def alinhar(celulas, colunas):
    """Linha com célula mesclada ou partida: cada célula vai para a coluna do cabeçalho com maior sobreposição em x."""
    import numpy as np
    novas = [None] * len(colunas)
    for c in celulas:
        sobra = [max(0, min(c['x1'], b) - max(c['x0'], a)) for a, b in colunas]
        i = int(np.argmax(sobra))
        if sobra[i] <= 0:
            continue
        if novas[i] is None:
            novas[i] = dict(c)
        else:
            n = novas[i]
            n.update(x0=min(n['x0'], c['x0']), x1=max(n['x1'], c['x1']), linhas=n['linhas'] + c['linhas'],
                     colorido=n['colorido'] or c['colorido'])
    if sum(1 for n in novas if n) < 2:
        return None
    y0, y1 = celulas[0]['y0'], celulas[0]['y1']
    return [n or {'x0': a, 'x1': b, 'y0': y0, 'y1': y1, 'linhas': [], 'colorido': False} for n, (a, b) in zip(novas, colunas)]


def inferir_papeis(cabecalho, linhas_item):
    """Coluna sem rótulo legível: entre a descrição e a UN é quantidade (ordem fixa da relação Sanepar); 4-6
    algarismos é código; curta antes da descrição é item. Código colado no começo da descrição é separado."""
    cab = list(cabecalho)
    if not linhas_item:
        return cab
    textos = [[' '.join(c['linhas']) for c in cs] for cs in linhas_item]
    n = len(cab)

    def fracao(i, rx):
        valores = [t[i].strip() for t in textos if t[i].strip()]
        return sum(bool(re.fullmatch(rx, v)) for v in valores) / len(valores) if valores else 0.0
    vazias = lambda i: sum(1 for t in textos if not t[i].strip()) / len(textos)
    idesc = cab.index('descricao') if 'descricao' in cab else None
    iun = cab.index('unidade') if 'unidade' in cab else None
    for i in range(n):
        if cab[i] or vazias(i) > 0.9:
            continue
        if idesc is not None and iun is not None and idesc < i < iun:
            cab[i] = 'quantidade' if not {'quantidade', 'etapa1'} & set(cab) else ('etapa2' if 'etapa1' in cab and 'etapa2' not in cab else None)
            if cab[i]:
                continue
        if fracao(i, r'\d{4,6}|-') > 0.6 and 'codigo' not in cab:
            cab[i] = 'codigo'
        elif idesc is not None and i < idesc and fracao(i, r'\*?\s?\d{1,3}[a-c]?|S/?N|.{1,4}') > 0.6 and 'item' not in cab:
            cab[i] = 'item'
        elif idesc is not None and i > idesc and fracao(i, r'[A-Za-zÇç²³/ ]{1,6}') > 0.6 and 'unidade' not in cab:
            cab[i] = 'unidade'
    if 'codigo' not in cab and idesc is not None:
        colados = [re.match(r'^\s*(\d{4,6}|-)(?:\s+(.*))?$', cs[idesc]['linhas'][0]) if cs[idesc]['linhas'] else None for cs in linhas_item]
        if sum(bool(m) for m in colados) > 0.6 * len(linhas_item):
            for cs, m in zip(linhas_item, colados):
                if m:
                    cs[idesc]['codigo_colado'] = m.group(1)
                    cs[idesc]['linhas'] = ([m.group(2)] if m.group(2) else []) + cs[idesc]['linhas'][1:]
    return cab


def ler(rgb, ler_a=None, ler_b=None):
    """Uma imagem de tabela (RGB, numpy) → {titulo, cabecalho, itens, linhas_fora, segundos}. ler_a/ler_b: funções
    imagem → palavras (os testes passam leitores falsos); None = os de conceitos/tabela.json → leitores."""
    marca = time.perf_counter()
    if ler_a is None:
        _, ler_a = leitor_a()
    if ler_b is None:
        _, ler_b = leitor_b()
    rgb, faixas, limpa = grade(rgb)
    largura = limpa.shape[1]
    palavras = ler_a(limpa) if ler_a else []
    linhas_tab = []
    for y0, y1, xs in faixas:
        celulas = []
        for x0, x1 in zip(xs, xs[1:]):
            if x1 - x0 < max(12, regra()['grade']['moldura_fracao'] * largura):
                continue
            dentro = [p for p in palavras if x0 <= p['x'] + p['w'] / 2 < x1 and y0 <= p['y'] + p['h'] / 2 < y1]
            celulas.append({'x0': x0, 'x1': x1, 'y0': y0, 'y1': y1, 'linhas': sublinhas(dentro),
                            'colorido': fundo_colorido(rgb, x0, x1, y0, y1)})
        if celulas:
            linhas_tab.append(celulas)
    return {**montar(linhas_tab, largura, limpa, ler_b), 'segundos': round(time.perf_counter() - marca, 2)}


def montar(linhas_tab, largura, limpa, ler_b):
    C = regra()['cabecalho']
    cab, colunas, secao, titulo, fora, itens_brutos = None, None, '', [], 0, []
    for cs in linhas_tab:
        if len(cs) == 1 or (len(cs) <= 3 and max(c['x1'] - c['x0'] for c in cs) > 0.6 * largura):
            texto = ' '.join(' '.join(c['linhas']) for c in cs).strip()
            if texto and cab is None:
                titulo.append(texto)
            elif texto:
                secao = texto
            continue
        campos = [campo_do_cabecalho(' '.join(c['linhas'])) for c in cs]
        etapas = 0
        for i, c in enumerate(cs):
            if re.search(C['etapa'], sem_acento(' '.join(c['linhas'])).replace(' ', '')):
                etapas += 1
                campos[i] = f'etapa{etapas}'
        if 'descricao' not in campos and sum(1 for k in campos if k) >= 2 and not cab:
            # o rótulo da descrição mal lido ('BRESCIA', 004_t9): com 2 rótulos certos na linha, a célula mais larga é a descrição
            larga = max(range(len(cs)), key=lambda i: cs[i]['x1'] - cs[i]['x0'])
            if not campos[larga] and cs[larga]['x1'] - cs[larga]['x0'] > 0.3 * largura:
                campos[larga] = 'descricao'
        if 'descricao' in campos and sum(1 for k in campos if k) >= 3:
            cab, colunas = campos, [(c['x0'], c['x1']) for c in cs]
            continue
        if cab is None:
            fora += 1
            continue
        if len(cs) != len(cab):
            cs = alinhar(cs, colunas)
            if cs is None:
                fora += 1
                continue
        itens_brutos.append((secao, cs))
    if cab is None:
        return {'titulo': titulo, 'cabecalho': None, 'itens': [], 'linhas_fora': fora}
    cab = inferir_papeis(cab, [cs for _, cs in itens_brutos])
    curtas = set(regra()['leitores']['curtas'])
    relidas = {}
    if ler_b:
        for i, campo in enumerate(cab):
            if campo in curtas:
                tipo = 'num' if campo in ('quantidade', 'etapa1', 'etapa2') else campo
                for k, r in enumerate(reler_coluna(limpa, [cs[i] for _, cs in itens_brutos], tipo, ler_b)):
                    relidas[(k, i)] = r
    itens = []
    for k, (sec, cs) in enumerate(itens_brutos):
        reg = {'secao': sec, 'estado': {}, 'colorido': []}
        for i, (campo, c) in enumerate(zip(cab, cs)):
            if not campo:
                continue
            texto = c['linhas']
            if campo in curtas:
                texto, reg['estado'][campo] = juntar(campo, texto, relidas.get((k, i)) if ler_b else None)
            if campo in ('quantidade', 'etapa1', 'etapa2'):
                texto = [decimal(t) for t in texto]
            if campo == 'item':
                texto = [item_sem_numero(t) for t in texto]
            if campo == 'unidade':
                texto = [unidade(t) or t.lower() for t in texto]
            reg[campo] = ' / '.join(texto)
            if campo == 'descricao':
                if c.get('codigo_colado'):
                    reg['codigo'] = c['codigo_colado']
                reg['descricao'], trocas = vocabulario(reg['descricao'])
                if trocas:
                    reg['correcoes'] = trocas
            if c['colorido']:
                reg['colorido'].append(campo)
        empilhar(reg)
        if reg.get('descricao') or reg.get('codigo'):
            itens.append(reg)
    return {'titulo': titulo, 'cabecalho': cab, 'itens': itens, 'linhas_fora': fora}


def status(registro, com_b):
    """confirmada: toda célula curta preenchida, os dois leitores leram o mesmo. divergente: alguma com duas leituras
    válidas e diferentes. so_um_leitor: alguma que só um leitor leu com a forma esperada. nao_confirmados: quais."""
    if not com_b:
        return 'um_leitor', ''
    faltam = [c for c, e in registro['estado'].items() if e != 'confirmada' and registro.get(c)]
    if any(registro['estado'][c] == 'divergente' for c in faltam):
        return 'divergente', ','.join(faltam)
    return ('so_um_leitor' if faltam else 'confirmada'), ','.join(faltam)


# ---------------------------------------------------------------- achar as tabelas na folha
def imagens(pagina):
    """As imagens coladas (soltas ou em Form XObject), na ordem do prancha.imagens_da_folha: (n, caixa_pt, rgb ou None, motivo)."""
    import numpy as np
    import pypdfium2.raw as raw
    import prancha
    L = regra()['localizar']
    largura_pt, altura_pt = pagina.get_size()
    saida = []
    for n, objeto in enumerate(pagina.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE], max_depth=L['profundidade_formularios']), 1):
        esquerda, baixo, direita, cima = prancha.limites(objeto)
        px = objeto.get_px_size()
        caixa = [round(v, 1) for v in (esquerda, altura_pt - cima, direita, altura_pt - baixo)]
        fracao = (direita - esquerda) * (cima - baixo) / (largura_pt * altura_pt)
        if max(px) < L['imagem_minima_px']:
            saida.append((n, caixa, None, 'pequena'))
            continue
        if fracao >= L['fracao_folha_max']:
            saida.append((n, caixa, None, 'folha_escaneada'))
            continue
        try:
            rgb = np.array(objeto.get_bitmap(render=False).to_pil().convert('RGB'))
        except Exception as falha:  # filtro de imagem que o pdfium não decodifica
            saida.append((n, caixa, None, f'nao_decodificou: {falha}'[:80]))
            continue
        saida.append((n, caixa, rgb, ''))
    return saida


def malhas(pagina, evitar):
    """As tabelas desenhadas em vetor: a folha a 150 dpi, horizontais e verticais longas, blocos com pelo menos
    malha_min_linhas horizontais; fora do carimbo e das imagens já achadas. (caixa_pt, rgb a 400 dpi)."""
    import cv2
    import numpy as np
    L = regra()['localizar']
    largura_pt, altura_pt = pagina.get_size()
    escala = L['malha_dpi'] / 72
    folha = np.array(pagina.render(scale=escala).to_pil().convert('RGB'))
    bw = tinta(folha)
    mh, _ = linhas(bw, 'h', 40)
    mv, _ = linhas(bw, 'v', 25)
    juntas = cv2.dilate(cv2.bitwise_or(mh, mv), np.ones((5, 5), np.uint8))
    quantos, _, estat, _ = cv2.connectedComponentsWithStats(juntas)
    blocos = sorted((list(map(int, estat[k][:4])) for k in range(1, quantos)
                     if estat[k][2] * estat[k][3] <= 0.5 * bw.shape[0] * bw.shape[1]), key=lambda b: (b[1], b[0]))  # sem a moldura da folha
    unidos = []  # 0v38: o cabeçalho separado do corpo por linha dupla (042A) é o mesmo bloco: mesma largura, empilhados
    for x, y, w, h in blocos:
        alvo = next((u for u in unidos if abs(u[0] - x) <= 0.03 * max(u[2], w) and abs((u[0] + u[2]) - (x + w)) <= 0.03 * max(u[2], w)
                     and 0 <= y - (u[1] + u[3]) <= 25 * escala), None)
        if alvo:
            alvo[3] = y + h - alvo[1]
        else:
            unidos.append([x, y, w, h])
    e_grade = lambda u: len(linhas(mh[u[1]:u[1] + u[3], u[0]:u[0] + u[2]], 'h', u[2] * 0.6)[1]) >= L['malha_min_linhas']
    grades = [u for u in unidos if e_grade(u)]  # a moldura do desenho não tem horizontais de 60 % da largura: não é grade
    unidos = [u for u in grades if not any(o is not u and o[0] <= u[0] and o[1] <= u[1] and o[0] + o[2] >= u[0] + u[2]
                                           and o[1] + o[3] >= u[1] + u[3] for o in grades)]  # grade dentro de grade: a de fora basta
    saida = []
    for x, y, w, h in unidos:
        caixa = [x / escala, y / escala, (x + w) / escala, (y + h) / escala]
        if (caixa[2] - caixa[0]) < L['malha_min_largura_pt']:
            continue
        cx0, cy0, cx1, cy1 = L['carimbo']
        if caixa[0] > cx0 * largura_pt and caixa[1] > cy0 * altura_pt:
            continue
        if any(not (caixa[2] < e[0] or caixa[0] > e[2] or caixa[3] < e[1] or caixa[1] > e[3]) for e in evitar):
            continue
        leitura = L['malha_dpi_leitura'] / 72
        recorte = pagina.render(scale=leitura, crop=(caixa[0] - 2, altura_pt - caixa[3] - 2, largura_pt - caixa[2] - 2, caixa[1] - 2))
        saida.append(([round(v, 1) for v in caixa], np.array(recorte.to_pil().convert('RGB'))))
    return saida


# ---------------------------------------------------------------- a tarefa
def linhas_da_tabela(base, n, origem, caixa, lida, com_b):
    """A tabela lida → linhas de prancha_tabela: a 0 é o cabeçalho canônico, as outras os itens."""
    R = regra()['cabecalho']['rotulos']
    cab = [c for c in lida['cabecalho'] if c]
    comum_ = {**base, 'imagem': n, 'faixa': 0, 'origem': origem, 'caixa_pt': json.dumps(caixa), 'titulo': ' | '.join(lida['titulo']), 'erro': ''}
    saida = [{**comum_, 'linha': 0, 'celulas': json.dumps([R[c] for c in cab], ensure_ascii=False), 'status': 'cabecalho',
              'nao_confirmados': '', 'secao': '', 'campos': '{}'}]
    for k, it in enumerate(lida['itens'], 1):
        situacao, faltam = status(it, com_b)
        campos = {c: it.get(c, '') for c in cab}
        saida.append({**comum_, 'linha': k, 'celulas': json.dumps([campos[c] for c in cab], ensure_ascii=False), 'status': situacao,
                      'nao_confirmados': faltam, 'secao': it['secao'],
                      'campos': json.dumps({**campos, 'colorido': it['colorido'], 'correcoes': it.get('correcoes', [])}, ensure_ascii=False)})
    return saida


def ler_tabelas(documento, rodada):
    """Tarefa de código: todas as tabelas de material da folha (imagem colada e malha vetorial) pela grade.
    prancha_tabela (extrator tabelas) e o resumo em prancha (extrator tabelas)."""
    import pypdfium2 as pdfium
    import prancha
    marca = time.perf_counter()
    base = prancha.base_da_linha(documento, 'tabelas', rodada)
    nome_a, ler_a = leitor_a()
    nome_b, ler_b = leitor_b()
    resumo = {**base, 'leitor_a': nome_a or '', 'leitor_b': nome_b or '', 'grade': disponivel()}
    linhas_saida, inventario = [], []
    if disponivel() and ler_a:
        documento_pdf = pdfium.PdfDocument(documento['arquivo_local'])
        try:
            pagina = documento_pdf[0]
            achadas = imagens(pagina)
            for n, caixa, rgb, motivo in achadas:
                registro = {'imagem': n, 'origem': 'imagem', 'caixa_pt': caixa, 'motivo': motivo, 'itens': 0, 'segundos': 0.0}
                if rgb is not None and not e_tabela(rgb):
                    registro['motivo'] = 'nao_e_tabela'
                elif rgb is not None:
                    try:
                        lida = ler(rgb, ler_a, ler_b)
                    except Exception as falha:  # o Vision travado numa tabela não derruba as outras da folha
                        registro['motivo'] = f'erro: {type(falha).__name__}: {falha}'[:200]
                        inventario.append(registro)
                        continue
                    registro.update(itens=len(lida['itens']), segundos=lida['segundos'],
                                    motivo='' if lida['itens'] else 'sem_cabecalho_de_lista')
                    if lida['itens']:
                        linhas_saida += linhas_da_tabela(base, n, 'imagem', caixa, lida, bool(ler_b))
                inventario.append(registro)
            proximo = len(achadas) + 1
            candidatas = [(c, r) for c, r in malhas(pagina, [c for _, c, _, _ in achadas]) if e_tabela(r)]
            for caixa, rgb in candidatas[:regra()['localizar']['malha_max']]:  # folha de planta com muita grade desenhada: um teto
                registro = {'imagem': proximo, 'origem': 'vetor', 'caixa_pt': caixa, 'motivo': '', 'itens': 0, 'segundos': 0.0}
                try:
                    lida = ler(rgb, ler_a, ler_b)
                except Exception as falha:
                    inventario.append({**registro, 'motivo': f'erro: {type(falha).__name__}: {falha}'[:200]})
                    continue
                if lida['itens']:
                    registro.update(itens=len(lida['itens']), segundos=lida['segundos'])
                    linhas_saida += linhas_da_tabela(base, proximo, 'vetor', caixa, lida, bool(ler_b))
                    inventario.append(registro)
                    proximo += 1
        finally:
            documento_pdf.close()
    itens = [l for l in linhas_saida if l['linha']]
    resumo.update(tabelas=len({l['imagem'] for l in itens}), itens=len(itens),
                  itens_confirmados=sum(l['status'] == 'confirmada' for l in itens),
                  imagens_lidas_pela_grade=json.dumps(sorted({l['imagem'] for l in itens if l['origem'] == 'imagem'})),
                  inventario_tabelas=json.dumps(inventario, ensure_ascii=False),
                  motivo='' if disponivel() and ler_a else ('sem OpenCV (codigo/requisitos.txt)' if not disponivel() else 'sem leitor A'))
    if linhas_saida:
        comum.gravar('prancha_tabela', linhas_saida)
    comum.gravar('prancha', [resumo], [{**base, 'familia': 'prancha', 'segundos': round(time.perf_counter() - marca, 2),
                                        'tabelas': resumo['tabelas'], 'itens': resumo['itens'], 'confirmados': resumo['itens_confirmados'], 'erro': ''}])
    return resumo


def lidas_pela_grade(identificador):
    """As imagens (número do inventário) que o ler_tabelas já leu com itens: o ler_prancha_ia não as manda ao glm-ocr."""
    feita = comum.ler('prancha', [identificador])
    linha = None if feita is None else next((l for l in feita.to_dicts() if l['extrator'] == 'tabelas'), None)
    return set(json.loads(linha.get('imagens_lidas_pela_grade') or '[]')) if linha else set()
