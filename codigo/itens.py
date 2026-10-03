"""A tabela de materiais vira itens (item 14 do plano; notas/amostras_tabelas_2026-10-03.md).

A entrada é a tabela como linhas de células de texto — da grade do vetor (leitura.tabelas) ou do OCR (ocr.ler_tabela);
a saída, um item por material × quantidade: seção, item, marcador e nota, código (vazio quando impresso '-' ou 'S/N',
o impresso ao lado), descrição como impressa, etapa, a quantidade como impressa e o valor em SI com a unidade e a
dimensão (estilo-caio-python, regra 15: 02 pç e 31,57 kg na mesma linha são dois itens, nunca somados). Sinônimos de
coluna, marcador, nota e o formato do número em conceitos/prancha.json → itens; unidades em conceitos/unidades.json.
"""
import re
from decimal import Decimal

import ia


def papel(texto):
    """O papel da célula de cabeçalho (item, codigo, descricao, quantidade, unidade, etapa:N) ou '' se não é cabeçalho."""
    COLUNAS = ia.configuracao('prancha')['itens']['colunas']
    texto = re.sub(r'\s+', ' ', texto or '').strip()
    for nome, padrao in COLUNAS.items():
        achado = re.match(padrao, texto)
        if achado:
            return f'etapa:{achado.group(1)}' if nome == 'etapa' else nome
    return ''


def cabecalho(linha):
    """Coluna → papel, se a linha é um cabeçalho: pelo menos `colunas_minimas` papéis, com descrição e quantidade (ou
    etapa); senão None."""
    MINIMAS = ia.configuracao('prancha')['itens']['colunas_minimas']
    papeis = {n: papel(c) for n, c in enumerate(linha) if papel(c)}
    valores = set(papeis.values())
    quantidade = 'quantidade' in valores or any(v.startswith('etapa:') for v in valores)
    return papeis if len(papeis) >= MINIMAS and 'descricao' in valores and quantidade else None


def numero(texto):
    """A quantidade impressa em Decimal (7.113,99 · 10221,25 · 3.30 · 02); None se não é número."""
    texto = (texto or '').strip()
    if not re.match(ia.configuracao('prancha')['itens']['numero'], texto):
        return None
    if ',' in texto or re.search(r'\.\d{3}$', texto):  # vírgula decimal, ponto de milhar
        texto = texto.replace('.', '').replace(',', '.')
    return Decimal(texto)


def unidade(texto):
    """A unidade impressa pela tabela de grafias: {'unidade_si', 'dimensao', 'fator'}; dimensão 'desconhecida' se não
    está declarada — o valor não vira SI e o item vai para conferir."""
    UNIDADES = ia.configuracao('unidades')
    bruto = (texto or '').strip().lower()
    chave = UNIDADES['grafias'].get(bruto) or UNIDADES['grafias'].get(bruto.rstrip('.')) or bruto.rstrip('.')
    achada = next((u for nome, u in UNIDADES['unidades'].items() if nome.lower() == chave.lower()), None)
    return achada or {'unidade_si': '', 'dimensao': 'desconhecida', 'fator': None}


def quantidades(celula, unidades):
    """Os pares (quantidade impressa, unidade impressa) de uma célula: a quantidade empilhada (02 sobre 31,57) casa com a
    unidade empilhada (pç sobre kg), na ordem; texto que não é número (o riscado '0 - 00') sai."""
    numeros = [t for t in re.split(r'[\s\n]+', celula or '') if numero(t) is not None]
    simbolos = [t for t in re.split(r'[\s\n]+', unidades or '') if t]
    if len(simbolos) == len(numeros):
        return list(zip(numeros, simbolos))
    return [(n, simbolos[0] if len(simbolos) == 1 else ' '.join(simbolos)) for n in numeros]


def itens(linhas, base=None, situacao=None):
    """Os itens de uma tabela (lista de linhas, cada uma lista de células). A linha com uma célula só é seção — ou nota
    de rodapé, se começa por marcador —; o cabeçalho pode se repetir (subtabelas da ETA de Foz) e vale do ponto em
    diante; linha sem descrição e sem quantidade não é item. `situacao`: a de cada linha, quando veio do OCR (confirmada,
    pendente, um_leitor); do vetor, o texto é o impresso."""
    ITENS = ia.configuracao('prancha')['itens']
    papeis, secao, achados, notas = None, '', [], {}
    for indice, linha in enumerate(linhas):
        cheias = [c.strip() for c in linha if (c or '').strip()]
        novo = cabecalho(linha)
        if novo:
            papeis = novo
            continue
        if len(cheias) == 1:
            nota = re.match(ITENS['nota'], cheias[0])
            if nota:
                notas[nota.group(1)] = nota.group(2).strip()
            else:
                secao = cheias[0]
            continue
        if papeis is None:
            continue
        campo = {p: (linha[n] if n < len(linha) else '').strip() for n, p in papeis.items()}
        marcador = re.match(ITENS['marcador'], campo.get('item', ''))
        codigo = campo.get('codigo', '')
        for chave in [p for p in papeis.values() if p == 'quantidade' or p.startswith('etapa:')]:
            for impressa, simbolo in quantidades(campo[chave], campo.get('unidade', '')):
                if chave.startswith('etapa:') and numero(impressa) == 0:
                    continue  # 00 na 1ª etapa: o material é só da 2ª
                medida = unidade(simbolo)
                achados.append({**(base or {}), 'linha': indice, 'situacao': situacao[indice] if situacao else 'vetor', 'secao': secao,
                                'item': campo.get('item', '')[marcador.end() if marcador else 0:].strip(), 'marcador': marcador.group(1) if marcador else '',
                                'codigo': '' if codigo.upper() in ITENS['codigo_vazio'] else codigo, 'codigo_impresso': codigo,
                                'descricao': re.sub(r'\s+', ' ', campo.get('descricao', '')), 'etapa': chave.split(':')[1] if ':' in chave else '',
                                'quantidade_impressa': impressa, 'unidade_declarada': simbolo, 'unidade_si': medida['unidade_si'],
                                'dimensao': medida['dimensao'],
                                'valor_si': str(numero(impressa) * Decimal(medida['fator'])) if medida['fator'] else None})
    for item in achados:
        item['nota'] = notas.get(item['marcador'], '')
    return [i for i in achados if i['descricao']]
