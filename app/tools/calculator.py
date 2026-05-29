from __future__ import annotations

import ast
import operator
import re
import time
from typing import Any

from app.schemas.tools import ToolResult


_ALLOWED_BINOPS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
_ALLOWED_UNARYOPS: dict[type[ast.unaryop], Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _extract_expression(message: str) -> str | None:
    normalized = message.strip().replace("×", "*").replace("x", "*")
    percent_match = re.search(
        r"(\d+(?:\.\d+)?)\s*%\s*(?:of|của)\s*(\d+(?:\.\d+)?)",
        normalized,
        flags=re.IGNORECASE,
    )
    if percent_match:
        left, right = percent_match.groups()
        return f"({left}/100)*({right})"

    candidate = re.sub(r"[^0-9+\-*/().%\s]", " ", normalized)
    candidate = " ".join(candidate.split())
    if not candidate or not re.search(r"[0-9]", candidate):
        return None
    if not re.search(r"[+\-*/%()]", candidate):
        return None
    return candidate


def _eval_ast(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        left = _eval_ast(node.left)
        right = _eval_ast(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 12:
            raise ValueError("Exponent too large.")
        return float(_ALLOWED_BINOPS[type(node.op)](left, right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
        return float(_ALLOWED_UNARYOPS[type(node.op)](_eval_ast(node.operand)))
    raise ValueError("Unsupported expression.")


async def execute_calculator(message: str, context: dict[str, Any] | None = None) -> ToolResult:
    started = time.perf_counter()
    expression = _extract_expression(message)
    if not expression:
        return ToolResult(
            name="calculator",
            success=False,
            content="Unable to find a safe arithmetic expression to evaluate.",
            error="invalid_expression",
            confidence="low",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    try:
        parsed = ast.parse(expression, mode="eval")
        value = _eval_ast(parsed)
    except Exception:
        return ToolResult(
            name="calculator",
            success=False,
            content="Expression could not be safely evaluated.",
            error="invalid_expression",
            confidence="low",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    value_out = int(value) if value.is_integer() else round(value, 8)
    return ToolResult(
        name="calculator",
        success=True,
        content=f"{expression} = {value_out}",
        data={"expression": expression, "result": value_out},
        confidence="high",
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
