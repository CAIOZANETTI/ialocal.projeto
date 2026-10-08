"""O rastro: uma vista única de como cada documento foi lido — uma linha por documento × etapa × executor, com o que
entrou, o que saiu, quantos valores confirmados e pendentes, quanto tempo a tarefa levou e com que código
(notas/saidas_e_rastro.md §5). É o acervo de quem extraiu o quê, para escolher a melhor ferramenta para cada etapa.

Não lê PDF nem chama modelo: junta o que as tarefas já gravaram em dados/ (prancha, carimbo, prancha_leitura,
prancha_tabela, sondagem_*, execucoes.jsonl). Sai em dados/rastro.parquet e é publicado como rastro.csv, por obra e
em _sistema/projeto/, junto com os outros CSVs (ciclo.publicar); os ensaios levam o deles em ensaios_rastro.csv.

ETAPAS, na ordem da leitura:
    leitura_inicial   ler_prancha       código (pypdfium2)       formato, classe, é prancha?, é boletim?
    carimbo           ler_prancha(_ia)  código (texto real) ou glm-ocr × Vision (desenhado)
    familia           ler_prancha(_ia)  regra (prancha.json) ou qwen3 × Apple FM (desempate)
    eixo              ler_prancha       código (geometria: faixa ou camadas de tubo)
    fatias            ler_prancha_ia    glm-ocr × Vision
    tabelas_coladas   ler_prancha_ia    glm-ocr em modo tabela × Vision
    conferencia       ler_prancha_ia    código (eixo × escala × tubo da relação)
    boletim           ler_sondagem(_ia) código (texto real) ou glm-ocr × Vision (digitalizado)

O tempo é o da TAREFA (segundos_tarefa, de execucoes.jsonl), repetido nas etapas que ela contém: o ler_prancha_ia soma
carimbo desenhado, fatias e tabelas. Separar o tempo por etapa é o passo seguinte (notas/saidas_e_rastro.md §5, item 4).
"""
import json

import polars as pl

import comum

COLUNAS = ['id', 'acervo', 'obra', 'arquivo', 'versao_documento', 'ordem', 'etapa', 'tarefa', 'executor', 'natureza',
           'entrada', 'resultado', 'valores', 'confirmados', 'pendentes', 'segundos_tarefa', 'versao_codigo', 'commit']
EXECUTOR = {'pdf': ('codigo:texto_do_pdf', 'codigo'), 'glm_ocr+vision': ('glm-ocr × Vision', 'generativo+testemunha')}
CONFIRMA = ('codigo', 'confirmado', 'confirmada')
TAREFA_DO_EXTRATOR = {'prancha': 'ler_prancha', 'prancha_ia': 'ler_prancha_ia', 'sondagem': 'ler_sondagem',
                      'sondagem_ia': 'ler_sondagem_ia'}


def tempos():
    """(id, extrator) → segundos da última execução da tarefa (dados/execucoes.jsonl)."""
    arquivo = comum.DADOS / 'execucoes.jsonl'
    if not arquivo.exists():
        return {}
    saida = {}
    for linha in arquivo.read_text().splitlines():
        try:
            registro = json.loads(linha)
        except ValueError:
            continue
        if 'id' in registro and 'extrator' in registro:
            saida[(registro['id'], registro['extrator'])] = registro.get('segundos')
    return saida


def por_id(familia):
    """id → linhas da família ([] sem a família)."""
    tabela = comum.ler(familia)
    grupos = {}
    for linha in (tabela.to_dicts() if tabela is not None else []):
        grupos.setdefault(linha['id'], []).append(linha)
    return grupos


def contagem(linhas):
    return len(linhas), sum(l.get('status') in CONFIRMA for l in linhas), sum(l.get('status') not in CONFIRMA for l in linhas)


def resumo_status(linhas):
    """'confirmado 96, so_glm 24' — os status das linhas, do mais comum ao menos."""
    vistos = {}
    for l in linhas:
        vistos[l.get('status') or ''] = vistos.get(l.get('status') or '', 0) + 1
    return ', '.join(f'{s} {n}' for s, n in sorted(vistos.items(), key=lambda v: -v[1]) if s)


def do_documento(perfil, ia, carimbos, leituras, tabelas, sondagem, tempo):
    """As linhas do rastro de um documento: perfil = a linha do ler_prancha; ia = a do ler_prancha_ia (ou None);
    o resto, as linhas das famílias deste id. Função pura."""
    base = {c: perfil.get(c) for c in ('id', 'acervo', 'obra', 'arquivo', 'versao_documento')}
    final = ia or perfil
    linhas = []

    def etapa(nome, tarefa, executor, natureza, entrada, resultado, valores=None, confirmados=None, pendentes=None, de=None):
        extrator = {v: k for k, v in TAREFA_DO_EXTRATOR.items()}[tarefa]
        origem = de or (ia if extrator.endswith('_ia') and ia else perfil)
        linhas.append({**base, 'ordem': len(linhas) + 1, 'etapa': nome, 'tarefa': tarefa, 'executor': executor,
                       'natureza': natureza, 'entrada': entrada, 'resultado': resultado, 'valores': valores,
                       'confirmados': confirmados, 'pendentes': pendentes,
                       'segundos_tarefa': tempo.get((perfil['id'], extrator)),
                       'versao_codigo': origem.get('versao_codigo'), 'commit': origem.get('commit')})

    classe = perfil.get('classe') or '—'
    tipo = 'boletim de sondagem' if perfil.get('boletim_sondagem') else 'prancha' if perfil.get('e_prancha') else 'nenhum'
    etapa('leitura_inicial', 'ler_prancha', 'codigo:pypdfium2', 'codigo', f"página 1 de {perfil.get('paginas') or '?'}",
          f"{perfil.get('formato') or '?'} · {classe} · {tipo} ({perfil.get('motivo') or ''})")
    if perfil.get('e_prancha'):
        por_leitor = {}
        for l in carimbos:
            por_leitor.setdefault(l.get('leitor') or '', []).append(l)
        for leitor, grupo in sorted(por_leitor.items()):
            executor, natureza = EXECUTOR.get(leitor, (leitor, ''))
            etapa('carimbo', 'ler_prancha' if leitor == 'pdf' else 'ler_prancha_ia', executor, natureza,
                  f"região do carimbo · camada {perfil.get('carimbo_camada') or '?'}", resumo_status(grupo), *contagem(grupo),
                  de=perfil if leitor == 'pdf' else None)
        if not por_leitor:
            etapa('carimbo', 'ler_prancha', 'codigo:texto_do_pdf', 'codigo', f"região do carimbo · camada {perfil.get('carimbo_camada') or '?'}",
                  'nenhum campo lido' + (' (desenhado: espera a IA)' if perfil.get('carimbo_camada') == 'imagem' else ''), 0, 0, 0)
        origem = final.get('familia_origem') or ''
        etapa('familia', 'ler_prancha_ia' if origem.startswith('ia') else 'ler_prancha',
              'qwen3 × Apple FM' if origem.startswith('ia') else 'regra:prancha.json',
              'generativo' if origem.startswith('ia') else 'codigo', 'nome do arquivo + texto do carimbo e das notas',
              f"{final.get('familia') or '?'} · {final.get('grupo') or '?'} · {final.get('desenho') or '?'}", de=final)
        etapa('eixo', 'ler_prancha', 'codigo:geometria', 'codigo', f"caminhos da página 1 ({perfil.get('curvas') or '?'})",
              f"{perfil.get('eixo') or '?'} · {perfil.get('eixo_mm') if perfil.get('eixo_mm') is not None else '—'} mm de papel"
              f" · deflexões {perfil.get('deflexoes') or '[]'}")
        if ia:
            etapa('fatias', 'ler_prancha_ia', 'glm-ocr × Vision', 'generativo+testemunha',
                  f"{ia.get('fatias_lidas')} de {ia.get('fatias_planejadas')} fatias", resumo_status(leituras) or 'nada lido',
                  *contagem(leituras))
            if tabelas:
                etapa('tabelas_coladas', 'ler_prancha_ia', 'glm-ocr (tabela) × Vision', 'generativo+testemunha',
                      f"{len({(t.get('imagem'), t.get('faixa')) for t in tabelas})} faixa(s) de imagem colada",
                      resumo_status(tabelas), *contagem(tabelas))
            etapa('conferencia', 'ler_prancha_ia', 'codigo:conferencia', 'codigo',
                  f"escala {ia.get('escalas_confirmadas') or '[]'} · tubo da relação {ia.get('tubo_relacao_m') or '—'} m",
                  f"{ia.get('conferencia') or '?'} · eixo {ia.get('eixo_m') if ia.get('eixo_m') is not None else '—'} m")
    if perfil.get('boletim_sondagem'):
        por_leitor = {}
        for l in sondagem:
            por_leitor.setdefault(l.get('leitor') or '', []).append(l)
        for leitor, grupo in sorted(por_leitor.items()):
            executor, natureza = EXECUTOR.get(leitor, (leitor, ''))
            furos = sorted({l.get('furo') for l in grupo if l.get('furo')})
            etapa('boletim', 'ler_sondagem' if leitor == 'pdf' else 'ler_sondagem_ia', executor, natureza,
                  f"{len({l.get('pagina') for l in grupo})} página(s)", f"furo(s) {', '.join(furos) or '?'} · {resumo_status(grupo)}",
                  *contagem(grupo), de=grupo[0])
    return linhas


def montar(ids=None):
    """O rastro de todos os documentos lidos (ou só dos ids), como DataFrame no esquema COLUNAS."""
    prancha = comum.ler('prancha')
    if prancha is None:
        return pl.DataFrame(schema={c: pl.Utf8 for c in COLUNAS})
    perfis, finais = {}, {}
    for l in prancha.to_dicts():
        (perfis if l['extrator'] == 'prancha' else finais)[l['id']] = l
    carimbos, leituras, tabelas = por_id('carimbo'), por_id('prancha_leitura'), por_id('prancha_tabela')
    sondagem = {}
    for familia in ('sondagem_campo', 'sondagem_spt', 'sondagem_camada'):
        for i, grupo in por_id(familia).items():
            sondagem.setdefault(i, []).extend(grupo)
    tempo = tempos()
    linhas = [l for i, perfil in sorted(perfis.items()) if ids is None or i in ids
              for l in do_documento(perfil, finais.get(i), carimbos.get(i, []), leituras.get(i, []), tabelas.get(i, []),
                                    sondagem.get(i, []), tempo)]
    esquema = {c: pl.Int64 if c in ('ordem', 'valores', 'confirmados', 'pendentes') else pl.Float64 if c == 'segundos_tarefa'
               else pl.Utf8 for c in COLUNAS}
    return pl.DataFrame([{c: l.get(c) for c in COLUNAS} for l in linhas], schema=esquema)


def gerar():
    """dados/rastro.parquet com o rastro de tudo o que foi lido; devolve o DataFrame."""
    tabela = montar()
    comum.DADOS.mkdir(parents=True, exist_ok=True)
    temporario = comum.DADOS / 'rastro.tmp'
    tabela.write_parquet(temporario)
    temporario.replace(comum.DADOS / 'rastro.parquet')
    return tabela


if __name__ == '__main__':
    with pl.Config(tbl_rows=60, tbl_cols=12, fmt_str_lengths=60, tbl_width_chars=220):
        print(gerar().select('arquivo', 'ordem', 'etapa', 'executor', 'entrada', 'resultado', 'confirmados', 'pendentes', 'segundos_tarefa'))
