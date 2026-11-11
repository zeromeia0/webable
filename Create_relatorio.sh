#!/usr/bin/env bash
# Create_relatorio.sh — gera o Relatório de Gastos de uma vez.
#
#   ./Create_relatorio.sh                      -> usa o Extracto*.pdf mais recente em ~/Downloads
#   ./Create_relatorio.sh caminho/extracto.pdf -> usa esse ficheiro
#
# O relatório é guardado em ~/money/Relatorio_Gastos_<Mês>_<Ano>.pdf e aberto no fim.
# Muda OUT_DIR / SEARCH_DIR abaixo se quiseres outras pastas.
set -euo pipefail

OUT_DIR="$HOME/money"
SEARCH_DIR="$HOME/Downloads"
DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

# 1. Escolher o extracto
if [ $# -ge 1 ]; then
    EXTRACTO="$1"
else
    EXTRACTO="$(ls -t "$SEARCH_DIR"/Extracto*.pdf 2>/dev/null | head -1 || true)"
    if [ -z "$EXTRACTO" ]; then
        echo "Nenhum Extracto*.pdf em $SEARCH_DIR. Uso: $0 caminho/extracto.pdf" >&2
        exit 1
    fi
fi
[ -f "$EXTRACTO" ] || { echo "Ficheiro não encontrado: $EXTRACTO" >&2; exit 1; }
echo "Extracto: $EXTRACTO"

# 2. Mostrar os movimentos e categorias (para conferires)
echo
echo "=== Movimentos ==="
"$DIR/create_relatorio" "$EXTRACTO" --list

# 3. Gerar o PDF em ~/money
mkdir -p "$OUT_DIR"
echo
echo "=== Relatório ==="
OUTPUT="$(cd "$OUT_DIR" && "$DIR/create_relatorio" "$EXTRACTO")"
echo "$OUTPUT"

# 4. Abrir o PDF (se houver visualizador)
PDF="$(printf '%s\n' "$OUTPUT" | sed -n 's/^Relatório criado: //p')"
if [ -n "$PDF" ] && command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$PDF" >/dev/null 2>&1 &
fi
