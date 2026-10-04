"""A tabela pela geometria, sem modelo nenhum (pedido do Caio, 04/10: código antes de IA, tudo o que der
determinístico). As palavras que o OCR leu, cada uma com a caixa dela na imagem, viram linhas pela altura e células
pelas colunas do cabeçalho da relação de materiais (CÓDIGO, Nº, DISCRIMINAÇÃO, QUANT., UND.).

Não gera texto: cada célula é uma palavra que o OCR leu, ou fica vazia; a célula vazia de quantidade ou de unidade é
relida no recorte dela, e a linha que ainda fica sem uma das duas não sai (faltou, nunca palpite). Sem cabeçalho, a regra das pontas: o código é a primeira palavra, a unidade a última e a
quantidade a penúltima. Regras em conceitos/bancada.json → grade.

Caixas normalizadas de 0 a 1 com a origem no canto de cima à esquerda: {'texto', 'x0', 'y0', 'x1', 'y1'}.
"""
import re
import statistics
import unicodedata

import comum

CODIGO = re.compile(r'\d{4,6}')
NUMERO = re.compile(r'\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?')


def regras():
    return comum.configuracao('bancada')['grade']


def simples(texto):
    """Sem acento, maiúsculas, sem a pontuação e o traço de grade das pontas: 'Código|' → 'CODIGO', 'UN,' → 'UN'."""
    sem = ''.join(c for c in unicodedata.normalize('NFKD', texto or '') if not unicodedata.combining(c))
    return sem.upper().strip().strip('.,:;|[]()')


def centro_y(p):
    return (p['y0'] + p['y1']) / 2


def em_linhas(palavras, fator=None):
    """As palavras em linhas da imagem, de cima para baixo, cada uma da esquerda para a direita: a palavra entra na
    linha cujo centro está a menos de `fator` × a altura (a menor das duas) do centro dela."""
    fator = regras()['mesma_linha'] if fator is None else fator
    linhas = []
    for palavra in sorted(palavras, key=centro_y):
        altura = palavra['y1'] - palavra['y0']
        for linha in reversed(linhas[-3:]):
            if abs(centro_y(palavra) - linha['centro']) <= fator * min(altura, linha['altura']):
                linha['palavras'].append(palavra)
                linha['centro'] = statistics.fmean(centro_y(p) for p in linha['palavras'])
                linha['altura'] = statistics.median(p['y1'] - p['y0'] for p in linha['palavras'])
                break
        else:
            linhas.append({'centro': centro_y(palavra), 'altura': altura, 'palavras': [palavra]})
    linhas.sort(key=lambda l: l['centro'])
    return [sorted(l['palavras'], key=lambda p: p['x0']) for l in linhas]


def cabecalho(linha):
    """{'codigo', 'numero', 'discriminacao', 'quant', 'und'} → a caixa de cada rótulo, se a linha é o cabeçalho de
    uma relação (tem CÓDIGO e QUANT); senão None."""
    ROTULOS = regras()['cabecalho']
    achados = {}
    for palavra in linha:
        texto = simples(palavra['texto'])
        for coluna, prefixos in ROTULOS.items():
            if coluna not in achados and any(texto.startswith(p) for p in prefixos):
                achados[coluna] = palavra
                break
    return achados if {'codigo', 'quant'} <= set(achados) else None


PARECIDOS = str.maketrans({'З': '3', 'з': '3', 'О': '0', 'о': '0', 'O': '0', 'o': '0', 'l': '1', 'I': '1'})
TRACOS = '|[]!¦'  # o traço da grade que o OCR lê na ponta da célula: sai antes de ver se é número


def numero(texto):
    return bool(NUMERO.fullmatch(texto.strip()))


def quantidade(texto):
    """A célula de quantidade com as letras que o OCR troca por algarismo (04/10: o Vision leu o 3 como o З cirílico):
    só se, trocadas, a célula inteira vira número; senão fica como foi lida (e conta errada, nunca palpite)."""
    trocado = texto.strip().translate(PARECIDOS)
    return trocado if numero(trocado) else texto.strip()


def codigo_de(texto):
    """O código de material no começo da palavra, sem o lixo que o OCR grudou depois ('309341Śł' → '309341', 04/10);
    '' se a palavra não começa por 4 a 6 algarismos ou se há outro algarismo depois."""
    achado = re.match(r'(\d{4,6})(\D*)$', texto.strip())
    return achado.group(1) if achado else ''


def unidade(texto):
    return simples(texto) in regras()['unidades']


def pelas_pontas(linha):
    """Sem cabeçalho: [código, nº, discriminação, quantidade, unidade] se a primeira palavra é código, a última é
    unidade e a penúltima é número; senão None."""
    textos = [p['texto'].strip() for p in linha if p['texto'].strip()]
    if len(textos) < 3 or not codigo_de(textos[0]) or not unidade(textos[-1]) or not numero(quantidade(textos[-2])):
        return None
    meio = textos[1:-2]
    numero_item = meio.pop(0) if meio and re.fullmatch(r'S/?N|\d{1,3}', meio[0], re.I) else ''
    return [codigo_de(textos[0]), numero_item, ' '.join(meio), quantidade(textos[-2]), textos[-1]]


def pelas_colunas(linha, rotulos):
    """Com o cabeçalho: cada palavra na coluna pela posição. O código é a primeira palavra se acaba antes do Nº (ou da
    discriminação); a quantidade, as palavras que acabam depois de onde começa o QUANT. (o número vem alinhado à
    direita) e antes do meio entre QUANT. e UND.; a unidade, as que passam desse meio. Devolve {'celulas', 'faltam'}:
    faltam = coluna → caixa da célula que ficou vazia (quant, und), para reler; None se a linha não tem código."""
    quant, und = rotulos['quant'], rotulos.get('und')
    largura = quant['x1'] - quant['x0']
    limite_und = (quant['x1'] + und['x0']) / 2 if und else quant['x1'] + largura * 0.25
    fim_codigo = (rotulos.get('numero') or rotulos.get('discriminacao') or quant)['x0']
    codigo, numero_item, meio, fim_meio, quantidades, unidades = '', '', [], 0.0, [], []
    for n, palavra in enumerate(linha):
        texto, centro = palavra['texto'].strip(), (palavra['x0'] + palavra['x1']) / 2
        if not texto:
            continue
        if n == 0 and codigo_de(texto) and palavra['x1'] <= fim_codigo + 0.01:
            codigo = codigo_de(texto)
        elif centro >= limite_und:
            unidades.append(texto)
        elif palavra['x1'] > quant['x0']:
            quantidades.append(texto)
        elif not meio and not numero_item and 'numero' in rotulos and palavra['x0'] < rotulos['numero']['x1']:
            numero_item = texto
        else:
            meio.append(texto)
            fim_meio = max(fim_meio, palavra['x1'])
    if not codigo:
        return None
    topo, fundo = min(p['y0'] for p in linha), max(p['y1'] for p in linha)
    folga = (fundo - topo) * 0.25
    faltam = {}
    if not quantidades:  # o número pode passar à esquerda do QUANT. (10221,25), mas não sobre a discriminação
        faltam['quant'] = (max(fim_meio + 0.005, quant['x0'] - largura), topo - folga, limite_und, fundo + folga)
    if not unidades:
        faltam['und'] = (limite_und, topo - folga, min(1.0, (und['x1'] if und else limite_und + largura) + largura * 0.5), fundo + folga)
    return {'celulas': [codigo, numero_item, ' '.join(meio), quantidade(''.join(quantidades)), ''.join(unidades)], 'faltam': faltam}


def montar(palavras, reler=None):
    """As palavras (com caixa) de uma imagem → as linhas de material [código, nº, discriminação, quantidade, unidade].
    Cada cabeçalho vale para as linhas até o próximo (relações empilhadas na mesma imagem); antes do primeiro, a
    regra das pontas. A célula de quantidade ou de unidade que ficou vazia (04/10: o Vision pula o algarismo sozinho,
    '6', '1', e a unidade 'M') é relida por `reler(caixas) → textos` — o mesmo OCR na célula recortada e ampliada,
    todas de uma vez —, se houver. A linha que ainda não fecha fica de fora: a regra das pontas tomaria o último
    número da discriminação ('DE 63') pela quantidade que o OCR não leu."""
    montadas, rotulos = [], None
    for linha in em_linhas(palavras):
        achado = cabecalho(linha)
        if achado:
            rotulos = achado
            continue
        if rotulos:
            montada = pelas_colunas(linha, rotulos)
        else:
            celulas = pelas_pontas(linha)
            montada = {'celulas': celulas, 'faltam': {}} if celulas else None
        if montada:
            montadas.append(montada)
    pedidos = [(m, coluna, caixa) for m in montadas for coluna, caixa in m['faltam'].items()]
    if reler and pedidos:
        for (montada, coluna, _), lido in zip(pedidos, reler([caixa for _, _, caixa in pedidos])):
            lido = ''.join((lido or '').split()).strip(TRACOS)
            if coluna == 'quant' and numero(quantidade(lido)):
                montada['celulas'][3] = quantidade(lido)
            elif coluna == 'und' and unidade(lido):
                montada['celulas'][4] = lido
    return [m['celulas'] for m in montadas if m['celulas'][3] and m['celulas'][4]]


def texto(linhas):
    return '\n'.join(' '.join(c for c in celulas if c) for celulas in linhas)
