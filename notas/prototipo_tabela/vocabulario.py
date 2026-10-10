"""Correção do OCR por vocabulário fechado: o token só muda se a troca de caracteres confundíveis leva a UM valor
válido da série (PN, DN). Sem candidato único, fica como leu e vai para conferência."""
import re, itertools
PN = {'6', '10', '16', '25', '40'}
DN = {str(x) for x in (15, 20, 25, 32, 40, 50, 60, 65, 75, 80, 100, 125, 150, 200, 250, 300, 350, 400, 450, 500, 600,
                       700, 800, 900, 1000, 1100, 1200, 1400, 1500)}
CONF = {'O': '0', 'o': '0', 'D': '0', 'Q': '0', 'I': '1', 'l': '1', '|': '1', 'i': '1', 'Z': '12', 'z': '12', 'S': '58',
        's': '5', 'B': '8', 'G': '6', 'b': '6', 'g': '9', 'q': '9', 'A': '4', 'd': '4', 'T': '7', '0': '0', '1': '1',
        '2': '2', '3': '3', '4': '4', '5': '5', '6': '6', '7': '7', '8': '8', '9': '9'}

def candidatos(corpo):
    opc = [CONF.get(c, '') for c in corpo]
    if any(not o for o in opc) or len(corpo) > 5: return set()
    return {''.join(p) for p in itertools.product(*opc)}

def corrigir_token(prefixo, corpo, serie):
    if corpo in serie: return corpo
    ok = candidatos(corpo) & serie
    return ok.pop() if len(ok) == 1 else None

RX = re.compile(r'\b(PN|DN|BN|DBN)\s?([0-9OoDQIl|iZzSsBGbgqAdT]{1,5})\b')

def corrigir(texto):
    trocas = []
    def f(m):
        pre, corpo = m.group(1), m.group(2)
        pre2 = 'DN' if pre in ('BN', 'DBN', 'DN') else 'PN'
        novo = corrigir_token(pre2, corpo, PN if pre2 == 'PN' else DN)
        if novo is None: return m.group(0)
        sep = ' ' if ' ' in m.group(0) else ''
        out = f'{pre2}{sep}{novo}'
        if out != m.group(0): trocas.append((m.group(0), out))
        return out
    return RX.sub(f, texto), trocas
