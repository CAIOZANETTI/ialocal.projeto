"""Protótipo: posição dos rótulos da malha (camada MALHA) e eixo da adutora (faixa roxa) em pt.

Os rótulos E=… são texto vertical e os N=… horizontal, desenhados como curva. O centro de
cada grupo de traços dá a posição do rótulo; o valor (747000…) é lido pela IA no recorte.
"""
import sys, math, collections
import pdfplumber
sys.path.insert(0, __file__.rsplit('/', 1)[0])
import camadas

ROXO = '(0.64706, 0.0, 0.86667)'
PT_POR_M = 72 / 25.4  # 1:1000


def grupos_malha(caminho):
    destino = caminho + '.malha.pdf'
    camadas.isolar(caminho, 'MALHA', destino)
    pagina = pdfplumber.open(destino).pages[0]
    objetos = [o for o in pagina.lines + pagina.curves if (o['x1'] - o['x0']) < 8 and (o['bottom'] - o['top']) < 8]
    grupos = collections.defaultdict(list)
    for o in objetos:
        grupos[(round((o['x0'] + o['x1']) / 2 / 12), round((o['top'] + o['bottom']) / 2 / 12))].append(o)
    unidos = []
    for chave in sorted(grupos):
        caixa = [min(o['x0'] for o in grupos[chave]), min(o['top'] for o in grupos[chave]),
                 max(o['x1'] for o in grupos[chave]), max(o['bottom'] for o in grupos[chave])]
        if unidos and caixa[0] - unidos[-1][2] < 6 and abs(caixa[1] - unidos[-1][1]) < 30 and abs(caixa[0] - unidos[-1][0]) < 30:
            unidos[-1] = [min(unidos[-1][0], caixa[0]), min(unidos[-1][1], caixa[1]), max(unidos[-1][2], caixa[2]), max(unidos[-1][3], caixa[3])]
        else:
            unidos.append(caixa)
    return unidos


def eixo(caminho, limite_x=1815, limite_y=745):
    pagina = pdfplumber.open(caminho).pages[0]
    triangulos = [o['pts'] for o in pagina.curves if str(o.get('non_stroking_color')) == ROXO and o.get('fill')
                  and o['bottom'] < limite_y and o['x1'] < limite_x]
    vertices = [((t[0][0] + t[1][0]) / 2, (t[0][1] + t[1][1]) / 2) for t in triangulos[0::2]]
    ultimo = triangulos[-1]
    vertices.append(((ultimo[1][0] + ultimo[2][0]) / 2, (ultimo[1][1] + ultimo[2][1]) / 2))
    return vertices


def para_utm(ponto, ancora_e, ancora_n):
    """ancora_e = (x_pt, E) de um rótulo E; ancora_n = (y_pt, N) de um rótulo N; norte para cima."""
    return (ancora_e[1] + (ponto[0] - ancora_e[0]) / PT_POR_M, ancora_n[1] - (ponto[1] - ancora_n[0]) / PT_POR_M)


if __name__ == '__main__':
    for caixa in grupos_malha(sys.argv[1]):
        print([round(v, 1) for v in caixa], 'centro', round((caixa[0] + caixa[2]) / 2, 1), round((caixa[1] + caixa[3]) / 2, 1))
    print('eixo', [(round(x, 1), round(y, 1)) for x, y in eixo(sys.argv[1])])
