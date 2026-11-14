"""A deliberately small, auditable repair-agent toolset.

The model never receives filesystem or arbitrary code execution. It can inspect the
current validation state and submit a narrow JSON Patch; deterministic evidence and
post-processed fields are immutable.
"""
import copy
import json
from typing import Iterable


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
    # 回喂修复模型：与改造前逐字一致，不带给界面的 msg（spec 子计划 5 F）
    return [finding.to_dict(shown=False) for finding in report.findings]


def coverage_query(report) -> dict:
    return copy.deepcopy(report.coverage)


def repair_request(report, extra_report: str = "") -> str:
    payload = {
        "validation": validation_list(report),
        "coverage": coverage_query(report),
        "quality_report": extra_report,
        "contract": {
            "allowed_ops": sorted(_PATCH_OPS),
            "locked": ["/meta", "/coverage", "/source/units/*/(id|text|para)"],
        },
    }
    return ("你是受限分镜修复 Agent。根据以下工具结果只修改被报告的问题。"
            "不要重写整份文档；请直接调用提供的工具："
            "需要时先用只读工具查询，然后恰好提交一个 json_patch（提交即结束本轮，程序会重新校验）；只有你判断无需任何修改时，才调用 task_done。"
            "下面是当前校验结果与补丁约束（allowed_ops 为允许的操作，locked 为禁止改动的路径）。\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2))


def _tokens(path: str) -> list[str]:
    if not isinstance(path, str) or not path.startswith("/"):
        raise RepairError(f"非法 JSON Pointer：{path!r}")  # i18n: llm
    return [part.replace("~1", "/").replace("~0", "~")
            for part in path[1:].split("/")]


def _assert_mutable(path: str) -> None:
    parts = _tokens(path)
    if any(path == prefix or path.startswith(prefix + "/")
           for prefix in _LOCKED_PREFIXES):
        raise RepairError(f"补丁试图修改锁定字段：{path}")  # i18n: llm
    if len(parts) >= 4 and parts[:2] == ["source", "units"] \
            and parts[3] in ("id", "text", "para"):
        raise RepairError(f"补丁试图修改冻结源证据：{path}")  # i18n: llm


def _parent(root, parts: list[str]):
    current = root
    for part in parts[:-1]:
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise RepairError(f"数组路径不存在：{part}") from exc  # i18n: llm
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise RepairError(f"对象路径不存在：{part}")  # i18n: llm
    return current, parts[-1]


def apply_json_patch(doc: dict, patch: list[dict]) -> dict:
    if not isinstance(patch, list) or not patch or len(patch) > 50:
        raise RepairError("patch 必须包含 1-50 个操作")  # i18n: llm
    result = copy.deepcopy(doc)
    for operation in patch:
        if not isinstance(operation, dict) or operation.get("op") not in _PATCH_OPS:
            raise RepairError("只允许 add/remove/replace 操作")  # i18n: llm
        required = ({"op", "path"} if operation["op"] == "remove"
                    else {"op", "path", "value"})
        if set(operation) != required:
            raise RepairError(f"{operation['op']} 操作字段必须且只能是 {sorted(required)}")  # i18n: llm
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
                raise RepairError(f"非法数组索引：{key}") from exc  # i18n: llm
            if op == "add":
                if not 0 <= index <= len(parent):
                    raise RepairError(f"数组插入越界：{path}")  # i18n: llm
                parent.insert(index, copy.deepcopy(operation.get("value")))
            elif op == "remove":
                if not 0 <= index < len(parent):
                    raise RepairError(f"数组删除越界：{path}")  # i18n: llm
                parent.pop(index)
            else:
                if not 0 <= index < len(parent):
                    raise RepairError(f"数组替换越界：{path}")  # i18n: llm
                parent[index] = copy.deepcopy(operation.get("value"))
        elif isinstance(parent, dict):
            if op in ("remove", "replace") and key not in parent:
                raise RepairError(f"对象路径不存在：{path}")  # i18n: llm
            if op == "remove":
                del parent[key]
            else:
                parent[key] = copy.deepcopy(operation.get("value"))
        else:
            raise RepairError(f"路径父节点不是容器：{path}")  # i18n: llm
    return result
