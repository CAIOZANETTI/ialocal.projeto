"""Operação no Mac mini: `atualizar` traz a main aprovada (só fast-forward) e reagenda o que mudou; `instalar` agenda a
rodada e o atualizar no launchd com o python do .venv. Registros em dados/ (launchd.log e atualizacao.jsonl).

    .venv/bin/python codigo/mini.py instalar     # só na primeira vez
    .venv/bin/python codigo/mini.py atualizar
"""
import hashlib
import json
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REGISTROS = RAIZ / 'dados'
PREFIXO = 'com.caiozanetti.ialocal.projeto'
AGENDAS = {
    'rodada': (['ciclo.py', 'rodada'], {'StartInterval': 300}),  # sai sozinha (rodada_max_s); a seguinte sai na hora se a anterior roda
    'pedido': (['pedido.py', 'vigiar'], {'StartInterval': 60, 'WatchPaths': [os.path.expanduser('~/dados/ialocal.web/saidas/pedidos')]}),  # 0v27: o pedido do Caio por e-mail, na hora
    'atualizar': (['mini.py', 'atualizar'], {'StartInterval': 300}),  # por último: reagendá-lo encerra quem reagenda
}


def git(*argumentos):
    return subprocess.run(['git', *argumentos], capture_output=True, text=True, cwd=RAIZ)


def registrar(registro):
    REGISTROS.mkdir(parents=True, exist_ok=True)
    with (REGISTROS / 'atualizacao.jsonl').open('a') as saida:
        saida.write(json.dumps({'em': time.strftime('%Y-%m-%dT%H:%M:%S'), **registro}, ensure_ascii=False) + '\n')


def atualizar():
    """Só fast-forward da main: fora dela, ou com mudança local, para e registra — o maestro vê o código fora da main."""
    ramo = git('rev-parse', '--abbrev-ref', 'HEAD').stdout.strip()
    if ramo != 'main':
        registrar({'ok': False, 'erro': f'fora da main: {ramo}'})
        sys.exit(f'FALHA  fora da main ({ramo}): git checkout main')
    antes = git('rev-parse', '--short', 'HEAD').stdout.strip()
    busca = git('fetch', '--quiet', 'origin', 'main')
    avanco = busca if busca.returncode else git('merge', '--ff-only', '--quiet', 'origin/main')
    depois = git('rev-parse', '--short', 'HEAD').stdout.strip()
    if avanco.returncode:
        registrar({'ok': False, 'commit': antes, 'erro': avanco.stderr.strip()})
        sys.exit(f'FALHA  {avanco.stderr.strip()}')
    if antes != depois:
        registrar({'ok': True, 'de': antes, 'para': depois, 'commits': git('log', '--format=%h %s', f'{antes}..{depois}').stdout.splitlines()})
    print(f'atualizar: {antes} → {depois}' if antes != depois else f'atualizar: {depois} já é a main')
    if Path(sys.executable).parent.parent == RAIZ / '.venv':
        requisitos()
        subprocess.run([sys.executable, str(RAIZ / 'codigo' / 'mini.py'), 'instalar', 'mudados'], cwd=RAIZ, timeout=120)


def requisitos():
    """0v38: codigo/requisitos.txt mudou desde a última instalação → pip install no .venv (o OpenCV e o PP-OCR da
    tabela pela grade chegam sem o Caio digitar nada). Falhou: registra e segue — o código diz o que faltou."""
    arquivo, marca = RAIZ / 'codigo' / 'requisitos.txt', REGISTROS / 'requisitos.sha1'
    if not arquivo.exists():
        return
    assinatura = hashlib.sha1(arquivo.read_bytes()).hexdigest()
    if marca.exists() and marca.read_text().strip() == assinatura:
        return
    try:
        feito = subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', '-r', str(arquivo)],
                               capture_output=True, text=True, cwd=RAIZ, timeout=1200)
    except subprocess.TimeoutExpired:
        registrar({'ok': False, 'requisitos': assinatura[:10], 'erro': 'pip passou de 20 min'})
        return
    if feito.returncode:
        registrar({'ok': False, 'requisitos': assinatura[:10], 'erro': feito.stderr.strip()[-500:]})
        return
    REGISTROS.mkdir(parents=True, exist_ok=True)
    marca.write_text(assinatura)
    registrar({'ok': True, 'requisitos': assinatura[:10]})


def plist(rotulo, argumentos, agenda):
    return plistlib.dumps({
        'Label': rotulo, 'ProgramArguments': [sys.executable, str(RAIZ / 'codigo' / argumentos[0]), *argumentos[1:]],
        'RunAtLoad': True, **agenda,
        'EnvironmentVariables': {'PATH': f'/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:{Path.home()}/.local/bin', 'PYTHONUNBUFFERED': '1'},
        'StandardOutPath': str(REGISTROS / 'launchd.log'), 'StandardErrorPath': str(REGISTROS / 'launchd.log')})


def instalar(modo='tudo'):
    """Agenda com o python que roda este comando; `mudados` só o plist que é novo ou mudou (o atualizar chama)."""
    REGISTROS.mkdir(parents=True, exist_ok=True)
    dominio = f'gui/{os.getuid()}'
    for nome, (argumentos, agenda) in AGENDAS.items():
        rotulo = f'{PREFIXO}.{nome}'
        destino = Path.home() / 'Library' / 'LaunchAgents' / f'{rotulo}.plist'
        conteudo = plist(rotulo, argumentos, agenda)
        if modo == 'mudados' and (nome == 'atualizar' or (destino.exists() and destino.read_bytes() == conteudo)):
            continue
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(conteudo)
        subprocess.run(['launchctl', 'bootout', dominio, str(destino)], capture_output=True, timeout=60)
        for _ in range(5):  # o bootstrap logo depois do bootout de um job que ainda está saindo falha (erro 5)
            if not subprocess.run(['launchctl', 'bootstrap', dominio, str(destino)], capture_output=True, timeout=60).returncode:
                break
            time.sleep(3)
        print(f'agendado: {rotulo}', flush=True)


if __name__ == '__main__':
    {'atualizar': atualizar, 'instalar': instalar}[sys.argv[1]](*sys.argv[2:])
