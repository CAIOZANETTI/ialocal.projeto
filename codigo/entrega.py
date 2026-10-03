"""O que o extrator entrega ao projeto: cada PDF com a primeira página A3 ou maior, o arquivo já no disco do mini.

O contrato (extrator 2v94, tarefa entregar_projeto): ~/dados/extracao/projeto_entrega/parte_*.parquet, uma linha por
PDF, com id, caminho, arquivo (o nome), versao (o conteúdo), candidata (A3 ou maior) e arquivo_local; e o mapa ARQ de
primeiro nível → acervo/obra em ~/dados/extracao/por_obra/.obras. O projeto só lê. Documento cuja obra saiu do mapa
(o zip ou a pasta saiu da entrada) fica de fora.
"""
import json
from pathlib import Path

import polars as pl

import comum
import respostas


def documentos():
    """Os PDFs da rodada: os do extrator e os anexos às respostas das demandas (respostas.py, obra _demandas)."""
    return do_extrator() + respostas.documentos()


def do_extrator():
    """Os PDFs candidatos a prancha, com a obra, na ordem do caminho; lista vazia sem entrega ou sem o mapa de obras."""
    ENTREGA = comum.configuracao('operacao')['entrega']
    partes = sorted((comum.EXTRATOR / ENTREGA['familia']).glob('parte_*.parquet'))
    mapa = comum.EXTRATOR / ENTREGA['obras']
    if not partes or not mapa.exists():
        return []
    obras = json.loads(mapa.read_text())
    tabela = pl.concat([pl.read_parquet(p) for p in partes], how='diagonal_relaxed').filter(pl.col('candidata'))
    lista = []
    for linha in tabela.sort('caminho').to_dicts():
        destino = obras.get(linha['id'].split('/')[0])
        if destino and Path(linha['arquivo_local']).exists():
            acervo, _, obra = destino.partition('/')
            lista.append({'id': linha['id'], 'caminho': linha['caminho'], 'nome': linha['arquivo'], 'versao': linha['versao'],
                          'arquivo_local': linha['arquivo_local'], 'acervo': acervo, 'obra': obra})
    return lista
