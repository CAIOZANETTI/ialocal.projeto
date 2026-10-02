"""Protótipo: distância do eixo georreferenciado da adutora às vias do OpenStreetMap (conferência externa)."""
import json, sys, math
sys.path.insert(0, __file__.rsplit('/', 1)[0])
import georef
from pyproj import Transformer

FOLHAS = {'010': ('010-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1.pdf', (358.7, 746000), (168.5, 7178200)),
          '011': ('011-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1.pdf', (209.8, 746500), (271.4, 7178200)),
          '012': ('012_AAT06PTPER_R1.pdf', (240.1, 747000), (212.0, 7178200))}


def distancia_segmento(ponto, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    quadrado = dx * dx + dy * dy
    u = 0 if quadrado == 0 else max(0, min(1, ((ponto[0] - a[0]) * dx + (ponto[1] - a[1]) * dy) / quadrado))
    return math.hypot(ponto[0] - a[0] - u * dx, ponto[1] - a[1] - u * dy)


def amostrar(vertices, passo=20):
    pontos = []
    for a, b in zip(vertices, vertices[1:]):
        n = max(1, int(math.dist(a, b) // passo))
        pontos += [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n)]
    return pontos + [vertices[-1]]


def conferir(osm='osm_foz.json', deslocamento=(0, 0)):
    transformar = Transformer.from_crs(4326, 31981, always_xy=True)
    vias = [(w.get('tags', {}).get('name', '(sem nome)'), [transformar.transform(p['lon'], p['lat']) for p in w['geometry']])
            for w in json.load(open(osm))['elements'] if len(w.get('geometry', [])) > 1]
    for folha, (arquivo, ancora_e, ancora_n) in FOLHAS.items():
        eixo = [georef.para_utm(p, ancora_e, ancora_n) for p in georef.eixo(arquivo)]
        resultados = []
        for p in amostrar(eixo):
            p = (p[0] + deslocamento[0], p[1] + deslocamento[1])
            resultados.append(min((min(distancia_segmento(p, a, b) for a, b in zip(g, g[1:])), nome) for nome, g in vias))
        distancias = sorted(r[0] for r in resultados)
        contagem = {}
        for _, nome in resultados:
            contagem[nome] = contagem.get(nome, 0) + 1
        print(folha, 'pontos', len(resultados), 'mediana', round(distancias[len(distancias) // 2], 1), 'm  máx',
              round(distancias[-1], 1), 'm ', contagem)


if __name__ == '__main__':
    conferir()
