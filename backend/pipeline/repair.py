"""A deliberately small, auditable repair-agent toolset.

The model never receives filesystem or arbitrary code execution. It can inspect the
current validation state and submit a narrow JSON Patch; deterministic evidence and
post-processed fields are immutable.
"""
import copy
import json
from typing import Iterable


ALLOWED_TOOLS = (
    "source_read", "asset_get", "validation_list", "coverage_query",
    "json_patch", "task_done",
)
_PATCH_OPS = {"add", "remove", "replace"}
_LOCKED_PREFIXES = ("/coverage", "/meta")


class RepairError(ValueError):
    pass


def source_read(doc: dict, unit_ids: Iterable[str]) -> list[dict]:
    wanted = set(unit_ids)
    return [u for u in (doc.get("source") or {}).get("units") or []
            if u.get("id") in wanted]


def asset_get(doc: dict, asset_ids: Iterable[str]) -> list[dict]:
    wanted = set(asset_ids)
    assets = doc.get("assets") or {}
    return [card for cards in assets.values() if isinstance(cards, list)
            for card in cards if card.get("id") in wanted]


def validation_list(report) -> list[dict]:
    return [finding.to_dict() for finding in report.findings]


def coverage_query(report) -> dict:
    return copy.deepcopy(report.coverage)


def repair_request(report, extra_report: str = "") -> str:
    payload = {
        "tools": list(ALLOWED_TOOLS),
        "validation": validation_list(report),
        "coverage": coverage_query(report),
        "quality_report": extra_report,
        "contract": {
            "calls": [
                {"tool": "source_read", "unit_ids": ["u0001"]},
                {"tool": "asset_get", "asset_ids": ["C01"]},
                {"tool": "validation_list"},
                {"tool": "coverage_query"},
                {"tool": "json_patch", "patch": [
                    {"op": "replace", "path": "/episodes/0/shots/0/action",
                     "value": "..."}
                ]},
                {"tool": "task_done"},
            ],
            "allowed_ops": sorted(_PATCH_OPS),
            "locked": ["/meta", "/coverage", "/source/units/*/(id|text|para)"],
        },
    }
    return ("你是受限分镜修复 Agent。根据以下工具结果只修改被报告的问题。"
            "不要重写整份文档；只输出一个 JSON 工具调用对象。\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2))


def _tokens(path: str) -> list[str]:
    if not isinstance(path, str) or not path.startswith("/"):
        raise RepairError(f"非法 JSON Pointer：{path!r}")
    return [part.replace("~1", "/").replace("~0", "~")
            for part in path[1:].split("/")]


def _assert_mutable(path: str) -> None:
    parts = _tokens(path)
    if any(path == prefix or path.startswith(prefix + "/")
           for prefix in _LOCKED_PREFIXES):
        raise RepairError(f"补丁试图修改锁定字段：{path}")
    if len(parts) >= 4 and parts[:2] == ["source", "units"] \
            and parts[3] in ("id", "text", "para"):
        raise RepairError(f"补丁试图修改冻结源证据：{path}")


def _parent(root, parts: list[str]):
    current = root
    for part in parts[:-1]:
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise RepairError(f"数组路径不存在：{part}") from exc
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise RepairError(f"对象路径不存在：{part}")
    return current, parts[-1]


def apply_json_patch(doc: dict, patch: list[dict]) -> dict:
    if not isinstance(patch, list) or not patch or len(patch) > 50:
        raise RepairError("patch 必须包含 1-50 个操作")
    result = copy.deepcopy(doc)
    for operation in patch:
        if not isinstance(operation, dict) or operation.get("op") not in _PATCH_OPS:
            raise RepairError("只允许 add/remove/replace 操作")
        required = ({"op", "path"} if operation["op"] == "remove"
                    else {"op", "path", "value"})
        if set(operation) != required:
            raise RepairError(f"{operation['op']} 操作字段必须且只能是 {sorted(required)}")
        path = operation.get("path")
        _assert_mutable(path)
        parts = _tokens(path)
        parent, key = _parent(result, parts)
        op = operation["op"]
        if isinstance(parent, list):
            if key == "-" and op == "add":
                parent.append(copy.deepcopy(operation.get("value")))
                continue
            try:
                index = int(key)
            except ValueError as exc:
                raise RepairError(f"非法数组索引：{key}") from exc
            if op == "add":
                if not 0 <= index <= len(parent):
                    raise RepairError(f"数组插入越界：{path}")
                parent.insert(index, copy.deepcopy(operation.get("value")))
            elif op == "remove":
                if not 0 <= index < len(parent):
                    raise RepairError(f"数组删除越界：{path}")
                parent.pop(index)
            else:
                if not 0 <= index < len(parent):
                    raise RepairError(f"数组替换越界：{path}")
                parent[index] = copy.deepcopy(operation.get("value"))
        elif isinstance(parent, dict):
            if op in ("remove", "replace") and key not in parent:
                raise RepairError(f"对象路径不存在：{path}")
            if op == "remove":
                del parent[key]
            else:
                parent[key] = copy.deepcopy(operation.get("value"))
        else:
            raise RepairError(f"路径父节点不是容器：{path}")
    return result


def apply_tool_call(doc: dict, envelope: dict) -> dict:
    if not isinstance(envelope, dict) or set(envelope) != {"tool", "patch"}:
        raise RepairError("工具调用必须且只能包含 tool 和 patch")
    if envelope.get("tool") != "json_patch":
        raise RepairError("当前步骤只接受 json_patch 工具调用")
    return apply_json_patch(doc, envelope["patch"])


def run_inspection_tool(doc: dict, report, envelope: dict) -> dict:
    """Execute one read-only repair tool and return a structured tool result."""
    if not isinstance(envelope, dict) or not isinstance(envelope.get("tool"), str):
        raise RepairError("工具调用缺少 tool")
    tool = envelope["tool"]
    if tool == "source_read":
        if set(envelope) != {"tool", "unit_ids"} or not isinstance(
                envelope["unit_ids"], list) or not all(
                    isinstance(v, str) for v in envelope["unit_ids"]):
            raise RepairError("source_read 只接受 unit_ids 数组")
        result = source_read(doc, envelope["unit_ids"])
    elif tool == "asset_get":
        if set(envelope) != {"tool", "asset_ids"} or not isinstance(
                envelope["asset_ids"], list) or not all(
                    isinstance(v, str) for v in envelope["asset_ids"]):
            raise RepairError("asset_get 只接受 asset_ids 数组")
        result = asset_get(doc, envelope["asset_ids"])
    elif tool == "validation_list":
        if set(envelope) != {"tool"}:
            raise RepairError("validation_list 不接受参数")
        result = validation_list(report)
    elif tool == "coverage_query":
        if set(envelope) != {"tool"}:
            raise RepairError("coverage_query 不接受参数")
        result = coverage_query(report)
    else:
        raise RepairError(f"不是只读工具：{tool}")
    return {"tool": tool, "result": result}


def is_task_done(envelope: dict) -> bool:
    if not isinstance(envelope, dict) or envelope.get("tool") != "task_done":
        return False
    if set(envelope) != {"tool"}:
        raise RepairError("task_done 不接受参数")
    return True
