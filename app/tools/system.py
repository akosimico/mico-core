from __future__ import annotations

import ast
import math
import operator
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.tools.base import Tool

# Common timezone alias mappings
TIMEZONE_ALIASES: dict[str, str] = {
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "est": "America/New_York",
    "edt": "America/New_York",
    "cst": "America/Chicago",
    "cdt": "America/Chicago",
    "mst": "America/Denver",
    "mdt": "America/Denver",
    "gmt": "UTC",
    "utc": "UTC",
    "bst": "Europe/London",
    "cet": "Europe/Paris",
    "jst": "Asia/Tokyo",
    "pht": "Asia/Manila",
    "manila": "Asia/Manila",
    "tokyo": "Asia/Tokyo",
    "london": "Europe/London",
    "new york": "America/New_York",
    "los angeles": "America/Los_Angeles",
    "singapore": "Asia/Singapore",
    "sgt": "Asia/Singapore",
}


def get_time(timezone_name: str = "UTC") -> str:
    """
    Get current date and time in the specified timezone.
    Returns human-friendly string with date, time, and timezone.
    """
    tz_clean = timezone_name.strip().lower()
    target_tz: ZoneInfo | timezone = timezone.utc

    if tz_clean in ("local", "system", ""):
        now = datetime.now().astimezone()
        return (
            f"The current local time is {now.strftime('%I:%M:%S %p')} on {now.strftime('%A, %B %d, %Y')} "
            f"({now.tzname() or 'Local Time'})."
        )

    resolved_name = TIMEZONE_ALIASES.get(tz_clean, timezone_name.strip())

    try:
        target_tz = ZoneInfo(resolved_name)
    except ZoneInfoNotFoundError:
        # Fallback to UTC if timezone not recognized
        now = datetime.now(timezone.utc)
        return (
            f"Timezone '{timezone_name}' was not recognized, so here is UTC time: "
            f"{now.strftime('%I:%M:%S %p')} on {now.strftime('%A, %B %d, %Y')} (UTC)."
        )

    now = datetime.now(target_tz)
    return (
        f"The current time in {resolved_name} is {now.strftime('%I:%M:%S %p')} on "
        f"{now.strftime('%A, %B %d, %Y')} ({now.tzname() or resolved_name})."
    )


# Allowed operators and functions for safe calculator
SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

SAFE_FUNCS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "abs": abs,
    "round": round,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "ceil": math.ceil,
    "floor": math.floor,
}

SAFE_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
}


def _eval_node(node: ast.AST) -> float | int:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value)}")

    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type in SAFE_OPS:
            operand = _eval_node(node.operand)
            return SAFE_OPS[op_type](operand)
        raise ValueError(f"Unsupported unary operator: {op_type}")

    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type in SAFE_OPS:
            left = _eval_node(node.left)
            right = _eval_node(node.right)
            if op_type in (ast.Div, ast.FloorDiv, ast.Mod) and right == 0:
                raise ZeroDivisionError("Division by zero")
            if op_type == ast.Pow and right > 1000:
                raise ValueError("Exponent too large (max 1000)")
            return SAFE_OPS[op_type](left, right)
        raise ValueError(f"Unsupported binary operator: {op_type}")

    if isinstance(node, ast.Name):
        name_lower = node.id.lower()
        if name_lower in SAFE_CONSTANTS:
            return SAFE_CONSTANTS[name_lower]
        raise ValueError(f"Unknown variable or constant: {node.id}")

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only direct math function calls are allowed")
        func_name = node.func.id.lower()
        if func_name not in SAFE_FUNCS:
            raise ValueError(f"Function '{func_name}' is not allowed in calculator")
        args = [_eval_node(arg) for arg in node.args]
        return SAFE_FUNCS[func_name](*args)

    raise ValueError(f"Unsupported expression element: {type(node).__name__}")


def calculator(expression: str) -> str:
    """
    Safely evaluate a mathematical expression.
    Supports standard arithmetic (+, -, *, /, //, %, **), constants (pi, e),
    and functions (sqrt, sin, cos, tan, abs, round, log, exp).
    """
    cleaned = expression.strip()
    if not cleaned:
        return "Error: Expression cannot be empty."

    try:
        parsed = ast.parse(cleaned, mode="eval")
        result = _eval_node(parsed)
        # Format nice float or int
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return f"{expression} = {result}"
    except ZeroDivisionError:
        return "Error: Division by zero."
    except Exception as exc:
        return f"Calculation error: {exc}"


get_time_tool = Tool(
    name="get_time",
    description="Get the current date and time in a specific timezone or city (e.g. 'UTC', 'Asia/Tokyo', 'America/New_York', or 'local').",
    parameters={
        "type": "object",
        "properties": {
            "timezone_name": {
                "type": "string",
                "description": "Timezone or city name (e.g. 'UTC', 'Asia/Tokyo', 'America/New_York', 'PST', 'local'). Defaults to 'UTC'.",
            }
        },
        "required": [],
    },
    func=get_time,
)

calculator_tool = Tool(
    name="calculator",
    description="Calculate the result of a mathematical expression (e.g. '12 * 45', 'sqrt(144) + 10', '2 ** 8').",
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Mathematical expression to evaluate (e.g. '25 * 4', 'sqrt(81)', '(100 - 25) / 5').",
            }
        },
        "required": ["expression"],
    },
    func=calculator,
)
