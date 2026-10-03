"""Protótipo: cotas do terreno e do tubo lidas na geometria do perfil (escala H 1:1000, V 1:100)."""
import pdfplumber

PT_POR_M_V = 72 / 25.4 * 10   # 1:100
PT_POR_ESTACA = 72 / 25.4 * 20  # 20 m em 1:1000


def linha(pagina, cor, caixa):
    objetos = [o for o in pagina.curves + pagina.lines if str(o.get('stroking_color')) == cor
               and o['top'] > caixa[1] and o['bottom'] < caixa[3] and o['x0'] > caixa[0] - 1 and o['x1'] < caixa[2] + 1]
    return sorted(p for o in objetos for p in o['pts'])


def y_em(pontos, x):
    for (x0, y0), (x1, y1) in zip(pontos, pontos[1:]):
        if x0 <= x <= x1 and x1 > x0:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return None


def cotas(caminho, x_primeira, estacas, y_topo, cota_topo, caixa=(270, 860, 1815, 1215)):
    pagina = pdfplumber.open(caminho).pages[0]
    terreno = linha(pagina, '(0.0, 0.0, 1.0)', caixa)
    tubo = linha(pagina, '(0.64706, 0.0, 0.86667)', caixa)
    elevacao = lambda y: cota_topo - (y - y_topo) / PT_POR_M_V
    saida = []
    for i, estaca in enumerate(estacas):
        x = x_primeira + i * PT_POR_ESTACA
        yt, yc = y_em(terreno, x), y_em(tubo, x)
        saida.append({'estaca': estaca, 'terreno': elevacao(yt) if yt else None, 'eixo_tubo': elevacao(yc) if yc else None})
    return saida
