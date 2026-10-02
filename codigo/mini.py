"""Operação no Mac mini (MASTER-PLAN §5.4, no ialocal.maestro): `atualizar` traz a main aprovada (só fast-forward,
registra cada troca de commit e reagenda o que mudou); `instalar` agenda a rodada e o atualizar no launchd, com o
python do .venv. A verificação da máquina (só IA local, FileVault, suspensão) é do extrator e do maestro, não daqui.
Registros em dados/mini/*.jsonl.

    .venv/bin/python codigo/mini.py instalar
    .venv/bin/python codigo/mini.py atualizar
"""
import json
import os
import plistlib
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REGISTROS = RAIZ / 'dados' / 'mini'
PREFIXO = 'com.caiozanetti.ialocal.projeto'


def rodar(*comando):
    return subprocess.run(comando, capture_output=True, text=True, cwd=RAIZ)


def registrar(arquivo, registro):
    """Acrescenta ao JSONL; a primeira linha de um arquivo novo é a metadata."""
    caminho = REGISTROS / arquivo
    caminho.parent.mkdir(parents=True, exist_ok=True)
    novo = not caminho.exists()
    with caminho.open('a') as saida:
        if novo:
            saida.write(json.dumps({'tipo': 'metadata', 'fonte': 'codigo/mini.py', 'arquivo': arquivo}, ensure_ascii=False) + '\n')
        saida.write(json.dumps({'em': datetime.now().isoformat(timespec='seconds'), **registro}, ensure_ascii=False) + '\n')


def atualizar():
    """Traz a main aprovada. Só fast-forward: mudança local, histórico reescrito ou outro ramo param e registram falha."""
    ramo = rodar('git', 'branch', '--show-current').stdout.strip()
    if ramo != 'main':
        registrar('atualizacao.jsonl', {'ok': False, 'erro': f'fora da main: {ramo or "HEAD solto"}'})
        sys.exit(f'FALHA  fora da main ({ramo or "HEAD solto"}): git checkout main')
    antes = rodar('git', 'rev-parse', '--short', 'HEAD').stdout.strip()
    busca = rodar('git', 'fetch', '--quiet', 'origin', 'main')
    avanco = busca if busca.returncode else rodar('git', 'merge', '--ff-only', '--quiet', 'origin/main')
    depois = rodar('git', 'rev-parse', '--short', 'HEAD').stdout.strip()
    if avanco.returncode:
        registrar('atualizacao.jsonl', {'ok': False, 'commit': antes, 'erro': avanco.stderr.strip()})
        sys.exit(f'FALHA  {avanco.stderr.strip()}')
    print(f"{datetime.now():%d/%m %H:%M:%S}  atualizar: {antes} → {depois}" if antes != depois else f'atualizar: {depois} já é a main')
    if antes != depois:
        registrar('atualizacao.jsonl', {'ok': True, 'de': antes, 'para': depois,
                                        'commits': rodar('git', 'log', '--format=%h %s', f'{antes}..{depois}').stdout.splitlines()})
        reagendar_se_mudou()


def agendas():
    """LaunchAgents (rodam depois do login). A rodada lê as entregas do extrator a cada 10 min e sai; o atualizar vai
    por último: reagendá-lo encerra o processo que está reagendando."""
    return {
        'rodada': (['projeto.py', 'rodada'], {'StartInterval': 600}),
        'atualizar': (['mini.py', 'atualizar'], {'StartInterval': 300}),
    }


def plist(rotulo, argumentos, agenda):
    return plistlib.dumps({
        'Label': rotulo,
        'ProgramArguments': [sys.executable, str(RAIZ / 'codigo' / argumentos[0]), *argumentos[1:]],
        'RunAtLoad': True,
        **agenda,
        'EnvironmentVariables': {'PATH': f'/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:{Path.home()}/.local/bin', 'PYTHONUNBUFFERED': '1'},
        'StandardOutPath': str(REGISTROS / 'launchd.log'),
        'StandardErrorPath': str(REGISTROS / 'launchd.log'),
    })


def instalar(modo='tudo'):
    """Agenda tudo com o python que roda este comando. `mudados`: só o que é novo ou mudou (o atualizar chama assim)."""
    REGISTROS.mkdir(parents=True, exist_ok=True)
    dominio = f'gui/{os.getuid()}'
    for nome, (argumentos, agenda) in agendas().items():
        rotulo = f'{PREFIXO}.{nome}'
        destino = Path.home() / 'Library' / 'LaunchAgents' / f'{rotulo}.plist'
        conteudo = plist(rotulo, argumentos, agenda)
        if modo == 'mudados' and destino.exists() and destino.read_bytes() == conteudo:
            continue
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(conteudo)
        print(f'agendado: {rotulo}', flush=True)
        subprocess.run(['launchctl', 'bootout', dominio, str(destino)], capture_output=True)
        subprocess.run(['launchctl', 'bootstrap', dominio, str(destino)], check=True)


def reagendar_se_mudou():
    """Depois de trazer código novo: o instalar do código novo (outro processo), só para as agendas que mudaram, e só
    com o python do .venv — o do sistema não tem as bibliotecas e trocaria o python de todas."""
    if Path(sys.executable).parent.parent != RAIZ / '.venv':
        return print('código novo: se a lista de agendas mudou, rode .venv/bin/python codigo/mini.py instalar')
    processo = subprocess.run([sys.executable, str(RAIZ / 'codigo' / 'mini.py'), 'instalar', 'mudados'], capture_output=True, text=True, cwd=RAIZ)
    registrar('atualizacao.jsonl', {'ok': processo.returncode == 0, 'erro': processo.stderr.strip()[-500:],
                                    'reagendadas': [l.split(': ', 1)[1] for l in processo.stdout.splitlines() if l.startswith('agendado: ')]})


if __name__ == '__main__':
    COMANDOS = {'atualizar': atualizar, 'instalar': instalar}
    COMANDOS[sys.argv[1]](*sys.argv[2:])
