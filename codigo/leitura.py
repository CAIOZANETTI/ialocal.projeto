"""O que a folha diz, lido por código sobre o vetor (notas/plano_projeto.md §2–§4): o texto em linhas, as células das
grades desenhadas, as tabelas pelo cabeçalho, o quadro de revisões, o carimbo por rótulo-âncora, as notas e a família.

Toda coordenada em mm de papel, origem embaixo à esquerda (folha.vetorizar). Célula é o retângulo de verdade: a grade
é a dos traços horizontais e verticais que se cruzam, e duas células vizinhas só se separam onde o traço entre elas
existe (o carimbo tem linhas com divisões diferentes). Regras, rótulos e limites em conceitos/prancha.json.
"""
import bisect
import re
import unicodedata
from pathlib import Path

import ia


def linhas_de_texto(primitivas):
    """Os textos da folha juntos em linhas: mesma base, mesmo ângulo e vão pequeno (o CAD às vezes grava letra a
    letra). Cada linha com a caixa, a altura e o texto."""
    TEXTO = ia.configuracao('prancha')['texto']
    itens = sorted((p for p in primitivas if p['tipo'] == 'texto'), key=lambda p: (round(p['angulo_graus']), -round(p['y_mm'][0], 1), p['x0_mm']))
    linhas = []
    for item in itens:
        altura = max(item['tamanho_mm'], 0.1)
        ultima = linhas[-1] if linhas else None
        if ultima and ultima['angulo'] == round(item['angulo_graus']) and item['angulo_graus'] == 0 and \
                abs(ultima['base'] - item['y_mm'][0]) <= TEXTO['mesma_base'] * altura and \
                -0.5 * altura <= item['x0_mm'] - ultima['x1'] <= TEXTO['vao_palavra'] * altura:
            ultima['texto'] += (' ' if item['x0_mm'] - ultima['x1'] > TEXTO['espaco'] * altura else '') + item['texto']
            ultima.update(x1=max(ultima['x1'], item['x1_mm']), y0=min(ultima['y0'], item['y0_mm']), y1=max(ultima['y1'], item['y1_mm']))
            continue
        linhas.append({'texto': item['texto'], 'x0': item['x0_mm'], 'y0': item['y0_mm'], 'x1': item['x1_mm'], 'y1': item['y1_mm'],
                       'base': item['y_mm'][0], 'altura': altura, 'angulo': round(item['angulo_graus']), 'camada': item['camada']})
    for linha in linhas:
        linha['texto'] = re.sub(r'\s+', ' ', linha['texto']).strip()
    return [l for l in linhas if l['texto']]


def celulas(primitivas):
    """As células das grades desenhadas: os traços retos (horizontais e verticais) que se cruzam formam grupos; em cada
    grupo, a grade das coordenadas distintas, e as células vizinhas se juntam onde falta o traço entre elas."""
    TABELAS = ia.configuracao('prancha')['tabelas']
    tolerancia, minimo = TABELAS['tolerancia_mm'], TABELAS['traco_minimo_mm']
    horizontais, verticais = [], []
    for p in primitivas:
        if p['tipo'] != 'traco':
            continue
        pontos = list(zip(p['x_mm'], p['y_mm']))
        for (xa, ya), (xb, yb) in zip(pontos, pontos[1:] + pontos[:1] * p['fechado']):
            if abs(ya - yb) <= tolerancia and abs(xa - xb) >= minimo:
                horizontais.append((min(xa, xb), max(xa, xb), (ya + yb) / 2))
            elif abs(xa - xb) <= tolerancia and abs(ya - yb) >= minimo:
                verticais.append((min(ya, yb), max(ya, yb), (xa + xb) / 2))
    pai = list(range(len(horizontais) + len(verticais)))

    def raiz(i):
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i
    verticais.sort(key=lambda v: v[2])
    posicoes = [v[2] for v in verticais]
    for h, (x0, x1, y) in enumerate(horizontais):
        for v in range(bisect.bisect_left(posicoes, x0 - tolerancia), bisect.bisect_right(posicoes, x1 + tolerancia)):
            if verticais[v][0] - tolerancia <= y <= verticais[v][1] + tolerancia:
                pai[raiz(h)] = raiz(len(horizontais) + v)
    grupos = {}
    for indice in range(len(pai)):
        grupos.setdefault(raiz(indice), []).append(indice)
    achadas = []
    for membros in grupos.values():
        hs = [horizontais[i] for i in membros if i < len(horizontais)]
        vs = [verticais[i - len(horizontais)] for i in membros if i >= len(horizontais)]
        if len(hs) >= 2 and len(vs) >= 2:
            achadas += celulas_do_grupo(hs, vs, tolerancia)
    return achadas


def celulas_do_grupo(horizontais, verticais, tolerancia):
    """As células de um grupo de traços: a grade das coordenadas distintas e a junção das vizinhas sem traço entre elas."""
    xs, ys = [], []
    for distintas, tracos in ((xs, verticais), (ys, horizontais)):
        for posicao in sorted(t[2] for t in tracos):
            if not distintas or posicao - distintas[-1] > tolerancia:
                distintas.append(posicao)
    coberto = lambda tracos, posicao, de, ate: any(abs(t[2] - posicao) <= tolerancia and t[0] <= de + tolerancia and t[1] >= ate - tolerancia
                                                  for t in tracos)
    rotulo = {(i, j): (i, j) for i in range(len(xs) - 1) for j in range(len(ys) - 1)}

    def raiz(chave):
        while rotulo[chave] != chave:
            chave = rotulo[chave]
        return chave
    for i, j in list(rotulo):
        if i + 1 < len(xs) - 1 and not coberto(verticais, xs[i + 1], ys[j], ys[j + 1]):
            rotulo[raiz((i + 1, j))] = raiz((i, j))
        if j + 1 < len(ys) - 1 and not coberto(horizontais, ys[j + 1], xs[i], xs[i + 1]):
            rotulo[raiz((i, j + 1))] = raiz((i, j))
    juntas = {}
    for i, j in rotulo:
        juntas.setdefault(raiz((i, j)), []).append((i, j))
    return [{'x0': xs[min(i for i, _ in a)], 'x1': xs[max(i for i, _ in a) + 1], 'y0': ys[min(j for _, j in a)], 'y1': ys[max(j for _, j in a) + 1]}
            for a in juntas.values()]


def onde(linha, todas):
    """A menor célula que contém o centro da linha de texto; None fora de toda grade."""
    x, y = (linha['x0'] + linha['x1']) / 2, (linha['y0'] + linha['y1']) / 2
    dentro = [c for c in todas if c['x0'] <= x <= c['x1'] and c['y0'] <= y <= c['y1']]
    return min(dentro, key=lambda c: (c['x1'] - c['x0']) * (c['y1'] - c['y0']), default=None)


def tabelas(linhas, todas):
    """As tabelas desenhadas, achadas pelo cabeçalho: uma fileira de células vizinhas com texto que casa um tipo
    (conceitos/prancha.json → tabelas.tipos) ou o quadro de revisões; daí, para cima e para baixo, as fileiras com as
    mesmas divisões. Cada tabela com o tipo, a caixa e as linhas (lista de células, o cabeçalho primeiro)."""
    TABELAS, REVISOES = ia.configuracao('prancha')['tabelas'], ia.configuracao('prancha')['revisoes']
    tolerancia = TABELAS['tolerancia_mm']
    textos = {}
    for linha in linhas:
        celula = onde(linha, todas)
        if celula:
            textos.setdefault(id(celula), []).append(linha)
    escrito = lambda c: ' '.join(l['texto'] for l in sorted(textos.get(id(c), []), key=lambda l: (-l['y1'], l['x0'])))
    fileiras = {}
    for celula in todas:
        fileiras.setdefault((round(celula['y0'] / tolerancia), round(celula['y1'] / tolerancia)), []).append(celula)
    corridas = []
    for chave, fileira in fileiras.items():
        fileira.sort(key=lambda c: c['x0'])
        corrida = [fileira[0]]
        for celula in fileira[1:] + [None]:
            if celula and abs(celula['x0'] - corrida[-1]['x1']) <= tolerancia:
                corrida.append(celula)
                continue
            if len(corrida) >= TABELAS['colunas_minimas']:
                corridas.append(corrida)
            corrida = [celula]
    divisoes = lambda corrida: tuple(round(c['x0'] / tolerancia) for c in corrida) + (round(corrida[-1]['x1'] / tolerancia),)
    achadas, usadas = [], set()
    for corrida in sorted(corridas, key=lambda c: -c[0]['y1']):
        cabecalho = [escrito(c) for c in corrida]
        if id(corrida[0]) in usadas or sum(bool(t) for t in cabecalho) < TABELAS['colunas_minimas']:
            continue
        revisao = bool(re.match(REVISOES['cabecalho'], cabecalho[0])) and any(re.match(REVISOES['colunas']['data'], t) for t in cabecalho)
        tipo = 'revisoes' if revisao else next((t for t, padrao in TABELAS['tipos'].items() if re.search(padrao, ' '.join(cabecalho))), '')
        if not tipo:
            continue
        bloco = estender([corrida], [c for c in corridas if divisoes(c) == divisoes(corrida)], todas, tolerancia)
        corpo = [[escrito(c) for c in fileira] for fileira in bloco]
        cheias = sum(bool(t) for fileira in corpo for t in fileira) / max(sum(len(f) for f in corpo), 1)
        if len(bloco) < TABELAS['linhas_minimas'] or cheias < TABELAS['ocupacao_minima']:
            continue
        usadas.update(id(c[0]) for c in bloco)
        cabeca = bloco.index(corrida)
        achadas.append({'tipo': tipo, 'x0': corrida[0]['x0'], 'x1': corrida[-1]['x1'], 'y0': bloco[-1][0]['y0'], 'y1': bloco[0][0]['y1'],
                        'linhas': [corpo[cabeca]] + [f for n, f in enumerate(corpo) if n != cabeca and any(f)]})
    return achadas


def estender(bloco, mesmas, todas, tolerancia):
    """A tabela cresce para cima e para baixo pelas fileiras com as mesmas divisões que encostam; a célula da largura
    inteira da tabela (a linha de seção, "REDE DE DISTRIBUIÇÃO") entra só entre duas fileiras da tabela — a que encosta
    só por fora é título ou carimbo, e fica fora."""
    x0, x1 = bloco[0][0]['x0'], bloco[0][-1]['x1']
    largas = [[c] for c in todas if abs(c['x0'] - x0) <= tolerancia and abs(c['x1'] - x1) <= tolerancia]
    encosta = lambda grupo, de, ate: next((c for c in grupo if abs(c[0][de] - ate) <= tolerancia and c not in bloco), None)
    for de, para, borda in (('y0', 'y1', lambda: bloco[0][0]['y1']), ('y1', 'y0', lambda: bloco[-1][0]['y0'])):
        while True:
            passo = [encosta(mesmas, de, borda())]
            if passo[0] is None and (larga := encosta(largas, de, borda())):
                passo = [larga, encosta(mesmas, de, larga[0][para])]
            if None in passo:
                break
            bloco = passo[::-1] + bloco if de == 'y0' else bloco + passo
    return bloco


def revisoes(tabela):
    """O quadro de revisões como lista: revisão, data, descrição (e quem, quando há a coluna); só as linhas cuja
    primeira coluna é revisão. A mais recente primeiro, pela ordem do número."""
    REVISOES = ia.configuracao('prancha')['revisoes']
    cabecalho, linhas = tabela['linhas'][0], tabela['linhas'][1:]
    colunas = {campo: next((n for n, t in enumerate(cabecalho) if re.match(padrao, t)), None) for campo, padrao in REVISOES['colunas'].items()}
    achadas = [{'revisao': linha[0], **{campo: linha[n] for campo, n in colunas.items() if n is not None}}
               for linha in linhas if re.match(REVISOES['revisao'], linha[0])]
    numero = lambda r: int(re.sub(r'\D', '', r['revisao']) or 0) if re.search(r'\d', r['revisao']) else ord(r['revisao'][-1])
    return sorted(achadas, key=numero, reverse=True)[:REVISOES['linhas_maximas']]


def carimbo(linhas, todas, folha_mm, nome, fora=()):
    """Os campos do carimbo por rótulo-âncora: o carimbo é a área das células com rótulos de `ancoras_minimas` campos
    diferentes (sem grade, a região fixa da folha); o valor é o resto da linha do rótulo ou, na mesma célula, a linha
    mais perto abaixo ou à direita que não é outro rótulo. Campo com `valida` só aceita o que casa. `fora`: as caixas das
    tabelas e do quadro de revisões (o DATA do quadro não é a data do carimbo)."""
    CARIMBO = ia.configuracao('prancha')['carimbo']
    dentro = lambda l, caixa: caixa['x0'] <= (l['x0'] + l['x1']) / 2 <= caixa['x1'] and caixa['y0'] <= (l['y0'] + l['y1']) / 2 <= caixa['y1']
    livres = [l for l in linhas if not any(dentro(l, caixa) for caixa in fora)]
    rotulos = {id(l): campo for l in livres for campo, regra in CARIMBO['campos'].items() if re.match(regra['ancora'], l['texto'])}
    celulas_dos_rotulos = [c for c in (onde(l, todas) for l in livres if id(l) in rotulos) if c]
    if len({rotulos[id(l)] for l in livres if id(l) in rotulos}) >= CARIMBO['ancoras_minimas'] and celulas_dos_rotulos:
        zona = {'x0': min(c['x0'] for c in celulas_dos_rotulos), 'x1': max(c['x1'] for c in celulas_dos_rotulos),
                'y0': min(c['y0'] for c in celulas_dos_rotulos), 'y1': max(c['y1'] for c in celulas_dos_rotulos), 'origem': 'celulas'}
    else:
        x0, y0, x1, y1 = CARIMBO['regiao']
        zona = {'x0': x0 * folha_mm[0], 'x1': x1 * folha_mm[0], 'y0': (1 - y1) * folha_mm[1], 'y1': (1 - y0) * folha_mm[1], 'origem': 'regiao'}
    nela = [l for l in livres if dentro(l, zona)]
    campos = {}
    for linha in sorted((l for l in nela if id(l) in rotulos), key=lambda l: (-l['y1'], l['x0'])):
        campo = rotulos[id(linha)]
        if campos.get(campo):
            continue
        campos[campo] = valor_do_rotulo(linha, CARIMBO['campos'][campo], [l for l in nela if id(l) not in rotulos], onde(linha, todas))
    texto = '\n'.join(l['texto'] for l in sorted(nela, key=lambda l: (-l['y1'], l['x0'])))
    for campo, padrao in CARIMBO['padroes'].items():
        achado = re.search(padrao, texto)
        campos[campo] = achado.group(0).strip() if achado else campos.get(campo, '')
    if campos.get('registro') and campos.get('responsavel_tecnico'):  # o CREA sai no campo dele, não no nome
        campos['responsavel_tecnico'] = campos['responsavel_tecnico'].replace(campos['registro'], '').strip(' -–,')
    revisao_nome = re.search(CARIMBO['revisao_nome'], Path(nome).stem)
    compacto = lambda s: re.sub(r'\s+', '', unicodedata.normalize('NFKC', s)).upper()
    return {'zona': zona, 'texto': texto, 'campos': {c: v for c, v in campos.items() if v},
            'revisao_nome': revisao_nome.group(1) if revisao_nome else '', 'arquivo_confere': compacto(Path(nome).stem) in compacto(texto),
            'disciplina': disciplina(nome, texto)}


def valor_do_rotulo(rotulo, regra, candidatas, celula):
    """O valor de um rótulo: o resto da linha dele ('DATA: 09/2020'); senão as linhas da mesma célula (sem grade, até
    3 alturas abaixo ou 60 mm à direita), da mais perto para a mais longe — todas, de cima para baixo, no `multilinha`."""
    fim = re.match(regra['ancora'], rotulo['texto']).end()
    resto = rotulo['texto'][fim:].strip(' :.-–')
    no_meio = fim < len(rotulo['texto']) and rotulo['texto'][fim - 1:fim + 1].isalpha()  # 'RESP. TÉC' dentro de 'TÉCNICO'
    if resto and not no_meio and (not regra.get('valida') or re.search(regra['valida'], resto)):
        return resto
    if celula:
        perto = [l for l in candidatas if celula['x0'] <= (l['x0'] + l['x1']) / 2 <= celula['x1'] and celula['y0'] <= (l['y0'] + l['y1']) / 2 <= celula['y1']]
    else:
        perto = [l for l in candidatas if (rotulo['y0'] - 3 * rotulo['altura'] <= l['y1'] <= rotulo['y1'] and l['x1'] >= rotulo['x0'] and l['x0'] <= rotulo['x1'] + 60)]
    perto = [l for l in perto if l['y1'] <= rotulo['y1'] + 0.5 * rotulo['altura']]
    if regra.get('multilinha'):
        return ' '.join(l['texto'] for l in sorted(perto, key=lambda l: (-l['y1'], l['x0'])))
    distancia = lambda l: (max(rotulo['y0'] - l['y1'], 0) + max(l['x0'] - rotulo['x1'], 0))
    return next((l['texto'] for l in sorted(perto, key=distancia) if not regra.get('valida') or re.search(regra['valida'], l['texto'])), '')


def disciplina(nome, texto):
    """A disciplina pelo código Sanepar no nome (PBHI, PBES…), senão pela primeira palavra do texto do carimbo que casa."""
    DISCIPLINAS = ia.configuracao('prancha')['carimbo']['disciplinas']
    codigo = next((d for c, d in DISCIPLINAS['codigo'].items() if re.search(rf'(?:^|[-_]){c}(?:[-_]|$)', Path(nome).stem)), '')
    return codigo or next((d for d, padrao in DISCIPLINAS['texto'].items() if re.search(padrao, texto)), '')


def notas(linhas):
    """Cada bloco de notas ou observações: o título e os itens de baixo, na mesma coluna, até um vão grande; a linha sem
    número ou marcador continua o item de cima."""
    NOTAS = ia.configuracao('prancha')['notas']
    blocos = []
    for titulo in (l for l in linhas if re.match(NOTAS['titulo'], l['texto'])):
        abaixo = sorted((l for l in linhas if l['y1'] < titulo['y0'] + 0.1 and titulo['x0'] - 2 * titulo['altura'] <= l['x0'] <= titulo['x0'] + 30 * titulo['altura']
                         and l['angulo'] == titulo['angulo']), key=lambda l: -l['y1'])
        itens, acima = [], titulo
        for linha in abaixo[:NOTAS['linhas_maximas']]:
            if acima['y0'] - linha['y1'] > NOTAS['vao_linhas'] * linha['altura'] or re.match(NOTAS['titulo'], linha['texto']):
                break
            marcador = re.match(NOTAS['item'], linha['texto'])
            if marcador or not itens:
                itens.append({'numero': re.sub(r'\D', '', marcador.group(1)) if marcador else '', 'texto': linha['texto'][marcador.end() if marcador else 0:].strip()})
            else:
                itens[-1]['texto'] += ' ' + linha['texto']
            acima = linha
        if itens:
            blocos.append({'titulo': titulo['texto'].rstrip(' :'), 'x0': titulo['x0'], 'y1': titulo['y1'], 'itens': itens})
    return blocos


def familia(nome, texto):
    """Família pela primeira regra que casa: no nome, depois no código do desenho escrito no carimbo, e só então no texto
    sem os rótulos de tipo de linha (GAS GAS GAS… é a interferência desenhada, não a obra), de formulário e de existente;
    o grupo (linear, localizada, apoio) sai da família, nunca de modelo (T7 de 26/09)."""
    FAMILIAS = ia.configuracao('prancha')['familias']
    procurar = lambda alvo: next((f for f in FAMILIAS['ordem'] if re.search(FAMILIAS['padroes'][f], alvo)), '')
    codigos = ' '.join(re.findall(FAMILIAS['codigo_desenho'], texto))
    sem_tracejado = re.sub(FAMILIAS['rotulos_ignorados'], ' ', re.sub(r'\b(\w+)(?:\s+\1\b){2,}', ' ', texto))
    achada = procurar(Path(nome).stem) or procurar(codigos) or procurar(sem_tracejado)
    alvo = f'{Path(nome).stem}\n{texto}'
    return {'familia': achada or 'indefinida', 'grupo': FAMILIAS['grupo'].get(achada, ''), 'familia_origem': 'regra' if achada else '',
            'desenho': next((d for d, padrao in FAMILIAS['desenhos'].items() if re.search(padrao, alvo)), 'outro')}
