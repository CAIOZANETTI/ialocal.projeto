"""A bancada dos leitores (notas/plano_agentes_nvidia.md §6–§8, F2): TODOS os candidatos na mesma régua — os do mini
(glm-ocr, gemma3 e o Vision, que leem a imagem; qwen3 e Apple FM, que montam a tabela com o texto do Vision) e os
agentes externos (Kimi K3 e Nemotron Parse, conceitos/agentes.json) — contra o gabarito, e a curadoria com e sem cada um.
Candidatos e critérios em conceitos/bancada.json.

    .venv/bin/python codigo/bancada.py tabelas            # B1: as 17 tabelas de Cambé (188 linhas transcritas pelo Caio)
    .venv/bin/python codigo/bancada.py controle           # B2: recortes sem número nenhum: todo número lido é invenção
    .venv/bin/python codigo/bancada.py sondagem [pdf…]    # B5: boletins de sondagem (sem pdf: os do acervo)
    .venv/bin/python codigo/bancada.py placar             # o placar e o veredito; saidas/bancada_agentes.csv e o Drive
    .venv/bin/python codigo/bancada.py tudo               # os três conjuntos e o placar
        --sem-local   só os agentes externos (o veredito fica provisório)
        --refazer     chama de novo o que está congelado: o tempo medido nas mesmas condições para todos
        --prioridade N  a vez da GPU com outra prioridade (4: à frente da extração de documentos, que é 5)

Quatro medidas, separadas (pedido do Caio, 04/10): QUALIDADE (linha certa, presença do número no texto, invenção,
confirmada errada), TEMPO ÚTIL (a chamada que deu certo), TAXA DE ERRO (o que falhou depois de todas as tentativas) e
TEMPO PERDIDO (ritmo do provedor, esperas entre tentativas, tentativas que falharam, fila da GPU). O perdido é do plano
ou da fila, não do modelo: não entra no veredito. Limite por provedor: os externos dividem o da conta da NVIDIA
(agentes.json → provedores); os locais vão um de cada vez, na vez da GPU do maestro.
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
ESQUEMA_LINHAS = {'type': 'object', 'required': ['linhas'], 'properties': {'linhas': {'type': 'string'}}}


def locais_da_bancada():
    return comum.configuracao('bancada')['locais']


def gravar(conjunto, linhas, chamadas):
    """dados/bancada_<conjunto>.parquet (uma linha por leitor × item do gabarito) e bancada_chamadas_<conjunto>.parquet
    (uma por leitor × recorte: tempo útil, perdido, tentativas, erro), inteiros a cada rodada do conjunto."""
    if not linhas:  # nada a medir (sem boletim reconhecido, por exemplo): fica a bancada anterior do conjunto
        print(f'bancada {conjunto}: nenhum recorte com referência para medir')
        return None
    comum.DADOS.mkdir(parents=True, exist_ok=True)
    extra = {**{c: pl.lit(v) for c, v in comum.codigo().items()}, 'conjunto': pl.lit(conjunto), 'em': pl.lit(comum.agora())}
    pl.DataFrame(chamadas, infer_schema_length=None).with_columns(**extra).write_parquet(comum.DADOS / f'bancada_chamadas_{conjunto}.parquet')
    tabela = pl.DataFrame(linhas, infer_schema_length=None).with_columns(**extra)
    tabela.write_parquet(comum.DADOS / f'bancada_{conjunto}.parquet')
    return tabela


def organizadas(texto):
    """As linhas que o organizador escreveu (células separadas por ;)."""
    return [[c.strip() for c in linha.split(';')] for linha in (texto or '').splitlines() if ';' in linha]


def ler_um_local(nome, imagem, modo, texto_vision):
    """Um recorte por um candidato do mini: {'linhas', 'texto', 'erro', 'util', 'congelado'} ou None se o candidato não
    lê este modo (organizador fora da tabela). O tempo útil é o da chamada original, mesmo quando a resposta veio
    congelada (o meta guarda); o Vision não congela: é medido na hora."""
    LOCAL = locais_da_bancada()[nome]
    if LOCAL['papel'] == 'organizador' and modo != 'tabela':
        return None
    chamadas, marca, linhas, texto, erro = ia.medir(), time.perf_counter(), [], '', ''
    try:
        if LOCAL['motor'] == 'vision':
            if not ia.instalado('Vision'):
                raise ImportError('Vision ausente (só no macOS)')
            texto = ia.ler_com_vision(imagem)['texto']
        elif LOCAL['papel'] == 'organizador':
            if not texto_vision:
                raise RuntimeError('sem o texto do Vision para organizar')
            pedido = ia.ler_prompt(LOCAL['prompt'])[0].replace('{texto}', texto_vision[:6000])
            if LOCAL['motor'] == 'apple':
                if not ia.instalado('apple_fm_sdk'):
                    raise ImportError('Apple FM ausente (só no macOS com o apple_fm_sdk)')
                resposta = ia.apple(pedido, ESQUEMA_LINHAS)[0]
            else:
                resposta = ia.ollama(LOCAL['modelo'], pedido, ESQUEMA_LINHAS)[0]
            linhas = organizadas(json.loads(resposta).get('linhas', ''))
            texto = '\n'.join(' '.join(c) for c in linhas)
        elif nome == 'glm_ocr':
            texto = ia.ocr_glm(imagem, ia.ler_prompt('prancha_tabela' if modo == 'tabela' else 'imagem_ocr', regras=False)[0])
            linhas = prancha.linhas_html(texto) if modo == 'tabela' else []
            texto = '\n'.join(' '.join(c) for c in linhas) if linhas else texto
        else:
            conteudo = agentes.sem_cerca(ia.ollama(LOCAL['modelo'], ia.ler_prompt(LOCAL['prompt'][modo])[0], imagens=[imagem])[0])
            linhas = agentes.linhas_da_tabela(conteudo) if modo == 'tabela' else []
            texto = '\n'.join(' '.join(c) for c in linhas) if linhas else conteudo
    except StopIteration:
        erro = f"{LOCAL.get('modelo')} não está no Ollama do mini"
    except (OSError, RuntimeError, ValueError, ImportError, KeyError) as falha:
        erro = f'{type(falha).__name__}: {falha}'[:300]
    util = sum(m.get('segundos', 0) for m in chamadas) if chamadas else time.perf_counter() - marca
    return {'linhas': linhas, 'texto': texto, 'erro': erro, 'util': round(util, 2),
            'congelado': bool(chamadas) and all(m.get('congelado') for m in chamadas)}


PRIORIDADE = None  # --prioridade N na linha de comando; sem ela, bancada.json → gpu.prioridade


def locais(imagens, modo):
    """recorte → {candidato: leitura} de cada imagem, na vez da GPU do maestro (um de cada vez), e a espera pela vez
    (tempo perdido da fila, rateado entre as chamadas). O Vision lê primeiro: os organizadores usam o texto dele. Sem a
    vez em bancada.json → gpu.espera_max_s, os locais ficam de fora desta rodada (e o placar diz)."""
    GPU = {**comum.configuracao('operacao')['gpu'], **comum.configuracao('bancada')['gpu']}
    if PRIORIDADE is not None:
        GPU['prioridade'] = PRIORIDADE
    nomes = sorted(locais_da_bancada(), key=lambda n: (n != 'vision', locais_da_bancada()[n]['papel'] == 'organizador'))
    print(f"locais: {', '.join(nomes)} em {len(imagens)} recortes; pedindo a vez da GPU ao maestro (prioridade {GPU['prioridade']}, "
          f"desiste em {GPU['espera_max_s'] // 60} min); --prioridade 4 passa à frente dos documentos, --sem-local pula", flush=True)
    lidas, marca, sem_ollama = {}, time.perf_counter(), False
    with cliente_gpu.vez_da_gpu('ialocal.projeto', str(comum.DADOS / 'gpu'), GPU['prioridade'], GPU['modelo'], 'bancada',
                                espera_max_s=GPU['espera_max_s']) as vez:
        espera = time.perf_counter() - marca
        if vez.negada:
            print(f'locais: sem a vez da GPU em {espera:.0f} s (o maestro deu a outros): ficam de fora desta rodada', flush=True)
            return {}, 0.0
        print(f"locais: vez da GPU depois de {espera:.0f} s{'' if vez.com_maestro else ' (maestro fora do ar: sem trava)'}", flush=True)
        for imagem in imagens:
            if not vez.minha():
                print('locais: a vez da GPU foi pedida de volta; o resto fica para a próxima rodada', flush=True)
                break
            leituras = {}
            for nome in nomes:
                if sem_ollama and locais_da_bancada()[nome]['motor'] == 'ollama':
                    leituras[nome] = {'linhas': [], 'texto': '', 'erro': 'Ollama fora do ar', 'util': None, 'congelado': False}
                    continue
                lida = ler_um_local(nome, imagem, modo, leituras.get('vision', {}).get('texto', ''))
                if lida is None:
                    continue
                leituras[nome] = lida
                sem_ollama = sem_ollama or 'Connection refused' in lida['erro'] or 'URLError' in lida['erro']
                print(f"local  {nome:<9} {Path(imagem).name[:30]:<30} útil {lida['util'] or 0:6.1f} s  "
                      f"{'congelado' if lida['congelado'] else '':<9} linhas {len(lida['linhas']):>3}"
                      + (f"  ERRO {lida['erro'][:100]}" if lida['erro'] else ''), flush=True)
            lidas[str(imagem)] = leituras
    return lidas, espera


def externos(imagens, modo):
    """(agente, recorte) → leitura de cada agente externo, em paralelo, uma fila por provedor."""
    print(f'agentes: {len(imagens)} recortes × {len(comum.configuracao("agentes")["agentes"])} agentes, modo {modo}', flush=True)
    return {(l['agente'], l['recorte']): l for l in agentes.em_paralelo(imagens, modo=modo, progresso=True)}


def leituras_do_recorte(imagem, de_fora, de_dentro):
    """leitor → {'linhas', 'texto', 'erro', 'util', 'perdido', 'tentativas', 'motivos', 'congelado', 'provedor',
    'modelo'}: os externos e os locais do mesmo recorte numa forma só."""
    AGENTES, LOCAIS = comum.configuracao('agentes')['agentes'], locais_da_bancada()
    juntas = {}
    for nome, agente in AGENTES.items():
        lida = de_fora.get((nome, str(imagem)))
        if lida is None:
            continue
        meta = lida['meta']
        tempo = 'segundos_util' in meta  # resposta congelada antes da 0v10 não separa o útil do perdido: --refazer
        juntas[nome] = {'linhas': lida['linhas'], 'texto': lida['texto'], 'erro': lida['erro'], 'congelado': bool(meta.get('congelado')),
                        'util': meta['segundos_util'] if tempo else None,
                        'perdido': meta['segundos_espera'] + meta['segundos_falhas'] if tempo else None,
                        'tentativas': meta.get('tentativas', 1 if not lida['erro'] else None), 'motivos': ','.join(meta.get('motivos', [])),
                        'provedor': agente['provedor'], 'modelo': agente['modelo']}
    for nome, lida in de_dentro.get(str(imagem), {}).items():
        juntas[nome] = {**lida, 'perdido': lida.get('perdido', 0.0), 'tentativas': 1, 'motivos': '',
                        'provedor': LOCAIS[nome]['provedor'], 'modelo': LOCAIS[nome].get('modelo', LOCAIS[nome]['motor'])}
    return juntas


def ratear(de_dentro, espera):
    """A espera pela vez da GPU, dividida igualmente entre as chamadas locais da rodada (tempo perdido da fila)."""
    total = sum(len(l) for l in de_dentro.values())
    for leituras in de_dentro.values():
        for lida in leituras.values():
            lida['perdido'] = round(espera / total, 2) if total else 0.0


def chamada(recorte, leitor, lida):
    return {'recorte': recorte, 'leitor': leitor, 'provedor': lida['provedor'], 'modelo': lida['modelo'], 'util': lida['util'],
            'perdido': lida['perdido'], 'tentativas': lida['tentativas'], 'motivos': lida['motivos'], 'erro': lida['erro'],
            'congelado': lida['congelado']}


def comparar(lidas, gabarito, base, status, texto):
    """As linhas da bancada de um leitor (ou curadoria) numa tabela: código → (quantidade, unidade) × gabarito; e,
    para todo leitor, se o código e a quantidade aparecem no texto dele (presença: o Vision, sem estrutura, só tem
    esta). lidas None = leitor sem estrutura de tabela; texto None = curadoria (não tem texto próprio: presença vazia)."""
    numeros = None if texto is None else curadoria.numeros(texto)
    linhas = []
    for linha in gabarito:
        esperado = (prancha.normalizar(linha['quant']), curadoria.unidade(linha['und']))
        presente = None if numeros is None else linha['codigo'] in numeros and esperado[0] in numeros
        if lidas is None:
            linhas.append({**base, 'chave': linha['codigo'], 'lido': '', 'esperado': ' '.join(esperado), 'resultado': '',
                           'presente': presente, 'status': ''})
            continue
        lido = lidas.get(linha['codigo'])
        resultado = 'faltou' if lido is None else 'certa' if lido == esperado else 'errada'
        linhas.append({**base, 'chave': linha['codigo'], 'lido': ' '.join(lido) if lido else '', 'esperado': ' '.join(esperado),
                       'resultado': resultado, 'presente': presente, 'status': status.get(linha['codigo'], '')})
    codigos = {l['codigo'] for l in gabarito}
    linhas += [{**base, 'chave': c, 'lido': ' '.join(v), 'esperado': '', 'resultado': 'inventada', 'presente': None,
                'status': status.get(c, '')} for c, v in (lidas or {}).items() if c not in codigos]
    return linhas


def tabelas(com_local=True):
    """B1: cada tabela de Cambé por cada candidato; e as curadorias: local (glm-ocr com o Vision de testemunha),
    local+<candidato> para cada um dos outros, todos, e externos (os agentes sem testemunha)."""
    gabaritos = agentes.gabarito_cambe()
    imagens = sorted(p for p in CAMBE.glob('*.png') if p.stem.upper() in gabaritos)
    de_fora = externos(imagens, 'tabela')
    de_dentro, espera = locais(imagens, 'tabela') if com_local else ({}, 0.0)
    ratear(de_dentro, espera)
    linhas, chamadas = [], []
    for imagem in imagens:
        gabarito, leituras = gabaritos[imagem.stem.upper()], leituras_do_recorte(imagem, de_fora, de_dentro)
        for leitor, lida in leituras.items():
            chamadas.append(chamada(imagem.name, leitor, lida))
            base = {'recorte': imagem.name, 'leitor': leitor, 'tipo': 'leitor'}
            estrutura = curadoria.por_codigo(lida['linhas']) if leitor != 'vision' else None
            linhas += comparar(estrutura, gabarito, base, {}, lida['texto'])
        geradores = [l for l in leituras if l != 'vision']
        combinacoes = {'externos': [l for l in geradores if l in comum.configuracao('agentes')['agentes']]}
        if 'glm_ocr' in leituras:
            combinacoes |= {'local': ['glm_ocr'], **{f'local+{c}': ['glm_ocr', c] for c in geradores if c != 'glm_ocr'},
                            'todos': geradores}
        testemunha = leituras.get('vision', {}).get('texto', '')
        for nome, quem in combinacoes.items():
            curadas = curadoria.curar_tabela({q: leituras[q]['linhas'] for q in quem}, '' if nome == 'externos' else testemunha)
            base = {'recorte': imagem.name, 'leitor': nome, 'tipo': 'curadoria'}
            linhas += comparar({c: (v['quant'], v['und']) for c, v in curadas.items()}, gabarito, base,
                               {c: v['status'] for c, v in curadas.items()}, None)
    return gravar('tabelas', linhas, chamadas)


def recortes_de_controle():
    """B2: recortes sem número nenhum, no formato das tabelas — em branco, a grade vazia de uma relação, o texto de uma
    legenda sem algarismo — e os do Caio em amostras/controle/, se houver. Ficam em dados/bancada/controle/."""
    from PIL import Image, ImageDraw
    pasta = PASTA / 'controle'
    pasta.mkdir(parents=True, exist_ok=True)
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
    return [branco, pasta / 'grade_vazia.png', pasta / 'legenda_sem_numero.png'] + sorted((comum.RAIZ / 'amostras' / 'controle').glob('*.png'))


def controle(com_local=True):
    """B2: cada recorte sem número por cada candidato que lê imagem, no modo texto; quantos números cada um escreveu."""
    imagens = recortes_de_controle()
    de_fora = externos(imagens, 'texto')
    de_dentro, espera = locais(imagens, 'texto') if com_local else ({}, 0.0)
    ratear(de_dentro, espera)
    linhas, chamadas = [], []
    for imagem in imagens:
        for leitor, lida in leituras_do_recorte(imagem, de_fora, de_dentro).items():
            chamadas.append(chamada(imagem.name, leitor, lida))
            inventados = re.findall(r'\d+(?:[.,]\d+)?', lida['texto'] or '')
            linhas.append({'recorte': imagem.name, 'leitor': leitor, 'tipo': 'leitor', 'chave': '', 'lido': ' '.join(inventados)[:300],
                           'esperado': '', 'resultado': 'inventada' if inventados else 'certa', 'presente': None, 'status': ''})
    return gravar('controle', linhas, chamadas)


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
    """campo → valor, nspt_<prof>m → N-SPT e camada_<de>_<ate> → 'sim', pelos padrões de sondagem.json."""
    lida = sondagem.leitura(texto or '')
    return {**{c: prancha.normalizar(v) for c, v in lida['campos'].items()},
            **{f'nspt_{p:g}m': str(n) for p, (_, n) in lida['spt'].items()},
            **{f'camada_{de:g}_{ate:g}': 'sim' for (de, ate) in lida['camadas']}}


def sondagem_bancada(pdfs=None, com_local=True):
    """B5: cada página de boletim por cada candidato que lê imagem, no modo texto, e o que os padrões do código tiram de
    cada leitura. Página com texto real: o gabarito é a leitura do código (B5a), e todos são medidos. Digitalizada: a
    referência é o que o glm-ocr e o Vision leram igual (B5b) — concordância, não acerto, até chegar o gabarito da
    demanda projeto-boletins-reais —, e só os outros são medidos contra ela."""
    pdfs = [Path(p) for p in pdfs] if pdfs else boletins()
    todas = [(pdf, imagem, texto) for pdf in pdfs for imagem, texto in paginas(pdf)]
    imagens = [imagem for _, imagem, _ in todas]
    de_fora = externos(imagens, 'texto')
    de_dentro, espera = locais(imagens, 'texto') if com_local else ({}, 0.0)
    ratear(de_dentro, espera)
    linhas, chamadas = [], []
    for pdf, imagem, texto in todas:
        leituras = leituras_do_recorte(imagem, de_fora, de_dentro)
        if len(texto.strip()) >= sondagem.regras()['paginas']['caracteres_texto']:
            referencia, tipo, medidos = chaves_do_boletim(texto), 'texto', leituras
        elif 'glm_ocr' in leituras and 'vision' in leituras:
            glm, vision = chaves_do_boletim(leituras['glm_ocr']['texto']), chaves_do_boletim(leituras['vision']['texto'])
            referencia, tipo = {c: v for c, v in glm.items() if vision.get(c) == v}, 'digitalizada'
            medidos = {l: v for l, v in leituras.items() if l not in ('glm_ocr', 'vision')}
        else:  # digitalizada sem o glm-ocr e o Vision: sem referência, não se mede
            continue
        recorte = f'{pdf.name}#{imagem.stem}'
        for leitor, lida in medidos.items():
            chamadas.append(chamada(recorte, leitor, lida))
            lido = chaves_do_boletim(lida['texto'])
            base = {'recorte': recorte, 'leitor': leitor, 'tipo': tipo, 'presente': None, 'status': ''}
            linhas += [{**base, 'chave': c, 'lido': lido.get(c, ''), 'esperado': v,
                        'resultado': 'faltou' if c not in lido else 'certa' if lido[c] == v else 'errada'} for c, v in referencia.items()]
            linhas += [{**base, 'chave': c, 'lido': v, 'esperado': '', 'resultado': 'inventada'}
                       for c, v in lido.items() if tipo == 'texto' and c not in referencia and c.startswith('nspt_')]
    return gravar('sondagem', linhas, chamadas)


def resumo_das_chamadas():
    """Por conjunto e leitor: provedor, modelo, chamadas, tempo útil (mediana e total), tempo perdido (total e % do
    tempo de parede), taxa de erro final, tentativas médias, quantos 429 e 5xx."""
    partes = [pl.read_parquet(p) for c in CONJUNTOS if (p := comum.DADOS / f'bancada_chamadas_{c}.parquet').exists()]
    if not partes:
        return None
    tabela = pl.concat(partes, how='diagonal_relaxed')
    return tabela.group_by('conjunto', 'leitor').agg(
        provedor=pl.col('provedor').first(), modelo=pl.col('modelo').first(), chamadas=pl.len(),
        util_mediana_s=pl.col('util').cast(pl.Float64).median(), util_total_s=pl.col('util').cast(pl.Float64).sum(),
        perdido_total_s=pl.col('perdido').cast(pl.Float64).sum(),
        taxa_erro=(pl.col('erro') != '').mean().round(3), tentativas_media=pl.col('tentativas').cast(pl.Float64).mean().round(2),
        n_429=pl.col('motivos').str.count_matches('429').sum(), n_5xx=pl.col('motivos').str.count_matches(r'\b5\d\d\b').sum(),
        sem_tempo=pl.col('util').is_null().sum(),
    ).with_columns(perdido_pct=(pl.col('perdido_total_s') / (pl.col('util_total_s') + pl.col('perdido_total_s'))).round(3))


def placar(publicar=True):
    """O placar por conjunto e leitor (ou curadoria) — qualidade, tempo útil, taxa de erro, tempo perdido — e o
    veredito de cada candidato (§7 do plano, conceitos/bancada.json → criterios)."""
    partes = [pl.read_parquet(p) for c in CONJUNTOS if (p := comum.DADOS / f'bancada_{c}.parquet').exists()]
    if not partes:
        print('bancada vazia: rode tabelas, controle ou sondagem antes')
        return None
    tabela = pl.concat(partes, how='diagonal_relaxed')
    resumo = tabela.group_by('conjunto', 'tipo', 'leitor').agg(
        certas=(pl.col('resultado') == 'certa').sum(), erradas=(pl.col('resultado') == 'errada').sum(),
        faltou=(pl.col('resultado') == 'faltou').sum(), inventadas=(pl.col('resultado') == 'inventada').sum(),
        presenca=pl.col('presente').cast(pl.Float64).mean().round(3),
        confirmadas_certas=((pl.col('status') == 'confirmada') & (pl.col('resultado') == 'certa')).sum(),
        confirmadas_erradas=((pl.col('status') == 'confirmada') & (pl.col('resultado').is_in(['errada', 'inventada']))).sum(),
        ia_certas=((pl.col('status') == 'confirmada_ia') & (pl.col('resultado') == 'certa')).sum(),
        ia_erradas=((pl.col('status') == 'confirmada_ia') & (pl.col('resultado').is_in(['errada', 'inventada']))).sum(),
        recortes=pl.col('recorte').n_unique(),
    ).with_columns(
        emitidas=pl.col('certas') + pl.col('erradas') + pl.col('inventadas'),
        esperadas=pl.col('certas') + pl.col('erradas') + pl.col('faltou'),
    ).with_columns(
        precisao=(pl.col('certas') / pl.col('emitidas')).round(3), cobertura=(pl.col('certas') / pl.col('esperadas')).round(3),
    )
    chamadas = resumo_das_chamadas()
    if chamadas is not None:
        resumo = resumo.join(chamadas, on=['conjunto', 'leitor'], how='left')
    resumo = resumo.sort('conjunto', 'tipo', 'leitor')
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
    colunas = [c for c in ('conjunto', 'tipo', 'leitor', 'certas', 'erradas', 'faltou', 'inventadas', 'cobertura', 'precisao',
                           'presenca', 'confirmadas_certas', 'confirmadas_erradas', 'util_mediana_s', 'taxa_erro',
                           'perdido_pct', 'tentativas_media', 'n_429', 'n_5xx') if c in resumo.columns]
    with pl.Config(tbl_rows=80, tbl_cols=25, tbl_width_chars=250, tbl_hide_dataframe_shape=True, tbl_hide_column_data_types=True):
        print(resumo.select(colunas))
    for linha in vereditos.to_dicts():
        print(f"{linha['leitor']:<9} → {linha['veredito']}: {linha['motivo']}")
    return saida


def veredito(resumo):
    """Os critérios do §7 do plano (conceitos/bancada.json → criterios), para cada candidato que não é a base (glm-ocr)
    nem a testemunha (Vision), na B1 (tabelas) e na B2 (controle):
    1. acrescenta: a curadoria local+<candidato> confirma certas ≥ acrescenta_pp mais linhas do gabarito que a local; ou
       ele sozinho acerta mais linhas que o glm-ocr; sem o local, sozinho ≥ 90 % das linhas;
    2. não contamina: nenhuma confirmada errada a mais que a local; inventadas ≤ inventadas_max do que emitiu; no
       controle, não mais números que o glm-ocr (sem o glm-ocr: nenhum);
    3. opera: taxa de erro final ≤ taxa_erro_max e tempo útil mediano ≤ util_mediana_max_s. O tempo perdido (plano
       gratuito, fila da GPU) não entra: sai na coluna perdido_pct.
    Falha em 1 ou 2: descontinua; só em 3: troca (pelo reserva, se externo); nos três: continua."""
    CRITERIOS = comum.configuracao('bancada')['criterios']
    def linha(conjunto, tipo, leitor):
        achadas = resumo.filter((pl.col('conjunto') == conjunto) & (pl.col('tipo') == tipo) & (pl.col('leitor') == leitor)).to_dicts()
        return achadas[0] if achadas else None
    candidatos = [*comum.configuracao('agentes')['agentes'], *(n for n in locais_da_bancada() if n not in ('glm_ocr', 'vision'))]
    glm, local = linha('tabelas', 'leitor', 'glm_ocr'), linha('tabelas', 'curadoria', 'local')
    glm_controle = linha('controle', 'leitor', 'glm_ocr')
    vereditos = []
    for nome in candidatos:
        sozinho, junto, controle = linha('tabelas', 'leitor', nome), linha('tabelas', 'curadoria', f'local+{nome}'), linha('controle', 'leitor', nome)
        if sozinho is None:
            continue
        total = sozinho['esperadas'] or 1
        if local is not None and junto is not None:
            ganho = (junto['confirmadas_certas'] - local['confirmadas_certas']) / total
            acrescenta = ganho >= CRITERIOS['acrescenta_pp'] or sozinho['certas'] > glm['certas']
            motivo = f"+{ganho:.0%} confirmadas certas com ele; sozinho {sozinho['certas']} × glm-ocr {glm['certas']}"
            contamina = junto['confirmadas_erradas'] > local['confirmadas_erradas']
            provisorio = ''
        else:
            acrescenta = sozinho['certas'] / total >= 0.90
            motivo, contamina, provisorio = f"sozinho {sozinho['certas']}/{total} certas", False, ' (provisório: sem o local)'
        inventa = sozinho['inventadas'] > CRITERIOS['inventadas_max'] * max(sozinho['emitidas'], 1)
        inventa_controle = controle is not None and controle['inventadas'] > (glm_controle['inventadas'] if glm_controle else 0)
        util, erro = sozinho.get('util_mediana_s'), sozinho.get('taxa_erro') or 0
        opera = erro <= CRITERIOS['taxa_erro_max'] and (util is None or util <= CRITERIOS['util_mediana_max_s'])
        falhas = [m for m, ruim in (('não acrescenta', not acrescenta), ('confirmou errado', contamina),
                                    ('inventa', inventa), ('inventa no controle', inventa_controle), ('não opera', not opera)) if ruim]
        decisao = 'continua' if not falhas else 'troca' if falhas == ['não opera'] else 'descontinua'
        tempo = (f"útil mediano {util} s" if util is not None else 'útil sem medida (congelado antes da 0v10: --refazer)')
        vereditos.append({'leitor': nome, 'veredito': decisao + provisorio,
                          'motivo': '; '.join([motivo, *falhas]) + f"; {tempo}; erro {erro:.0%}; "
                                    f"perdido {sozinho.get('perdido_pct') if sozinho.get('perdido_pct') is not None else '?'} do tempo (plano/fila)"})
    return pl.DataFrame(vereditos, schema={'leitor': pl.Utf8, 'veredito': pl.Utf8, 'motivo': pl.Utf8})


def principal(argumentos):
    comando, resto = (argumentos[0] if argumentos else ''), argumentos[1:]
    motivo = agentes.permitido()
    if comando in ('tabelas', 'controle', 'sondagem', 'tudo') and motivo:
        print(f'bancada parada: {motivo}')
        return
    com_local = '--sem-local' not in resto
    ia.REFAZER = '--refazer' in resto
    global PRIORIDADE
    if '--prioridade' in resto:
        posicao = resto.index('--prioridade')
        PRIORIDADE = int(resto[posicao + 1])
        resto = resto[:posicao] + resto[posicao + 2:]
    resto = [r for r in resto if not r.startswith('--')]
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
