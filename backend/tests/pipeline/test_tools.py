#!/usr/bin/env python3
"""修复工具的单元测试。用法: python3 tests/pipeline/test_tools.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from langgraph.types import Command

from pipeline import repair, tools
from pipeline.verification import VerificationReport

DOC = {
    "meta": {"work_title": "药"},
    "coverage": {"total_units": 1},
    "source": {"units": [{"id": "u0001", "text": "秋天的后半夜。"}]},
    "assets": {"characters": [{"id": "C01", "name": "老栓"}]},
    "episodes": [{"id": "E01", "shots": [{"id": "E01S001", "action": "旧"}]}],
}


def main() -> int:
    # 1. 工具清单与改造前的自研协议一一对应
    assert {t.name for t in tools.REPAIR_TOOLS} == {
        "source_read", "asset_get", "validation_list", "coverage_query",
        "json_patch", "task_done"}
    print("tools: 6 个工具名单正确 ✓")

    # 2. 每个工具都有中文 docstring（它就是喂给模型的工具说明）
    for t in tools.REPAIR_TOOLS:
        assert t.description and any("一" <= c <= "鿿"
                                     for c in t.description), \
            f"{t.name} 缺中文说明"
    print("tools: 工具说明齐备 ✓")

    # 3. 模型看得见的参数恰好是这些（36KB 的 doc 靠 InjectedState 注入，绝不能出现在这里）。
    #    注意要看 tool_call_schema——它才是发给模型的契约；args_schema 是函数的完整签名，
    #    本来就含 state / tool_call_id 这些注入参数，拿它断言会把正确实现判红。
    visible = {t.name: sorted(t.tool_call_schema.model_json_schema()
                              .get("properties", {}))
               for t in tools.REPAIR_TOOLS}
    assert visible == {
        "source_read": ["unit_ids"], "asset_get": ["asset_ids"],
        "validation_list": [], "coverage_query": [],
        "json_patch": ["patch"], "task_done": [],
    }, f"模型可见参数不对：{visible}"
    print("tools: 模型只看得见业务参数，state/tool_call_id 均被注入 ✓")

    # 4. json_patch 产出 Command，把补丁后的 doc 写回状态
    patched = tools.json_patch.func(
        patch=[{"op": "replace", "path": "/episodes/0/shots/0/action",
                "value": "新"}],
        tool_call_id="call_1",
        state={"doc": DOC, "structured": VerificationReport()})
    assert isinstance(patched, Command)
    assert patched.update["doc"]["episodes"][0]["shots"][0]["action"] == "新"
    assert patched.update["patch_applied"] is True
    assert DOC["episodes"][0]["shots"][0]["action"] == "旧", "不许原地改入参"
    print("tools: json_patch 用 Command 写回新 doc ✓")

    # 5. 锁定前缀照旧拦住（/coverage 与 /meta 是后处理结果，模型不得改）
    try:
        tools.json_patch.func(
            patch=[{"op": "replace", "path": "/coverage/total_units", "value": 99}],
            tool_call_id="call_1",
            state={"doc": DOC, "structured": VerificationReport()})
        raise AssertionError("/coverage 必须锁定")
    except repair.RepairError:
        pass
    print("tools: /coverage 与 /meta 仍然锁定 ✓")

    # 6. task_done 标记收工
    done = tools.task_done.func(tool_call_id="call_1")
    assert isinstance(done, Command) and done.update["task_done"] is True
    print("tools: task_done 标记收工 ✓")

    # 7. 只读工具直接复用 repair.py 的实现
    assert tools.source_read.func(unit_ids=["u0001"],
                                  state={"doc": DOC})[0]["id"] == "u0001"
    assert tools.asset_get.func(asset_ids=["C01"],
                                state={"doc": DOC})[0]["name"] == "老栓"
    print("tools: 只读工具复用 repair.py 实现 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
