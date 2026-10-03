"""O que todo módulo do projeto usa: pastas, conceitos, tabelas Parquet com troca por chave, JSONL com trava e o
envio ao Drive pelo rclone.

O projeto escreve só na própria pasta (dados/ e saidas/, fora do git) e lê a entrega do extrator em
~/dados/extracao/ sem escrever nela (MASTER-PLAN, regra de independência). Toda linha gravada leva a versão e o
commit do código que a produziu.
"""
import fcntl
import functools
import json
import subprocess
from datetime import datetime
from pathlib import Path

import polars as pl

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / 'dados'
SAIDAS = RAIZ / 'saidas'
EXTRATOR = Path.home() / 'dados' / 'extracao'
CHAVES = ['id', 'extrator', 'arquivo']


@functools.cache
def configuracao(nome):
    """Um arquivo de conceitos/ (prancha, ia, operacao), lido uma vez por execução."""
    return json.loads((RAIZ / 'conceitos' / f'{nome}.json').read_text())


def agora():
    return datetime.now().isoformat(timespec='seconds')


def versoes():
    """As linhas de codigo/versoes.jsonl sem a metadata (a primeira)."""
    return [json.loads(l) for l in (RAIZ / 'codigo' / 'versoes.jsonl').read_text().splitlines()[1:] if l.strip()]


@functools.cache
def codigo():
    """Versão declarada (última linha de codigo/versoes.jsonl) e o commit deste processo: o processo não troca de
    código no meio, então a linha diz com que código saiu."""
    processo = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, cwd=RAIZ)
    return {'versao_codigo': versoes()[-1]['versao'], 'commit': processo.stdout.strip() if processo.returncode == 0 else ''}


def anexar(arquivo, texto):
    """Acrescenta ao JSONL com trava de arquivo: a rodada e quem mede não intercalam linhas."""
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    with open(arquivo, 'a') as saida:
        fcntl.flock(saida, fcntl.LOCK_EX)
        saida.write(texto)
        saida.flush()


def gravar_no_lugar(destino, texto):
    """Temporário e rename: quem lê (o maestro, o painel) nunca vê meio arquivo."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(destino.suffix + '.tmp')
    temporario.write_text(texto)
    temporario.replace(destino)


def gravar(familia, linhas, bancada=()):
    """Linhas em dados/<familia>.parquet (a linha com o mesmo id × extrator × arquivo substitui a anterior) e o
    registro de cada execução em dados/execucoes.jsonl. Um arquivo por família: são centenas de pranchas, não as
    dezenas de milhares de documentos do extrator."""
    if linhas:
        destino = DADOS / f'{familia}.parquet'
        novos = pl.DataFrame(linhas, infer_schema_length=None).with_columns(
            **{coluna: pl.lit(valor) for coluna, valor in codigo().items()})
        with open(DADOS / f'{familia}.lock', 'w') as trava:
            fcntl.flock(trava, fcntl.LOCK_EX)
            if destino.exists():
                antigas = pl.read_parquet(destino).join(novos.select(CHAVES).unique(), on=CHAVES, how='anti')
                novos = pl.concat([antigas, novos], how='diagonal_relaxed')
            temporario = destino.with_suffix('.tmp')
            novos.write_parquet(temporario)
            temporario.replace(destino)
    anexar(DADOS / 'execucoes.jsonl', ''.join(json.dumps({'em': agora(), **b}, ensure_ascii=False) + '\n' for b in bancada))


def ler(familia, ids=None):
    """A família inteira (ou só as linhas dos `ids`), ou None se nada foi gravado."""
    origem = DADOS / f'{familia}.parquet'
    if not origem.exists():
        return None
    tabela = pl.read_parquet(origem)
    return tabela.filter(pl.col('id').is_in(list(ids))) if ids is not None else tabela


def publicar(tabela, destino_no_drive):
    """CSV para o Excel (;, UTF-8 com BOM), gravado em saidas/ com o mesmo caminho e subido com --checksum: só o
    que mudou vai ao Drive."""
    local = SAIDAS / destino_no_drive
    local.parent.mkdir(parents=True, exist_ok=True)
    tabela.write_csv(local, separator=';', include_bom=True)
    remoto = configuracao('operacao')['drive']['saida']
    subprocess.run(['rclone', 'copyto', '--checksum', str(local), f'{remoto}/{destino_no_drive}'], check=True, capture_output=True)
