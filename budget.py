import sqlite3
import os
import matplotlib.pyplot as plt
from datetime import datetime
from dateutil.relativedelta import relativedelta
import sys

USAR_CORES = (
    sys.stdout.isatty() and
    os.getenv("TERM") not in ("dumb", None) and
    os.getenv("PYFOX") is None
)

DB_FINANCAS = "financas.db"
DB_IEFP = "iefp_bolsas.db"

VALOR_HORA_BOLSA = 2.06
LIMITE_MENSAL_BOLSA = 268.57
VALOR_ALIMENTACAO_DIA = 6.15
MIN_HORAS_ALIMENTACAO = 3

HORAS_MES = {
    "2026-04": 36, "2026-05": 119, "2026-06": 118,
    "2026-07": 138, "2026-08": 60, "2026-09": 132,
    "2026-10": 126, "2026-11": 117, "2026-12": 36,
    "2027-01": 120, "2027-02": 97, "2027-03": 138,
    "2027-04": 132, "2027-05": 120, "2027-06": 54,
}

def cor(texto, nome):
    if not USAR_CORES:
        return texto

    cores = {
        "verde": "\033[92m",
        "vermelho": "\033[91m",
        "azul": "\033[96m",
        "rosa": "\033[95m",
        "bold": "\033[1m",
        "fim": "\033[0m",
    }
    return f"{cores.get(nome, '')}{texto}{cores['fim']}"


def pedir_input(msg):
    valor = input(msg).strip()
    if valor == "00":
        print(cor("Ação cancelada.", "laranja"))
        return None
    return valor


def limpar_terminal():
    os.system("cls" if os.name == "nt" else "clear")


def conectar_financas():
    return sqlite3.connect(DB_FINANCAS)


def conectar_iefp():
    return sqlite3.connect(DB_IEFP)


def criar_tabelas():
    conn = conectar_financas()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rendimentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            valor REAL NOT NULL,
            ativo INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS gastos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            valor REAL NOT NULL,
            ativo INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS transacoes_unicas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            nome TEXT NOT NULL,
            valor REAL NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def recalcular_ids(tabela):
    conn = conectar_financas()
    cur = conn.cursor()

    if tabela == "rendimentos":
        cur.execute("""
            CREATE TABLE rendimentos_nova (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                valor REAL NOT NULL,
                ativo INTEGER DEFAULT 1
            )
        """)
        cur.execute("""
            INSERT INTO rendimentos_nova (nome, valor, ativo)
            SELECT nome, valor, ativo FROM rendimentos ORDER BY id
        """)
        cur.execute("DROP TABLE rendimentos")
        cur.execute("ALTER TABLE rendimentos_nova RENAME TO rendimentos")

    elif tabela == "gastos":
        cur.execute("""
            CREATE TABLE gastos_nova (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                valor REAL NOT NULL,
                ativo INTEGER DEFAULT 1
            )
        """)
        cur.execute("""
            INSERT INTO gastos_nova (nome, valor, ativo)
            SELECT nome, valor, ativo FROM gastos ORDER BY id
        """)
        cur.execute("DROP TABLE gastos")
        cur.execute("ALTER TABLE gastos_nova RENAME TO gastos")

    elif tabela == "transacoes_unicas":
        cur.execute("""
            CREATE TABLE transacoes_unicas_nova (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data TEXT NOT NULL,
                nome TEXT NOT NULL,
                valor REAL NOT NULL
            )
        """)
        cur.execute("""
            INSERT INTO transacoes_unicas_nova (data, nome, valor)
            SELECT data, nome, valor FROM transacoes_unicas ORDER BY data, id
        """)
        cur.execute("DROP TABLE transacoes_unicas")
        cur.execute("ALTER TABLE transacoes_unicas_nova RENAME TO transacoes_unicas")

    conn.commit()
    conn.close()


def adicionar_rendimento():
    nome = pedir_input("Nome do rendimento mensal: ")
    if nome is None:
        return

    valor = pedir_input("Valor mensal: ")
    if valor is None:
        return

    valor = float(valor.replace(",", "."))

    conn = conectar_financas()
    cur = conn.cursor()
    cur.execute("INSERT INTO rendimentos (nome, valor) VALUES (?, ?)", (nome, valor))
    conn.commit()
    conn.close()

    print(cor("Rendimento guardado.", "verde"))


def adicionar_gasto():
    nome = pedir_input("Nome do gasto mensal: ")
    if nome is None:
        return

    valor = pedir_input("Valor mensal a gastar: ")
    if valor is None:
        return

    valor = float(valor.replace(",", "."))

    conn = conectar_financas()
    cur = conn.cursor()
    cur.execute("INSERT INTO gastos (nome, valor) VALUES (?, ?)", (nome, valor))
    conn.commit()
    conn.close()

    print(cor("Gasto guardado.", "verde"))


def adicionar_transacao_unica():
    data = pedir_input("Data da transação (AAAA-MM-DD): ")
    if data is None:
        return

    nome = pedir_input("Descrição: ")
    if nome is None:
        return

    valor = pedir_input("Valor (+ entrada / - gasto): ")
    if valor is None:
        return

    valor = float(valor.replace(",", "."))

    conn = conectar_financas()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO transacoes_unicas (data, nome, valor)
        VALUES (?, ?, ?)
    """, (data, nome, valor))

    conn.commit()
    conn.close()

    print(cor("Transação única guardada.", "verde"))


def listar_rendimentos():
    conn = conectar_financas()
    cur = conn.cursor()
    cur.execute("SELECT id, nome, valor, ativo FROM rendimentos ORDER BY id")
    dados = cur.fetchall()
    conn.close()

    print("\n" + cor("=== RENDIMENTOS MENSAIS ===", "azul"))
    print(cor("IEFP automático | calculado pela base iefp_bolsas.db", "rosa"))

    if not dados:
        print(cor("Nenhum rendimento extra registado.", "amarelo"))
        return

    for id_, nome, valor, ativo in dados:
        estado = cor("ativo", "verde") if ativo else cor("inativo", "vermelho")
        print(f"{id_} | {nome} | {valor:.2f} € | {estado}")


def listar_gastos():
    conn = conectar_financas()
    cur = conn.cursor()
    cur.execute("SELECT id, nome, valor, ativo FROM gastos ORDER BY id")
    dados = cur.fetchall()
    conn.close()

    print("\n" + cor("=== GASTOS MENSAIS ===", "azul"))

    if not dados:
        print(cor("Nenhum gasto registado. A poupança será tudo o que receberes.", "verde"))
        return

    for id_, nome, valor, ativo in dados:
        estado = cor("ativo", "verde") if ativo else cor("inativo", "vermelho")
        print(f"{id_} | {nome} | {valor:.2f} € | {estado}")


def listar_transacoes_unicas():
    conn = conectar_financas()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, data, nome, valor
        FROM transacoes_unicas
        ORDER BY data, id
    """)

    dados = cur.fetchall()
    conn.close()

    print("\n" + cor("=== TRANSAÇÕES ÚNICAS ===", "azul"))

    if not dados:
        print(cor("Nenhuma transação única registada.", "amarelo"))
        return

    for id_, data, nome, valor in dados:
        valor_txt = cor(f"{valor:.2f} €", "verde") if valor >= 0 else cor(f"{valor:.2f} €", "vermelho")
        print(f"{id_} | {data} | {nome} | {valor_txt}")


def apagar_rendimento():
    listar_rendimentos()

    id_ = pedir_input("ID do rendimento para apagar: ")
    if id_ is None:
        return

    conn = conectar_financas()
    cur = conn.cursor()
    cur.execute("DELETE FROM rendimentos WHERE id = ?", (id_,))
    apagou = cur.rowcount > 0
    conn.commit()
    conn.close()

    if apagou:
        recalcular_ids("rendimentos")
        print(cor("Rendimento apagado.", "verde"))
    else:
        print(cor("Nenhum rendimento encontrado com esse ID.", "vermelho"))


def apagar_gasto():
    listar_gastos()

    id_ = pedir_input("ID do gasto para apagar: ")
    if id_ is None:
        return

    conn = conectar_financas()
    cur = conn.cursor()
    cur.execute("DELETE FROM gastos WHERE id = ?", (id_,))
    apagou = cur.rowcount > 0
    conn.commit()
    conn.close()

    if apagou:
        recalcular_ids("gastos")
        print(cor("Gasto apagado.", "verde"))
    else:
        print(cor("Nenhum gasto encontrado com esse ID.", "vermelho"))


def apagar_transacao_unica():
    listar_transacoes_unicas()

    id_ = pedir_input("ID da transação para apagar: ")
    if id_ is None:
        return

    conn = conectar_financas()
    cur = conn.cursor()
    cur.execute("DELETE FROM transacoes_unicas WHERE id = ?", (id_,))
    apagou = cur.rowcount > 0
    conn.commit()
    conn.close()

    if apagou:
        recalcular_ids("transacoes_unicas")
        print(cor("Transação apagada.", "verde"))
    else:
        print(cor("Nenhuma transação encontrada com esse ID.", "vermelho"))


def total_rendimentos_extra():
    conn = conectar_financas()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(valor), 0) FROM rendimentos WHERE ativo = 1")
    total = cur.fetchone()[0]
    conn.close()
    return total


def total_gastos():
    conn = conectar_financas()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(valor), 0) FROM gastos WHERE ativo = 1")
    total = cur.fetchone()[0]
    conn.close()
    return total


def total_transacoes_mes(chave_mes):
    conn = conectar_financas()
    cur = conn.cursor()

    cur.execute("""
        SELECT COALESCE(SUM(valor), 0)
        FROM transacoes_unicas
        WHERE substr(data, 1, 7) = ?
    """, (chave_mes,))

    total = cur.fetchone()[0]
    conn.close()
    return total


def calcular_iefp_mes(chave_mes):
    if chave_mes not in HORAS_MES:
        return 0

    try:
        conn = conectar_iefp()
        cur = conn.cursor()

        cur.execute("""
            SELECT COALESCE(SUM(horas), 0)
            FROM faltas
            WHERE substr(data, 1, 7) = ?
        """, (chave_mes,))
        faltas_mes = cur.fetchone()[0]

        cur.execute("""
            SELECT data, horas_previstas
            FROM dias_aula
            WHERE substr(data, 1, 7) = ?
        """, (chave_mes,))
        dias = cur.fetchall()

        cur.execute("""
            SELECT data, COALESCE(SUM(horas), 0)
            FROM faltas
            WHERE substr(data, 1, 7) = ?
            GROUP BY data
        """, (chave_mes,))
        faltas_por_dia = dict(cur.fetchall())

        conn.close()

    except sqlite3.Error:
        return 0

    horas_previstas = HORAS_MES[chave_mes]
    horas_consideradas = max(horas_previstas - faltas_mes, 0)

    bolsa = min(horas_consideradas * VALOR_HORA_BOLSA, LIMITE_MENSAL_BOLSA)

    dias_alimentacao = 0

    for data, horas_dia in dias:
        faltas_dia = faltas_por_dia.get(data, 0)
        horas_vistas = max(horas_dia - faltas_dia, 0)

        if horas_vistas >= MIN_HORAS_ALIMENTACAO:
            dias_alimentacao += 1

    alimentacao = dias_alimentacao * VALOR_ALIMENTACAO_DIA

    return bolsa + alimentacao


def calcular_mes():
    ano = pedir_input("Ano: ")
    if ano is None:
        return

    mes = pedir_input("Mês: ")
    if mes is None:
        return

    chave = f"{ano}-{mes.zfill(2)}"

    iefp = calcular_iefp_mes(chave)
    extras = total_rendimentos_extra()
    gastos = total_gastos()
    transacoes = total_transacoes_mes(chave)

    total_entrada = iefp + extras
    total_final = total_entrada + transacoes
    poupanca = total_final - gastos

    print("\n" + cor("=== RESUMO FINANCEIRO DO MÊS ===", "azul"))
    print(f"Mês: {chave}")
    print(cor(f"IEFP automático: {iefp:.2f} €", "rosa"))
    print(cor(f"Rendimentos extras: {extras:.2f} €", "azul"))

    if transacoes >= 0:
        print(cor(f"Transações únicas: +{transacoes:.2f} €", "verde"))
    else:
        print(cor(f"Transações únicas: {transacoes:.2f} €", "vermelho"))

    print(cor(f"Total antes dos gastos mensais: {total_final:.2f} €", "verde"))
    print(cor(f"Gastos mensais: {gastos:.2f} €", "vermelho"))

    if poupanca >= 0:
        print(cor(f"\033[1mPoupança estimada: {poupanca:.2f} €\033[0m", "verde"))
    else:
        print(cor(f"\033[1mSaldo negativo: {abs(poupanca):.2f} €\033[0m", "vermelho"))


def calcular_longo_prazo():
    inicio = pedir_input("Mês inicial (AAAA-MM): ")
    if inicio is None:
        return

    meses = pedir_input("Quantos meses queres calcular? ")
    if meses is None:
        return

    meses = int(meses)
    data_inicio = datetime.strptime(inicio, "%Y-%m")

    extras = total_rendimentos_extra()
    gastos = total_gastos()

    total_iefp = 0
    total_extras = 0
    total_transacoes = 0
    total_recebido = 0
    total_gastos_geral = 0
    total_poupanca = 0
    acumulado = 0

    print("\n" + cor("=== PROJEÇÃO DE LONGO PRAZO ===", "azul"))

    for i in range(meses):
        data_mes = data_inicio + relativedelta(months=i)
        chave = data_mes.strftime("%Y-%m")

        iefp = calcular_iefp_mes(chave)
        transacoes = total_transacoes_mes(chave)

        recebido = iefp + extras + transacoes
        poupanca = recebido - gastos
        acumulado += poupanca

        total_iefp += iefp
        total_extras += extras
        total_transacoes += transacoes
        total_recebido += recebido
        total_gastos_geral += gastos
        total_poupanca += poupanca

        transacoes_txt = (
            cor(f"Únicas: +{transacoes:.2f} €", "verde")
            if transacoes >= 0
            else cor(f"Únicas: {transacoes:.2f} €", "vermelho")
        )

        poupanca_txt = (
            cor(f"Poupança: {poupanca:.2f} €", "verde")
            if poupanca >= 0
            else cor(f"Negativo: {abs(poupanca):.2f} €", "vermelho")
        )

        acumulado_txt = (
            cor(f"Acumulado: {acumulado:.2f} €", "verde")
            if acumulado >= 0
            else cor(f"Acumulado negativo: {abs(acumulado):.2f} €", "vermelho")
        )

        print(
            f"{chave} | "
            f"{cor(f'IEFP: {iefp:.2f} €', 'rosa')} | "
            f"{cor(f'Extras: {extras:.2f} €', 'azul')} | "
            f"{transacoes_txt} | "
            f"{cor(f'Gastos: {gastos:.2f} €', 'vermelho')} | "
            f"{poupanca_txt} | "
            f"{acumulado_txt}"
        )

    print("\n" + cor("=== TOTAL DA PROJEÇÃO ===", "azul"))
    print(cor(f"Total IEFP: {total_iefp:.2f} €", "rosa"))
    print(cor(f"Total rendimentos extras: {total_extras:.2f} €", "azul"))

    if total_transacoes >= 0:
        print(cor(f"Total transações únicas: +{total_transacoes:.2f} €", "verde"))
    else:
        print(cor(f"Total transações únicas: {total_transacoes:.2f} €", "vermelho"))

    print(cor(f"Total recebido: {total_recebido:.2f} €", "verde"))
    print(cor(f"Total gastos mensais: {total_gastos_geral:.2f} €", "vermelho"))

    if total_poupanca >= 0:
        print(cor(f"\033[1mPOUPANÇA TOTAL: {total_poupanca:.2f} €\033[0m", "verde"))
    else:
        print(cor(f"\033[1mSALDO NEGATIVO TOTAL: {abs(total_poupanca):.2f} €\033[0m", "vermelho"))


def mostrar_grafico_longo_prazo():
    inicio = pedir_input("Mês inicial (AAAA-MM): ")
    if inicio is None:
        return

    meses = pedir_input("Quantos meses queres mostrar no gráfico? ")
    if meses is None:
        return

    meses = int(meses)
    data_inicio = datetime.strptime(inicio, "%Y-%m")

    extras = total_rendimentos_extra()
    gastos = total_gastos()

    meses_lista = []
    valores_iefp = []
    valores_extras = []
    valores_gastos = []
    valores_transacoes = []
    valores_poupanca = []
    valores_acumulado = []

    acumulado = 0

    for i in range(meses):
        data_mes = data_inicio + relativedelta(months=i)
        chave = data_mes.strftime("%Y-%m")

        iefp = calcular_iefp_mes(chave)
        transacoes = total_transacoes_mes(chave)

        recebido = iefp + extras + transacoes
        poupanca = recebido - gastos
        acumulado += poupanca

        meses_lista.append(chave)
        valores_iefp.append(iefp)
        valores_extras.append(extras)
        valores_gastos.append(gastos)
        valores_transacoes.append(transacoes)
        valores_poupanca.append(poupanca)
        valores_acumulado.append(acumulado)

    plt.figure(figsize=(13, 7))

    plt.plot(meses_lista, valores_iefp, marker="o", label="IEFP")
    plt.plot(meses_lista, valores_extras, marker="o", label="Rendimentos extras")
    plt.plot(meses_lista, valores_gastos, marker="o", label="Gastos mensais")
    plt.plot(meses_lista, valores_transacoes, marker="o", label="Transações únicas")
    plt.plot(meses_lista, valores_poupanca, marker="o", label="Poupança mensal")
    plt.plot(meses_lista, valores_acumulado, marker="o", linewidth=3, label="Poupança acumulada")

    plt.title("Projeção financeira - tempo x dinheiro")
    plt.xlabel("Mês")
    plt.ylabel("Valor (€)")
    plt.xticks(rotation=45)
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()

def menu():
    criar_tabelas()

    while True:
        print("\n" + cor("=== FINANÇAS ===", "azul"))
        print("1 - Adicionar rendimento extra mensal")
        print("2 - Adicionar gasto mensal")
        print("3 - Adicionar transação única")
        print("4 - Calcular mês")
        print("5 - Calcular longo prazo")
        print("6 - Ver rendimentos")
        print("7 - Ver gastos")
        print("8 - Ver transações únicas")
        print("9 - Apagar rendimento extra mensal")
        print("10 - Apagar gasto mensal")
        print("11 - Apagar transação única")
        print("12 - Mostrar grafico")
        print("0 - Sair")

        op = input("> ").strip().lower()

        if op == "clear":
            limpar_terminal()
        elif op == "1":
            adicionar_rendimento()
        elif op == "2":
            adicionar_gasto()
        elif op == "3":
            adicionar_transacao_unica()
        elif op == "4":
            calcular_mes()
        elif op == "5":
            calcular_longo_prazo()
        elif op == "6":
            listar_rendimentos()
        elif op == "7":
            listar_gastos()
        elif op == "8":
            listar_transacoes_unicas()
        elif op == "9":
            apagar_rendimento()
        elif op == "10":
            apagar_gasto()
        elif op == "11":
            apagar_transacao_unica()
        elif op == "12":
            mostrar_grafico_longo_prazo()
        elif op == "0":
            break
        elif op == "00":
            print(cor("Nada para cancelar aqui. Escolhe uma opção do menu.", "laranja"))
        else:
            print(cor("Opção inválida.", "vermelho"))


if __name__ == "__main__":
    menu()