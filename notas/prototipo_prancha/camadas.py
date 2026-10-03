"""Protótipo (fora do repositório): separa uma prancha PDF do AutoCAD por camada (OCG).

Cada bloco `/OC /MCn BDC … EMC` do fluxo de conteúdo pertence a uma camada; o que está fora
de bloco vai para `(sem camada)`. Grava um PDF por camada, com a geometria dela e nada mais,
para o pdfplumber medir e o pypdfium2 renderizar. Teste de viabilidade do plano_projeto.md.
"""
import sys, re, json, pathlib
import pikepdf, pdfplumber, pypdfium2 as pdfium

CONSTRUCAO = {'m', 'l', 'c', 'v', 'y', 'h', 're'}
PINTURA = {'m', 'l', 'c', 'v', 'y', 'h', 're', 'S', 's', 'f', 'F', 'f*', 'B', 'B*', 'b', 'b*', 'n', 'Do', 'Tj', 'TJ', "'", '"', 'sh'}


def nomes_camadas(pagina):
    props = pagina.Resources.get('/Properties') or {}
    return {str(chave): str(valor.Name) for chave, valor in props.items() if '/Name' in valor}


def blocos_por_camada(pdf):
    pagina = pdf.pages[0]
    nomes = nomes_camadas(pagina)
    operacoes = pikepdf.parse_content_stream(pagina)
    camada_de = []
    atual = None
    for operandos, operador in operacoes:
        nome = str(operador)
        if nome == 'BDC' and str(operandos[0]) == '/OC':
            atual = nomes.get(str(operandos[1]), str(operandos[1]))
        camada_de.append(atual)
        if nome == 'EMC':
            atual = None
    return operacoes, camada_de


def isolar(caminho, camada, destino):
    pdf = pikepdf.open(caminho)
    operacoes, camada_de = blocos_por_camada(pdf)
    alvo = None if camada == '(sem camada)' else camada
    mantidas, caminho_aberto = [], []
    for (operandos, operador), dono in zip(operacoes, camada_de):
        nome = str(operador)
        if nome in CONSTRUCAO or nome in ('W', 'W*'):
            caminho_aberto.append(((operandos, operador), dono))
            continue
        if nome in PINTURA and nome not in CONSTRUCAO:
            e_recorte = any(str(op) in ('W', 'W*') for (_, op), _ in caminho_aberto)
            if e_recorte or dono == alvo:  # recorte (clip) vale para todas as camadas
                mantidas += [item for item, _ in caminho_aberto] + [(operandos, operador)]
            caminho_aberto = []
            continue
        mantidas.append((operandos, operador))
    pdf.pages[0].Contents = pdf.make_stream(pikepdf.unparse_content_stream(mantidas))
    pdf.save(destino)


def medir(caminho_pdf):
    pagina = pdfplumber.open(caminho_pdf).pages[0]
    objetos = pagina.lines + pagina.curves + pagina.rects
    if not objetos and not pagina.images:
        return None
    caixas = [(o['x0'], o['top'], o['x1'], o['bottom']) for o in objetos] + \
             [(i['x0'], i['top'], i['x1'], i['bottom']) for i in pagina.images]
    return {'objetos': len(objetos), 'imagens': len(pagina.images), 'caracteres': len(pagina.chars),
            'caixa_pt': [round(min(c[0] for c in caixas)), round(min(c[1] for c in caixas)),
                         round(max(c[2] for c in caixas)), round(max(c[3] for c in caixas))]}


def separar(caminho, pasta):
    pasta = pathlib.Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    pdf = pikepdf.open(caminho)
    _, camada_de = blocos_por_camada(pdf)
    camadas = sorted({c for c in camada_de if c}) + ['(sem camada)']
    resumo = {}
    for camada in camadas:
        arquivo = pasta / (re.sub(r'[^\w-]+', '_', camada) + '.pdf')
        isolar(caminho, camada, arquivo)
        medida = medir(arquivo)
        if medida is None:
            arquivo.unlink()
            continue
        pdfium.PdfDocument(str(arquivo))[0].render(scale=50 / 72).to_pil().save(arquivo.with_suffix('.png'))
        resumo[camada] = medida
    (pasta / 'camadas.json').write_text(json.dumps(resumo, ensure_ascii=False, indent=1))
    return resumo


if __name__ == '__main__':
    for camada, medida in separar(sys.argv[1], sys.argv[2]).items():
        print(f"{camada:45s} {medida['objetos']:6d} obj {medida['imagens']} img {medida['caracteres']:4d} car  caixa {medida['caixa_pt']}")
