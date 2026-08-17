import builtins
import types


RESTRICTED_BUILTINS: set[str] = {
    "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes",
    "chr", "complex", "dict", "divmod", "enumerate", "filter", "float",
    "format", "frozenset", "hex", "int", "iter", "len", "list", "map",
    "max", "min", "next", "object", "oct", "ord", "pow", "range",
    "repr", "reversed", "round", "set", "slice", "sorted", "str",
    "sum", "tuple", "type", "zip", "True", "False", "None",
    "hash", "id", "isinstance", "issubclass",
}


class ExecutionError(Exception):
    pass


class SkillExecutor:
    def __init__(self):
        self._skills: dict[str, types.FunctionType] = {}

    def register(self, skill_id: str, code: str) -> None:
        safe_builtins = {
            k: v for k, v in builtins.__dict__.items()
            if k in RESTRICTED_BUILTINS
        }
        global_ns = {"__builtins__": safe_builtins}
        local_ns: dict = {}
        try:
            exec(code, global_ns, local_ns)
        except Exception as e:
            raise ExecutionError(f"Failed to compile skill {skill_id}: {e}") from e

        func_name = None
        for name, obj in local_ns.items():
            if isinstance(obj, types.FunctionType):
                func_name = name
                break

        if not func_name:
            raise ExecutionError(
                f"No function defined in skill code for {skill_id}"
            )

        self._skills[skill_id] = local_ns[func_name]

    def unregister(self, skill_id: str) -> None:
        self._skills.pop(skill_id, None)

    def list(self) -> list[str]:
        return list(self._skills.keys())

    async def execute(self, skill_id: str, params: dict | None = None) -> dict:
        func = self._skills.get(skill_id)
        if not func:
            return {"error": f"Skill not found: {skill_id}"}

        try:
            result = func(**(params or {}))
            if hasattr(result, "__await__"):
                result = await result
            return {"result": result}
        except Exception as e:
            return {"error": str(e)}
