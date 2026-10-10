"""Gabarito: lê o 'Resumo de Materiais' (texto real) e atribui cada valor à coluna pelo x do cabeçalho."""
import re, sys, json
import pdfplumber

# centros (pt) das colunas, medidos nos rótulos do cabeçalho da folha 1
COLS = {
    "concreto_m3": 462, "forma_m2": 515, "enchimento_m3": 576, "lastro_m3": 630, "imperm_m2": 695,
    "ca60_4_2": 753, "ca60_5_0": 801,
    "ca50_6_3": 849, "ca50_8_0": 897, "ca50_10_0": 948, "ca50_12_5": 999,
    "ca50_16_0": 1047, "ca50_20_0": 1095, "aco_total_kg": 1151,
}
RE_ARQ = re.compile(r"^\d{3}-SAA-\d{4}-\d{4}-(PBES|IMPE)-DE-0000[A-Z0-9]+-R\d$")

def num(t):
    return float(t.replace(".", "").replace(",", ".")) if "," in t else float(t)

def ler(pdf_path):
    linhas, totais = [], None
    with pdfplumber.open(pdf_path) as pdf:
        for pg, p in enumerate(pdf.pages, 1):
            ws = p.extract_words()
            arqs = [w for w in ws if RE_ARQ.match(w["text"])]
            for a in arqs:
                y = a["top"]
                reg = {"arquivo": a["text"], "pagina_resumo": pg}
                for w in ws:
                    if abs(w["top"] - y) < 4 and w["x0"] > a["x1"] and re.fullmatch(r"-?[\d.]+,\d\d", w["text"]):
                        cx = (w["x0"] + w["x1"]) / 2
                        col = min(COLS, key=lambda c: abs(COLS[c] - cx))
                        if abs(COLS[col] - cx) > 30:
                            col = "?x%d" % cx
                        reg[col] = num(w["text"])
                linhas.append(reg)
            tot = [w for w in ws if w["text"] == "I"]
            for w in ws:
                if w["text"] == "T":
                    y = w["top"]
                    vals = [x for x in ws if abs(x["top"] - y) < 4 and re.fullmatch(r"-?[\d.]+,\d\d", x["text"])]
                    if vals:
                        t = {}
                        for x in vals:
                            cx = (x["x0"] + x["x1"]) / 2
                            t[min(COLS, key=lambda c: abs(COLS[c] - cx))] = num(x["text"])
                        totais = t
    return linhas, totais

if __name__ == "__main__":
    l, t = ler(sys.argv[1])
    print(len(l), "arquivos"); print("TOTAIS impressos:", t)
    json.dump({"linhas": l, "totais": t}, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
