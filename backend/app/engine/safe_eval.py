"""AST whitelist evaluator for workflow condition expressions.

Replaces raw eval() to prevent code injection via object attribute chains
(e.g. (().__class__.__bases__[0].__subclasses__())). Only pure, side-effect
free boolean/arithmetic logic over JSON-safe values is supported.
"""
import ast
import operator

SAFE_TYPES = (bool, int, float, str, list, dict, tuple, set, type(None))

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARYOPS = {
    ast.Not: operator.not_,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Invert: operator.invert,
}

_CMPOPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

_ALLOWED_FUNCS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "float": float,
    "int": int,
    "isinstance": isinstance,
    "len": len,
    "max": max,
    "min": min,
    "round": round,
    "sorted": sorted,
    "str": str,
    "sum": sum,
}


class UnsafeExpressionError(ValueError):
    pass


def _reject(node: ast.AST) -> None:
    raise UnsafeExpressionError(
        f"Unsupported construct in condition expression: {type(node).__name__}"
    )


def _eval(node: ast.AST, env: dict) -> object:
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        raise NameError(f"Undefined variable: {node.id}")

    if isinstance(node, ast.List):
        return [_eval(e, env) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval(e, env) for e in node.elts)
    if isinstance(node, ast.Set):
        return {_eval(e, env) for e in node.elts}
    if isinstance(node, ast.Dict):
        result = {}
        for k, v in zip(node.keys, node.values):
            result[_eval(k, env)] = _eval(v, env)
        return result

    if isinstance(node, ast.BinOp):
        op = _BINOPS.get(type(node.op))
        if op is None:
            _reject(node.op)
        return op(_eval(node.left, env), _eval(node.right, env))

    if isinstance(node, ast.UnaryOp):
        op = _UNARYOPS.get(type(node.op))
        if op is None:
            _reject(node.op)
        return op(_eval(node.operand, env))

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result = True
            for v in node.values:
                result = _eval(v, env)
                if not result:
                    break
            return result
        if isinstance(node.op, ast.Or):
            result = False
            for v in node.values:
                result = _eval(v, env)
                if result:
                    break
            return result
        _reject(node.op)

    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        for op_node, comparator in zip(node.ops, node.comparators):
            op = _CMPOPS.get(type(op_node))
            if op is None:
                _reject(op_node)
            right = _eval(comparator, env)
            if not op(left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.IfExp):
        return _eval(node.body, env) if _eval(node.test, env) else _eval(node.orelse, env)

    if isinstance(node, ast.Attribute):
        obj = _eval(node.value, env)
        if not isinstance(obj, SAFE_TYPES):
            raise UnsafeExpressionError(
                f"Attribute access on non-JSON type: {type(obj).__name__}"
            )
        if node.attr.startswith("_"):
            raise UnsafeExpressionError(
                f"Attribute access to dunder/private name: {node.attr}"
            )
        if isinstance(obj, dict) and node.attr in obj:
            return obj[node.attr]
        return getattr(obj, node.attr)

    if isinstance(node, ast.Subscript):
        obj = _eval(node.value, env)
        if not isinstance(obj, SAFE_TYPES):
            raise UnsafeExpressionError(
                f"Subscript on non-JSON type: {type(obj).__name__}"
            )
        index = _eval(node.slice, env)
        if not isinstance(index, SAFE_TYPES):
            raise UnsafeExpressionError(
                f"Subscript index of non-JSON type: {type(index).__name__}"
            )
        return obj[index]

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise UnsafeExpressionError("Function calls must use whitelisted names")
        fn = _ALLOWED_FUNCS.get(node.func.id)
        if fn is None:
            raise UnsafeExpressionError(
                f"Function not whitelisted: {node.func.id}"
            )
        if node.keywords:
            raise UnsafeExpressionError("Keyword arguments are not supported")
        args = [_eval(a, env) for a in node.args]
        for arg in args:
            if not isinstance(arg, SAFE_TYPES):
                raise UnsafeExpressionError(
                    f"Argument of non-JSON type: {type(arg).__name__}"
                )
        return fn(*args)

    _reject(node)


def safe_eval(expression: str, env: dict) -> object:
    if not isinstance(expression, str):
        raise TypeError("Condition expression must be a string")
    tree = ast.parse(expression, mode="eval")
    return _eval(tree.body, env)