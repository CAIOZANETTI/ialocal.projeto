"""A curadoria (notas/plano_agentes_nvidia.md §5): Python decide o que vale, o modelo só lê. Junta o que N leitores
leram no mesmo recorte e diz, por chave, qual valor ficou e com que status. Nenhuma regra escolhe a resposta mais longa
nem a com mais campos.

Leitores: `vision` e `pdf` são testemunhas (não geram texto: não inventam sequência); `glm_ocr`, `kimi` e `parse` são
generativos, de famílias diferentes (Zhipu, Moonshot, NVIDIA); `codigo` (codigo/grade.py) monta a tabela com as palavras
do próprio Vision: não gera texto, mas também não é testemunha de si mesmo — o valor que só ele leu não se confirma
pelo Vision (seria o Vision confirmando o Vision). Status:
- confirmada: a testemunha tem o valor e mais um leitor o leu igual;
- confirmada_ia: dois ou mais generativos leram igual, sem testemunha — não é fato, é a hipótese H8 da bancada;
- divergente: leram valores diferentes e nenhum chegou a confirmado;
- so_<leitor>: só um leu.
"""
import re

import prancha

TESTEMUNHAS = ('vision', 'pdf')
CODIGO = re.compile(r'\d{4,6}')


def unidade(texto):
    return prancha.normalizar(texto or '').rstrip('.')


def numeros(texto):
    """Os números do texto da testemunha, normalizados (vírgula decimal como ponto), para conferir presença."""
    return {prancha.normalizar(n) for n in re.findall(prancha.NUMERO, texto or '')}


DERIVADOS = ('codigo',)  # leem com as palavras da testemunha: não a contam como segundo leitor


def chaves(codigos):
    """Os códigos na ordem em que aparecem, com a repetição numerada: ['282665', '309898', '282665'] → ['282665',
    '309898', '282665#2']. Duas relações empilhadas na mesma imagem repetem o código com outra quantidade (Cambé,
    tabelas 04-06, 10-11 e 13-14): pela ordem, cada linha tem a sua chave."""
    vezes, saida = {}, []
    for codigo in codigos:
        vezes[codigo] = vezes.get(codigo, 0) + 1
        saida.append(codigo if vezes[codigo] == 1 else f'{codigo}#{vezes[codigo]}')
    return saida


def base(chave):
    return chave.split('#')[0]


def por_codigo(linhas):
    """código → (quantidade, unidade) de cada linha de tabela que começa por um código de material; quantidade e
    unidade são as duas últimas células cheias (a ordem das relações: código, nº, discriminação, quantidade, unidade).
    O código repetido ganha a chave da ordem (chaves): 282665, 282665#2."""
    validas = [cheias for cheias in ([c.strip() for c in celulas if c and c.strip()] for celulas in linhas)
               if len(cheias) >= 3 and CODIGO.fullmatch(cheias[0])]
    return {chave: (prancha.normalizar(cheias[-2]), unidade(cheias[-1]))
            for chave, cheias in zip(chaves(c[0] for c in validas), validas)}


def curar_tabela(leituras, testemunha=''):
    """leituras: leitor → linhas da tabela; testemunha: o texto do Vision do mesmo recorte ('' sem ele). Devolve
    código → {'quant', 'und', 'status', 'leitores'}: o valor com testemunha vence; sem ela, o com mais leitores. O
    valor que só os DERIVADOS leram não conta a testemunha (é a leitura dela mesma)."""
    votos = {leitor: por_codigo(linhas) for leitor, linhas in leituras.items()}
    vistos = numeros(testemunha)
    curadas = {}
    for codigo in sorted({c for v in votos.values() for c in v}):
        apoio = {}
        for leitor, lidas in votos.items():
            if codigo in lidas:
                apoio.setdefault(lidas[codigo], []).append(leitor)
        com_testemunha = {valor for valor in apoio if base(codigo) in vistos and valor[0] in vistos
                          and any(leitor not in DERIVADOS for leitor in apoio[valor])}
        valor = max(apoio, key=lambda v: (v in com_testemunha, len(apoio[v])))
        quem = sorted(apoio[valor])
        status = ('confirmada' if valor in com_testemunha else 'confirmada_ia' if len(quem) >= 2
                  else 'divergente' if len(apoio) > 1 else f'so_{quem[0]}')
        curadas[codigo] = {'quant': valor[0], 'und': valor[1], 'status': status, 'leitores': ','.join(quem)}
    return curadas
