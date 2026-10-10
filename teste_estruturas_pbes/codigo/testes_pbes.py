"""Testes das funções determinísticas do extrator de referência, com os casos reais do PBES de Foz (python3 testes_pbes.py)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extrator_pbes import bitola_pela_massa, num_br, faixas_de_tinta
from conferir import reparar, dist
import numpy as np

# --- quant × unit = total (cm): os erros de OCR reais encontrados
assert reparar(56, 693, 538808)[:3] == (56, 693, 38808)               # dígito espúrio no total (360 L, PAR9 pos 12)
assert reparar(6, 3582, 2292)[:3] == (6, 382, 2292)                   # unit com dígito errado (CXA05 pos 7): 6 × 382 = 2292
assert reparar(44, 541, 15004)[:3] == (44, 341, 15004)                # unit 541 -> 341 (CXA05 pos 1)
assert reparar(None, 809, 7281)[:3] == (9, 809, 7281)                 # quantidade perdida: 7281 / 809 = 9
assert reparar(62, 452, 28024)[3] == ''                               # linha certa não é tocada
assert reparar(3, 100, 999)[3] == ''                                  # distância de edição > 2: não inventa
assert dist('538808', '38808') == 1

# --- física NBR 7480: a bitola que o OCR perdeu sai de peso / comprimento
assert bitola_pela_massa(2810, 1110) == 8.0                           # 600 L-009: o '8' isolado sumiu
assert bitola_pela_massa(2504, 1545) == 10.0
assert bitola_pela_massa(70, 67) == 12.5
assert bitola_pela_massa(131, 322) == 20.0
assert bitola_pela_massa(100, 50) is None                             # razão que não é de nenhuma bitola

# --- decimal misto na mesma tabela ('0,86' e '11.48')
assert num_br('0,86') == 0.86 and num_br('11.48') == 11.48 and num_br('2078,50') == 2078.5 and num_br('--') is None

# --- faixas de tinta (linhas de texto sem horizontais entre elas)
perfil = np.zeros(200); perfil[10:40] = 1; perfil[50:80] = 1; perfil[150:152] = 1
assert faixas_de_tinta(perfil, vazio=6, minimo=14) == [(10, 39), (50, 79)]
print('ok: todos os testes passaram')
