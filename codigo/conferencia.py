"""A IA local no carimbo e na família, sempre conferida por código (notas/plano_projeto.md §11.1: um valor de IA só é
aceito com presença, concordância e rastro).

O qwen3 (Ollama) e o Foundation Model da Apple preenchem o esquema do carimbo a partir do texto lido do recorte — a
camada de texto do PDF ou, na folha sem texto real, o OCR do Vision e do glm-ocr. Cada valor passa pelas provas:
**presença** (o valor de IA está no texto lido; o que não está é `inventado` e não conta) e **concordância** (duas
fontes de natureza diferente — rótulo-âncora do código, regra sobre os dois OCRs, qwen3, Apple FM — dizem o mesmo:
`confirmado`; uma só: `um_leitor`; discordam: `divergente`). Pergunta fechada: a família só se escolhe numa lista.
"""
import json
import re
import unicodedata

import ia


def normalizar(valor):
    """Para comparar leitores: NFKC, maiúsculas, sem espaço, vírgula decimal como ponto."""
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', valor or '')).upper().replace(',', '.')


def recorte(caminho, pagina, caixa, dpi, destino):
    """A caixa da folha (mm de papel, origem embaixo à esquerda) renderizada a `dpi` em PNG."""
    import pypdfium2 as pdfium
    PT = 72 / 25.4
    documento = pdfium.PdfDocument(caminho)
    folha = documento[pagina - 1]
    largura, altura = folha.get_size()
    folha.render(scale=dpi / 72, crop=(caixa['x0'] * PT, caixa['y0'] * PT, largura - caixa['x1'] * PT, altura - caixa['y1'] * PT)).to_pil().save(destino)
    documento.close()
    return destino


def ocr_duplo(imagem):
    """A mesma imagem lida pelo Vision e pelo glm-ocr: os textos e, de quem não leu, o motivo."""
    leituras, erros = {}, {}
    leitores = {'vision': ia.vision, 'glm_ocr': lambda c: ia.ocr_glm(c, ia.ler_prompt('imagem_ocr', regras=False))}
    for leitor, ler in leitores.items():
        if leitor == 'vision' and not ia.instalado('Vision'):
            erros[leitor] = 'Vision ausente: .venv/bin/pip install pyobjc-framework-Vision'
            continue
        try:
            leituras[leitor] = ler(imagem)
        except (RuntimeError, OSError) as falha:
            erros[leitor] = str(falha)[:300]
    return leituras, erros


def motores_de_texto(prompt, esquema):
    """Os motores de texto do mini que respondem a um esquema: o qwen3 (Ollama) e, no macOS com o SDK, o Apple FM."""
    motores = {'qwen3': lambda: ia.ollama(ia.configuracao('extratores')['modelos']['qwen3'], prompt, esquema)}
    if ia.instalado('apple_fm_sdk'):
        motores['apple'] = lambda: ia.apple(prompt, esquema)
    return motores


def campos_por_ia(texto):
    """O carimbo no esquema pelos motores de texto, cada um à parte: {motor: {campo: valor}} e, de quem falhou, o motivo."""
    CAMPOS = ia.configuracao('prancha')['carimbo']['campos_ia']
    prompt = ia.ler_prompt('prancha_carimbo').replace('{texto}', texto[:4000])
    ESQUEMA = {'type': 'object', 'required': CAMPOS, 'properties': {c: {'type': 'string'} for c in CAMPOS}}
    respostas, erros = {}, {}
    for motor, chamar in motores_de_texto(prompt, ESQUEMA).items():
        try:
            resposta = json.loads(chamar()[0])
            respostas[motor] = {c: str(resposta.get(c) or '').strip() for c in CAMPOS}
        except (RuntimeError, ValueError, OSError) as falha:
            erros[motor] = str(falha)[:200]
    return respostas, erros


def provas(candidatos, lidos):
    """Cada campo com o valor aceito, o status e as fontes. `candidatos`: {campo: {fonte: valor}}; `lidos`: os textos do
    recorte. Código e regra leram o texto e valem como fonte; o valor de IA ausente do texto lido é inventado."""
    textos = [normalizar(t) for t in lidos if t]
    saida = {}
    for campo, fontes in candidatos.items():
        validas = {f: v for f, v in fontes.items() if v and (f in ('codigo', 'regras') or any(normalizar(v) in t for t in textos))}
        grupos = {}
        for fonte, valor in validas.items():
            grupos.setdefault(normalizar(valor), []).append(fonte)
        maior = max(grupos.values(), key=len, default=[])
        status = 'vazio' if not validas else 'confirmado' if len(maior) >= 2 else 'um_leitor' if len(validas) == 1 else 'divergente'
        valor = validas[maior[0]] if status in ('confirmado', 'um_leitor') else validas.get('codigo', '')
        saida[campo] = {'valor': valor, 'status': status, 'fontes': {f: v for f, v in fontes.items() if v},
                        'inventado': sorted(f for f, v in fontes.items() if v and f not in validas)}
    return saida


def carimbo_conferido(lido, ocr, com_ia):
    """O carimbo de uma folha, campo a campo, pelas provas: o rótulo-âncora do código (texto real), a regra sobre os
    dois OCRs (sem texto real) e, com a IA ligada, o qwen3 e o Apple FM sobre o texto lido. Devolve os campos e o
    motivo de quem não respondeu."""
    REGRAS = ia.configuracao('prancha')['carimbo']['regras_ocr']
    lidos = [lido['texto'], *ocr.values()]
    candidatos = {campo: {'codigo': valor} for campo, valor in lido['campos'].items()}
    if len(ocr) == 2:  # a regra só vale quando o mesmo valor aparece nos dois leitores
        for campo, padrao in REGRAS.items():
            comuns = [v for v in re.findall(padrao, ocr['vision']) if any(normalizar(v) == normalizar(g) for g in re.findall(padrao, ocr['glm_ocr']))]
            if comuns and not candidatos.get(campo, {}).get('codigo'):
                candidatos.setdefault(campo, {})['regras'] = comuns[0]
    respostas, erros = campos_por_ia('\n'.join(t for t in lidos if t)) if com_ia else ({}, {})
    for motor, campos in respostas.items():
        for campo, valor in campos.items():
            candidatos.setdefault(campo, {})[motor] = valor
    return provas(candidatos, lidos), erros


def desempatar(texto):
    """Família sem regra que case: os motores de texto escolhem entre as opções pelo texto do carimbo; vale só se todo
    motor chamado escolheu a mesma opção da lista — erro ou discordância deixa `indefinida`."""
    FAMILIAS = ia.configuracao('prancha')['familias']
    opcoes = FAMILIAS['ordem']
    prompt = ia.ler_prompt('prancha_familia').replace('{opcoes}', ', '.join(opcoes)).replace('{texto}', texto[:3000])
    ESQUEMA = {'type': 'object', 'required': ['familia'], 'properties': {'familia': {'type': 'string', 'enum': [*opcoes, 'indefinida']}}}
    votos = {}
    for motor, chamar in motores_de_texto(prompt, ESQUEMA).items():
        try:
            votos[motor] = json.loads(chamar()[0]).get('familia', '')
        except (RuntimeError, ValueError, OSError) as falha:
            votos[motor] = f'erro: {falha}'[:120]
    escolhida = next(iter(set(votos.values()))) if len(set(votos.values())) == 1 and set(votos.values()) <= set(opcoes) else 'indefinida'
    return {'familia': escolhida, 'grupo': FAMILIAS['grupo'].get(escolhida, ''), 'familia_votos': votos,
            'familia_origem': 'ia_concordante' if escolhida != 'indefinida' else 'ia_sem_acordo'}
