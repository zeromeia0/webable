#!/usr/bin/env python3
"""
create_relatorio — gera o "Relatório de Gastos" (PDF) a partir de um
Extracto Integrado do Crédito Agrícola (PDF).

Uso:
    ./create_relatorio Extracto_Integrado_Outubro_2026.pdf
    ./create_relatorio Extracto.pdf -o ~/money/Relatorio.pdf
    ./create_relatorio Extracto.pdf --list      # só mostra os movimentos e categorias (debug)

O ficheiro está organizado em secções (procura por "SECÇÃO"):
    1. CONFIGURAÇÃO      -> nomes (tu, família), regras de categorias, nomes bonitos
    2. LEITURA DO PDF    -> extrai texto e movimentos do extracto
    3. CLASSIFICAÇÃO     -> põe cada movimento numa categoria
    4. CÁLCULOS          -> totais, entradas, investimentos, saldo
    5. GRÁFICOS          -> matplotlib (3 imagens)
    6. PDF               -> reportlab (layout do relatório)
Vê o README.md (secção "create_relatorio") para resolver problemas comuns.
"""
from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date

# =============================================================================
# SECÇÃO 1 — CONFIGURAÇÃO  (é aqui que mexes 95% das vezes)
# =============================================================================

# O teu nome como aparece nas transferências IPS que fazes para ti próprio
# (ex.: "IPS/R3185199798-VINICIUS VAZ CA"). Estas entradas são descontadas do
# investimento na Revolut, não contam como entrada.
OWNER_MATCH = "VINICIUS VAZ"
OWNER_FULL_NAME = "VINICIUS VAZ CASCAIS"

# Família: transferências que ENVIAS para esta pessoa = "Ajuda familiar";
# transferências que RECEBES dela = "Família (Jeslin)".
FAMILY_MATCH = "JESLIN"
FAMILY_FULL_NAME = "Jeslin Ticiane Vaz"
FAMILY_SHORT = "Jeslin"

# Investimento: transferências de saída que contêm isto vão para a Revolut.
INVEST_MATCH = "AFT VISA REVOLUT"

# Regras de categorias para COMPRAS (cartão). A primeira regra que bater ganha.
# Cada regra: (categoria, [palavras a procurar no descritivo, em MAIÚSCULAS]).
# Para recategorizar uma loja "por identificar", acrescenta a palavra aqui.
CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("Saúde", ["FARMACIA", "FARMÁCIA", "CLINICA", "CLÍNICA", "HOSPITAL", "CUF ",
               "LUSIADAS", "DENTIST", "OPTICA", "WELLS", "MEDICO", "MÉDICO"]),
    ("Restauração", ["BK", "BURGER", "MCDONALD", "KFC", "TELEPIZZA", "PIZZA",
                     "SUSHI", "SAKURARIO", "ESCALA25", "GO CHEF", "BAR ", "CAFE",
                     "CAFÉ", "PASTELARIA", "RESTAURANTE", "TRIGO", "A S AVEIRAS",
                     "PORTOFINO", "CANTINHO", "KIBO", "UBER EATS", "GLOVO",
                     "STARBUCKS", "H3", "PADARIA", "REST "]),
    ("Supermercado", ["CONTINENTE", "CONTI ", "PINGO DOCE", "MEU SUPER", "AUCHAN",
                      "LIDL", "ALDI", "MINIPRECO", "MERCADONA", "INTERMARCHE",
                      "SPAR"]),
    ("Transportes", ["BOLT", "LIME", "UBER", "CARRIS", "METROPOLITANO", "CP ",
                     "COMBOIOS", "FERTAGUS", "NAVEGANTE", "GALP", "REPSOL",
                     "PRIO", "BP "]),
    ("Tecnologia / Subscrições", ["ANTHROPIC", "CLOUDFLARE", "OPENAI", "GOOGLE",
                                  "APPLE", "SPOTIFY", "NETFLIX", "GITHUB",
                                  "MICROSOFT", "AMAZON PRIME", "DISNEY"]),
    ("Lazer e cultura", ["CINE", "TICKET LINE", "TICKETLINE", "FREETOUR", "MUSEU",
                         "TEATRO", "BOL ", "FNAC"]),
    ("Serviços e documentos", ["CONSULADO", "CTT", "LOJA DO CIDADAO", "AT ",
                               "FINANCAS"]),
    ("Pagamentos (Payshop)", ["PAYSHOP"]),
    ("Compras", ["YUPIK", "DECATHLON", "PRIMARK", "ZARA", "H&M", "IKEA",
                 "WORTEN", "AMAZON", "SHEIN", "ALIEXPRESS", "BRICOLAG", "LEROY"]),
]
UNKNOWN_CATEGORY = "Outros (por identificar)"

# Nomes "bonitos" para compras (aplicados depois de tirar o nº do cartão).
# (expressão regular sobre o nome, nome a mostrar)
DISPLAY_ALIASES: list[tuple[str, str]] = [
    (r"^BK\d*\b.*", "BURGER KING"),
    (r"^BURGER KING.*", "BURGER KING"),
    (r"^BOLT\b.*", "BOLT"),
    (r"^CONTI BOM DI.*", "CONTINENTE BOM DIA"),
    (r"^CONTINENTE( [A-Z])?$", "CONTINENTE"),
    (r"^PINGO DOCE.*", "PINGO DOCE"),
    (r"^PORTOFINO.*", "PORTOFINO"),
    (r"^ANTHROPIC.*", "ANTHROPIC"),
    (r"^LIME RIDE.*", "LIME RIDE"),
    (r"^PAYSHOP.*", "PAYSHOP PORTUGAL"),
    (r"^FARMACIA.*", "FARMÁCIA"),
    (r"^CANTINHO DA$", "CANTINHO DA ..."),
]

# Entradas: salários. (texto a procurar, nome curto, grupo da tabela "Entradas")
SALARY_SOURCES: list[tuple[str, str, str]] = [
    ("ORDENADOS -CAPGEMINI", "Capgemini", "Salário — Capgemini (inclui Real Vida)"),
    ("REAL VIDA", "Real Vida", "Salário — Capgemini (inclui Real Vida)"),
    ("ORDENADOS -IEFP", "IEFP", "Salário — IEFP"),
]
INSURANCE_MATCH = ["SEGUROS", "SEGURO", "MEDIS", "MULTICARE"]  # reembolsos de seguro
CLINIC_MATCH = "CLINICA LAMB"
CLINIC_NAME = "Clínica Lamb"

MONTHS_PT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
             "agosto", "setembro", "outubro", "novembro", "dezembro"]

# Cores e tipografia (iguais aos relatórios originais)
C_TEXT = "#1f2430"
C_MUTED = "#6b7280"
C_BORDER = "#e5e7eb"
C_RULE = "#c9d1dd"
C_ROW_BG = "#f1f4f9"
C_BLUE = "#2f6fdf"
C_GREEN = "#2a9d78"
C_ORANGE = "#e07a2f"
C_RED = "#c0262d"

# =============================================================================
# SECÇÃO 2 — LEITURA DO PDF
# =============================================================================

MONEY = r"-?\d{1,3}(?:\.\d{3})*,\d{2}"
TX_RE = re.compile(
    rf"^\s*(\d{{2}}-\d{{2}}-\d{{2}})\s+(\d{{2}}-\d{{2}}-\d{{2}})\s+(.+?)\s+({MONEY})\s+({MONEY})\s*$"
)


def parse_money(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def pdf_text(path: str) -> str:
    """Texto do PDF com layout. Usa pdftotext (poppler) se existir; senão pypdf."""
    if shutil.which("pdftotext"):
        out = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.decode("utf-8", errors="replace")
    from pypdf import PdfReader  # fallback
    import logging
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = PdfReader(path)
    return "\n".join(p.extract_text(extraction_mode="layout") or "" for p in reader.pages)


@dataclass
class Tx:
    date: date            # data do movimento
    raw: str              # descritivo original (espaços normalizados)
    amount: float         # sempre positivo
    is_debit: bool
    balance: float        # saldo depois do movimento
    category: str = ""
    display: str = ""

    @property
    def dm(self) -> str:
        return self.date.strftime("%d-%m")


@dataclass
class Statement:
    account: str = ""
    product: str = "Superjovem"
    bank: str = "Crédito Agrícola"
    number: str = ""
    period_start: date | None = None
    period_end: date | None = None
    issued: str = ""
    opening: float = 0.0
    closing: float = 0.0
    txs: list[Tx] = field(default_factory=list)


def _d(s: str) -> date:
    d, m, y = s.split("-")
    y = int(y)
    return date(y + 2000 if y < 100 else y, int(m), int(d))


def parse_statement(path: str) -> Statement:
    text = pdf_text(path)
    st = Statement()
    m = re.search(r"Conta D\.O\.:\s+(\d+)", text)
    if m:
        st.account = m.group(1)
    m = re.search(r"DEP[ÓO]SITOS [ÀA] ORDEM CONTA\s+(\w+)", text)
    if m:
        st.product = m.group(1).capitalize()
    if not re.search(r"CR[ÉE]DITO AGR[ÍI]COLA", text, re.I):
        st.bank = "Banco"
    m = re.search(r"EXTRACTO N[º°o]\s*(\d+/\d+)\s*-\s*Per[íi]odo de\s+(\d{2}-\d{2}-\d{4})\s+a\s+(\d{2}-\d{2}-\d{4})", text)
    if not m:
        sys.exit("ERRO: não encontrei 'EXTRACTO Nº ... Período de ... a ...' — isto é um Extracto Integrado do Crédito Agrícola?")
    st.number, st.period_start, st.period_end = m.group(1), _d(m.group(2)), _d(m.group(3))
    m = re.search(r"DATA EMISS[ÃA]O:\s+(\d{2}-\d{2}-\d{4})", text)
    st.issued = m.group(1) if m else ""
    m = re.search(rf"Saldo Contabil[íi]stico em\s+\d{{2}}-\d{{2}}-\d{{4}}\s+({MONEY})", text)
    if not m:
        sys.exit("ERRO: não encontrei o saldo inicial ('Saldo Contabilístico em ...').")
    st.opening = parse_money(m.group(1))

    prev = st.opening
    for line in text.splitlines():
        mm = TX_RE.match(line)
        if not mm:
            continue
        dmov, _dval, desc, amt, bal = mm.groups()
        amount, balance = parse_money(amt), parse_money(bal)
        desc = re.sub(r"\s+", " ", desc).strip()
        # débito ou crédito? decide-se pela variação do saldo
        if abs(round(prev - amount, 2) - balance) < 0.005:
            is_debit = True
        elif abs(round(prev + amount, 2) - balance) < 0.005:
            is_debit = False
        else:
            print(f"AVISO: saldo não bate na linha: {line.strip()}", file=sys.stderr)
            is_debit = balance < prev
        st.txs.append(Tx(_d(dmov), desc, amount, is_debit, balance))
        prev = balance
    if not st.txs:
        sys.exit("ERRO: nenhum movimento encontrado no extracto.")
    st.closing = st.txs[-1].balance
    return st


# =============================================================================
# SECÇÃO 3 — CLASSIFICAÇÃO
# =============================================================================

CARD_SUFFIX = re.compile(r"\s+\d{7}/\d+$")
FX_SUFFIX = re.compile(r"^(.*?)\s+(USD|GBP|BRL|CHF|SEK|DKK|NOK|PLN|CZK)\s+[\d.,]+$")

# categorias "fora dos gastos"
CAT_INVEST = "Investimentos (Revolut)"
CAT_FAMILY = "Ajuda familiar"


def clean_purchase(name: str) -> str:
    name = CARD_SUFFIX.sub("", name).strip()
    fx = FX_SUFFIX.match(name)
    if fx:
        name = f"{fx.group(1).strip()} ({fx.group(2)})"
        base = fx.group(1).strip()
    else:
        base = name
    for pat, disp in DISPLAY_ALIASES:
        if re.match(pat, base):
            return disp + (name[len(base):] if fx else "")
    return name


def classify(tx: Tx) -> None:
    u = tx.raw.upper()
    if not tx.is_debit:
        tx.category = "entrada"
        tx.display = tx.raw
        return
    if INVEST_MATCH in u:
        tx.category, tx.display = CAT_INVEST, re.sub(r"\s+\d+$", "", tx.raw)
        return
    if u.startswith("TRF") and FAMILY_MATCH in u:
        name = re.sub(r"^Trf.*?(?=" + FAMILY_MATCH + ")", "", tx.raw, flags=re.I)
        tx.category, tx.display = CAT_FAMILY, f"Trf {name}"
        return
    if u.startswith("COMISS") or u.startswith("TRANSFERÊNCIA COM CARTÃO") or u.startswith("IMPOSTO"):
        tx.category = "Comissões bancárias"
        tx.display = "Comissão de compras POS (inclui I.S.)" if "COMPRAS POS" in u else tx.raw
        return
    if u.startswith("LEVANT"):
        tx.category = "Levantamentos (numerário)"
        tx.display = "LEVANTAMENTO " + CARD_SUFFIX.sub("", tx.raw[len("LEVANT"):]).strip()
        return
    if u.startswith("TRF"):
        tx.category, tx.display = "Transferências a amigos", tx.raw
        return
    if u.startswith("COMPRA "):
        name = clean_purchase(tx.raw[len("COMPRA "):])
        tx.display = "COMPRA " + name
        target = " " + CARD_SUFFIX.sub("", tx.raw[len("COMPRA "):]).upper() + " "
        for cat, words in CATEGORY_RULES:
            if any((" " + w) in target or target.startswith(" " + w) for w in words):
                tx.category = cat
                return
        tx.category = UNKNOWN_CATEGORY
        return
    # outros débitos (pagamentos de serviços, etc.): tenta as mesmas regras
    tx.display = CARD_SUFFIX.sub("", re.sub(r"\s+\d+/\d+$", "", tx.raw)).strip()
    target = " " + tx.display.upper() + " "
    for cat, words in CATEGORY_RULES:
        if any((" " + w) in target for w in words):
            tx.category = cat
            return
    tx.category = UNKNOWN_CATEGORY


# =============================================================================
# SECÇÃO 4 — CÁLCULOS
# =============================================================================

def eur(v: float, signed: bool = False) -> str:
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if v < 0 and signed else "") + s + " €"


def pct1(v: float) -> str:
    return f"{v:.1f}%"


def first_name(raw: str) -> str:
    n = re.sub(r"^IPS/\S+?-", "", raw).split()
    return n[0].capitalize() if n else raw


@dataclass
class Report:
    st: Statement
    spend: list[Tx]
    cats: list[tuple[str, list[Tx], float]]      # ordenado por total desc
    spend_total: float
    invest_sent: list[Tx]
    invest_back: list[Tx]                        # créditos teus (IPS teu nome)
    family: list[Tx]
    inflows: list[tuple[str, float]]             # (origem, total) ordenado
    inflow_total: float
    salary_parts: list[tuple[str, float]]
    friends_total: float
    friend_names: list[str]
    insurance_total: float
    family_in_total: float

    @property
    def invest_net(self) -> float:
        return sum(t.amount for t in self.invest_sent) - sum(t.amount for t in self.invest_back)

    @property
    def family_total(self) -> float:
        return sum(t.amount for t in self.family)

    @property
    def net_out(self) -> float:
        return self.spend_total + self.invest_net + self.family_total


def build_report(st: Statement) -> Report:
    for t in st.txs:
        classify(t)
    debits = [t for t in st.txs if t.is_debit]
    credits = [t for t in st.txs if not t.is_debit]
    spend = [t for t in debits if t.category not in (CAT_INVEST, CAT_FAMILY)]
    groups: dict[str, list[Tx]] = {}
    for t in spend:
        groups.setdefault(t.category, []).append(t)
    cats = sorted(((c, ts, round(sum(x.amount for x in ts), 2)) for c, ts in groups.items()),
                  key=lambda x: -x[2])

    invest_back: list[Tx] = []
    salary: dict[str, float] = {}
    salary_groups: dict[str, float] = {}
    friends: list[Tx] = []
    insurance = fam_in = other = 0.0
    for t in credits:
        u = t.raw.upper()
        if OWNER_MATCH in u:
            invest_back.append(t)
            continue
        src = next((s for s in SALARY_SOURCES if s[0] in u), None)
        if src:
            salary[src[1]] = salary.get(src[1], 0) + t.amount
            salary_groups[src[2]] = salary_groups.get(src[2], 0) + t.amount
        elif FAMILY_MATCH in u:
            fam_in += t.amount
        elif any(w in u for w in INSURANCE_MATCH):
            insurance += t.amount
        elif u.startswith("IPS/") or u.startswith("TRF"):
            friends.append(t)
        else:
            other += t.amount
    friends_total = sum(t.amount for t in friends)
    names: list[str] = []
    for t in friends:
        n = first_name(t.raw)
        if n not in names:
            names.append(n)
    inflows = list(salary_groups.items())
    for label, v in [("Seguros (reembolsos)", insurance),
                     ("Reembolsos / transferências de amigos", friends_total),
                     (f"Família ({FAMILY_SHORT})", fam_in),
                     ("Outras entradas", other)]:
        if v > 0.004:
            inflows.append((label, v))
    inflows.sort(key=lambda x: -x[1])
    return Report(
        st=st, spend=spend, cats=cats, spend_total=round(sum(t.amount for t in spend), 2),
        invest_sent=[t for t in debits if t.category == CAT_INVEST],
        invest_back=invest_back,
        family=[t for t in debits if t.category == CAT_FAMILY],
        inflows=inflows, inflow_total=sum(v for _, v in inflows),
        salary_parts=sorted(salary.items(), key=lambda kv: [x[1] for x in SALARY_SOURCES].index(kv[0])),
        friends_total=friends_total,
        friend_names=names, insurance_total=insurance, family_in_total=fam_in,
    )


def summary_text(r: Report) -> str:
    st = r.st
    month = MONTHS_PT[st.period_start.month - 1]
    no = r.net_out or 1
    sent = sum(t.amount for t in r.invest_sent)
    back = sum(t.amount for t in r.invest_back)
    s = f"Em {month} saíram da conta, em termos líquidos, <b>{eur(r.net_out)}</b>. Desse valor, "
    s += (f"<b>{eur(r.invest_net)}</b> ({r.invest_net / no * 100:.0f}%) foram investimentos para a Revolut "
          f"({eur(sent)} enviados menos {eur(back)} que transferiste de volta para ti) e ")
    s += (f"<b>{eur(r.family_total)}</b> ({r.family_total / no * 100:.0f}%) foram ajuda familiar. "
          f"Os gastos propriamente ditos somaram <b>{eur(r.spend_total)}</b> "
          f"({r.spend_total / no * 100:.0f}%).")
    if r.cats:
        c0 = r.cats[0]
        s += f" A maior categoria de gasto foi <b>{c0[0]}</b> com {eur(c0[2])}"
        rest = [f"{c} ({eur(v)})" for c, _, v in r.cats[1:3]]
        if len(rest) == 2:
            s += f", seguida de {rest[0]} e {rest[1]}."
        elif len(rest) == 1:
            s += f", seguida de {rest[0]}."
        else:
            s += "."
    s += (f" Entraram {eur(r.inflow_total)} de fora (sem contar transferências tuas), "
          f"e o saldo passou de {eur(st.opening)} para {eur(st.closing)}.")
    return s


def observations(r: Report) -> list[str]:
    out: list[str] = []
    cat = {c: (ts, v) for c, ts, v in r.cats}

    if "Restauração" in cat:
        ts, v = cat["Restauração"]
        by: dict[str, list[float]] = {}
        for t in ts:
            by.setdefault(t.display.replace("COMPRA ", "", 1), []).append(t.amount)
        name, amts = max(by.items(), key=lambda kv: sum(kv[1]))
        n = len(amts)
        out.append(f"<b>Restauração</b> ({eur(v)}, {len(ts)} compra{'s' if len(ts) != 1 else ''}): "
                   f"o maior gasto foi em {name.title()} ({eur(sum(amts))} em {n} visita{'s' if n != 1 else ''}).")

    bolt = [t for t in r.spend if t.display == "COMPRA BOLT"]
    if bolt:
        top = max(bolt, key=lambda t: t.amount)
        n = len(bolt)
        out.append(f"<b>Bolt</b>: {n} viage{'ns' if n != 1 else 'm'}, {eur(sum(t.amount for t in bolt))} no total, "
                   f"a mais cara de {eur(top.amount)} ({top.dm}).")

    if "Saúde" in cat:
        ts, v = cat["Saúde"]
        clinic = [t for t in ts if CLINIC_MATCH in t.raw.upper()]
        if clinic or r.insurance_total or r.family_in_total:
            s = f"<b>Saúde</b>: {eur(v)} no total"
            if clinic:
                s += (f", dos quais {eur(sum(t.amount for t in clinic))} em {len(clinic)} "
                      f"pagamento{'s' if len(clinic) != 1 else ''} à {CLINIC_NAME}.")
            else:
                s += "."
            parts = []
            if r.insurance_total:
                parts.append(f"{eur(r.insurance_total)} de reembolsos do seguro")
            if r.family_in_total:
                parts.append(f"{eur(r.family_in_total)} da {FAMILY_SHORT}")
            if parts:
                s += f" Recebeste {' e '.join(parts)}, o que reduz bastante o custo real."
            out.append(s)

    if "Levantamentos (numerário)" in cat:
        ts, v = cat["Levantamentos (numerário)"]
        out.append(f"<b>Levantamentos</b>: {eur(v)} em numerário ({', '.join(t.dm for t in ts)}). "
                   f"Não é possível saber em que foi gasto.")

    if UNKNOWN_CATEGORY in cat:
        ts, _ = cat[UNKNOWN_CATEGORY]
        items = ", ".join(f"{t.display.replace('COMPRA ', '', 1)} ({eur(t.amount)}, {t.dm})" for t in ts)
        out.append(f"<b>Por identificar</b>: {items}. O nome no extrato não deixa perceber o que foi; "
                   f"acrescenta-o a CATEGORY_RULES no script para o recategorizar.")

    if "Comissões bancárias" in cat:
        ts, v = cat["Comissões bancárias"]
        out.append(f"<b>Comissões bancárias</b>: {eur(v)} ({len(ts)} movimento{'s' if len(ts) != 1 else ''}).")

    lo = min(r.st.txs, key=lambda t: t.balance)
    hi = max(r.st.txs, key=lambda t: t.balance)
    out.append(f"<b>Saldo mínimo</b>: {eur(lo.balance)} a {lo.dm}. Saldo máximo: {eur(hi.balance)} a {hi.dm}.")
    return out


# =============================================================================
# SECÇÃO 5 — GRÁFICOS (matplotlib -> PNG em memória)
# =============================================================================

def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = "DejaVu Sans"
    return plt


def _png(fig) -> io.BytesIO:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, facecolor="white")
    _plt().close(fig)
    buf.seek(0)
    return buf


def chart_flow(r: Report) -> io.BytesIO:
    """Barra horizontal: Investimentos / Gastos / Ajuda familiar.

    Desenhado em coordenadas de píxeis (imagem 1440x260). Segmentos com menos de
    15% do total não têm espaço para texto: a etiqueta vai para baixo da barra,
    centrada no segmento, e a escala encolhe para a etiqueta caber.
    """
    from matplotlib.patches import Rectangle
    plt = _plt()
    WPX, HPX, L, R = 1440, 260, 32, 1407
    fig = plt.figure(figsize=(7.2, 1.3), dpi=200)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, WPX)
    ax.set_ylim(HPX, 0)
    ax.axis("off")
    parts = [(n, v, c) for n, v, c in [("Investimentos", max(r.invest_net, 0), C_GREEN),
                                       ("Gastos", r.spend_total, C_ORANGE),
                                       ("Ajuda familiar", r.family_total, C_BLUE)] if v > 0]
    total = sum(v for _, v, _ in parts) or 1
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    below = []  # (meio do segmento em €, largura do texto em px, nome, valor, cor)
    acc = 0.0
    for n, v, c in parts:
        if v / total < 0.15:
            t = ax.text(0, 0, f"{n}: {eur(v)}", fontsize=7.8, fontweight="bold")
            w = t.get_window_extent(rend).width
            t.remove()
            below.append((acc + v / 2, w, n, v, c))
        acc += v
    # escolher a (início da barra) e b (px por €) com b máximo e etiquetas dentro de [L, R]
    best = (L, (R - L) / total)
    if below:
        best = None
        for a in range(L, 900):
            b = (R - a) / total
            for mid, w, *_ in below:
                b = min(b, (R - w / 2 - a) / mid)
            if b > 0 and all(a + b * mid - w / 2 >= L - 0.5 for mid, w, *_ in below):
                if best is None or b > best[1]:
                    best = (a, b)
        best = best or (L, (R - L) / total)
    a, b = best
    y0, y1 = (37, 137) if below else (41, 218)
    x = a
    for n, v, c in parts:
        wseg = v * b
        ax.add_patch(Rectangle((x, y0), wseg, y1 - y0, facecolor=c, edgecolor="white", linewidth=1.6))
        if v / total >= 0.15:
            ax.text(x + wseg / 2, (y0 + y1) / 2, f"{n}\n{eur(v)}", ha="center", va="center",
                    color="white", fontsize=8.3, fontweight="bold", linespacing=1.2)
        x += wseg
    for mid, w, n, v, c in below:
        ax.text(a + b * mid, 177, f"{n}: {eur(v)}", ha="center", va="center", color=c,
                fontsize=7.8, fontweight="bold")
    return _png(fig)


def chart_categories(r: Report) -> io.BytesIO:
    plt = _plt()
    n = max(len(r.cats), 1)
    fig, ax = plt.subplots(figsize=(7.2, 3.1), dpi=200)
    names = [c for c, _, _ in r.cats][::-1]
    vals = [v for _, _, v in r.cats][::-1]
    ax.barh(names, vals, color=C_BLUE, height=0.6, zorder=3)
    mx = max(vals) if vals else 1
    for i, v in enumerate(vals):
        ax.text(v + mx * 0.01, i, f"{eur(v)}  ({v / (r.spend_total or 1) * 100:.0f}%)",
                va="center", ha="left", fontsize=7.65, color=C_TEXT, zorder=4)
    ax.set_xlim(0, mx * 1.28)
    ax.set_ylim(-0.75, n - 0.27)
    ax.xaxis.grid(True, color=C_BORDER, linewidth=0.8, zorder=0)
    ax.set_xticklabels([])
    ax.tick_params(axis="x", length=0)
    ax.tick_params(axis="y", length=0, labelsize=8.5, labelcolor=C_TEXT)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(C_BORDER)
    # posição dos eixos igual aos originais (imagem 1440x620 px)
    fig.canvas.draw()
    lw = max((t.get_window_extent().width for t in ax.get_yticklabels()), default=0)
    ax.set_position([(33 + lw + 12) / 1440, 38 / 620, (1410 - 45 - lw) / 1440, (620 - 38 - 30) / 620])
    return _png(fig)


def chart_balance(r: Report) -> io.BytesIO:
    plt = _plt()
    st = r.st
    ys = [st.opening] + [t.balance for t in st.txs]
    xs = list(range(len(ys)))
    fig, ax = plt.subplots(figsize=(7.2, 2.6), dpi=200)
    ax.plot(xs, ys, drawstyle="steps-post", color=C_BLUE, linewidth=1.8, zorder=3)
    ax.fill_between(xs, ys, step="post", color=C_BLUE, alpha=0.08, zorder=2)
    ax.yaxis.grid(True, color=C_BORDER, linewidth=0.8, zorder=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(C_BORDER)
    ax.tick_params(colors=C_MUTED, labelsize=7.5, length=0)
    ax.set_ylabel("Saldo (€)", color=C_MUTED, fontsize=7.5)
    # marcas no eixo x: 1º movimento, 1º movimento a partir dos dias 8, 15, 22, último
    ticks: list[int] = [1]
    for day in (8, 15, 22):
        i = next((k + 1 for k, t in enumerate(st.txs) if t.date.day >= day), None)
        if i and i not in ticks and i < len(st.txs):
            ticks.append(i)
    if len(st.txs) not in ticks:
        ticks.append(len(st.txs))
    ax.set_xticks(ticks)
    ax.set_xticklabels([st.txs[i - 1].dm for i in ticks])
    hi = max(st.txs, key=lambda t: t.balance)
    # etiqueta do máximo: mesma posição que nos relatórios originais (~64% da largura)
    n = len(st.txs)
    ax.annotate(f"Máximo: {eur(hi.balance)} ({hi.dm})", xy=(n * 0.637, hi.balance),
                xytext=(0, -1.5), textcoords="offset points",
                ha="center", va="center", fontsize=7.6, color=C_TEXT, zorder=5)
    ax.set_xlim(-n * 0.0559, n * 1.0483)
    ax.set_position([106 / 1440, 63 / 520, 1304 / 1440, (457 - 30) / 520])
    return _png(fig)


# =============================================================================
# SECÇÃO 6 — PDF (reportlab)
# =============================================================================

def build_pdf(r: Report, out_path: str) -> None:
    import matplotlib
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph,
                                    SimpleDocTemplate, Spacer, Table, TableStyle)

    fdir = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
    pdfmetrics.registerFont(TTFont("DejaVuSans", os.path.join(fdir, "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", os.path.join(fdir, "DejaVuSans-Bold.ttf")))
    from reportlab.lib.fonts import addMapping
    addMapping("DejaVuSans", 0, 0, "DejaVuSans")
    addMapping("DejaVuSans", 1, 0, "DejaVuSans-Bold")
    F, FB = "DejaVuSans", "DejaVuSans-Bold"

    st = r.st
    col = colors.HexColor
    month_t = MONTHS_PT[st.period_start.month - 1].capitalize()
    title = f"Relatório de Gastos — {month_t} {st.period_start.year}"
    W = A4[0] - 36 * mm  # largura útil das tabelas

    sty = {
        "title": ParagraphStyle("t", fontName=FB, fontSize=20, leading=24.4, textColor=col(C_TEXT)),
        "sub": ParagraphStyle("s", fontName=F, fontSize=9.5, leading=13, textColor=col(C_MUTED)),
        "h2": ParagraphStyle("h", fontName=FB, fontSize=13, leading=16, textColor=col(C_TEXT),
                             spaceBefore=18.1, spaceAfter=6.9),
        "h2_img": None,  # (definido abaixo) título logo a seguir a um gráfico
        "body": ParagraphStyle("b", fontName=F, fontSize=9.5, leading=14, textColor=col(C_TEXT)),
        "bullet": ParagraphStyle("bl", fontName=F, fontSize=9.5, leading=14, textColor=col(C_TEXT),
                                 spaceAfter=3),
        "note": ParagraphStyle("n", fontName=F, fontSize=8, leading=11, textColor=col(C_MUTED)),
        "card_l": ParagraphStyle("cl", fontName=F, fontSize=8, leading=10, textColor=col(C_MUTED)),
        "card_v": ParagraphStyle("cv", fontName=FB, fontSize=15, leading=18, textColor=col(C_TEXT)),
        "card_s": ParagraphStyle("cs", fontName=F, fontSize=8, leading=11, textColor=col(C_MUTED)),
    }
    sty["h2_img"] = ParagraphStyle("hi", parent=sty["h2"], spaceBefore=10)
    TS = 8.3   # tamanho do texto nas tabelas
    TSD = 7.8  # valores nas linhas de detalhe

    def footer(canv, doc):
        canv.saveState()
        canv.setFont(F, 7.5)
        canv.setFillColor(col(C_MUTED))
        canv.drawString(18 * mm, 28.3, f"Gerado a partir do Extracto Integrado de {st.issued}")
        canv.drawRightString(A4[0] - 18 * mm, 28.3, f"Página {doc.page}")
        canv.restoreState()

    doc = SimpleDocTemplate(out_path, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=18 * mm - 5.7, bottomMargin=18 * mm, title=title,
                            author="", subject="", creator="")
    story: list = []

    # --- cabeçalho
    story.append(Paragraph(title, sty["title"]))
    story.append(Spacer(1, 2.5))
    story.append(Paragraph(
        f"Conta D.O. {st.product} {st.account} · {st.bank} · Extracto nº {st.number} "
        f"({st.period_start:%d-%m-%Y} a {st.period_end:%d-%m-%Y})", sty["sub"]))
    story.append(Spacer(1, 12.1))

    # --- cartões
    sent = sum(t.amount for t in r.invest_sent)
    back = sum(t.amount for t in r.invest_back)
    inv_sub = f"{eur(sent)} enviados − {eur(back)} devolvidos" if back else f"{eur(sent)} enviados"
    fam_names = sorted({re.sub(r"^Trf\s+", "", t.display).title() for t in r.family})
    sal_total = sum(v for _, v in r.salary_parts)
    sal_sub = " + ".join(f"{n} {eur(v)}" for n, v in r.salary_parts) or "—"

    def card(label, value, sub):
        return [Paragraph(label, sty["card_l"]), Paragraph(value, sty["card_v"]),
                Spacer(1, 1), Paragraph(sub, sty["card_s"])]

    cards = Table([[
        card("Gastos reais", eur(r.spend_total), f"{len(r.spend)} movimentos"),
        card("Investido (Revolut)", eur(r.invest_net), inv_sub),
        card("Ajuda familiar", eur(r.family_total), ", ".join(fam_names) or FAMILY_FULL_NAME),
        card("Salário recebido", eur(sal_total), sal_sub),
    ]], colWidths=[W / 4] * 4)
    cards.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, col(C_BORDER)),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, col(C_BORDER)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(cards)

    # --- resumo
    story.append(Paragraph("Resumo", sty["h2"]))
    story.append(Paragraph(summary_text(r), sty["body"]))

    # --- gráficos
    story.append(KeepTogether([Paragraph("Para onde foi o dinheiro", sty["h2"]),
                               Image(chart_flow(r), width=W, height=W * 1.3 / 7.2)]))
    story.append(KeepTogether([
        Paragraph("Gastos por categoria", sty["h2_img"]),
        Paragraph("Exclui investimentos e ajuda familiar. A percentagem é sobre o total de gastos reais.",
                  sty["note"]),
        Image(chart_categories(r), width=W, height=W * 0.425)]))

    # --- tabela por categoria
    story.append(PageBreak())
    story.append(Paragraph("Tabela por categoria", sty["h2"]))
    cw = [W * 0.44, W * 0.12, W * 0.16, W * 0.14, W * 0.14]

    def base_style(n_rows, header_color=C_MUTED):
        return [
            ("FONT", (0, 0), (-1, -1), F, TS),
            ("FONT", (0, 0), (-1, 0), FB, TS),
            ("TEXTCOLOR", (0, 0), (-1, 0), col(header_color)),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, col(C_RULE)),
            ("LINEBELOW", (0, 1), (-1, n_rows - 1), 0.4, col(C_BORDER)),
        ]

    rows = [["Categoria", "Nº mov.", "Total", "% dos gastos", "Média/mov."]]
    style = []
    for c, ts, v in r.cats:
        i = len(rows)
        rows.append([c, str(len(ts)), eur(v), pct1(v / (r.spend_total or 1) * 100), eur(v / len(ts))])
        style += [("BACKGROUND", (0, i), (-1, i), col(C_ROW_BG)), ("FONT", (0, i), (-1, i), FB, TS)]
        for t in ts:
            j = len(rows)
            rows.append([f"  {t.dm}  ·  {t.display}", "", eur(t.amount), "", ""])
            style += [("FONT", (2, j), (2, j), F, TSD), ("TEXTCOLOR", (2, j), (2, j), col(C_MUTED)),
                      ("LEFTPADDING", (0, j), (0, j), 8.6),
                      ("TOPPADDING", (0, j), (-1, j), 3.75), ("BOTTOMPADDING", (0, j), (-1, j), 3.75)]
    i = len(rows)
    rows.append(["Total gastos", str(len(r.spend)), eur(r.spend_total), "100%", ""])
    style += [("FONT", (0, i), (-1, i), FB, TS), ("LINEABOVE", (0, i), (-1, i), 0.8, col(C_TEXT))]
    t1 = Table(rows, colWidths=cw, repeatRows=1)
    t1.setStyle(TableStyle(base_style(len(rows)) + style))
    story.append(t1)
    story.append(Spacer(1, 9.9))

    # --- fora dos gastos
    rows = [["Fora dos gastos", "Nº mov.", "Total", "% das saídas", "Média/mov."]]
    style = []
    no = r.net_out or 1
    inv_rows = sorted(r.invest_sent + r.invest_back, key=lambda t: r.st.txs.index(t))
    i = len(rows)
    cnt = f"{len(r.invest_sent)} + {len(r.invest_back)}" if r.invest_back else str(len(r.invest_sent))
    rows.append(["Investimentos (Revolut, líquido)", cnt, eur(r.invest_net), pct1(r.invest_net / no * 100), ""])
    style += [("BACKGROUND", (0, i), (-1, i), col(C_ROW_BG)), ("FONT", (0, i), (-1, i), FB, TS)]
    for t in inv_rows:
        j = len(rows)
        if t.is_debit:
            rows.append([f"  {t.dm}  ·  {t.display}", "", eur(t.amount), "", ""])
            style += [("TEXTCOLOR", (2, j), (2, j), col(C_MUTED))]
        else:
            rows.append([f"  {t.dm}  ·  Devolvido para mim — IPS {OWNER_FULL_NAME}", "",
                         eur(-t.amount, signed=True), "", ""])
            style += [("TEXTCOLOR", (2, j), (2, j), col(C_RED))]
        style += [("FONT", (2, j), (2, j), F, TSD), ("LEFTPADDING", (0, j), (0, j), 8.6),
                  ("TOPPADDING", (0, j), (-1, j), 3.75), ("BOTTOMPADDING", (0, j), (-1, j), 3.75)]
    if r.family:
        i = len(rows)
        ft = r.family_total
        rows.append([CAT_FAMILY, str(len(r.family)), eur(ft), pct1(ft / no * 100), eur(ft / len(r.family))])
        style += [("BACKGROUND", (0, i), (-1, i), col(C_ROW_BG)), ("FONT", (0, i), (-1, i), FB, TS)]
        for t in r.family:
            j = len(rows)
            rows.append([f"  {t.dm}  ·  {t.display}", "", eur(t.amount), "", ""])
            style += [("FONT", (2, j), (2, j), F, TSD), ("TEXTCOLOR", (2, j), (2, j), col(C_MUTED)),
                      ("LEFTPADDING", (0, j), (0, j), 8.6),
                      ("TOPPADDING", (0, j), (-1, j), 3.75), ("BOTTOMPADDING", (0, j), (-1, j), 3.75)]
    i = len(rows)
    rows.append(["Total de saídas líquidas", "", eur(r.net_out), "100%", ""])
    style += [("FONT", (0, i), (-1, i), FB, TS), ("LINEABOVE", (0, i), (-1, i), 0.8, col(C_TEXT))]
    t2 = Table(rows, colWidths=cw, repeatRows=1)
    t2.setStyle(TableStyle(base_style(len(rows)) + style))
    story.append(t2)
    story.append(Spacer(1, 4))
    story.append(Paragraph("Valores a vermelho são transferências que fizeste para ti próprio; foram "
                           "descontadas do total investido na Revolut.", sty["note"]))

    # --- entradas
    story.append(Paragraph("Entradas", sty["h2_img"]))
    rows = [["Origem", "Total"]] + [[k, eur(v)] for k, v in r.inflows]
    rows.append(["Total de entradas (sem transferências tuas)", eur(r.inflow_total)])
    t3 = Table(rows, colWidths=[W * 0.75, W * 0.25])
    t3.setStyle(TableStyle(base_style(len(rows)) + [
        ("FONT", (0, -1), (-1, -1), FB, TS), ("LINEABOVE", (0, -1), (-1, -1), 0.8, col(C_TEXT))]))
    story.append(t3)
    notes = []
    if back:
        notes.append(f"As transferências de “{OWNER_FULL_NAME}” ({eur(back)}) não contam como entrada: "
                     f"foram descontadas do investimento na Revolut.")
    if r.friends_total:
        notes.append(f"Os {eur(r.friends_total)} recebidos de amigos ({', '.join(r.friend_names)}) "
                     f"parecem ser reembolsos de despesas partilhadas.")
    if notes:
        story.append(Spacer(1, 4))
        story.append(Paragraph(" ".join(notes), sty["note"]))

    # --- saldo
    story.append(KeepTogether([Paragraph("Evolução do saldo", sty["h2"]),
                               Image(chart_balance(r), width=W, height=W * 2.6 / 7.2)]))

    # --- observações
    obs = [Paragraph("Observações", sty["h2_img"])]
    obs += [Paragraph("• " + o, sty["bullet"]) for o in observations(r)]
    story.append(KeepTogether(obs))

    # --- todos os movimentos de saída
    story.append(Spacer(1, 2.9))
    story.append(Paragraph("Todos os movimentos de saída", sty["h2"]))
    rows = [["Data", "Descritivo", "Categoria", "Valor"]]
    for t in r.st.txs:
        if t.is_debit:
            rows.append([t.dm, t.display, t.category, eur(t.amount)])
    total_out = sum(t.amount for t in r.st.txs if t.is_debit)
    rows.append(["", "Total", "", eur(total_out)])
    t4 = Table(rows, colWidths=[W * 0.10, W * 0.45, W * 0.30, W * 0.15], repeatRows=1)
    st4 = base_style(len(rows))
    st4 = [s for s in st4 if s[0] != "ALIGN"] + [
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("TOPPADDING", (0, 1), (-1, -1), 3.75), ("BOTTOMPADDING", (0, 1), (-1, -1), 3.75),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, col(C_TEXT)),
        ("FONT", (0, -1), (-1, -1), FB, TS),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, col(C_TEXT)),
    ]
    t4.setStyle(TableStyle(st4))
    story.append(t4)

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    ap = argparse.ArgumentParser(description="Gera o Relatório de Gastos a partir de um Extracto Integrado (PDF).")
    ap.add_argument("extracto", help="PDF do Extracto Integrado do Crédito Agrícola")
    ap.add_argument("-o", "--output", help="PDF de saída (por omissão: Relatorio_Gastos_<Mês>_<Ano>.pdf na pasta atual)")
    ap.add_argument("--list", action="store_true", help="só lista os movimentos e categorias (não gera PDF)")
    a = ap.parse_args()
    if not os.path.isfile(a.extracto):
        sys.exit(f"ERRO: ficheiro não encontrado: {a.extracto}")

    st = parse_statement(a.extracto)
    r = build_report(st)

    if a.list:
        print(f"Extracto {st.number}  {st.period_start} a {st.period_end}  saldo {st.opening} -> {st.closing}")
        for t in st.txs:
            sign = "-" if t.is_debit else "+"
            print(f"{t.dm}  {sign}{t.amount:>9.2f}  {t.category:<28} {t.display}")
        return

    month = MONTHS_PT[st.period_start.month - 1].capitalize()
    out = a.output or f"Relatorio_Gastos_{month}_{st.period_start.year}.pdf"
    out = os.path.expanduser(out)
    build_pdf(r, out)
    print(f"Relatório criado: {os.path.abspath(out)}")
    print(f"  Gastos reais {eur(r.spend_total)} | Investido {eur(r.invest_net)} | "
          f"Ajuda familiar {eur(r.family_total)} | Entradas {eur(r.inflow_total)}")
    unknown = [t for t in r.spend if t.category == UNKNOWN_CATEGORY]
    if unknown:
        print("  Por identificar (adiciona a CATEGORY_RULES se quiseres):")
        for t in unknown:
            print(f"    {t.dm}  {t.amount:>8.2f}  {t.raw}")


if __name__ == "__main__":
    main()
