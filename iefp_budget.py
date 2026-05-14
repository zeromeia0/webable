import sqlite3
import math
import os
def limpar_terminal():
    os.system('cls' if os.name == 'nt' else 'clear')

DB_NAME = "iefp_bolsas.db"

VALOR_HORA_BOLSA = 2.06
LIMITE_MENSAL_BOLSA = 268.57
VALOR_ALIMENTACAO_DIA = 6.15
MIN_HORAS_ALIMENTACAO = 3

MODULOS = [
    ("00245", "Desenvolver algoritmos", 25),
    ("00598", "Efetuar operações e cálculos matemáticos", 50),
    ("00599", "Inglês nas atividades do setor da informática", 50),
    ("00600", "Funções e estrutura da organização", 25),
    ("00602", "Bases de dados relacionais", 25),
    ("00606", "Programas em linguagem estruturada", 50),
    ("00613", "Políticas de segurança em sistemas informáticos", 25),
    ("00616", "Segurança e saúde no trabalho", 25),
    ("00631", "Infraestrutura de redes locais", 50),
    ("00633", "Sistemas operativos de servidor", 50),
    ("00634", "Sistema operativo de cliente", 25),
    ("00635", "Serviços de rede", 25),
    ("01476", "Legislação relativa à cibersegurança", 25),
    ("01477", "Métodos estatísticos", 50),
    ("01478", "Configurar redes de computadores", 25),
    ("01479", "Proteção contra ameaças cibernéticas", 25),
    ("01480", "Evidências de ataques cibernéticos", 50),
    ("01481", "Scripts aplicados à cibersegurança", 25),
    ("01482", "Normalização e filtragem de logs", 50),
    ("01483", "Vulnerabilidades em soluções web", 50),
    ("01484", "Vulnerabilidades em sistemas de rede", 50),
    ("01485", "Ferramentas de análise e recolha de logs", 50),
    ("01486", "Sistemas de deteção de intrusos IDS", 50),
    ("01487", "Wargaming cibersegurança", 50),
    ("01488", "Segurança da informação e criptografia", 25),
    ("01489", "Análise forense digital", 50),
    ("01490", "Hacking ético", 25),
    ("FPCT", "Formação Prática em Contexto de Trabalho", 500),
    ("Proj", "Apresentação do projeto final", 18),
]

HORAS_MES = {
    "2026-04": 36,
    "2026-05": 119,
    "2026-06": 118,
    "2026-07": 138,
    "2026-08": 60,
    "2026-09": 132,
    "2026-10": 126,
    "2026-11": 117,
    "2026-12": 36,
    "2027-01": 120,
    "2027-02": 97,
    "2027-03": 138,
    "2027-04": 132,
    "2027-05": 120,
    "2027-06": 54,
}


def gerar_dias(dias, horas):
    return dict(zip(dias, horas))


DIAS_AULA = {}

DIAS_AULA.update(gerar_dias(
    ["2026-04-22", "2026-04-23", "2026-04-24", "2026-04-27", "2026-04-28", "2026-04-29", "2026-04-30"],
    [3, 6, 3, 6, 6, 6, 6]
))

DIAS_AULA.update(gerar_dias(
    [f"2026-05-{d:02d}" for d in [4,5,6,7,8,11,12,13,14,15,18,19,20,21,22,25,26,27,28,29]],
    [5] + [6] * 19
))

DIAS_AULA.update(gerar_dias(
    [f"2026-06-{d:02d}" for d in [1,2,3,4,5,8,9,10,11,12,15,16,17,18,19,22,23,24,25,26,29,30]],
    [6,6,6,3,3,6,6,6,6,3,6,6,6,6,6,6,6,6,6,3,4,6]
))

DIAS_AULA.update(gerar_dias(
    [f"2026-07-{d:02d}" for d in [1,2,3,6,7,8,9,10,13,14,15,16,17,20,21,22,23,24,27,28,29,30,31]],
    [6] * 23
))

DIAS_AULA.update(gerar_dias(
    [f"2026-08-{d:02d}" for d in [3,4,5,6,7,10,11,12,13,14]],
    [6] * 10
))

DIAS_AULA.update(gerar_dias(
    [f"2026-09-{d:02d}" for d in [1,2,3,4,7,8,9,10,11,14,15,16,17,18,21,22,23,24,25,28,29,30]],
    [6] * 22
))

DIAS_AULA.update(gerar_dias(
    [f"2026-10-{d:02d}" for d in [1,2,6,7,8,9,12,13,14,15,16,19,20,21,22,23,26,27,28,29,30]],
    [6] * 21
))

DIAS_AULA.update(gerar_dias(
    [f"2026-11-{d:02d}" for d in [2,3,4,5,6,9,10,11,12,13,16,17,18,19,20,23,24,25,26,27]],
    [6] * 19 + [3]
))

DIAS_AULA.update(gerar_dias(
    [f"2026-12-{d:02d}" for d in [2,3,4,9,10,11]],
    [6,6,6,6,6,6]
))

DIAS_AULA.update(gerar_dias(
    [f"2027-01-{d:02d}" for d in [4,5,6,7,8,11,12,13,14,15,18,19,20,21,22,25,26,27,28,29]],
    [6] * 20
))

DIAS_AULA.update(gerar_dias(
    [f"2027-02-{d:02d}" for d in [1,2,3,4,5,10,11,12,15,16,17,18,19,22,23,24,25,26]],
    [5,5,5,5,6,6,6,6,6,6,6,6,6,6,6,6,6,5]
))

DIAS_AULA.update(gerar_dias(
    [f"2027-03-{d:02d}" for d in [1,2,3,4,5,8,9,10,11,12,15,16,17,18,19,22,23,24,25,26,29,30,31]],
    [6] * 23
))

DIAS_AULA.update(gerar_dias(
    [f"2027-04-{d:02d}" for d in [1,2,5,6,7,8,9,12,13,14,15,16,19,20,21,22,23,26,27,28,29,30]],
    [6] * 22
))

DIAS_AULA.update(gerar_dias(
    [f"2027-05-{d:02d}" for d in [3,4,5,6,7,10,11,12,13,14,17,18,19,20,21,24,25,26,28,31]],
    [6] * 20
))

DIAS_AULA.update(gerar_dias(
    [f"2027-06-{d:02d}" for d in [1,2,3,4,7,8,9,10,11]],
    [6] * 9
))


def conectar():
    return sqlite3.connect(DB_NAME)


def cor(texto, nome):
    cores = {
        "verde": "\033[92m",
        "amarelo": "\033[93m",
        "vermelho": "\033[91m",
        "azul": "\033[94m",
        "rosa": "\033[38;5;218m",  # rosa claro
        "laranja": "\033[38;5;215m",
        "bold": "\033[1m",
        "fim": "\033[0m",
    }
    return f"{cores.get(nome, '')}{texto}{cores['fim']}"


def ordenar_codigo(codigo):
    if codigo.isdigit():
        return (0, int(codigo))
    return (1, codigo)


def criar_tabelas():
    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS modulos (
            codigo TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            total_horas REAL NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS dias_aula (
            data TEXT PRIMARY KEY,
            horas_previstas REAL NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS faltas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            modulo TEXT NOT NULL,
            horas REAL NOT NULL,
            observacao TEXT
        )
    """)

    conn.commit()
    conn.close()


def carregar_dados_iniciais():
    conn = conectar()
    cur = conn.cursor()

    for codigo, nome, horas in MODULOS:
        cur.execute("""
            INSERT INTO modulos (codigo, nome, total_horas)
            VALUES (?, ?, ?)
            ON CONFLICT(codigo) DO UPDATE SET
                nome = excluded.nome,
                total_horas = excluded.total_horas
        """, (codigo, nome, horas))

    for data, horas in DIAS_AULA.items():
        cur.execute("""
            INSERT INTO dias_aula (data, horas_previstas)
            VALUES (?, ?)
            ON CONFLICT(data) DO UPDATE SET
                horas_previstas = excluded.horas_previstas
        """, (data, horas))

    conn.commit()
    conn.close()

def cor(texto, nome):
    cores = {
        "verde": "\033[92m",
        "amarelo": "\033[93m",
        "vermelho": "\033[91m",
        "azul": "\033[94m",
        "rosa": "\033[95m",
        "bold": "\033[1m",
        "fim": "\033[0m",
    }
    return f"{cores.get(nome, '')}{texto}{cores['fim']}"

def adicionar_falta():
    data = input("Data da falta (AAAA-MM-DD): ").strip()
    modulo = input("Código do módulo: ").strip()
    horas = float(input("Quantas horas faltaste? ").replace(",", "."))
    obs = input("Observação opcional: ").strip()

    conn = conectar()
    cur = conn.cursor()

    cur.execute("SELECT codigo FROM modulos WHERE codigo = ?", (modulo,))
    if not cur.fetchone():
        print(cor("Esse módulo não existe.", "vermelho"))
        conn.close()
        return

    cur.execute("SELECT horas_previstas FROM dias_aula WHERE data = ?", (data,))
    dia = cur.fetchone()

    if not dia:
        print(cor("Esse dia não está marcado como dia de aula no cronograma.", "vermelho"))
        conn.close()
        return

    horas_previstas = dia[0]

    cur.execute("""
        SELECT COALESCE(SUM(horas), 0)
        FROM faltas
        WHERE data = ?
    """, (data,))
    faltas_ja_registadas = cur.fetchone()[0]

    if faltas_ja_registadas + horas > horas_previstas:
        print(cor("Erro: as faltas desse dia passam as horas previstas.", "vermelho"))
        conn.close()
        return

    cur.execute("""
        INSERT INTO faltas (data, modulo, horas, observacao)
        VALUES (?, ?, ?, ?)
    """, (data, modulo, horas, obs))

    conn.commit()
    conn.close()

    print(cor("Falta guardada.", "verde"))


def calcular_mes():
    ano = input("Ano: ").strip()
    mes = input("Mês: ").strip().zfill(2)
    chave = f"{ano}-{mes}"

    if chave not in HORAS_MES:
        print(cor("Mês fora do cronograma.", "vermelho"))
        return

    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        SELECT COALESCE(SUM(horas), 0)
        FROM faltas
        WHERE substr(data, 1, 7) = ?
    """, (chave,))
    faltas_mes = cur.fetchone()[0]

    cur.execute("""
        SELECT data, horas_previstas
        FROM dias_aula
        WHERE substr(data, 1, 7) = ?
        ORDER BY data
    """, (chave,))
    dias = cur.fetchall()

    cur.execute("""
        SELECT data, COALESCE(SUM(horas), 0)
        FROM faltas
        WHERE substr(data, 1, 7) = ?
        GROUP BY data
    """, (chave,))
    faltas_por_dia = dict(cur.fetchall())

    conn.close()

    horas_previstas_mes = HORAS_MES[chave]
    horas_consideradas = max(horas_previstas_mes - faltas_mes, 0)

    bolsa_prevista = min(horas_previstas_mes * VALOR_HORA_BOLSA, LIMITE_MENSAL_BOLSA)
    bolsa_final = min(horas_consideradas * VALOR_HORA_BOLSA, LIMITE_MENSAL_BOLSA)

    dias_alimentacao = 0
    dias_sem_alimentacao = []

    for data, horas_dia in dias:
        faltas_dia = faltas_por_dia.get(data, 0)
        horas_vistas = max(horas_dia - faltas_dia, 0)

        if horas_vistas >= MIN_HORAS_ALIMENTACAO:
            dias_alimentacao += 1
        else:
            dias_sem_alimentacao.append((data, horas_dia, faltas_dia, horas_vistas))

    alimentacao = dias_alimentacao * VALOR_ALIMENTACAO_DIA
    total = bolsa_final + alimentacao

    print("\n" + cor("=== RESUMO DO MÊS ===", "azul"))
    print(f"Mês: {chave}")
    print(f"Horas previstas: {horas_previstas_mes}h")
    print(f"Horas faltadas: {faltas_mes}h")
    print(f"Horas consideradas: {horas_consideradas}h")
    print(f"Bolsa prevista: {bolsa_prevista:.2f} €")
    print(f"Bolsa após faltas: {bolsa_final:.2f} €")
    print(f"Perda na bolsa: {(bolsa_prevista - bolsa_final):.2f} €")
    print(f"Dias previstos com aula: {len(dias)}")
    print(f"Dias com alimentação: {dias_alimentacao}")
    print(f"Subsídio alimentação: {alimentacao:.2f} €")
    print(cor(f"Total estimado: {total:.2f} €", "verde"))

    if dias_sem_alimentacao:
        print("\n" + cor("Dias sem alimentação por causa das faltas:", "vermelho"))
        for data, previstas, faltadas, vistas in dias_sem_alimentacao:
            print(f"{data} | Previstas: {previstas}h | Faltaste: {faltadas}h | Viste: {vistas}h")


def ver_faltas_por_modulo():
    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        SELECT m.codigo, m.nome, m.total_horas, COALESCE(SUM(f.horas), 0)
        FROM modulos m
        LEFT JOIN faltas f ON m.codigo = f.modulo
        GROUP BY m.codigo, m.nome, m.total_horas
    """)

    dados = sorted(cur.fetchall(), key=lambda x: ordenar_codigo(x[0]))
    conn.close()

    print("\n" + cor("=== FALTAS POR MÓDULO ===", "azul"))

    for codigo, nome, total, faltas in dados:
        limite = math.ceil(total * 0.10)
        restante = limite - faltas

        atual = cor(f"Atual: {faltas}h", "amarelo")
        limite_txt = cor(f"Limite: {limite}h", "vermelho")

        if faltas == 0:
            estado = cor("OK", "verde")
        elif restante > 0:
            estado = cor(f"Ainda podes faltar {restante}h", "amarelo")
        elif restante == 0:
            estado = cor("No limite", "amarelo")
        else:
            estado = cor(f"PASSASTE {abs(restante)}h", "vermelho")

        print(f"{codigo:>5} | {atual} | {limite_txt} | {estado} | {nome}")


def listar_faltas():
    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        SELECT f.id, f.data, f.modulo, m.nome, f.horas, m.total_horas, f.observacao
        FROM faltas f
        LEFT JOIN modulos m ON f.modulo = m.codigo
        ORDER BY f.data
    """)

    dados = cur.fetchall()
    conn.close()

    if not dados:
        print(cor("Sem faltas registadas.", "verde"))
        return

    for id_, data, modulo, nome, horas, total_horas, obs in dados:
        limite = math.ceil(total_horas * 0.10)

        print(
            f"{id_} | {data} | {modulo} - {nome} | "
            f"{cor(f'Atual: {horas}h', 'amarelo')} | "
            f"{cor(f'Limite: {limite}h', 'vermelho')} | "
            f"{obs or ''}"
        )


def recalcular_ids_faltas():
    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE faltas_nova (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            modulo TEXT NOT NULL,
            horas REAL NOT NULL,
            observacao TEXT
        )
    """)

    cur.execute("""
        INSERT INTO faltas_nova (data, modulo, horas, observacao)
        SELECT data, modulo, horas, observacao
        FROM faltas
        ORDER BY data, id
    """)

    cur.execute("DROP TABLE faltas")
    cur.execute("ALTER TABLE faltas_nova RENAME TO faltas")

    conn.commit()
    conn.close()


def apagar_falta():
    listar_faltas()
    id_ = input("ID da falta para apagar: ").strip()

    conn = conectar()
    cur = conn.cursor()

    cur.execute("DELETE FROM faltas WHERE id = ?", (id_,))

    apagou = cur.rowcount > 0

    conn.commit()
    conn.close()

    if apagou:
        recalcular_ids_faltas()
        print(cor("Falta apagada e IDs recalculados.", "verde"))
    else:
        print(cor("Nenhuma falta encontrada com esse ID.", "vermelho"))


def calcular_todos_os_meses():
    total_geral = 0

    print("\n" + cor("=== TOTAL ESTIMADO DE TODOS OS MESES ===", "azul"))

    for chave in sorted(HORAS_MES.keys()):
        conn = conectar()
        cur = conn.cursor()

        cur.execute("""
            SELECT COALESCE(SUM(horas), 0)
            FROM faltas
            WHERE substr(data, 1, 7) = ?
        """, (chave,))
        faltas_mes = cur.fetchone()[0]

        cur.execute("""
            SELECT data, horas_previstas
            FROM dias_aula
            WHERE substr(data, 1, 7) = ?
            ORDER BY data
        """, (chave,))
        dias = cur.fetchall()

        cur.execute("""
            SELECT data, COALESCE(SUM(horas), 0)
            FROM faltas
            WHERE substr(data, 1, 7) = ?
            GROUP BY data
        """, (chave,))
        faltas_por_dia = dict(cur.fetchall())

        conn.close()

        horas_previstas = HORAS_MES[chave]
        horas_consideradas = max(horas_previstas - faltas_mes, 0)

        bolsa_prevista = min(horas_previstas * VALOR_HORA_BOLSA, LIMITE_MENSAL_BOLSA)
        bolsa_final = min(horas_consideradas * VALOR_HORA_BOLSA, LIMITE_MENSAL_BOLSA)

        dias_alimentacao_previstos = len(dias)
        dias_alimentacao = 0

        for data, horas_dia in dias:
            faltas_dia = faltas_por_dia.get(data, 0)
            horas_vistas = max(horas_dia - faltas_dia, 0)

            if horas_vistas >= MIN_HORAS_ALIMENTACAO:
                dias_alimentacao += 1

        alimentacao_prevista = dias_alimentacao_previstos * VALOR_ALIMENTACAO_DIA
        alimentacao_final = dias_alimentacao * VALOR_ALIMENTACAO_DIA

        total_previsto = bolsa_prevista + alimentacao_prevista
        total_mes = bolsa_final + alimentacao_final
        total_perdido = total_previsto - total_mes

        total_geral += total_mes

        horas_previstas_txt = cor(f"Horas previstas: {horas_previstas}h", "azul")

        if faltas_mes > 0:
            faltas_txt = cor(f"Faltas: {faltas_mes}h", "amarelo")
        else:
            faltas_txt = cor("Faltas: 0h", "azul")

        alimentacao_txt = cor(
            f"Alimentação: {dias_alimentacao}/{dias_alimentacao_previstos} dias "
            f"({alimentacao_final:.2f} €)",
            "rosa"
        )

        if total_perdido > 0:
            perdido_txt = cor(f"Perdido: {total_perdido:.2f} €", "vermelho")
        else:
            perdido_txt = cor(f"Perdido: {total_perdido:.2f} €", "laranja")
        total_txt = cor(f"Total: {total_mes:.2f} €", "verde")

        print(
            f"{chave} | "
            f"{horas_previstas_txt} | "
            f"{faltas_txt} | "
            f"{alimentacao_txt} | "
            f"{perdido_txt} | "
            f"{total_txt}"
        )

    print("\n" + cor(f"\033[1mTOTAL GERAL ESTIMADO: {total_geral:.2f} €\033[0m", "verde"))


def menu():
    criar_tabelas()
    carregar_dados_iniciais()

    while True:
        print("\n" + cor("=== IEFP ===", "azul"))
        print("1 - Adicionar falta")
        print("2 - Calcular mês")
        print("3 - Ver faltas por módulo")
        print("4 - Ver faltas registadas")
        print("5 - Apagar falta")
        print("6 - Calcular todos os meses")
        print("7 - Sair")

        op = input("> ").strip().lower()

        if op == "clear":
            limpar_terminal()

        elif op == "1":
            adicionar_falta()
        elif op == "2":
            calcular_mes()
        elif op == "3":
            ver_faltas_por_modulo()
        elif op == "4":
            listar_faltas()
        elif op == "5":
            apagar_falta()
        elif op == "6":
            calcular_todos_os_meses()
        elif op == "7":
            break
        else:
            print(cor("Opção inválida.", "vermelho"))


if __name__ == "__main__":
    menu()