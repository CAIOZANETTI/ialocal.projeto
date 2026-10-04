"""A bancada dos agentes (notas/plano_agentes_nvidia.md §6–§8, F2): cada leitor contra um gabarito, e a curadoria
com e sem cada agente — o veredito de cada agente sai dos critérios do §7, escritos antes de rodar.

    .venv/bin/python codigo/bancada.py tabelas            # B1: as 17 tabelas de Cambé (188 linhas transcritas pelo Caio)
    .venv/bin/python codigo/bancada.py controle           # B2: recortes sem número nenhum: todo número lido é invenção
    .venv/bin/python codigo/bancada.py sondagem [pdf…]    # B5: boletins de sondagem (sem pdf: os do acervo)
    .venv/bin/python codigo/bancada.py placar             # o placar e o veredito; saidas/bancada_agentes.csv e o Drive
    .venv/bin/python codigo/bancada.py tudo               # os três conjuntos e o placar

Os agentes leem em paralelo (agentes.em_paralelo); os leitores locais (glm-ocr e Vision) só no mini, na vez da GPU —
sem eles a bancada mede os agentes sozinhos e o placar diz que faltou o local. Tudo é congelado: rodar de novo não
chama modelo nenhum para o que já foi lido.
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import polars as pl

import agentes
import cliente_gpu
import comum
import curadoria
import ia
import prancha
import sondagem

CAMBE = comum.RAIZ / 'amostras' / 'tabelas' / '216_cambe'
PASTA = comum.DADOS / 'bancada'
CONJUNTOS = ('tabelas', 'controle', 'sondagem')


def gravar(conjunto, linhas):
    """dados/bancada_<conjunto>.parquet, inteiro a cada rodada do conjunto (a congelada não chama modelo: é barato)."""
    if not linhas:  # nada a medir (sem boletim reconhecido, por exemplo): fica a bancada anterior do conjunto
        print(f'bancada {conjunto}: nenhum recorte com referência para medir')
        return None
    comum.DADOS.mkdir(parents=True, exist_ok=True)
    tabela = pl.DataFrame(linhas, infer_schema_length=None).with_columns(
        **{coluna: pl.lit(valor) for coluna, valor in comum.codigo().items()}, conjunto=pl.lit(conjunto), em=pl.lit(comum.agora()))
    tabela.write_parquet(comum.DADOS / f'bancada_{conjunto}.parquet')
    return tabela


def ler_local(imagem, modo):
    """glm-ocr e Vision no recorte: (linhas da tabela do glm-ocr, texto do glm-ocr, texto do Vision, erro). Sem
    Ollama ou sem Vision, o que faltou fica no erro e a bancada segue com os agentes."""
    com_vision = ia.instalado('Vision')
    try:
        if modo == 'tabela':
            lidas = prancha.ler_tabela(imagem, com_vision, {})
            linhas = [json.loads(l['celulas']) for l in lidas if l['linha']]
            texto = '\n'.join(' '.join(c) for c in linhas)
            erro = next((l['erro'] for l in lidas if l.get('erro')), '')
        else:
            lida = ia.ocr_da_pagina(imagem)
            linhas, texto, erro = [], lida['texto'], lida['erro']
    except (OSError, RuntimeError, ValueError, StopIteration) as falha:  # StopIteration: o modelo não está no Ollama
        return [], '', '', f'glm-ocr: {type(falha).__name__}: {falha}'[:300]
    try:
        vision = ia.ler_com_vision(imagem)['texto'] if com_vision else ''
    except (ImportError, RuntimeError) as falha:
        vision, erro = '', erro or f'Vision: {falha}'[:300]
    return linhas, texto, vision, erro or ('' if com_vision else 'Vision ausente (só no macOS)')


def locais(imagens, modo):
    """recorte → leitura local de cada imagem, na vez da GPU do maestro (a bancada é de fundo: prioridade da rodada)."""
    GPU = comum.configuracao('operacao')['gpu']
    print(f"local: pedindo a vez da GPU ao maestro (prioridade {GPU['prioridade']}) para {len(imagens)} recortes; "
          '--sem-local pula esta parte', flush=True)
    lidas = {}
    with cliente_gpu.vez_da_gpu('ialocal.projeto', str(comum.DADOS / 'gpu'), GPU['prioridade'], GPU['modelo'], 'bancada') as vez:
        for imagem in imagens:
            if not vez.minha():
                break
            marca = time.perf_counter()
            linhas, texto, vision, erro = ler_local(imagem, modo)
            print(f'local  {Path(imagem).name[:34]:<34} {time.perf_counter() - marca:6.1f} s  linhas {len(linhas):>3}'
                  + (f'  ERRO {erro[:100]}' if erro else ''), flush=True)
            lidas[str(imagem)] = {'linhas': linhas, 'texto': texto, 'vision': vision, 'erro': erro,
                                  'segundos': round(time.perf_counter() - marca, 2)}
            if erro.startswith('glm-ocr'):  # sem Ollama não adianta tentar as outras
                break
    return lidas


def externos(imagens, modo):
    """(agente, recorte) → leitura de cada agente, em paralelo."""
    print(f'agentes: {len(imagens)} recortes × {len(comum.configuracao("agentes")["agentes"])} agentes, modo {modo}', flush=True)
    return {(l['agente'], l['recorte']): l for l in agentes.em_paralelo(imagens, modo=modo, progresso=True)}


def tabelas(com_local=True):
    """B1: cada tabela de Cambé por cada leitor; uma linha por leitor (e por curadoria) × linha do gabarito: certa,
    errada (código achado, quantidade ou unidade diferente) ou faltou; e uma por linha lida com código fora do gabarito
    (inventada). As curadorias: local (glm-ocr + Vision), local+<agente>, local+agentes, agentes (sem testemunha)."""
    gabaritos = agentes.gabarito_cambe()
    imagens = sorted(p for p in CAMBE.glob('*.png') if p.stem.upper() in gabaritos)
    de_fora = externos(imagens, 'tabela')
    de_dentro = locais(imagens, 'tabela') if com_local else {}
    nomes = list(comum.configuracao('agentes')['agentes'])
    linhas = []
    for imagem in imagens:
        gabarito = gabaritos[imagem.stem.upper()]
        local = de_dentro.get(str(imagem))
        leituras = {n: de_fora[(n, str(imagem))]['linhas'] for n in nomes}
        quem_leu = {n: (de_fora[(n, str(imagem))]['segundos'], de_fora[(n, str(imagem))]['erro']) for n in nomes}
        if local:  # sem leitura local (fora do mini, ou sem Ollama) o glm-ocr não entra: nem como leitor nem na curadoria
            leituras['glm_ocr'], quem_leu['glm_ocr'] = local['linhas'], (local['segundos'], local['erro'])
        for leitor, lidas in leituras.items():
            segundos, erro = quem_leu[leitor]
            base = {'recorte': imagem.name, 'leitor': leitor, 'tipo': 'leitor', 'segundos': segundos, 'erro': erro,
                    'respondeu': bool(lidas) or not erro}
            linhas += comparar(curadoria.por_codigo(lidas), gabarito, base, status={})
        combinacoes = {'agentes': nomes}
        if local:
            combinacoes |= {'local': ['glm_ocr'], **{f'local+{n}': ['glm_ocr', n] for n in nomes}, 'local+agentes': ['glm_ocr', *nomes]}
        for nome, quem in combinacoes.items():
            testemunha = local['vision'] if local and nome != 'agentes' else ''
            curadas = curadoria.curar_tabela({q: leituras[q] for q in quem}, testemunha)
            base = {'recorte': imagem.name, 'leitor': nome, 'tipo': 'curadoria', 'segundos': None, 'erro': '', 'respondeu': True}
            linhas += comparar({c: (v['quant'], v['und']) for c, v in curadas.items()}, gabarito, base,
                               status={c: v['status'] for c, v in curadas.items()})
    return gravar('tabelas', linhas)


def comparar(lidas, gabarito, base, status):
    """As linhas da bancada de um leitor (ou curadoria) numa tabela: código → (quantidade, unidade) × gabarito."""
    linhas = []
    for linha in gabarito:
        lido = lidas.get(linha['codigo'])
        esperado = (prancha.normalizar(linha['quant']), curadoria.unidade(linha['und']))
        resultado = 'faltou' if lido is None else 'certa' if lido == esperado else 'errada'
        linhas.append({**base, 'chave': linha['codigo'], 'lido': ' '.join(lido) if lido else '', 'esperado': ' '.join(esperado),
                       'resultado': resultado, 'status': status.get(linha['codigo'], '')})
    codigos = {l['codigo'] for l in gabarito}
    linhas += [{**base, 'chave': c, 'lido': ' '.join(v), 'esperado': '', 'resultado': 'inventada', 'status': status.get(c, '')}
               for c, v in lidas.items() if c not in codigos]
    return linhas


def recortes_de_controle():
    """B2: recortes sem número nenhum, no formato das tabelas — em branco, a grade vazia de uma relação, o texto de uma
    legenda sem algarismo — e os do Caio em amostras/controle/, se houver. Ficam em dados/bancada/controle/."""
    from PIL import Image, ImageDraw
    pasta = PASTA / 'controle'
    pasta.mkdir(parents=True, exist_ok=True)
    feitos = []
    branco = pasta / 'em_branco.png'
    Image.new('RGB', (800, 300), 'white').save(branco)
    grade = Image.new('RGB', (800, 300), 'white')
    desenho = ImageDraw.Draw(grade)
    for y in range(20, 300, 40):
        desenho.line([(20, y), (780, y)], fill='black', width=2)
    for x in (20, 140, 200, 600, 700, 780):
        desenho.line([(x, 20), (x, 260)], fill='black', width=2)
    grade.save(pasta / 'grade_vazia.png')
    legenda = Image.new('RGB', (800, 300), 'white')
    desenho = ImageDraw.Draw(legenda)
    for n, texto in enumerate(['LEGENDA', 'REDE PROJETADA', 'REDE EXISTENTE', 'REGISTRO DE GAVETA', 'VENTOSA',
                               'DESCARGA', 'LIMITE DE LOTE', 'MEIO-FIO']):
        desenho.text((40, 20 + 32 * n), texto, fill='black')
    legenda.save(pasta / 'legenda_sem_numero.png')
    feitos += [branco, pasta / 'grade_vazia.png', pasta / 'legenda_sem_numero.png']
    return feitos + sorted((comum.RAIZ / 'amostras' / 'controle').glob('*.png'))


def controle(com_local=True):
    """B2: cada recorte sem número por cada leitor, no modo texto; quantos números cada um escreveu."""
    imagens = recortes_de_controle()
    de_fora = externos(imagens, 'texto')
    de_dentro = locais(imagens, 'texto') if com_local else {}
    linhas = []
    for imagem in imagens:
        local = de_dentro.get(str(imagem))
        lidas = {n: (l['texto'], l['segundos'], l['erro']) for (n, r), l in de_fora.items() if r == str(imagem)}
        if local:
            lidas['glm_ocr'] = (local['texto'], local['segundos'], local['erro'])
            lidas['vision'] = (local['vision'], local['segundos'], '')
        for leitor, (texto, segundos, erro) in lidas.items():
            inventados = re.findall(r'\d+(?:[.,]\d+)?', texto or '')
            linhas.append({'recorte': imagem.name, 'leitor': leitor, 'tipo': 'leitor', 'chave': '', 'lido': ' '.join(inventados)[:300],
                           'esperado': '', 'resultado': 'inventada' if inventados else 'certa', 'status': '',
                           'segundos': segundos, 'erro': erro, 'respondeu': not erro})
    return gravar('controle', linhas)


def boletins():
    """Os PDFs de boletim de sondagem que o ler_prancha já reconheceu (prancha.parquet → boletim_sondagem)."""
    import entrega
    perfil = comum.ler('prancha')
    ids = set() if perfil is None or 'boletim_sondagem' not in perfil.columns else \
        set(perfil.filter(pl.col('boletim_sondagem').fill_null(False))['id'])
    return [Path(d['arquivo_local']) for d in entrega.documentos() if d['id'] in ids]


def paginas(pdf):
    """Cada página do boletim (até sondagem.json → paginas.maximo) em PNG a dpi_ocr e o texto real dela (vazio na
    digitalizada): o gabarito da página com texto é a leitura do código, que não inventa."""
    import pypdfium2 as pdfium
    PAGINAS = sondagem.regras()['paginas']
    pasta = PASTA / 'sondagem' / Path(pdf).stem
    pasta.mkdir(parents=True, exist_ok=True)
    documento = pdfium.PdfDocument(str(pdf))
    feitas = []
    for numero in range(min(len(documento), PAGINAS['maximo'])):
        destino = pasta / f'pagina{numero + 1:02d}.png'
        if not destino.exists():
            documento[numero].render(scale=PAGINAS['dpi_ocr'] / 72).to_pil().save(destino)
        feitas.append((destino, documento[numero].get_textpage().get_text_range()))
    documento.close()
    return feitas


def chaves_do_boletim(texto):
    """campo → valor, nspt_<prof>m → N-SPT e camada_<de>_<ate> → descrição, pelos padrões de sondagem.json."""
    lida = sondagem.leitura(texto)
    return {**{c: prancha.normalizar(v) for c, v in lida['campos'].items()},
            **{f'nspt_{p:g}m': str(n) for p, (_, n) in lida['spt'].items()},
            **{f'camada_{de:g}_{ate:g}': 'sim' for (de, ate) in lida['camadas']}}


def sondagem_bancada(pdfs=None, com_local=True):
    """B5: cada página de boletim por cada leitor, no modo texto, e o que os padrões do código tiram de cada leitura.
    Página com texto real: o gabarito é a leitura do código (B5a). Digitalizada: a referência é o que o glm-ocr e o
    Vision leram igual (B5b) — concordância, não acerto, até chegar o gabarito da demanda projeto-boletins-reais."""
    pdfs = [Path(p) for p in pdfs] if pdfs else boletins()
    todas = [(pdf, imagem, texto) for pdf in pdfs for imagem, texto in paginas(pdf)]
    imagens = [imagem for _, imagem, _ in todas]
    de_fora = externos(imagens, 'texto')
    de_dentro = locais(imagens, 'texto') if com_local else {}
    nomes = list(comum.configuracao('agentes')['agentes'])
    linhas = []
    for pdf, imagem, texto in todas:
        local = de_dentro.get(str(imagem))
        if len(texto.strip()) >= sondagem.regras()['paginas']['caracteres_texto']:
            referencia, tipo = chaves_do_boletim(texto), 'texto'
        elif not local:  # digitalizada sem o glm-ocr e o Vision: sem referência, não se mede
            continue
        else:
            glm, vision = chaves_do_boletim(local['texto']), chaves_do_boletim(local['vision'])
            referencia, tipo = {c: v for c, v in glm.items() if vision.get(c) == v}, 'digitalizada'
        lidas = {n: (de_fora[(n, str(imagem))]['texto'], de_fora[(n, str(imagem))]['segundos'], de_fora[(n, str(imagem))]['erro']) for n in nomes}
        if tipo == 'texto' and local:
            lidas |= {'glm_ocr': (local['texto'], local['segundos'], local['erro']), 'vision': (local['vision'], local['segundos'], '')}
        for leitor, (lido_texto, segundos, erro) in lidas.items():
            lido = chaves_do_boletim(lido_texto)
            base = {'recorte': f'{pdf.name}#{imagem.stem}', 'leitor': leitor, 'tipo': tipo, 'segundos': segundos, 'erro': erro,
                    'respondeu': not erro, 'status': ''}
            linhas += [{**base, 'chave': c, 'lido': lido.get(c, ''), 'esperado': v,
                        'resultado': 'faltou' if c not in lido else 'certa' if lido[c] == v else 'errada'} for c, v in referencia.items()]
            linhas += [{**base, 'chave': c, 'lido': v, 'esperado': '', 'resultado': 'inventada'}
                       for c, v in lido.items() if tipo == 'texto' and c not in referencia and c.startswith('nspt_')]
    return gravar('sondagem', linhas)


def placar(publicar=True):
    """Por conjunto e leitor (ou curadoria): certas, erradas, faltou, inventadas, precisão e cobertura; nas curadorias,
    confirmadas certas e confirmadas erradas (contaminação). E o veredito de cada agente (§7 do plano)."""
    partes = [pl.read_parquet(p) for c in CONJUNTOS if (p := comum.DADOS / f'bancada_{c}.parquet').exists()]
    if not partes:
        print('bancada vazia: rode tabelas, controle ou sondagem antes')
        return None
    tabela = pl.concat(partes, how='diagonal_relaxed')
    resumo = tabela.group_by('conjunto', 'tipo', 'leitor').agg(
        certas=(pl.col('resultado') == 'certa').sum(), erradas=(pl.col('resultado') == 'errada').sum(),
        faltou=(pl.col('resultado') == 'faltou').sum(), inventadas=(pl.col('resultado') == 'inventada').sum(),
        confirmadas_certas=((pl.col('status') == 'confirmada') & (pl.col('resultado') == 'certa')).sum(),
        confirmadas_erradas=((pl.col('status') == 'confirmada') & (pl.col('resultado').is_in(['errada', 'inventada']))).sum(),
        ia_certas=((pl.col('status') == 'confirmada_ia') & (pl.col('resultado') == 'certa')).sum(),
        ia_erradas=((pl.col('status') == 'confirmada_ia') & (pl.col('resultado').is_in(['errada', 'inventada']))).sum(),
        recortes=pl.col('recorte').n_unique(),
        responderam=pl.col('recorte').filter(pl.col('respondeu')).n_unique(),
        segundos_mediana=pl.col('segundos').drop_nulls().median(),
    ).with_columns(
        emitidas=pl.col('certas') + pl.col('erradas') + pl.col('inventadas'),
        esperadas=pl.col('certas') + pl.col('erradas') + pl.col('faltou'),
    ).with_columns(
        precisao=(pl.col('certas') / pl.col('emitidas')).round(3), cobertura=(pl.col('certas') / pl.col('esperadas')).round(3),
    ).sort('conjunto', 'tipo', 'leitor')
    vereditos = veredito(resumo)
    saida = resumo.join(vereditos, on='leitor', how='left')
    destino = comum.SAIDAS / 'bancada_agentes.csv'
    destino.parent.mkdir(parents=True, exist_ok=True)
    saida.write_csv(destino, separator=';', include_bom=True)
    if publicar:
        try:
            comum.publicar(saida, f"{comum.configuracao('operacao')['drive']['sistema']}/bancada_agentes.csv")
        except (OSError, subprocess.CalledProcessError) as falha:  # sem rclone (fora do mini) o CSV local basta
            print(f'Drive: não publicado ({type(falha).__name__})')
    with pl.Config(tbl_rows=60, tbl_cols=20, tbl_width_chars=200, tbl_hide_dataframe_shape=True):
        print(resumo.select('conjunto', 'tipo', 'leitor', 'certas', 'erradas', 'faltou', 'inventadas', 'precisao', 'cobertura',
                            'confirmadas_certas', 'confirmadas_erradas', 'ia_certas', 'ia_erradas', 'responderam', 'recortes',
                            'segundos_mediana'))
    for linha in vereditos.to_dicts():
        print(f"{linha['leitor']:<6} → {linha['veredito']}: {linha['motivo']}")
    return saida


def veredito(resumo):
    """Os critérios do §7 do plano, por agente, na B1 (tabelas) e na B2 (controle):
    1. acrescenta: a curadoria local+<agente> confirma certas ≥ 10 pp mais linhas do gabarito que a local; ou, sem o
       local, o agente sozinho acerta ≥ 90 % das linhas;
    2. não contamina: nenhuma confirmada errada a mais que a local; inventadas ≤ 2 % do que emitiu; no controle, não
       mais números que o glm-ocr (sem o glm-ocr: nenhum);
    3. opera: ≥ 90 % dos recortes respondidos e mediana ≤ 60 s.
    Falha em 1 ou 2: descontinua; só em 3: troca pelo reserva; nos três: continua."""
    def linha(conjunto, tipo, leitor):
        achadas = resumo.filter((pl.col('conjunto') == conjunto) & (pl.col('tipo') == tipo) & (pl.col('leitor') == leitor)).to_dicts()
        return achadas[0] if achadas else None
    vereditos = []
    for agente in comum.configuracao('agentes')['agentes']:
        sozinho, local, junto = linha('tabelas', 'leitor', agente), linha('tabelas', 'curadoria', 'local'), linha('tabelas', 'curadoria', f'local+{agente}')
        glm, controle = linha('tabelas', 'leitor', 'glm_ocr'), linha('controle', 'leitor', agente)
        if sozinho is None:
            vereditos.append({'leitor': agente, 'veredito': 'sem bancada', 'motivo': 'rode bancada.py tabelas'})
            continue
        com_local = glm is not None and glm['responderam'] > 0
        total = sozinho['esperadas'] or 1
        if com_local:
            ganho = (junto['confirmadas_certas'] - local['confirmadas_certas']) / total
            acrescenta = ganho >= 0.10 or sozinho['certas'] > glm['certas']
            motivo1 = f'+{ganho:.0%} confirmadas certas com ele; sozinho {sozinho["certas"]} × glm-ocr {glm["certas"]}'
            contamina = junto['confirmadas_erradas'] > local['confirmadas_erradas']
        else:
            acrescenta = sozinho['certas'] / total >= 0.90
            motivo1 = f'sem o local no mini: sozinho {sozinho["certas"]}/{total} certas'
            contamina = False
        inventa = sozinho['inventadas'] > 0.02 * max(sozinho['emitidas'], 1)
        glm_controle = linha('controle', 'leitor', 'glm_ocr')
        inventa_controle = controle is not None and controle['inventadas'] > (glm_controle['inventadas'] if glm_controle else 0)
        opera = sozinho['responderam'] >= 0.9 * sozinho['recortes'] and (sozinho['segundos_mediana'] or 0) <= 60
        falhas = [m for m, ruim in (('não acrescenta', not acrescenta), ('confirmou errado', contamina),
                                    ('inventa > 2 %', inventa), ('inventa no controle', inventa_controle), ('não opera', not opera)) if ruim]
        decisao = 'continua' if not falhas else 'troca pelo reserva' if falhas == ['não opera'] else 'descontinua'
        vereditos.append({'leitor': agente, 'veredito': decisao + ('' if com_local else ' (provisório: sem o local)'),
                          'motivo': '; '.join([motivo1, *falhas]) + f"; mediana {sozinho['segundos_mediana']} s; "
                                    f"{sozinho['responderam']}/{sozinho['recortes']} respondidos"})
    return pl.DataFrame(vereditos, schema={'leitor': pl.Utf8, 'veredito': pl.Utf8, 'motivo': pl.Utf8})


def principal(argumentos):
    comando, resto = (argumentos[0] if argumentos else ''), argumentos[1:]
    motivo = agentes.permitido()
    if comando in ('tabelas', 'controle', 'sondagem', 'tudo') and motivo:
        print(f'bancada parada: {motivo}')
        return
    com_local = '--sem-local' not in resto
    resto = [r for r in resto if r != '--sem-local']
    if comando in ('tabelas', 'tudo'):
        tabelas(com_local)
    if comando in ('controle', 'tudo'):
        controle(com_local)
    if comando in ('sondagem', 'tudo'):
        sondagem_bancada(resto or None, com_local)
    if comando in ('placar', 'tabelas', 'controle', 'sondagem', 'tudo'):
        placar()
    else:
        print(__doc__)


if __name__ == '__main__':
    agentes.sair_no_ctrl_c(principal, sys.argv[1:])
