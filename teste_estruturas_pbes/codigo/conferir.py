"""Conferência: extraído de cada prancha x resumo geral (Resumo de Materiais.pdf) x física (NBR 7480).
Entradas: saidas/<estrutura>/<codigo>/*.csv, gabarito_resumo.json. Saídas: saidas/consolidado/*.csv (CSV é a fonte)."""
import os, sys, json, glob, re
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extrator_pbes import MASSA

AQUI = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.environ.get('SAIDA', os.path.join(AQUI, '..', 'resultados'))
GAB = json.load(open(os.path.join(AQUI, '..', 'gabarito', 'gabarito_resumo.json')))
COL_BIT = {6.3: 'ca50_6_3', 8.0: 'ca50_8_0', 10.0: 'ca50_10_0', 12.5: 'ca50_12_5', 16.0: 'ca50_16_0', 20.0: 'ca50_20_0', 5.0: 'ca60_5_0'}
LER = dict(sep=';', dtype=str, keep_default_na=False)
TOL_KG = 2.0          # o desenho arredonda cada linha: até 2 kg é arredondamento, não erro
TOL_VOL = 0.011       # duas casas decimais impressas


def f(x):
    try: return float(str(x).replace(',', '.'))
    except ValueError: return None


def ler(estrutura, codigo, nome):
    p = f'{SAIDA}/{estrutura}/{codigo}/{nome}.csv'
    return pd.read_csv(p, **LER) if os.path.exists(p) else pd.DataFrame()


def sem_revisao(codigo):
    return re.sub(r'-R\d$', '', codigo)


def tratar_armadura(df):
    """Só linhas válidas; POS reindexada por elemento (o dígito isolado erra no OCR); confere quant x unit = total."""
    if df.empty: return df
    df = df.copy()
    df['valida'] = df['valida'].astype(str) == 'True'
    df['pos_lida'] = df['pos']
    df['elemento'] = df['elemento'].where(df['elemento'].str.strip() != '', '(conjunto)')      # folha de caixa única: sem título de elemento
    chave = ['tabela', 'sub_tabela', 'elemento'] if 'sub_tabela' in df else ['tabela', 'elemento']
    df['pos'] = 0
    # a POS é a sequência 1..n entre as linhas que valem (a linha de ruído não conta)
    df.loc[df['valida'] | (df['total_cm'].astype(str) != ''), 'pos'] = 1
    df['pos'] = df.groupby(chave, sort=False)['pos'].cumsum()
    df['pos_reindexada'] = df['pos'].astype(str) != df['pos_lida']
    for c in ('bit_mm', 'quant', 'total_cm'): df[c] = df[c].map(f)
    df['unit_cm'] = df['unit_txt'].map(f)
    df['reparo'] = ''
    for i in df.index:
        u_txt = df.at[i, 'unit_txt']
        if u_txt and not re.search(r'\d', u_txt): continue      # --CORR-- / --VAR--: sem comprimento unitário para conferir
        if df.at[i, 'bit_mm'] is None and df.at[i, 'total_cm'] is None: continue
        q, u, t = df.at[i, 'quant'], df.at[i, 'unit_cm'], df.at[i, 'total_cm']
        q2, u2, t2, rep = reparar(None if pd.isna(q) else q, None if pd.isna(u) else u, None if pd.isna(t) else t)
        if rep:
            df.at[i, 'quant'], df.at[i, 'unit_cm'], df.at[i, 'total_cm'], df.at[i, 'reparo'] = q2, u2, t2, rep
            if q2 is not None and t2 is not None and u2 is not None: df.at[i, 'valida'] = True
    # barra de comprimento variável (--VAR--): sem unit para conferir, mas a média por barra não passa de 20 m (as variáveis do acervo
    # ficam entre 2 e 18 m; a corrida --CORR-- passa disso legitimamente e fica de fora). Total com dígito a mais (77355 para 33 barras
    # = 23 m) só é consertado se retirar UM dígito dá um único valor plausível; senão fica SUSPEITO, sem alterar o valor.
    for i in df.index:
        q, t, u_txt = df.at[i, 'quant'], df.at[i, 'total_cm'], df.at[i, 'unit_txt']
        if pd.isna(q) or pd.isna(t) or 'VAR' not in (u_txt or '').upper() or not q: continue
        if t / q > 2000:
            ts = str(int(t))
            cands = {int(ts[:k] + ts[k + 1:]) for k in range(len(ts)) if ts[:k] + ts[k + 1:]}
            ok = sorted(c for c in cands if 20 <= c / q <= 2000)
            df.at[i, 'reparo'] = (f'total lido {int(t)}→{ok[0]} (média {t / q:.0f} cm/barra > 20 m)' if len(ok) == 1
                                  else f'SUSPEITO: média {t / q:.0f} cm/barra > 20 m; candidatos {ok}')
            if len(ok) == 1: df.at[i, 'total_cm'] = float(ok[0])
    df['confere_quant_x_unit'] = [None if (pd.isna(u) or pd.isna(q) or pd.isna(t)) else abs(q * u - t) <= 1
                                  for q, u, t in zip(df['quant'], df['unit_cm'], df['total_cm'])]
    df['bit_valida'] = df['bit_mm'].isin(list(MASSA))
    df['comp_m'] = df['total_cm'] / 100
    df['valida_peso'] = df['total_cm'].notna() & df['bit_valida']          # o peso só precisa do total e da bitola
    df['peso_kg'] = [m * MASSA[b] if v else None for m, b, v in zip(df['comp_m'], df['bit_mm'], df['valida_peso'])]
    return df


def dist(a, b):
    """Distância de edição entre duas sequências de dígitos."""
    a, b = str(a), str(b)
    d = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        n = [i]
        for j, cb in enumerate(b, 1):
            n.append(min(d[j] + 1, n[j - 1] + 1, d[j - 1] + (ca != cb)))
        d = n
    return d[-1]


def reparar(q, u, t):
    """quant x unit = total (comprimentos em cm, inteiros). Devolve (q, u, t, reparo). Só conserta com distância de edição <= 2."""
    if None in (q, u, t) and sum(x is None for x in (q, u, t)) == 1:
        if t is None: return q, u, q * u, 'total=quant×unit'
        if q is None and u and t % u == 0: return t / u, u, t, 'quant=total/unit'
        if u is None and q and t % q == 0: return q, t / q, t, 'unit=total/quant'
        return q, u, t, ''
    if None in (q, u, t): return q, u, t, ''
    if q * u == t: return q, u, t, ''
    cand = []
    if dist(int(t), int(q * u)) <= 2: cand.append((dist(int(t), int(q * u)), 'total', (q, u, q * u)))
    if q and t % q == 0 and dist(int(u), int(t // q)) <= 2: cand.append((dist(int(u), int(t // q)), 'unit', (q, t / q, t)))
    if u and t % u == 0 and dist(int(q), int(t // u)) <= 2: cand.append((dist(int(q), int(t // u)), 'quant', (t / u, u, t)))
    if not cand: return q, u, t, ''
    cand.sort(key=lambda c: c[0])
    qq, uu, tt = cand[0][2]
    return qq, uu, tt, f'{cand[0][1]} lido {int(t) if cand[0][1]=="total" else (int(u) if cand[0][1]=="unit" else int(q))}→{int({"total": tt, "unit": uu, "quant": qq}[cand[0][1]])} (quant×unit=total)'


def tipo_prancha(cod):
    return 'ARMADURA' if 'ARMADURA' in cod else ('FORMARMAD' if 'FORMARMAD' in cod else 'FORMA')


def main():
    gab, gab_base = {}, {}          # nome do arquivo -> linhas do resumo (CXA01 e CXA02 aparecem 2x, em unidades diferentes)
    for r in GAB['linhas']:
        gab.setdefault(r['arquivo'], []).append(r)
        gab_base.setdefault(sem_revisao(r['arquivo']), []).append(r)

    def radical(txt):
        return {w[:7] for w in re.findall(r'[A-ZÇÃÕÉÊÁÍÓÚ]{5,}', (txt or '').upper().replace('_', ' '))}

    def escolher(linhas, estrutura):
        """Entre linhas de mesmo nome, a da unidade construtiva que tem a ver com a pasta (INTERLIGAÇÕES ~ CAIXAS DE INTERLIGAÇÃO)."""
        if not linhas: return None
        if len(linhas) == 1: return linhas[0]
        return max(linhas, key=lambda l: len(radical(l.get('unidade_construtiva')) & radical(estrutura)))
    escolhidas = set()
    reg_all, arm_all, aco_all, mat_all, met_all, div = [], [], [], [], [], []
    for pj in sorted(glob.glob(f'{SAIDA}/*/*/prancha.json')):
        info = json.load(open(pj)); est, cod = info['estrutura'], info['codigo_arquivo']
        arm = tratar_armadura(ler(est, cod, 'tabela_armadura'))
        aco = ler(est, cod, 'resumo_aco'); mat = ler(est, cod, 'resumo_materiais'); met = ler(est, cod, 'resumo_material_metalico')
        for df, acc in ((arm, arm_all), (aco, aco_all), (mat, mat_all), (met, met_all)):
            if not df.empty: acc.append(df)
        g, nota = escolher(gab.get(cod), est), ''
        if g is None:
            g = escolher(gab_base.get(sem_revisao(cod)), est)
            nota = ('revisão diferente: o resumo traz ' + g['arquivo'][-2:] + ', o PDF é ' + cod[-2:]) if g else 'sem linha no resumo geral'
        if g: escolhidas.add(g['ordem'])
        reg = {'estrutura': est, 'codigo_arquivo': cod, 'tipo': tipo_prancha(cod), 'linha_no_resumo': 'sim' if g else 'não', 'nota': nota, 'erro': info['erro']}
        # ---- forma/concreto (tabela RESUMO DOS MATERIAIS da prancha)
        tot = mat[mat['divisao'].str.upper().str.startswith('TOTAL')] if not mat.empty else mat
        reg['concreto_m3'] = f(tot.iloc[0]['volume_m3']) if len(tot) else None
        reg['forma_m2'] = f(tot.iloc[0]['area_forma_m2']) if len(tot) else None
        # física do RESUMO DOS MATERIAIS: a soma das divisões fecha com a linha TOTAL (volume e área)
        if len(tot) and not mat.empty:
            div_ = mat[(mat['tabela'] != '-1') & ~mat['divisao'].str.upper().str.startswith('TOTAL') & (mat['divisao'] != '')]
            sv, sa_ = div_['volume_m3'].map(f).sum(), div_['area_forma_m2'].map(f).sum()
            reg['soma_divisoes_fecha_concreto'] = abs(sv - (reg['concreto_m3'] or 0)) <= 0.03 if reg['concreto_m3'] is not None else None
            reg['soma_divisoes_fecha_forma'] = abs(sa_ - (reg['forma_m2'] or 0)) <= 0.03 if reg['forma_m2'] is not None else None
        for k in ('LASTRO', 'ENCHIMENTO'):
            v = mat[mat['divisao'] == k] if not mat.empty else mat
            reg[k.lower() + '_m3'] = f(v.iloc[0]['volume_m3']) if len(v) else None
        # ---- aço: (a) soma das tabelas de armadura, (b) RESUMO AÇO impresso na prancha, (c) resumo geral
        calc_kg, calc_m = {}, {}
        if not arm.empty:
            ok = arm[arm['valida_peso']]
            for b, sub in ok.groupby('bit_mm'):
                calc_kg[b] = sub['peso_kg'].sum(); calc_m[b] = sub['comp_m'].sum()
        pr_kg, pr_m, impresso = {}, {}, None
        if not aco.empty:
            for _, r in aco.iterrows():
                if r['bit_txt'] == 'TOTAL': impresso = (impresso or 0) + (f(r['peso_kg']) or 0)
                else:
                    b, p, c = f(r.get('bit_mm')), f(r.get('peso_kg')), f(r.get('comp_m'))
                    if b in MASSA and p is not None:
                        pr_kg[b] = pr_kg.get(b, 0) + p; pr_m[b] = pr_m.get(b, 0) + (c or 0)
        soma_prancha = sum(pr_kg.values()) if pr_kg else None
        reg['aco_tabelas_kg'] = round(sum(calc_kg.values())) if calc_kg else None
        reg['aco_resumo_prancha_kg'] = soma_prancha
        reg['aco_peso_total_impresso_kg'] = impresso
        # o 'Peso Total' impresso é lido por OCR: se não fecha com a soma das linhas do próprio RESUMO AÇO, vale a soma
        reg['peso_total_impresso_fecha'] = None if (impresso is None or soma_prancha is None) else abs(impresso - soma_prancha) <= TOL_KG + len(pr_kg)
        # consenso: número só é fato com duas fontes independentes (Σ tabelas de armadura, Σ linhas do RESUMO AÇO, Peso Total impresso)
        fontes = {'tabelas': reg['aco_tabelas_kg'], 'resumo_linhas': soma_prancha, 'peso_total': impresso}
        tol = TOL_KG + max(len(pr_kg), 1)
        pares = [(a, b) for a, b in (('tabelas', 'resumo_linhas'), ('tabelas', 'peso_total'), ('resumo_linhas', 'peso_total'))
                 if fontes[a] is not None and fontes[b] is not None and abs(fontes[a] - fontes[b]) <= tol]
        if pares:
            vals = [fontes[x] for p in pares for x in p]
            reg['aco_adotado_kg'] = sorted(vals)[len(vals) // 2]
            reg['aco_consenso'] = '+'.join(sorted({x for p in pares for x in p}))
        else:
            reg['aco_adotado_kg'] = impresso if impresso is not None else reg['aco_tabelas_kg']
            reg['aco_consenso'] = 'sem consenso'

        reg['linhas_armadura'] = int(arm['valida_peso'].sum()) if not arm.empty else 0
        reg['linhas_descartadas'] = int((~arm['valida_peso']).sum()) if not arm.empty else 0
        reg['linhas_reparadas'] = int((arm['reparo'] != '').sum()) if not arm.empty else 0
        reg['linhas_quant_x_unit_falham'] = int((arm['confere_quant_x_unit'] == False).sum()) if not arm.empty else 0  # noqa: E712
        reg['pos_reindexadas'] = int(arm['pos_reindexada'].sum()) if not arm.empty else 0
        for b, col in COL_BIT.items():
            reg['tabelas_' + col] = None if b not in calc_kg else round(calc_kg[b])
            reg['prancha_' + col] = pr_kg.get(b)
            # física: comprimento somado nas tabelas x comprimento do RESUMO AÇO da prancha
            if b in calc_m and b in pr_m: reg['dm_' + col] = round(calc_m[b] - pr_m[b], 1)
        if g:
            for k in ['concreto_m3', 'forma_m2', 'enchimento_m3', 'lastro_m3', 'aco_total_kg'] + list(COL_BIT.values()):
                reg['resumo_' + k] = g.get(k)
        reg['tabelas_com_aco_zero_lidas'] = bool(tipo_prancha(cod) != 'FORMA' and reg['linhas_armadura'] == 0 and info.get('n_resumo_aco', 0) == 0)
        reg['segundos'] = info['segundos']
        reg_all.append(reg)
        # ---- divergências (cada grandeza x resumo geral), com a causa provável
        def cmp(grandeza, lido, ref, tol, origem):
            if g is None: return
            if lido is None and ref is None: return
            if lido is None:
                div.append({'estrutura': est, 'codigo_arquivo': cod, 'grandeza': grandeza, 'extraido': None, 'resumo_geral': ref, 'dif': None, 'origem': origem,
                            'classe': 'nao_extraido', 'nota': nota}); return
            r0 = ref if ref is not None else 0.0
            d = round(lido - r0, 3)
            if abs(d) <= tol: return
            div.append({'estrutura': est, 'codigo_arquivo': cod, 'grandeza': grandeza, 'extraido': lido, 'resumo_geral': ref, 'dif': d, 'origem': origem,
                        'classe': 'revisao' if nota.startswith('revis') else 'diferenca', 'nota': nota})
        if g:
            tp = tipo_prancha(cod)
            if tp != 'ARMADURA':
                cmp('concreto_m3', reg['concreto_m3'], g.get('concreto_m3'), TOL_VOL, 'resumo_materiais da prancha')
                cmp('forma_m2', reg['forma_m2'], g.get('forma_m2'), TOL_VOL, 'resumo_materiais da prancha')
                cmp('lastro_m3', reg['lastro_m3'], g.get('lastro_m3'), TOL_VOL, 'barra LASTRO')
                cmp('enchimento_m3', reg['enchimento_m3'], g.get('enchimento_m3'), TOL_VOL, 'barra ENCHIMENTO')
            if tp != 'FORMA':
                cmp('aco_total_kg', reg['aco_adotado_kg'], g.get('aco_total_kg'), TOL_KG, 'RESUMO AÇO/Peso Total')
                cmp('aco_total_kg[soma das tabelas de armadura]', reg['aco_tabelas_kg'], g.get('aco_total_kg'), TOL_KG, 'tabelas de armadura (Σ comp × kg/m)')
                for b, col in COL_BIT.items():
                    # por bitola: a soma das tabelas de armadura é a fonte completa; o RESUMO AÇO impresso só entra quando foi lido
                    cmp('aço ' + col, round(calc_kg[b]) if b in calc_kg else None, g.get(col), 3.0, 'tabelas de armadura (Σ comp × kg/m)')
                    if b in pr_kg: cmp('aço ' + col, pr_kg[b], g.get(col), TOL_KG, 'RESUMO AÇO da prancha')
    pd.DataFrame(reg_all).to_csv(f'{SAIDA}/consolidado/conferencia_por_prancha.csv', sep=';', index=False) if os.path.isdir(f'{SAIDA}/consolidado') else None
    os.makedirs(f'{SAIDA}/consolidado', exist_ok=True)
    pd.DataFrame(reg_all).to_csv(f'{SAIDA}/consolidado/conferencia_por_prancha.csv', sep=';', index=False)
    pd.DataFrame(div).to_csv(f'{SAIDA}/consolidado/divergencias.csv', sep=';', index=False)
    for nome, acc in (('tabela_armadura', arm_all), ('resumo_aco', aco_all), ('resumo_materiais', mat_all), ('resumo_material_metalico', met_all)):
        if acc: pd.concat(acc).to_csv(f'{SAIDA}/consolidado/{nome}.csv', sep=';', index=False)
    # ---- rastreabilidade: uma linha por estrutura x prancha x quantidade, com a tabela de origem e o valor do resumo geral
    longo, UN = [], {'concreto_m3': 'm³', 'forma_m2': 'm²', 'lastro_m3': 'm³', 'enchimento_m3': 'm³', 'aco_adotado_kg': 'kg'}
    for r in reg_all:
        pj = json.load(open(f"{SAIDA}/{r['estrutura']}/{r['codigo_arquivo']}/prancha.json"))
        caixa = {t: [c['caixa_pt'] for c in pj['caixas'] if c['tipo'] == t] for t in ('resumo_materiais', 'armadura', 'resumo_aco')}
        quant = [('concreto_m3', 'resumo_materiais', 'concreto_m3'), ('forma_m2', 'resumo_materiais', 'forma_m2'), ('lastro_m3', 'resumo_materiais', 'lastro_m3'),
                 ('enchimento_m3', 'resumo_materiais', 'enchimento_m3'), ('aco_adotado_kg', 'armadura+resumo_aco', 'aco_total_kg')]
        quant += [(f'tabelas_{col}', 'armadura', col) for col in COL_BIT.values()]
        for chave, origem, col_resumo in quant:
            v = r.get(chave)
            if v is None or pd.isna(v): continue
            ref = r.get('resumo_' + col_resumo)
            tol = TOL_VOL if chave.endswith(('_m3', '_m2')) else (TOL_KG if chave == 'aco_adotado_kg' else 3.0)
            longo.append({'estrutura': r['estrutura'], 'codigo_arquivo': r['codigo_arquivo'], 'quantidade': chave.replace('tabelas_', 'aco_'),
                          'valor_extraido': v, 'unidade': UN.get(chave, 'kg'), 'tabela_de_origem': origem,
                          'caixa_pt': json.dumps(sum((caixa[o] for o in origem.split('+')), [])), 'valor_resumo_geral': ref if ref is not None and not pd.isna(ref) else None,
                          'confere': None if (ref is None or pd.isna(ref)) else abs(v - ref) <= tol,
                          'consenso': r.get('aco_consenso') if chave == 'aco_adotado_kg' else None})
    pd.DataFrame(longo).to_csv(f'{SAIDA}/consolidado/quantitativos_por_estrutura.csv', sep=';', index=False)
    por = pd.DataFrame(reg_all).groupby('estrutura').agg(pranchas=('codigo_arquivo', 'count'), concreto_m3=('concreto_m3', 'sum'), forma_m2=('forma_m2', 'sum'),
                                                           lastro_m3=('lastro_m3', 'sum'), enchimento_m3=('enchimento_m3', 'sum'), aco_kg=('aco_adotado_kg', 'sum')).reset_index()
    ref = pd.DataFrame([{'estrutura': r['estrutura'], **{k: r.get('resumo_' + k) for k in ('concreto_m3', 'forma_m2', 'lastro_m3', 'enchimento_m3', 'aco_total_kg')}}
                        for r in reg_all if r['linha_no_resumo'] == 'sim']).groupby('estrutura').sum(numeric_only=True).add_prefix('resumo_').reset_index()
    por.merge(ref, on='estrutura', how='left').to_csv(f'{SAIDA}/consolidado/totais_por_estrutura.csv', sep=';', index=False)
    # ---- cobertura: o que o resumo geral lista x o que existe na pasta do Drive
    tem = {r['codigo_arquivo'] for r in reg_all}; tem_base = {sem_revisao(c) for c in tem}
    cob = []
    for r in GAB['linhas']:
        achou = 'sim' if r['ordem'] in escolhidas and r['arquivo'] in tem else ('sim (outra revisão)' if r['ordem'] in escolhidas else 'não')
        cob.append({'ordem': r['ordem'], 'folha': r['folha'], 'unidade_construtiva': r.get('unidade_construtiva'), 'arquivo_no_resumo': r['arquivo'], 'pdf_na_pasta': achou})
    cob += [{'ordem': None, 'arquivo_no_resumo': '', 'pdf_na_pasta': c + ' (sem linha no resumo)'} for c in sorted(tem) if c not in gab and sem_revisao(c) not in gab_base]
    pd.DataFrame(cob).to_csv(f'{SAIDA}/consolidado/cobertura_resumo_x_pasta.csv', sep=';', index=False)
    print(len(reg_all), 'pranchas;', len(div), 'divergências')


if __name__ == '__main__':
    main()
