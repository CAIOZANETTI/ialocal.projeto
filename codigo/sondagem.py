"""Boletim de sondagem à percussão (SPT, NBR 6484:2020), regras em conceitos/sondagem.json. Pedido do Caio (03/10/2026):
o boletim é projeto — coordenadas, perfil do solo, se tem água —, quase sempre A4 e às vezes só digitalizado.

Por camada, como a prancha: a página com texto real é lida pelo código (pypdfium2) em ler_sondagem; a digitalizada vai
ao OCR em ler_sondagem_ia, na vez da GPU — glm-ocr e Vision na página inteira, e um valor só é `confirmado` quando os
dois leram o mesmo. Saem, por furo: os campos do cabeçalho (coordenadas, cota da boca, nível d'água, profundidade
final, paralisação), o N-SPT de cada metro e as camadas do perfil.
"""
import json
import re
import time
from pathlib import Path

import comum
import ia
import prancha


def regras():
    return comum.configuracao('sondagem')


def e_boletim(nome, texto, formato):
    """Boletim: formato de boletim e 2 sinais distintos no texto; sem texto (digitalizado), o nome basta."""
    RECONHECER = regras()['reconhecer']
    if formato not in RECONHECER['formatos']:
        return False
    sinais = sum(bool(re.search(padrao, texto)) for padrao in RECONHECER['texto'])
    if len(texto.strip()) < regras()['paginas']['caracteres_texto']:
        return bool(re.search(RECONHECER['nome'], Path(nome).stem))
    return sinais >= RECONHECER['sinais_minimos']


def numero(texto):
    return float(texto.replace(' ', '').replace('.', '').replace(',', '.')) if re.fullmatch(r'\d[\d .]*,\d+', texto) \
        else float(texto.replace(',', '.'))


def campos(texto):
    """Os campos do cabeçalho no texto de uma página, como estão escritos; nível d'água 'ausente' quando o boletim diz
    que não encontrou."""
    CAMPOS = {c: p for c, p in regras()['campos'].items() if not c.startswith('_')}
    achados = {}
    for campo, padrao in CAMPOS.items():
        achado = re.search(padrao, texto)
        if achado:
            achados[campo] = (achado.group(1) if achado.groups() else achado.group(0)).strip()
    if 'nivel_agua_ausente' in achados and 'nivel_agua' not in achados:
        achados['nivel_agua'] = 'ausente: ' + achados['nivel_agua_ausente']
    achados.pop('nivel_agua_ausente', None)
    if 'furo' in achados:
        achados['furo'] = re.sub(r'[\s.–_]+', '-', achados['furo'].upper()).strip('-')
    return achados


def spt(texto):
    """profundidade (m) → (golpes como estão, N-SPT) de cada linha de ensaio: três trechos golpes/penetração ou três
    colunas de golpes; o N-SPT é a soma dos dois últimos trechos."""
    SPT = regras()['spt']
    linhas = {}
    for linha in texto.splitlines():
        if achado := re.match(SPT['tres_trechos'], linha):
            profundidade, golpes = achado.group(1), [f'{achado.group(i)}/{achado.group(i + 1)}' for i in (2, 4, 6)]
            nspt = int(achado.group(4)) + int(achado.group(6))
        elif achado := re.match(SPT['golpes_15cm'], linha):
            profundidade, golpes = achado.group(1), [achado.group(i) for i in (2, 3, 4)]
            nspt = int(achado.group(3)) + int(achado.group(4))
        else:
            continue
        metros = numero(profundidade)
        if 0 < metros <= SPT['profundidade_maxima_m']:
            linhas[round(metros, 2)] = (' '.join(golpes), nspt)
    return linhas


def camadas(texto):
    """(de, até) em metros → descrição, de cada linha com faixa de profundidade e palavra de solo."""
    CAMADA = regras()['camada']
    achadas = {}
    for linha in texto.splitlines():
        achado = re.search(CAMADA['faixa'], linha)
        if achado and re.search(CAMADA['solo'], achado.group(3)):
            achadas[(round(numero(achado.group(1)), 2), round(numero(achado.group(2)), 2))] = achado.group(3).strip()[:200]
    return achadas


def leitura(texto):
    return {'campos': campos(texto), 'spt': spt(texto), 'camadas': camadas(texto)}


def status(glm, vision):
    """Quem leu: confirmado (os dois, o mesmo), divergente (os dois, outra coisa), so_glm, so_vision."""
    if glm is not None and vision is not None:
        return 'confirmado' if prancha.normalizar(str(glm)) == prancha.normalizar(str(vision)) else 'divergente'
    return 'so_glm' if glm is not None else 'so_vision'


def linhas(lidas, base, pagina, furo):
    """As linhas das três famílias para uma página: `lidas` é {leitor: leitura}; com um leitor só (o texto do PDF), o
    status é `codigo`; com o glm-ocr e o Vision, o de status()."""
    furo = next((l['campos']['furo'] for l in lidas.values() if l['campos'].get('furo')), furo)
    contexto = {**base, 'pagina': pagina, 'furo': furo}
    if 'pdf' in lidas:
        unica = lidas['pdf']
        juntar = lambda chaves, valor: [(c, valor(unica, c), None, 'codigo') for c in chaves(unica)]
    else:
        glm, vision = lidas.get('glm_ocr') or leitura(''), lidas.get('vision') or leitura('')
        juntar = lambda chaves, valor: [
            (c, valor(glm, c) if valor(glm, c) is not None else valor(vision, c),
             valor(vision, c) if valor(glm, c) is not None and valor(vision, c) is not None and status(valor(glm, c), valor(vision, c)) == 'divergente' else None,
             status(valor(glm, c), valor(vision, c))) for c in sorted(set(chaves(glm)) | set(chaves(vision)))]
    pega = lambda grupo: (lambda l: l[grupo].keys(), lambda l, c: l[grupo].get(c))
    return (
        [{**contexto, 'campo': c, 'valor': v, 'valor_vision': o or '', 'status': s} for c, v, o, s in juntar(*pega('campos'))],
        [{**contexto, 'profundidade_m': c, 'golpes': v[0], 'nspt': v[1], 'nspt_vision': o[1] if o else None, 'status': s}
         for c, v, o, s in juntar(*pega('spt'))],
        [{**contexto, 'de_m': c[0], 'ate_m': c[1], 'descricao': v, 'descricao_vision': o or '', 'status': s}
         for c, v, o, s in juntar(*pega('camadas'))])


def gravar(familias, resumo, bancada):
    for nome, grupo in zip(('sondagem_campo', 'sondagem_spt', 'sondagem_camada'), familias):
        comum.gravar(nome, grupo)
    comum.gravar('sondagem', [resumo], [bancada])


def ler_sondagem(documento, rodada):
    """Tarefa de código: cada página com texto real lida pelo código; as sem texto ficam para ler_sondagem_ia
    (paginas_ocr no resumo)."""
    import pypdfium2 as pdfium
    marca = time.perf_counter()
    base = prancha.base_da_linha(documento, 'sondagem', rodada)
    PAGINAS = regras()['paginas']
    pdf = pdfium.PdfDocument(documento['arquivo_local'])
    familias, sem_texto, furo = ([], [], []), [], ''
    for numero_pagina in range(min(len(pdf), PAGINAS['maximo'])):
        texto = pdf[numero_pagina].get_textpage().get_text_range()
        if len(texto.strip()) < PAGINAS['caracteres_texto']:
            sem_texto.append(numero_pagina + 1)
            continue
        achadas = linhas({'pdf': leitura(texto)}, {**base, 'leitor': 'pdf'}, numero_pagina + 1, furo)
        furo = next((l['furo'] for l in achadas[0] if l['furo']), furo)
        for grupo, novas in zip(familias, achadas):
            grupo += novas
    paginas = len(pdf)
    pdf.close()
    resumo = {**base, 'paginas': paginas, 'paginas_texto': min(paginas, PAGINAS['maximo']) - len(sem_texto),
              'paginas_ocr': json.dumps(sem_texto), 'furos': json.dumps(sorted({l['furo'] for l in familias[0] if l['furo']})),
              'metros_spt': len(familias[1]), 'camadas': len(familias[2])}
    gravar(familias, resumo, {**base, 'familia': 'sondagem', 'segundos': round(time.perf_counter() - marca, 2), 'erro': ''})
    return resumo


def ler_sondagem_ia(documento, rodada):
    """Tarefa de IA: as páginas sem texto (digitalizadas) renderizadas a dpi_ocr e lidas pelo glm-ocr e pelo Vision;
    para no limite da operação entre páginas."""
    import pypdfium2 as pdfium
    marca, relogio = time.perf_counter(), time.monotonic()
    base = prancha.base_da_linha(documento, 'sondagem_ia', rodada)
    codigo = next(l for l in comum.ler('sondagem', [documento['id']]).to_dicts() if l['extrator'] == 'sondagem')
    pasta, com_vision = comum.DADOS / 'recortes' / Path(documento['arquivo_local']).stem, ia.instalado('Vision')
    pasta.mkdir(parents=True, exist_ok=True)
    prazo = relogio + comum.configuracao('operacao')['limite_ia_s']
    pdf = pdfium.PdfDocument(documento['arquivo_local'])
    familias, furo, lidas = ([], [], []), '', 0
    for numero_pagina in json.loads(codigo['paginas_ocr']):
        if time.monotonic() > prazo:
            break
        imagem = pasta / f'pagina{numero_pagina:02d}.png'
        if not imagem.exists():
            pdf[numero_pagina - 1].render(scale=regras()['paginas']['dpi_ocr'] / 72).to_pil().save(imagem)
        lida = ia.dupla_leitura(ia.ocr_da_pagina(imagem), imagem, com_vision)
        leitores = {leitor: leitura(texto) for leitor, texto in (('glm_ocr', lida['texto']), ('vision', lida['texto_vision'])) if texto}
        achadas = linhas(leitores, {**base, 'leitor': 'glm_ocr+vision'}, numero_pagina, furo)
        furo = next((l['furo'] for l in achadas[0] if l['furo']), furo)
        for grupo, novas in zip(familias, achadas):
            grupo += novas
        lidas += 1
    pdf.close()
    resumo = {**base, 'paginas_lidas': lidas, 'com_vision': com_vision, 'metros_spt': len(familias[1]), 'camadas': len(familias[2]),
              'confirmados': sum(l['status'] == 'confirmado' for g in familias for l in g),
              'motivo': 'tempo: parou no limite (operacao.json → limite_ia_s)' if time.monotonic() > prazo else ''}
    gravar(familias, resumo, {**base, 'familia': 'sondagem', 'segundos': round(time.perf_counter() - marca, 2), 'erro': ''})
    return resumo
