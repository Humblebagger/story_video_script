#!/usr/bin/env python3
"""助手智能体：系统提示带当前位置与语言、历史裁剪（≤20 条、首条为用户、不拆工具调用）、补全被打断的工具调用、
事件流顺序（tool_start → tool_end → goto → token → done）、出错事件、存档跨轮接上、历史视图。
用法: python3 tests/assistant/test_graph.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage  # noqa: E402
from fake_model import ScriptedChat, call  # noqa: E402
from assistant import events, graph, store  # noqa: E402
from server import auth, novels  # noqa: E402


def main() -> int:
    uid = auth.register("alice", "secret1")["id"]
    nid = novels.create_novel(uid, "药")["id"]
    cid = novels.create_chapter(uid, nid, "第一章 茶馆", text="原文")["id"]

    # 1. 裁剪：最多 20 条、首条是 HumanMessage
    msgs = []
    for i in range(15):
        msgs += [HumanMessage(f"q{i}"), AIMessage(f"a{i}")]
    cut = graph.trim(msgs)
    assert len(cut) <= graph.HISTORY and isinstance(cut[0], HumanMessage) and cut[-1].content == "a14"
    tail = [HumanMessage("q"), call("plot_get", {}, "t1"), ToolMessage("x", tool_call_id="t1"), AIMessage("a")] * 6
    cut = graph.trim(tail)
    assert isinstance(cut[0], HumanMessage) and len(cut) <= graph.HISTORY
    print("1. 历史裁剪 ✓")

    # 2. 补全被打断的工具调用
    broken = [HumanMessage("q"), call("plot_get", {}, "t9"), HumanMessage("再问")]
    fixed = graph.close_dangling(broken)
    assert isinstance(fixed[2], ToolMessage) and fixed[2].tool_call_id == "t9" and fixed[2].content == "（已中断）"
    assert graph.close_dangling([HumanMessage("q")]) == [HumanMessage("q")]
    print("2. 补全被打断的工具调用 ✓")

    # 3. 系统提示带当前位置与语言
    sys_text = graph.system_text(uid, nid, {"chapter_id": cid, "step": "review"}, "en")
    assert "第一章 茶馆" in sys_text and "review" in sys_text and "English" in sys_text
    assert "小说概览" in graph.system_text(uid, nid, {}, "zh")
    print("3. 系统提示 ✓")

    # 4. 一轮完整对话：工具 → 跳转 → 文字；事件顺序
    model = ScriptedChat(script=[
        call("chapter_status", {}, "t1"),
        call("goto", {"step": "render"}, "t2"),
        AIMessage("第一章还没有出片。"),
    ])
    with store.saver(uid, nid) as cp:
        agent = graph.build_agent(model, cp)
        evs = list(events.stream(agent, graph.run_config(uid, nid, {"chapter_id": cid}, "zh"), "第一章怎样了？"))
    kinds = [e["event"] for e in evs]
    assert kinds == ["tool_start", "tool_end", "tool_start", "tool_end", "goto", "token", "done"], kinds
    assert evs[0]["data"] == {"id": "t1", "name": "chapter_status", "args": {}}
    assert evs[1]["data"]["ok"] is True and evs[1]["data"]["id"] == "t1"
    assert evs[4]["data"] == {"chapter_id": cid, "step": "render"}
    assert evs[5]["data"] == {"text": "第一章还没有出片。"}
    first_call = model.seen[0]
    assert isinstance(first_call[0], SystemMessage) and "第一章 茶馆" in first_call[0].content
    print("4. 事件顺序 ✓")

    # 5. 存档接上：第二轮模型看到第一轮的消息；系统提示不进存档
    model2 = ScriptedChat(script=[AIMessage("好的。")])
    with store.saver(uid, nid) as cp:
        agent = graph.build_agent(model2, cp)
        list(events.stream(agent, graph.run_config(uid, nid, {}, "zh"), "谢谢"))
        hist = events.history(agent, graph.run_config(uid, nid, {}, "zh"))
    contents = [m.content for m in model2.seen[0]]
    assert "第一章怎样了？" in contents and "谢谢" in contents
    assert sum(isinstance(m, SystemMessage) for m in model2.seen[0]) == 1
    print("5. 存档跨轮 ✓")

    # 6. 历史视图：两问两答；第一答带两个工具与一个跳转
    assert [h["role"] for h in hist] == ["user", "assistant", "user", "assistant"]
    a1 = hist[1]
    assert a1["text"] == "第一章还没有出片。"
    assert [t["name"] for t in a1["tools"]] == ["chapter_status", "goto"] and all(t["ok"] for t in a1["tools"])
    assert a1["goto"] == [{"chapter_id": cid, "step": "render"}]
    assert hist[3] == {"role": "assistant", "text": "好的。", "tools": [], "goto": []}
    print("6. 历史视图 ✓")

    # 7. 工具出错：tool_end ok=False，对话继续
    model3 = ScriptedChat(script=[call("shots_get", {"chapter": "第九章"}, "t5"), AIMessage("没有第九章。")])
    with store.saver(uid, nid) as cp:
        agent = graph.build_agent(model3, cp)
        evs = list(events.stream(agent, graph.run_config(uid, nid, {}, "zh"), "第九章的镜头"))
    end = next(e for e in evs if e["event"] == "tool_end")
    assert end["data"]["ok"] is False and "可选章节" in end["data"]["summary"]
    assert evs[-1]["event"] == "done"
    print("7. 工具出错不中断 ✓")

    # 8. 模型出错：error 事件，报错里没有服务器路径
    class Boom(ScriptedChat):
        def _generate(self, *a, **k):
            raise RuntimeError(f"网关炸了 {_TMP.name}/x")
    with store.saver(uid, nid) as cp:
        agent = graph.build_agent(Boom(script=[]), cp)
        evs = list(events.stream(agent, graph.run_config(uid, nid, {}, "zh"), "hi", hide=_TMP.name))
    assert evs[-1]["event"] == "error" and _TMP.name not in evs[-1]["data"]["message"]
    print("8. 出错事件 ✓")

    # 9. 步数上限：模型一直调工具，最后给出「步骤太多」并结束
    loop = ScriptedChat(script=[call("plot_get", {}, f"L{i}") for i in range(40)])
    with store.saver(uid, nid) as cp:
        agent = graph.build_agent(loop, cp)
        evs = list(events.stream(agent, graph.run_config(uid, nid, {}, "zh"), "循环"))
    assert evs[-2]["event"] == "token" and "步骤太多" in evs[-2]["data"]["text"] and evs[-1]["event"] == "done"
    print("9. 步数上限 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
