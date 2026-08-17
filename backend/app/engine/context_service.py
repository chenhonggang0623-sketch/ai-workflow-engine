import json
import logging

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONTEXT_CHARS = 64_000
DEFAULT_MAX_NODE_OUTPUT_CHARS = 50_000


class ContextService:
    """执行期全局上下文的共享与归一化。

    - build_agent_context: 按节点 input_mapping 声明，从全局 ctx 提取上游产出，
      作为该 agent 节点的共享上下文（不再恒为空 dict）。
    - select_context_text: 把共享上下文渲染成紧凑文本（截断保护）。
    - normalize_output: 异构 provider 输出归一化为统一契约，写入 ctx。
    """

    def __init__(
        self,
        max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
        max_node_output_chars: int = DEFAULT_MAX_NODE_OUTPUT_CHARS,
    ):
        self._max_context_chars = max_context_chars
        self._max_node_output_chars = max_node_output_chars

    def build_agent_context(
        self,
        node,
        node_input: dict,
        ctx: dict,
    ) -> dict:
        """按节点 input_mapping.target 提取 ctx 键值，作为共享上下文。

        逻辑：
        - 每个 input_mapping.target 若在全局 ctx 中存在，原样携带；
        - 总是追加全局 requirement（原始需求）与 _context_meta 摘要；
        - 结果浅拷贝，绝不让节点拿到整个 ctx。
        """
        shared: dict[str, object] = {}
        for mapping in getattr(node, "input_mapping", []) or []:
            target = mapping.target
            if target and target in ctx:
                shared[target] = ctx[target]
            elif target and target in node_input:
                shared[target] = node_input[target]

        requirement = ctx.get("requirement") or ctx.get("_requirement")
        if requirement is not None:
            shared.setdefault("requirement", requirement)

        upstream = []
        for n in getattr(node, "input_mapping", []) or []:
            if getattr(n, "target", None) in ctx:
                upstream.append(f"{n.source} -> {n.target}")
        shared["_context_meta"] = {
            "node": getattr(node, "id", None),
            "upstream_keys": sorted(upstream),
        }
        return shared

    def build_context_text(self, context: dict) -> str:
        """把共享上下文序列化为紧凑文本，带截断保护。"""
        if not context:
            return ""
        try:
            text = json.dumps(context, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(context)
        if len(text) > self._max_context_chars:
            text = text[: self._max_context_chars] + "\n...(context truncated)"
        return text

    def normalize_output(self, provider: str, raw: dict) -> dict:
        """异构 provider 输出 → 统一契约。

        返回 {"text", "structured", "provider", "empty", "truncated"}
        """
        raw = raw or {}
        text: str | None = None
        structured: dict = {}

        if "output" in raw and isinstance(raw.get("output"), str):
            text = raw["output"]
            structured = {k: v for k, v in raw.items() if k != "output"}
        elif "content" in raw and isinstance(raw.get("content"), str):
            text = raw["content"]
            structured = {k: v for k, v in raw.items() if k != "content"}
        elif "message" in raw and isinstance(raw.get("message"), str):
            text = raw["message"]
            structured = {k: v for k, v in raw.items() if k != "message"}
        elif raw:
            # 结构化输出（dict/list）直接作为 structured 保留
            structured = dict(raw)

        truncated = False
        if text and len(text) > self._max_node_output_chars:
            text = text[: self._max_node_output_chars] + "\n...(output truncated)"
            truncated = True

        return {
            "text": text,
            "structured": structured,
            "provider": provider,
            "empty": not text and not structured,
            "truncated": truncated,
        }

    def write_output(
        self,
        ctx: dict,
        node_id: str,
        raw_output: dict,
        output_mappings,
    ) -> None:
        """归一化后写回全局 ctx（含 _context_audit 摘要）。"""
        provider = (
            (raw_output.get("_executor_metadata") or {}).get("provider")
            or raw_output.get("provider")
            or "unknown"
        )
        normalized = self.normalize_output(provider, raw_output)

        for mapping in output_mappings or []:
            source = mapping.source
            target = mapping.target
            value = raw_output.get(source)
            if value is None and normalized["text"] is not None and source in ("output", "content", "message"):
                value = normalized["text"]
            if value is not None:
                ctx[target] = value

        audit = ctx.setdefault("_context_audit", {})
        audit[node_id] = {
            "provider": provider,
            "empty": normalized["empty"],
            "truncated": normalized["truncated"],
            "text_chars": len(normalized["text"] or ""),
            "structured_keys": list(normalized["structured"].keys())[:10],
        }