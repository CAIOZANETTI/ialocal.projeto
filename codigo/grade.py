"""A tabela pela geometria, sem modelo nenhum (pedido do Caio, 04/10: código antes de IA, tudo o que der
determinístico). As palavras que o OCR leu, cada uma com a caixa dela na imagem, viram linhas pela altura e células
pelas colunas do cabeçalho da relação de materiais (CÓDIGO, Nº, DISCRIMINAÇÃO, QUANT., UND.).

Não gera texto: cada célula é uma palavra que o OCR leu, ou fica vazia; a linha sem quantidade ou sem unidade não sai
(faltou, nunca palpite). Sem cabeçalho, a regra das pontas: o código é a primeira palavra, a unidade a última e a
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


def numero(texto):
    return bool(NUMERO.fullmatch(texto.strip()))


def unidade(texto):
    return simples(texto) in regras()['unidades']


def pelas_pontas(linha):
    """Sem cabeçalho: [código, nº, discriminação, quantidade, unidade] se a primeira palavra é código, a última é
    unidade e a penúltima é número; senão None."""
    textos = [p['texto'].strip() for p in linha if p['texto'].strip()]
    if len(textos) < 3 or not CODIGO.fullmatch(textos[0]) or not unidade(textos[-1]) or not numero(textos[-2]):
        return None
    meio = textos[1:-2]
    numero_item = meio.pop(0) if meio and re.fullmatch(r'S/?N|\d{1,3}', meio[0], re.I) else ''
    return [textos[0], numero_item, ' '.join(meio), textos[-2], textos[-1]]


def pelas_colunas(linha, rotulos):
    """Com o cabeçalho: cada palavra na coluna pela posição. O código é a primeira palavra se acaba antes do Nº (ou da
    discriminação); a quantidade, as palavras que acabam depois de onde começa o QUANT. (o número vem alinhado à
    direita) e antes do meio entre QUANT. e UND.; a unidade, as que passam desse meio."""
    quant, und = rotulos['quant'], rotulos.get('und')
    limite_und = (quant['x1'] + und['x0']) / 2 if und else quant['x1'] + (quant['x1'] - quant['x0']) * 0.25
    fim_codigo = (rotulos.get('numero') or rotulos.get('discriminacao') or quant)['x0']
    codigo, numero_item, meio, quantidade, unidade_ = '', '', [], [], []
    for n, palavra in enumerate(linha):
        texto, centro = palavra['texto'].strip(), (palavra['x0'] + palavra['x1']) / 2
        if not texto:
            continue
        if n == 0 and CODIGO.fullmatch(texto) and palavra['x1'] <= fim_codigo + 0.01:
            codigo = texto
        elif centro >= limite_und:
            unidade_.append(texto)
        elif palavra['x1'] > quant['x0']:
            quantidade.append(texto)
        elif not meio and not numero_item and 'numero' in rotulos and palavra['x0'] < rotulos['numero']['x1']:
            numero_item = texto
        else:
            meio.append(texto)
    if not codigo or not quantidade or not unidade_:
        return None
    return [codigo, numero_item, ' '.join(meio), ''.join(quantidade), ''.join(unidade_)]


def montar(palavras):
    """As palavras (com caixa) de uma imagem → as linhas de material [código, nº, discriminação, quantidade, unidade].
    Cada cabeçalho vale para as linhas até o próximo (relações empilhadas na mesma imagem); antes do primeiro, a
    regra das pontas. Com cabeçalho, a linha cuja coluna não fecha fica de fora: a regra das pontas tomaria o último
    número da discriminação ('DE 63') pela quantidade que o OCR não leu."""
    linhas, rotulos = [], None
    for linha in em_linhas(palavras):
        achado = cabecalho(linha)
        if achado:
            rotulos = achado
            continue
        celulas = pelas_colunas(linha, rotulos) if rotulos else pelas_pontas(linha)
        if celulas:
            linhas.append(celulas)
    return linhas


def texto(linhas):
    return '\n'.join(' '.join(c for c in celulas if c) for celulas in linhas)
