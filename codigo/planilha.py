"""A planilha XLSX da entrega, só com a biblioteca padrão (zipfile + XML): abre no Excel e no LibreOffice com número
como número, uma aba por tabela, o cabeçalho congelado e com filtro, e a célula a conferir em amarelo. Sem openpyxl
nem xlsxwriter: o .venv do mini não precisa de pacote novo.

    planilha.escrever(caminho, [('Resumo', ['Arquivo', 'Título'], [['A.pdf', 'ADUTORA'], ['B.pdf', ('?', 'conferir')]])])

Cada célula é um valor (texto, número, None) ou (valor, 'conferir'): a segunda forma pinta a célula de amarelo.
"""
import re
import zipfile
from xml.sax.saxutils import escape

ESTILOS = {'normal': 0, 'cabecalho': 1, 'conferir': 2}
CONTROLE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')  # o XML não aceita; o texto do PDF às vezes traz

STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
          '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
          '<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
          '<fill><patternFill patternType="solid"><fgColor rgb="FFD9E1F2"/><bgColor indexed="64"/></patternFill></fill>'
          '<fill><patternFill patternType="solid"><fgColor rgb="FFFFEB9C"/><bgColor indexed="64"/></patternFill></fill></fills>'
          '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
          '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
          '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
          '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
          '<xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyFill="1"/></cellXfs>'
          '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')


def coluna(indice):
    """0 → A, 25 → Z, 26 → AA."""
    nome = ''
    indice += 1
    while indice:
        indice, resto = divmod(indice - 1, 26)
        nome = chr(65 + resto) + nome
    return nome


def celula(referencia, valor, estilo):
    s = ESTILOS[estilo]
    if valor is None or valor == '':
        return f'<c r="{referencia}" s="{s}"/>' if s else ''
    if isinstance(valor, bool):
        valor = 'sim' if valor else 'não'
    if isinstance(valor, (int, float)):
        return f'<c r="{referencia}" s="{s}"><v>{valor}</v></c>'
    texto = escape(CONTROLE.sub('', str(valor)))[:32000]
    return f'<c r="{referencia}" s="{s}" t="inlineStr"><is><t xml:space="preserve">{texto}</t></is></c>'


def aba(cabecalho, linhas):
    """O XML de uma aba: o cabeçalho em negrito, congelado e com filtro; a largura das colunas pelo conteúdo."""
    todas = [[(c, 'cabecalho') for c in cabecalho]] + [[c if isinstance(c, tuple) else (c, 'normal') for c in linha] for linha in linhas]
    largura = [min(60, max(8, *(len(str(l[i][0] if i < len(l) and l[i][0] is not None else '')) + 2 for l in todas)))
               for i in range(len(cabecalho))]
    cols = ''.join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(largura))
    corpo = ''.join(f'<row r="{n}">' + ''.join(celula(f'{coluna(i)}{n}', valor, estilo) for i, (valor, estilo) in enumerate(linha)) + '</row>'
                    for n, linha in enumerate(todas, 1))
    ultima = f'{coluna(max(len(cabecalho), 1) - 1)}{len(todas)}'
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            f'<cols>{cols}</cols><sheetData>{corpo}</sheetData><autoFilter ref="A1:{ultima}"/></worksheet>')


def nome_de_aba(nome, usados):
    """Até 31 caracteres, sem []:*?/\\, sem repetir."""
    base = re.sub(r'[\[\]:*?/\\]', ' ', nome).strip()[:31] or 'Aba'
    candidato, n = base, 2
    while candidato.lower() in usados:
        candidato, n = f'{base[:28]} {n}', n + 1
    usados.add(candidato.lower())
    return candidato


def escrever(caminho, abas):
    """abas = [(nome, cabecalho, linhas)]: grava o XLSX em caminho (substitui)."""
    usados = set()
    nomes = [nome_de_aba(nome, usados) for nome, _, _ in abas]
    with zipfile.ZipFile(caminho, 'w', zipfile.ZIP_DEFLATED) as zipado:
        zipado.writestr('[Content_Types].xml',
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                        '<Default Extension="xml" ContentType="application/xml"/>'
                        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                        + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                                  'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                                  for i in range(1, len(abas) + 1)) + '</Types>')
        zipado.writestr('_rels/.rels',
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                        'Target="xl/workbook.xml"/></Relationships>')
        zipado.writestr('xl/workbook.xml',
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                        + ''.join(f'<sheet name="{escape(nome, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>' for i, nome in enumerate(nomes, 1))
                        + '</sheets>'
                        + '</workbook>')
        zipado.writestr('xl/_rels/workbook.xml.rels',
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                        + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                                  f'Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(abas) + 1))
                        + f'<Relationship Id="rId{len(abas) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
                          'Target="styles.xml"/></Relationships>')
        zipado.writestr('xl/styles.xml', STYLES)
        for i, (_, cabecalho, linhas) in enumerate(abas, 1):
            zipado.writestr(f'xl/worksheets/sheet{i}.xml', aba(cabecalho, linhas))
    return caminho


def ler(caminho):
    """{aba: [[valor, …], …]} de um XLSX escrito por escrever (para os testes; texto e número, sem estilo)."""
    import xml.etree.ElementTree as arvore
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(caminho) as zipado:
        livro = arvore.fromstring(zipado.read('xl/workbook.xml'))
        nomes = [s.get('name') for s in livro.find('m:sheets', ns)]
        saida = {}
        for i, nome in enumerate(nomes, 1):
            folha = arvore.fromstring(zipado.read(f'xl/worksheets/sheet{i}.xml'))
            linhas = []
            for linha in folha.find('m:sheetData', ns):
                valores = {}
                for c in linha:
                    indice = sum((ord(ch) - 64) * 26 ** p for p, ch in enumerate(reversed(re.match(r'[A-Z]+', c.get('r')).group()))) - 1
                    texto, numero = c.find('m:is/m:t', ns), c.find('m:v', ns)
                    valores[indice] = (texto.text if texto is not None else float(numero.text) if numero is not None else None,
                                       {'0': 'normal', '1': 'cabecalho', '2': 'conferir'}[c.get('s', '0')])
                linhas.append([valores.get(j, (None, 'normal')) for j in range(max(valores, default=-1) + 1)])
            saida[nome] = linhas
        return saida
