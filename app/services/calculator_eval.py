"""Safe arithmetic evaluation for the global quick calculator (no code execution)."""

from __future__ import annotations

import re
from typing import Any

_ALLOWED = re.compile(r"^[\d+\-*/().\s]+$")


def _tokenize(expr: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    while i < len(expr):
        c = expr[i]
        if c.isspace():
            i += 1
            continue
        if c in "+-*/()":
            tokens.append(c)
            i += 1
            continue
        if c.isdigit() or c == ".":
            j = i
            while j < len(expr) and (expr[j].isdigit() or expr[j] == "."):
                j += 1
            tokens.append(expr[i:j])
            i = j
            continue
        raise ValueError("invalid")
    return tokens


def _parse(tokens: list[str]) -> float:
    pos = 0

    def peek() -> str | None:
        return tokens[pos] if pos < len(tokens) else None

    def consume(expected: str | None = None) -> str:
        nonlocal pos
        t = peek()
        if t is None:
            raise ValueError("unexpected end")
        if expected is not None and t != expected:
            raise ValueError("expected " + expected)
        pos += 1
        return t

    def parse_expr() -> float:
        left = parse_term()
        while peek() in ("+", "-"):
            op = consume()
            right = parse_term()
            left = left + right if op == "+" else left - right
        return left

    def parse_term() -> float:
        left = parse_unary()
        while peek() in ("*", "/"):
            op = consume()
            right = parse_unary()
            if op == "/":
                if right == 0:
                    raise ZeroDivisionError
                left = left / right
            else:
                left = left * right
        return left

    def parse_unary() -> float:
        if peek() == "-":
            consume("-")
            return -parse_unary()
        if peek() == "+":
            consume("+")
            return parse_unary()
        return parse_primary()

    def parse_primary() -> float:
        t = peek()
        if t == "(":
            consume("(")
            v = parse_expr()
            consume(")")
            return v
        if t is None or t in "+-*/)":
            raise ValueError("empty")
        consume()
        return float(t)

    result = parse_expr()
    if pos != len(tokens):
        raise ValueError("trailing")
    return result


def safe_eval(expr: str) -> dict[str, Any]:
    """
    Evaluate a basic arithmetic expression.
    Returns {"ok": True, "value": float} or {"ok": False, "error": str}.
    """
    raw = (expr or "").strip()
    if not raw:
        return {"ok": False, "error": "empty"}
    if not _ALLOWED.match(raw):
        return {"ok": False, "error": "invalid characters"}
    try:
        value = _parse(_tokenize(raw))
    except ZeroDivisionError:
        return {"ok": False, "error": "division by zero"}
    except (ValueError, TypeError, OverflowError):
        return {"ok": False, "error": "invalid expression"}
    if value != value:
        return {"ok": False, "error": "not a number"}
    return {"ok": True, "value": round(value, 10)}
