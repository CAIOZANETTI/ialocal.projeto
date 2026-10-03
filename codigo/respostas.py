"""As respostas das demandas (0v4, pedido do Caio de 03/10: "a minha equipe manda direto para você"). O ialocal.web
(0v8) guarda cada e-mail que responde uma demanda em ~/dados/ialocal.web/saidas/demandas/<demanda>/<recebido>/
(anexos/, corpo.txt, meta.json); o projeto só lê. O PDF anexo entra na rodada como documento da obra
_demandas/<demanda> (boletim, prancha) e é lido como qualquer outro. O CSV anexo é o gabarito da demanda
(conceitos/demandas.json → gabarito): o de sondagem é comparado campo a campo com o que o leitor tirou dos boletins; o
de carimbo traz a conferência da equipe (c, p, e). Lidos os PDFs, sai o resultado, que o maestro e o web mandam ao Caio.
"""
import csv
import hashlib
import io
import json
import os
from collections import Counter
from pathlib import Path

import comum
import prancha

RESPOSTAS = Path(os.path.expanduser(comum.configuracao('operacao')['respostas']))


def recebidas():
    """Cada resposta guardada pelo web, da mais antiga à mais nova: demanda, pasta e o meta.json dela."""
    lista = []
    for meta in sorted(RESPOSTAS.glob('*/*/meta.json')):
        lista.append({**json.loads(meta.read_text()), 'demanda': meta.parent.parent.name, 'pasta': meta.parent})
    return sorted(lista, key=lambda r: r['recebido_em'])


def documentos():
    """Os PDFs anexos às respostas, como documentos da rodada: obra _demandas/<demanda>, versão pelo conteúdo."""
    lista = []
    for resposta in recebidas():
        for nome in resposta['anexos']:
            arquivo = resposta['pasta'] / 'anexos' / nome
            if arquivo.suffix.lower() == '.pdf' and arquivo.exists():
                lista.append({'id': f"DEMANDA/{resposta['demanda']}/{resposta['pasta'].name}/{nome}",
                              'caminho': f"_demandas/{resposta['demanda']}/{nome}", 'nome': nome,
                              'versao': hashlib.sha256(arquivo.read_bytes()).hexdigest()[:16], 'arquivo_local': str(arquivo),
                              'acervo': '_demandas', 'obra': resposta['demanda']})
    return lista


def tabela_csv(arquivo):
    """As linhas de um CSV como dicts com as colunas em minúsculas: UTF-8 (com ou sem BOM) ou o CSV comum do Excel
    (cp1252), separado por ; ou por vírgula."""
    bruto = arquivo.read_bytes()
    try:
        texto = bruto.decode('utf-8-sig')
    except UnicodeDecodeError:
        texto = bruto.decode('cp1252')
    cabecalho = texto.splitlines()[0] if texto.strip() else ''
    separador = ';' if cabecalho.count(';') >= cabecalho.count(',') else ','
    return [{(k or '').strip().lower(): (v or '').strip() for k, v in linha.items()}
            for linha in csv.DictReader(io.StringIO(texto), delimiter=separador)]


def medir_sondagem(gabarito):
    """Campo → (certos, conferidos) do leitor de boletim contra o gabarito (uma linha por arquivo), e as divergências.
    nspt_<n>m confere o N-SPT do metro n."""
    campos, spt = comum.ler('sondagem_campo'), comum.ler('sondagem_spt')
    lidos = {} if campos is None else {(l['arquivo'], l['campo']): l['valor'] for l in campos.to_dicts()}
    lidos |= {} if spt is None else {(l['arquivo'], f"nspt_{int(l['profundidade_m'])}m"): str(l['nspt']) for l in spt.to_dicts()
                                     if float(l['profundidade_m']).is_integer()}
    placar, divergencias = {}, []
    for linha in gabarito:
        for campo, esperado in linha.items():
            if campo == 'arquivo' or not esperado:
                continue
            lido = lidos.get((linha.get('arquivo', ''), campo), '')
            certo = prancha.normalizar(lido) == prancha.normalizar(esperado)
            certos, total = placar.get(campo, (0, 0))
            placar[campo] = (certos + certo, total + 1)
            if not certo:
                divergencias.append(f"{linha.get('arquivo')} · {campo}: lido '{lido or '—'}' × gabarito '{esperado}'")
    return placar, divergencias


def medir_carimbo(conferidos):
    """Campo → Counter das marcas da equipe (c certo, p parcial, e errado) no carimbos.csv conferido."""
    placar = {}
    for linha in conferidos:
        marca = (linha.get('conferido') or '').lower()[:1]
        if marca in ('c', 'p', 'e'):
            placar.setdefault(linha.get('campo') or '?', Counter())[marca] += 1
    return placar


def texto_do_placar(tipo, gabaritos):
    """As linhas do resultado para o gabarito de um tipo (sondagem, carimbo)."""
    if tipo == 'sondagem':
        placar, divergencias = medir_sondagem([l for g in gabaritos for l in g])
        certos, total = sum(c for c, _ in placar.values()), sum(t for _, t in placar.values())
        linhas = [f'Acerto contra o gabarito: {certos} de {total} campos' + (f' ({certos / total:.0%})' if total else ''),
                  *(f'  {campo}: {c} de {t}' for campo, (c, t) in sorted(placar.items()))]
        return linhas + (['Divergências (o boletim diz × o leitor tirou):', *(f'  {d}' for d in divergencias[:15])] if divergencias else [])
    placar = medir_carimbo([l for g in gabaritos for l in g])
    total = sum(sum(c.values()) for c in placar.values())
    certos = sum(c['c'] for c in placar.values())
    return ([f'Conferência da equipe: {certos} de {total} campos certos' + (f' ({certos / total:.0%})' if total else '')]
            + [f"  {campo}: {c['c']} certo, {c['p']} parcial, {c['e']} errado" for campo, c in sorted(placar.items())])


def situacao(estados, documentos_da_rodada):
    """(respondidas, resultados): as demandas que já têm resposta guardada e, das que têm os PDFs todos lidos (feito
    ou falhou), o resultado para o Caio — um por resposta nova (o id muda com o número de respostas)."""
    DEMANDAS = {d['id']: d for d in comum.configuracao('demandas')['demandas']}
    por_demanda = {}
    for resposta in recebidas():
        por_demanda.setdefault(resposta['demanda'], []).append(resposta)
    resultados = []
    for demanda, respostas in por_demanda.items():
        dela = [d for d in documentos_da_rodada if d['id'].startswith(f'DEMANDA/{demanda}/')]
        if demanda not in DEMANDAS or any(estados.get(d['id']) not in ('feito', 'falhou') for d in dela):
            continue
        gabaritos = [tabela_csv(r['pasta'] / 'anexos' / n) for r in respostas for n in r['anexos'] if n.lower().endswith('.csv')]
        lidos = Counter(estados[d['id']] for d in dela)
        linhas = [f"Recebi {sum(len(r['anexos']) for r in respostas)} arquivo(s) em {len(respostas)} resposta(s), a última de "
                  f"{respostas[-1]['de']} em {respostas[-1]['recebido_em'][:16].replace('T', ' ')}.",
                  f"PDFs lidos: {lidos['feito']} de {len(dela)}" + (f" ({lidos['falhou']} falharam: dados/falhas.jsonl)" if lidos['falhou'] else '') + '.']
        tipo = DEMANDAS[demanda].get('gabarito')
        linhas += texto_do_placar(tipo, gabaritos) if gabaritos and tipo else ['Sem CSV de gabarito na resposta: só os PDFs foram lidos.']
        resultados.append({'id': f'{demanda}-resultado-{len(respostas)}', 'demanda': demanda,
                           'titulo': f"Resultado: {DEMANDAS[demanda]['titulo']}", 'texto': '\n'.join(linhas)})
    return set(por_demanda), resultados
