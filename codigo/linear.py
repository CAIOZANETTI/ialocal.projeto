"""Obra linear (adutora, rede, coletor, recalque): o eixo desenhado e a conferência da extensão (notas/plano_projeto.md
§2, §4-A e §6; teste de mesa da AAT-06 de Foz, 26/09).

O eixo sai do vetor da folha (folha.vetorizar, em mm de papel): a faixa preenchida na cor de eixo do projetista
(triângulos em sequência, o eixo é o ponto médio de cada par de bordas) ou, sem ela, a soma dos traços abertos das
camadas de tubo projetado. Vira metro com a escala, e a extensão é conferida contra o tubo da relação de materiais —
na AAT-06 o eixo bateu com a relação a 0,004 % e achou o erro de 2 m da folha 012. Trazido do prancha.py do
ialocal.extrator até a 2v75 (lá lido de novo no pdfium; aqui, das primitivas que já existem).
"""
import math
import re
from decimal import Decimal

import ia


def cadeias(triangulos):
    """Triângulos em sequência que dividem vértice formam uma faixa; a sequência que quebra abre outra."""
    faixas = []
    for pontos in triangulos:
        vertices = {(round(x, 2), round(y, 2)) for x, y in pontos}
        if faixas and vertices & faixas[-1][1]:
            faixas[-1] = (faixas[-1][0] + [pontos], vertices)
        else:
            faixas.append(([pontos], vertices))
    return [f[0] for f in faixas]


def centro(faixa):
    """Eixo da faixa: o ponto médio de cada par de bordas (o primeiro par de cada dois triângulos) e o do fim."""
    medio = lambda a, b: ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    return [medio(t[0], t[1]) for t in faixa[0::2]] + [medio(faixa[-1][1], faixa[-1][2])]


def comprimento(vertices):
    return sum(math.dist(a, b) for a, b in zip(vertices, vertices[1:]))


def deflexoes(vertices):
    """Ângulo de cada dobra do eixo, em graus com sinal, a partir de `deflexao_minima_graus`."""
    MINIMA = ia.configuracao('prancha')['eixo']['deflexao_minima_graus']
    rumos = [math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) for a, b in zip(vertices, vertices[1:]) if math.dist(a, b) > 0.2]
    angulos = [(b - a + 180) % 360 - 180 for a, b in zip(rumos, rumos[1:])]
    return [round(a, 1) for a in angulos if abs(a) >= MINIMA]


def eixo(primitivas):
    """O eixo desenhado, em mm de papel: a faixa mais longa na cor de eixo (conceitos/prancha.json → eixo.cores), com as
    deflexões; sem ela, a soma dos traços abertos das camadas de tubo projetado (eixo.camadas_tubo), por camada."""
    EIXO = ia.configuracao('prancha')['eixo']
    cores = {'{:02x}{:02x}{:02x}'.format(*(round(c * 255) for c in cor)) for cor in EIXO['cores']}
    triangulos = [list(zip(p['x_mm'], p['y_mm']))[:3] for p in primitivas
                  if p['tipo'] == 'preenchimento' and p['cor'] in cores and 3 <= len(p['x_mm']) <= 5]
    melhor = max((centro(f) for f in cadeias(triangulos)), key=comprimento, default=[])
    if len(melhor) >= 2:
        return {'eixo': 'faixa', 'eixo_mm': round(comprimento(melhor), 2), 'eixo_vertices': len(melhor),
                'deflexoes': deflexoes(melhor), 'eixo_camadas': {}}
    TUBO, tubos = EIXO['camadas_tubo'], {}
    for p in primitivas:
        if p['tipo'] == 'traco' and not p['fechado'] and re.search(TUBO['incluir'], p['camada'], re.I) and not re.search(TUBO['excluir'], p['camada'], re.I):
            tubos[p['camada']] = tubos.get(p['camada'], 0.0) + comprimento(list(zip(p['x_mm'], p['y_mm'])))
    if not tubos:
        return {'eixo': 'nao_encontrado', 'eixo_mm': None, 'eixo_vertices': 0, 'deflexoes': [], 'eixo_camadas': {}}
    return {'eixo': 'camada', 'eixo_mm': round(sum(tubos.values()), 2), 'eixo_vertices': 0, 'deflexoes': [],
            'eixo_camadas': {c: round(mm, 1) for c, mm in tubos.items()}}


def conferir(desenhado, escalas, tubos):
    """Extensão desenhada × tubo da relação: a escala da planta é a maior das confirmadas (o perfil tem a vertical
    menor); o tubo é a primeira quantidade em metro das linhas de tubo confirmadas (com o eixo por camada, a soma: a
    rede tem vários diâmetros). Só entra valor confirmado; sem ele, a conferência diz o que faltou."""
    CONFERENCIA = ia.configuracao('prancha')['conferencia']
    numero = lambda texto: Decimal(texto.replace('.', '').replace(',', '.')) if re.fullmatch(r'\d{1,3}(\.\d{3})*(,\d+)?|\d+(,\d+)?', texto.strip()) else None
    quantidades = []
    for celulas in tubos:
        if any(re.search(CONFERENCIA['tubo'], c) for c in celulas):
            for n, celula in enumerate(celulas):
                if celula.strip().lower() == 'm':  # a quantidade está ao lado da unidade, antes ou depois
                    vizinhas = [numero(celulas[k]) for k in (n + 1, n - 1) if 0 <= k < len(celulas)]
                    quantidades += [v for v in vizinhas if v is not None][:1]
    resultado = {'escala_planta': max(escalas, default=None), 'tubo_relacao_m': str(quantidades[0]) if quantidades else '',
                 'eixo_m': None, 'eixo_m_camadas': {}, 'conferencia': '', 'diferenca_relativa': None}
    if not desenhado.get('eixo_mm'):
        return {**resultado, 'conferencia': 'sem_eixo'}
    if not escalas:
        return {**resultado, 'conferencia': 'sem_escala_confirmada'}
    resultado['eixo_m'] = round(desenhado['eixo_mm'] * max(escalas) / 1000, 2)
    resultado['eixo_m_camadas'] = {c: round(mm * max(escalas) / 1000, 1) for c, mm in desenhado.get('eixo_camadas', {}).items()}
    if not quantidades:
        return {**resultado, 'conferencia': 'sem_tubo_confirmado'}
    alvo = float(sum(quantidades)) if desenhado.get('eixo') == 'camada' else float(quantidades[0])
    resultado['tubo_relacao_m'] = str(round(alvo, 2))
    diferenca = abs(resultado['eixo_m'] - alvo) / max(alvo, 1e-9)
    return {**resultado, 'conferencia': 'fecha' if diferenca <= CONFERENCIA['tolerancia_relativa'] else 'diverge',
            'diferenca_relativa': round(diferenca, 5)}


def escala(texto):
    """O denominador de cada escala '1:1000' (ou 1:7.500) num texto; [] se nenhuma."""
    return [int(d.replace('.', '')) for d in re.findall(r'1\s*[:/]\s*(\d{1,3}(?:\.\d{3})+|\d+)(?![\d.])', texto or '')]

