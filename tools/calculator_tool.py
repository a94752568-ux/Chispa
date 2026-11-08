import ast
import math
import operator

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "Calculadora segura para expresiones matematicas. Soporta + - * / ** sqrt sin cos tan log exp etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Expresion matematica, ej: 2**10 * 3"}
            },
            "required": ["expression"]
        }
    }
}

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}

_UNOOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_MATH_FUNCS = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
_MATH_CONSTS = {k: getattr(math, k) for k in ("pi", "e", "tau")}


def _eval_node(node):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.BinOp):
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Operador no soportado: {type(node.op).__name__}")
        return op(_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _UNOOPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Operador unario no soportado: {type(node.op).__name__}")
        return op(_eval_node(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Solo se permiten llamadas a funciones directas")
        func = _MATH_FUNCS.get(node.func.id)
        if func is None:
            raise ValueError(f"Funcion no permitida: {node.func.id}")
        args = [_eval_node(a) for a in node.args]
        return func(*args)
    if isinstance(node, ast.Name):
        if node.id in _MATH_CONSTS:
            return _MATH_CONSTS[node.id]
        raise ValueError(f"Variable no permitida: {node.id}")
    raise ValueError(f"Nodo AST no permitido: {type(node).__name__}")


def execute(expression: str) -> str:
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval_node(tree)
        return f"{expression} = {result}"
    except Exception as e:
        return f"Error calculadora: {e}"
