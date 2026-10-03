"""A prancha de projeto vira dado e vetor: a entrada é o PDF que o ialocal.extrator reconheceu como prancha e entregou
em ~/dados/extracao/para_projeto/ (ou um PDF e uma pasta à mão); a saída, por prancha, a geometria, o DXF e a leitura
inteira (carimbo, revisões, notas, tabelas, família, eixo, o que a IA leu e as provas), e os CSV para o Excel.

    .venv/bin/python codigo/projeto.py ler <arquivo.pdf> [sem_ia]   # uma prancha à mão → saidas/avulsas/
    .venv/bin/python codigo/projeto.py pasta <pasta> [sem_ia]       # todo PDF da pasta
    .venv/bin/python codigo/projeto.py rodada                       # o que o extrator entregou e ainda não foi lido (agendado)
    .venv/bin/python codigo/projeto.py status                       # só regera os CSV e o status.json

Cada prancha é lida uma vez por versão (sha256 × versão em dados/lidas.jsonl); a IA congelada não chama o modelo de
novo na releitura. A rodada pede a vez da GPU ao maestro (cliente_gpu.py, falha aberta).
"""
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import conferencia
import folha
import ia
import itens
import leitura
import linear
import ocr

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / 'dados'
SAIDAS = RAIZ / 'saidas'


def versao():
    """A última versão de codigo/versoes.jsonl e o commit em que o código está."""
    ultima = json.loads((RAIZ / 'codigo' / 'versoes.jsonl').read_text().splitlines()[-1])
    commit = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, cwd=RAIZ).stdout.strip()
    return {'versao': ultima['versao'], 'commit': commit}


def ler(caminho, origem=None, com_ia=None):
    """Uma prancha inteira: cada página de formato A3 ou maior é uma folha, lida pelo código e, com a IA ligada, pelos
    motores locais. Grava dados/pranchas/<sha>/ (geometria por página e leitura.json) e o DXF na pasta da obra."""
    import pypdfium2 as pdfium
    OPERACAO, RECONHECER = ia.configuracao('operacao'), ia.configuracao('prancha')['reconhecer']
    caminho = Path(caminho)
    sha = hashlib.sha256(caminho.read_bytes()).hexdigest()
    origem = origem or {'id': '', 'caminho': f'avulsas/{caminho.name}', 'nome': caminho.name}
    acervo, obra = obra_de(origem)
    destino = SAIDAS / acervo / obra / 'projeto'
    pasta = DADOS / 'pranchas' / sha[:16]
    pasta.mkdir(parents=True, exist_ok=True)
    destino.mkdir(parents=True, exist_ok=True)
    catalogo, documento = folha.catalogo(caminho), pdfium.PdfDocument(caminho)
    prazo, folhas = time.monotonic() + OPERACAO['limite_prancha_s'], []
    for numero in range(min(len(documento), RECONHECER['maximo_paginas'])):
        perfil = folha.perfilar(documento, numero, origem['nome'], catalogo['camadas'])
        if perfil['e_prancha']:
            dxf = destino / f"{Path(origem['nome']).stem}{f'_p{numero + 1}' if len(documento) > 1 else ''}.dxf"
            perfil, primitivas = ler_folha(documento, perfil, pasta, dxf, origem['nome'])
            if OPERACAO['ia'] if com_ia is None else com_ia:
                perfil.update(ler_com_ia(caminho, perfil, primitivas, pasta, prazo))
        folhas.append(perfil)
    registro = {'sha256': sha, 'id': origem.get('id', ''), 'caminho': origem['caminho'], 'nome': origem['nome'], 'acervo': acervo, 'obra': obra,
                'paginas': len(documento), 'camadas': catalogo['camadas'], 'geopdf': catalogo['geopdf'], **versao(),
                'lida_em': datetime.now().isoformat(timespec='seconds'), 'folhas': folhas}
    documento.close()
    (pasta / 'leitura.json').write_text(json.dumps(registro, ensure_ascii=False, indent=1))
    return registro


def obra_de(origem):
    """Acervo e obra da prancha: os que o extrator entregou (o mapa dele, com os nomes do obras.csv); sem eles, pelo
    caminho, com a regra do extrator — o zip ou a pasta do primeiro nível do acervo, e `_avulsos` o arquivo solto."""
    if origem.get('acervo') and origem.get('obra'):
        return origem['acervo'], origem['obra']
    partes = Path(origem['caminho']).parts
    return partes[0], Path(partes[1]).stem if len(partes) > 2 else '_avulsos'


def ler_folha(documento, perfil, pasta, dxf, nome):
    """O que o código lê de uma folha: o vetor (geometria.parquet e DXF), as linhas de texto, as células, as tabelas e o
    quadro de revisões, o carimbo, as notas, a família e, na obra linear, o eixo com a conferência pelo texto real.
    Devolve a folha lida e as primitivas, que a IA usa para achar as imagens coladas."""
    numero = perfil['pagina']
    primitivas = folha.vetorizar(documento[numero - 1], numero - 1)
    folha.gravar_geometria(primitivas, pasta / f'p{numero}_geometria.parquet')
    camadas_dxf = folha.gravar_dxf(primitivas, dxf, (perfil['largura_mm'], perfil['altura_mm']))
    linhas, celulas = leitura.linhas_de_texto(primitivas), leitura.celulas(primitivas)
    achadas = leitura.tabelas(linhas, celulas)
    carimbo = leitura.carimbo(linhas, celulas, (perfil['largura_mm'], perfil['altura_mm']), nome, fora=achadas)
    familia = leitura.familia(nome, carimbo['texto'] or '\n'.join(l['texto'] for l in linhas))
    eixo = linear.eixo(primitivas) if familia['grupo'] == 'linear' else None
    tubos = [f for t in achadas if t['tipo'] == 'relacao_materiais' for f in t['linhas'][1:]]
    return {**perfil, 'dxf': str(dxf.relative_to(SAIDAS)), 'camadas_dxf': camadas_dxf, **folha.contagem(primitivas),
            'carimbo': {**carimbo, 'conferido': conferencia.provas({c: {'codigo': v} for c, v in carimbo['campos'].items()}, [carimbo['texto']])},
            'revisoes': [r for t in achadas if t['tipo'] == 'revisoes' for r in leitura.revisoes(t)],
            'tabelas': [{**t, 'origem': 'vetor', 'itens': itens.itens(t['linhas'], {'tabela': n})}
                        for n, t in enumerate((t for t in achadas if t['tipo'] != 'revisoes'), 1)], 'notas': leitura.notas(linhas),
            'familia': familia, 'eixo': eixo,
            'conferencia': linear.conferir(eixo, linear.escala(carimbo['campos'].get('escala', '')), tubos) if eixo else None}, primitivas


def ler_com_ia(caminho, perfil, primitivas, pasta, prazo):
    """O que a IA local acrescenta a uma folha, sempre conferido: o carimbo pelas provas (sem texto real, o recorte dele
    lido pelo Vision e pelo glm-ocr), a família sem regra, as fatias da folha sem texto real e as tabelas coladas como
    imagem; a conferência refeita com as escalas e os tubos confirmados."""
    PARAMETROS, numero = ia.configuracao('extratores')['parametros'], perfil['pagina']
    carimbo, lidos, erros = perfil['carimbo'], {}, {}
    if not carimbo['texto']:
        imagem = conferencia.recorte(caminho, numero, carimbo['zona'], PARAMETROS['carimbo_dpi'], pasta / f'p{numero}_carimbo.png')
        lidos, erros = conferencia.ocr_duplo(imagem)
    conferido, erros_ia = conferencia.carimbo_conferido(carimbo, lidos, True)
    texto = carimbo['texto'] or '\n'.join(lidos.values())
    familia = perfil['familia']
    if familia['familia'] == 'indefinida':
        familia = {**familia, **conferencia.desempatar(texto)}
    valores, conta = ocr.ler_fatias(caminho, numero, pasta, prazo) if perfil['classe'] != 'vetorial_texto' else ([], {})
    coladas = ocr.tabelas_coladas(caminho, numero, primitivas, pasta, prazo) if perfil['classe'] != 'raster' else []
    resultado = {'carimbo': {**carimbo, 'conferido': conferido, 'ocr': lidos}, 'familia': familia, 'valores_ocr': valores,
                 'fatias': conta, 'tabelas_coladas': coladas, 'itens_colados': itens_colados(coladas), 'erros_ia': {**erros, **erros_ia},
                 'motivo_ia': 'tempo: parou no limite (operacao.json → limite_prancha_s)' if time.monotonic() > prazo else ''}
    if perfil.get('eixo'):
        escala = conferido.get('escala', {})
        escalas = linear.escala(escala['valor']) if escala.get('status') == 'confirmado' or 'codigo' in escala.get('fontes', {}) else []
        escalas += [int(v['valor'].split(':')[1].replace('.', '')) for v in valores if v['padrao'] == 'escala' and v['status'] == 'confirmado']
        tubos = [f for t in perfil['tabelas'] if t['tipo'] == 'relacao_materiais' for f in t['linhas'][1:]] + \
                [c['celulas'] for c in coladas if c['status'] == 'confirmada']
        resultado['conferencia'] = linear.conferir(perfil['eixo'], escalas, tubos)
    return resultado


def itens_colados(coladas):
    """Os itens de cada tabela colada como imagem: as faixas na ordem, sem as linhas que a sobreposição repetiu no
    começo da faixa seguinte (a linha repetida dentro da mesma faixa fica: pode estar impressa duas vezes, Cambé 12)."""
    achados = []
    for imagem in sorted({c['imagem'] for c in coladas}):
        linhas, situacao, anterior = [], [], []
        for faixa in sorted({c['faixa'] for c in coladas if c['imagem'] == imagem}):
            atuais = [c for c in sorted(coladas, key=lambda c: c['linha']) if c['imagem'] == imagem and c['faixa'] == faixa and c['celulas']]
            while atuais and anterior and atuais[0]['celulas'] in anterior[-len(atuais):]:
                atuais.pop(0)
            linhas += [c['celulas'] for c in atuais]
            situacao += [c['status'] for c in atuais]
            anterior = [c['celulas'] for c in atuais] or anterior
        achados += itens.itens(linhas, {'tabela': f'imagem{imagem}'}, situacao)
    return achados


def lidas():
    """sha256 → a última leitura (versão, quando, erro) de dados/lidas.jsonl."""
    arquivo = DADOS / 'lidas.jsonl'
    return {r['sha256']: r for r in map(json.loads, arquivo.read_text().splitlines())} if arquivo.exists() else {}


def anexar_lida(registro):
    DADOS.mkdir(parents=True, exist_ok=True)
    with open(DADOS / 'lidas.jsonl', 'a') as saida:
        saida.write(json.dumps(registro, ensure_ascii=False) + '\n')


def entregas():
    """O que o extrator entregou: uma linha por PDF (o mesmo sha256 entregue de novo vale uma vez), o arquivo na pasta."""
    pasta = Path(ia.configuracao('operacao')['entregas']).expanduser()
    arquivo = pasta / 'entregas.jsonl'
    if not arquivo.exists():
        return pasta, []
    unicas = {}
    for linha in map(json.loads, arquivo.read_text().splitlines()):
        if linha.get('tipo') != 'metadata':
            unicas[linha['sha256']] = linha
    return pasta, list(unicas.values())


def rodada():
    """Lê o que o extrator entregou e ainda não foi lido nesta versão, até `pranchas_por_rodada`, na vez da GPU; depois
    publica."""
    from cliente_gpu import vez_da_gpu
    OPERACAO = ia.configuracao('operacao')
    pasta, todas = entregas()
    atual, feitas = versao()['versao'], lidas()
    pendentes = [e for e in todas if feitas.get(e['sha256'], {}).get('versao') != atual][:OPERACAO['pranchas_por_rodada']]
    marca, resultado = time.monotonic(), {'lidas': 0, 'erros': 0}
    if pendentes:
        GPU = OPERACAO['gpu']
        with vez_da_gpu('ialocal.projeto', str(DADOS / 'gpu'), GPU['prioridade'], modelo='glm-ocr', tarefa=GPU['tarefa']) as vez:
            resultado = ler_pendentes(pendentes, pasta, atual, vez)
    publicar({**resultado, 'pendentes': len(pendentes), 'segundos': round(time.monotonic() - marca, 1)})


def ler_pendentes(pendentes, pasta, atual, vez):
    """Cada prancha pendente, enquanto a vez é nossa; a que falha registra o erro e não segura as outras."""
    resultado = {'lidas': 0, 'erros': 0}
    for entrega in pendentes:
        if not vez.minha():  # alguém mais importante espera: a próxima rodada continua
            break
        try:
            registro = ler(pasta / f"{entrega['sha256']}.pdf", entrega)
            anexar_lida({'sha256': entrega['sha256'], 'versao': atual, 'em': registro['lida_em'], 'erro': ''})
            resultado['lidas'] += 1
        except Exception as falha:  # a prancha que não abre fica com o motivo; a rodada segue
            anexar_lida({'sha256': entrega['sha256'], 'versao': atual, 'em': datetime.now().isoformat(timespec='seconds'),
                         'erro': f'{type(falha).__name__}: {falha}'[:300]})
            resultado['erros'] += 1
    return resultado


def escrever_csv(destino, linhas):
    """CSV com ; e UTF-8 com BOM (o que o Excel em português abre certo), as colunas na ordem em que aparecem."""
    colunas = list(dict.fromkeys(c for linha in linhas for c in linha))
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, 'w', newline='', encoding='utf-8-sig') as saida:
        escritor = csv.DictWriter(saida, colunas, delimiter=';')
        escritor.writeheader()
        escritor.writerows({c: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for c, v in linha.items()} for linha in linhas)


def publicar(ultima_rodada=None):
    """Os CSV (pranchas, carimbo campo a campo, tabelas, revisões, notas, valores do OCR): de todas as pranchas em
    saidas/_sistema/projeto/ e os de cada obra em saidas/<acervo>/<obra>/projeto/, ao lado do DXF dela — no Drive, ao
    lado do extrator/, revisor/ e contexto/ da obra (extrator 2v93). Depois o status.json no formato comum do maestro e,
    na rodada com rclone, a pasta saidas/ no Drive (só o que mudou; o status e as avulsas ficam no mini)."""
    registros = [json.loads(a.read_text()) for a in sorted((DADOS / 'pranchas').glob('*/leitura.json'))] if (DADOS / 'pranchas').exists() else []
    por_obra = {}
    for registro in registros:
        por_obra.setdefault((registro['acervo'], registro['obra']), []).append(registro)
    for pasta, grupo in [(SAIDAS / '_sistema' / 'projeto', registros)] + [(SAIDAS / a / o / 'projeto', g) for (a, o), g in por_obra.items()]:
        for nome, linhas in tabelas_csv(grupo).items():
            escrever_csv(pasta / f'{nome}.csv', linhas)
    status(registros, ultima_rodada)
    if shutil.which('rclone') and ultima_rodada is not None:
        subprocess.run(['rclone', 'copy', '--checksum', '--exclude', '/status.json', '--exclude', '/avulsas/**', str(SAIDAS),
                        ia.configuracao('operacao')['drive']], capture_output=True)


def tabelas_csv(registros):
    """As linhas de cada CSV, de um grupo de pranchas: uma por folha, por campo do carimbo, por linha de tabela, por
    revisão, por item de nota e por valor lido no OCR."""
    tabelas = {nome: [] for nome in ('pranchas', 'carimbo', 'itens', 'tabelas', 'revisoes', 'notas', 'valores_ocr')}
    for registro in registros:
        for f in (f for f in registro['folhas'] if f['e_prancha']):
            chave = {'obra': registro['obra'], 'arquivo': registro['nome'], 'caminho': registro['caminho'], 'pagina': f['pagina']}
            tabelas['pranchas'].append(linha_da_prancha(registro, f, chave))
            tabelas['carimbo'] += [{**chave, 'campo': c, **v} for c, v in f['carimbo']['conferido'].items()]
            tabelas['tabelas'] += [{**chave, 'tabela': n, 'tipo': t['tipo'], 'origem': t['origem'], 'linha': k, **{f'c{j + 1}': v for j, v in enumerate(l)}}
                                   for n, t in enumerate(f['tabelas'], 1) for k, l in enumerate(t['linhas'])]
            tabelas['tabelas'] += [{**chave, 'tabela': f"imagem{c['imagem']}", 'tipo': 'colada', 'origem': 'ocr', 'linha': c['linha'],
                                    'status': c['status'], **{f'c{j + 1}': v for j, v in enumerate(c['celulas'])}} for c in f.get('tabelas_coladas', [])]
            tabelas['itens'] += [{**chave, 'origem': 'vetor', **i} for t in f['tabelas'] for i in t.get('itens', [])]
            tabelas['itens'] += [{**chave, 'origem': 'ocr', **i} for i in f.get('itens_colados', [])]
            tabelas['revisoes'] += [{**chave, **r} for r in f['revisoes']]
            tabelas['notas'] += [{**chave, 'bloco': b['titulo'], **i} for b in f['notas'] for i in b['itens']]
            tabelas['valores_ocr'] += [{**chave, **v} for v in f.get('valores_ocr', [])]
    return tabelas


def linha_da_prancha(registro, f, chave):
    """Uma linha do pranchas.csv: formato, classe, família, os campos do carimbo aceitos, contagens e a conferência."""
    campos = {c: v['valor'] for c, v in f['carimbo']['conferido'].items() if v['status'] in ('confirmado', 'um_leitor')}
    return {**chave, 'formato': f['formato'], 'classe': f['classe'], 'familia': f['familia']['familia'], 'grupo': f['familia']['grupo'],
            'desenho_tipo': f['familia']['desenho'], 'disciplina': f['carimbo']['disciplina'], **campos,
            'revisao_nome': f['carimbo']['revisao_nome'], 'arquivo_confere': f['carimbo']['arquivo_confere'],
            'campos_confirmados': sum(v['status'] == 'confirmado' for v in f['carimbo']['conferido'].values()),
            'campos_divergentes': sum(v['status'] == 'divergente' for v in f['carimbo']['conferido'].values()),
            'inventados': sum(bool(v['inventado']) for v in f['carimbo']['conferido'].values()),
            'revisoes': len(f['revisoes']), 'tabelas': len(f['tabelas']),
            'itens': sum(len(t.get('itens', [])) for t in f['tabelas']) + len(f.get('itens_colados', [])), 'notas': sum(len(b['itens']) for b in f['notas']),
            'primitivas': f['primitivas'], 'camadas': len(registro['camadas']), 'geopdf': registro['geopdf'], 'dxf': f['dxf'],
            'eixo_mm': (f['eixo'] or {}).get('eixo_mm'), **{k: (f['conferencia'] or {}).get(k) for k in ('eixo_m', 'tubo_relacao_m', 'conferencia')},
            'versao': registro['versao'], 'lida_em': registro['lida_em']}


def status(registros=None, ultima_rodada=None):
    """O saidas/status.json no formato comum do maestro (repo, versão, commit, saúde, motivo, progresso, precisa_do_caio,
    usa_gpu). Atenção: sem a pasta de entregas do extrator, ou com prancha que falhou na versão atual."""
    pasta, todas = entregas()
    atual, feitas = versao(), lidas()
    nesta = [feitas[e['sha256']] for e in todas if feitas.get(e['sha256'], {}).get('versao') == atual['versao']]
    falhas = [l for l in nesta if l['erro']]
    motivo = (f'sem entregas do extrator em {pasta}' if not pasta.exists() else
              f'{len(falhas)} prancha(s) com erro na {atual["versao"]}' if falhas else '')
    conteudo = {'repo': 'ialocal.projeto', **atual, 'gerado_em': datetime.now().isoformat(timespec='seconds'),
                'saude': 'atenção' if motivo else 'ok', 'motivo': motivo,
                'progresso': {'feito': len(nesta), 'total': len(todas)}, 'precisa_do_caio': [l['sha256'][:16] for l in falhas][:20],
                'usa_gpu': True, 'pranchas_lidas': len(registros or []), 'ultima_rodada': ultima_rodada or {}}
    SAIDAS.mkdir(parents=True, exist_ok=True)
    temporario = SAIDAS / '.status.json'
    temporario.write_text(json.dumps(conteudo, ensure_ascii=False, indent=1))
    temporario.replace(SAIDAS / 'status.json')
    return conteudo


def pasta_inteira(pasta, sem_ia=''):
    """Todo PDF de uma pasta, à mão: cada um em saidas/avulsas/, e os CSV no fim."""
    for caminho in sorted(Path(pasta).rglob('*.pdf')):
        registro = ler(caminho, com_ia=False if sem_ia else None)
        print(f"{caminho.name}: {sum(f['e_prancha'] for f in registro['folhas'])} folha(s) de prancha de {registro['paginas']}")
    publicar()


if __name__ == '__main__':
    COMANDOS = {'ler': lambda caminho, sem_ia='': (ler(caminho, com_ia=False if sem_ia else None), publicar()),
                'pasta': pasta_inteira, 'rodada': rodada, 'status': publicar}
    COMANDOS[sys.argv[1] if len(sys.argv) > 1 else 'rodada'](*sys.argv[2:])
