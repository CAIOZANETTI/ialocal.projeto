"""A curadoria (notas/plano_agentes_nvidia.md §5): Python decide o que vale, o modelo só lê. Junta o que N leitores
leram no mesmo recorte e diz, por chave, qual valor ficou e com que status. Nenhuma regra escolhe a resposta mais longa
nem a com mais campos.

Leitores: `vision` e `pdf` são testemunhas (não geram texto: não inventam sequência); `glm_ocr`, `kimi` e `parse` são
generativos, de famílias diferentes (Zhipu, Moonshot, NVIDIA). Status:
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


def por_codigo(linhas):
    """código → (quantidade, unidade) de cada linha de tabela que começa por um código de material; quantidade e
    unidade são as duas últimas células cheias (a ordem das relações: código, nº, discriminação, quantidade, unidade).
    O primeiro valor lido de cada código fica."""
    lidas = {}
    for celulas in linhas:
        cheias = [c.strip() for c in celulas if c and c.strip()]
        if len(cheias) >= 3 and CODIGO.fullmatch(cheias[0]) and cheias[0] not in lidas:
            lidas[cheias[0]] = (prancha.normalizar(cheias[-2]), unidade(cheias[-1]))
    return lidas


def curar_tabela(leituras, testemunha=''):
    """leituras: leitor → linhas da tabela; testemunha: o texto do Vision do mesmo recorte ('' sem ele). Devolve
    código → {'quant', 'und', 'status', 'leitores'}: o valor com testemunha vence; sem ela, o com mais leitores."""
    votos = {leitor: por_codigo(linhas) for leitor, linhas in leituras.items()}
    vistos = numeros(testemunha)
    curadas = {}
    for codigo in sorted({c for v in votos.values() for c in v}):
        apoio = {}
        for leitor, lidas in votos.items():
            if codigo in lidas:
                apoio.setdefault(lidas[codigo], []).append(leitor)
        com_testemunha = {valor for valor in apoio if codigo in vistos and valor[0] in vistos}
        valor = max(apoio, key=lambda v: (v in com_testemunha, len(apoio[v])))
        quem = sorted(apoio[valor])
        status = ('confirmada' if valor in com_testemunha else 'confirmada_ia' if len(quem) >= 2
                  else 'divergente' if len(apoio) > 1 else f'so_{quem[0]}')
        curadas[codigo] = {'quant': valor[0], 'und': valor[1], 'status': status, 'leitores': ','.join(quem)}
    return curadas
