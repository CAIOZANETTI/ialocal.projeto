"""O desenho que o código não lê: a folha com texto em curva ou escaneada, em fatias, e a imagem colada (a relação de
materiais da AAT-06 é uma imagem), em faixas — cada pedaço lido pelo Vision e pelo glm-ocr.

Um número só é `confirmado` quando os dois leram o mesmo no mesmo recorte (teste de 26/09: o gemma3 inventou cotas e o
glm-ocr continuou a sequência de estacas até a 323, que não existe). Fatia de até `lado_px` com sobreposição: o glm-ocr
dava 500 com ~1.600 px e abortava por repetição na tabela inteira (T5, T6). Trazido do prancha.py do ialocal.extrator
até a 2v75; regras em conceitos/prancha.json → fatias e padroes.
"""
import json
import re
import time
import unicodedata

import conferencia
import ia

NUMERO = r'\d+(?:[.,]\d+)?'


def inicios(total, lado, passo):
    """Onde começa cada pedaço ao longo de um lado: de `passo` em `passo`, e o último encostado no fim."""
    return sorted({*range(0, max(total - lado, 0) + 1, passo), max(total - lado, 0)})


def alegacoes(leituras, erros, base):
    """Cada valor (padrões de conceitos/prancha.json) lido no pedaço, com quem o leu: confirmado (Vision e glm-ocr),
    so_glm, so_vision; um_leitor se um dos dois não leu. Pedaço sem valor fica numa linha `vazia`, com os erros."""
    PADROES = {k: v for k, v in ia.configuracao('prancha')['padroes'].items() if not k.startswith('_')}
    achar = lambda texto: {p: {conferencia.normalizar(m.group(0)) for m in re.finditer(r, unicodedata.normalize('NFKC', texto or ''))}
                           for p, r in PADROES.items()}
    glm, vision = achar(leituras.get('glm_ocr')), achar(leituras.get('vision'))
    dois, linhas = len(leituras) == 2, []
    for padrao in PADROES:
        for valor in sorted(glm[padrao] | vision[padrao]):
            status = ('um_leitor' if not dois else 'confirmado' if valor in glm[padrao] and valor in vision[padrao]
                      else 'so_glm' if valor in glm[padrao] else 'so_vision')
            linhas.append({**base, 'padrao': padrao, 'valor': valor, 'status': status})
    return linhas or [{**base, 'padrao': '', 'valor': '', 'status': 'vazia', 'erros': json.dumps(erros, ensure_ascii=False)}]


def ler_fatias(caminho, pagina, pasta, prazo):
    """A folha renderizada uma vez a `dpi`, cortada em fatias de até `lado_px` com sobreposição; cada fatia pelos dois
    leitores. Para no prazo: o que foi lido fica, e quantas faltaram sai na conta."""
    import pypdfium2 as pdfium
    from PIL import Image
    FATIAS = ia.configuracao('prancha')['fatias']
    folha = pasta / f'folha_p{pagina}.png'
    if not folha.exists():
        documento = pdfium.PdfDocument(caminho)
        documento[pagina - 1].render(scale=FATIAS['dpi'] / 72).to_pil().save(folha)
        documento.close()
    linhas, lidas = [], 0
    with Image.open(folha) as imagem:
        lado, passo = FATIAS['lado_px'], round(FATIAS['lado_px'] * (1 - FATIAS['sobreposicao']))
        plano = [(x, y, min(x + lado, imagem.width), min(y + lado, imagem.height))
                 for y in inicios(imagem.height, lado, passo) for x in inicios(imagem.width, lado, passo)]
        for numero, caixa in enumerate(plano[:FATIAS['maximo_fatias']], 1):
            if time.monotonic() > prazo:
                break
            destino = pasta / f'p{pagina}_fatia{numero:02d}.png'
            imagem.crop(caixa).save(destino)
            leituras, erros = conferencia.ocr_duplo(destino)
            linhas += alegacoes(leituras, erros, {'pagina': pagina, 'fatia': numero, 'caixa_px': json.dumps(caixa)})
            lidas += 1
    return linhas, {'fatias_planejadas': len(plano), 'fatias_lidas': lidas}


def linhas_html(html):
    """Linhas da tabela que o glm-ocr devolve em HTML, cada célula sem marcação; a linha repetida (o laço) sai."""
    vistas, linhas = set(), []
    for linha in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S):
        celulas = [re.sub(r'<[^>]+>', '', c).strip() for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', linha, re.S)]
        if celulas and tuple(celulas) not in vistas:
            vistas.add(tuple(celulas))
            linhas.append(celulas)
    return linhas


def ler_tabela(imagem, base):
    """Faixa de tabela: o glm-ocr em modo tabela, o Vision como texto; a linha é `confirmada` se todo número dela
    aparece também no que o Vision leu na mesma faixa, `pendente` se falta algum, `um_leitor` sem o Vision."""
    try:
        html, erro = ia.ocr_glm(imagem, ia.ler_prompt('prancha_tabela', regras=False)), ''
    except RuntimeError as falha:
        html, erro = '', str(falha)[:200]
    try:
        vision, erro_vision = (ia.vision(imagem), '') if ia.instalado('Vision') else ('', 'Vision ausente')
    except RuntimeError as falha:
        vision, erro_vision = '', str(falha)[:200]
    do_vision = {conferencia.normalizar(n) for n in re.findall(NUMERO, vision)}
    linhas = []
    for numero, celulas in enumerate(linhas_html(html), 1):
        faltam = [conferencia.normalizar(c) for c in celulas if re.fullmatch(NUMERO, c.strip()) and conferencia.normalizar(c) not in do_vision]
        status = 'um_leitor' if erro_vision else 'pendente' if faltam else 'confirmada'
        linhas.append({**base, 'linha': numero, 'celulas': celulas, 'status': status, 'nao_confirmados': faltam})
    return linhas or [{**base, 'linha': 0, 'celulas': [], 'status': 'vazia', 'nao_confirmados': [], 'erro': erro or erro_vision}]


def tabelas_coladas(caminho, pagina, primitivas, pasta, prazo):
    """Cada imagem colada na folha (não a folha escaneada inteira), renderizada e lida como tabela em faixas
    horizontais de `faixa_altura_px` com sobreposição."""
    from PIL import Image
    FATIAS, LIMITE = ia.configuracao('prancha')['fatias'], ia.configuracao('prancha')['classe']['fracao_imagem_raster']
    folha = max(((p['x1_mm'], p['y1_mm']) for p in primitivas), default=(1, 1))
    caixas = [p for p in primitivas if p['tipo'] == 'imagem' and (p['x1_mm'] - p['x0_mm']) * (p['y1_mm'] - p['y0_mm']) < LIMITE * folha[0] * folha[1]
              and max(p['x1_mm'] - p['x0_mm'], p['y1_mm'] - p['y0_mm']) >= FATIAS['imagem_minima_mm']]
    linhas = []
    for numero, caixa in enumerate(caixas, 1):
        if time.monotonic() > prazo:
            break
        destino = conferencia.recorte(caminho, pagina, {k[:2]: caixa[k] for k in ('x0_mm', 'y0_mm', 'x1_mm', 'y1_mm')}, FATIAS['dpi'], pasta / f'p{pagina}_imagem{numero}.png')
        with Image.open(destino) as imagem:
            imagem.thumbnail((FATIAS['lado_px'], 10 ** 6))
            altura = FATIAS['faixa_altura_px']
            for faixa, y in enumerate(inicios(imagem.height, altura, round(altura * (1 - FATIAS['sobreposicao']))), 1):
                pedaco = pasta / f'p{pagina}_imagem{numero}_faixa{faixa:02d}.png'
                imagem.crop((0, y, imagem.width, min(y + altura, imagem.height))).save(pedaco)
                linhas += ler_tabela(pedaco, {'pagina': pagina, 'imagem': numero, 'faixa': faixa})
    return linhas
