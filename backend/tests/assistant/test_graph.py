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
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402
from fake_model import ScriptedChat, call  # noqa: E402
from assistant import actions, events, graph, store  # noqa: E402
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
    long_turn = [HumanMessage("旧"), AIMessage("旧答"), HumanMessage("本轮")]
    for i in range(12):
        long_turn += [call("plot_get", {}, f"x{i}"), ToolMessage("x", tool_call_id=f"x{i}")]
    cut = graph.trim(long_turn)
    assert cut[0].content == "本轮" and len(cut) == 25, "本轮工具调用很多时整轮保留"
    assert graph.trim([]) == []
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
    assert hist[3] == {"role": "assistant", "text": "好的。", "tools": [], "goto": [], "cards": []}
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

    # 10. 历史：被停掉的工具调用标「（已中断）」不再转圈；几条 AI 文字空行隔开；工具结果隐去服务器目录
    from types import SimpleNamespace
    from assistant import tools as tools_mod
    archive = [HumanMessage("q"),
               AIMessage("我查一下。", tool_calls=[{"name": "plot_get", "args": {}, "id": "h1"}]),
               ToolMessage(f"错在 {_TMP.name}/u/x.mp4", tool_call_id="h1", name="plot_get"),
               AIMessage("再看看。", tool_calls=[{"name": "film_status", "args": {}, "id": "h2"}])]
    fake = SimpleNamespace(get_state=lambda cfg: SimpleNamespace(values={"messages": archive}))
    h = events.history(fake, {}, hide=_TMP.name)
    assert h[1]["text"] == "我查一下。\n\n再看看。", h[1]["text"]
    assert h[1]["tools"][0]["ok"] is True and _TMP.name not in h[1]["tools"][0]["summary"]
    assert h[1]["tools"][1]["ok"] is False and h[1]["tools"][1]["summary"] == events.INTERRUPTED
    assert _TMP.name not in tools_mod._dump({"error": f"{auth.DATA_DIR}/u/clip.mp4 坏了"})
    print("10. 历史中断与隐去路径 ✓")

    # 11. 关掉并行工具调用（操作工具会中断，并行时恢复一个会让另一个重跑）
    class Rec(ScriptedChat):
        bound: dict = {}

        def bind_tools(self, tools, **kwargs):
            self.bound.update(kwargs)
            return self
    r = Rec(script=[])
    graph.build_agent(r, InMemorySaver())
    assert r.bound.get("parallel_tool_calls") is False
    assert [t.name for t in graph.ALL_TOOLS][-4:] == list(actions.ACTIONS)
    print("11. 关并行 ✓")

    # 12. 操作工具出卡：只发 confirm（不发 tool_start），流以 done 结束；历史里是待确认的卡
    starts = []
    actions.ops["start_version"] = lambda user, nid_, cid_, ov, strict: starts.append(cid_) or {"job_id": "j1", "version_id": "j1"}
    cfg = graph.run_config(uid, nid, {"chapter_id": cid}, "zh")
    store.clear(uid, nid)
    model = ScriptedChat(script=[call("generate_storyboard", {}, "g1"), AIMessage("开始了。")])
    with store.saver(uid, nid) as cp:
        agent = graph.build_agent(model, cp)
        evs = list(events.stream(agent, cfg, "生成分镜"))
        assert [e["event"] for e in evs] == ["confirm", "done"], evs
        conf = evs[0]["data"]
        assert conf["tool_call_id"] == "g1" and conf["action"] == "generate_storyboard" and conf["id"]
        assert conf["amount"] is None and conf["detail"] == {"chars": 2, "archived": False}
        assert [it.id for it in graph.pending(agent, cfg)] == [conf["id"]]
        h = events.history(agent, cfg)
    assert h[-1]["tools"] == [] and h[-1]["cards"] == [
        {"tool_call_id": "g1", "action": "generate_storyboard", "outcome": "pending", "card": conf}], h[-1]
    print("12. 出卡 ✓")

    # 13. 恢复（确认）：action 事件带结果与任务，之后模型接着说；历史里卡变成已确认
    with store.saver(uid, nid) as cp:
        agent = graph.build_agent(model, cp)
        card = graph.pending(agent, cfg)[0].value
        rcfg = graph.run_config(uid, nid, {"chapter_id": cid}, "zh", resume_tool_call="g1")
        assert rcfg["configurable"]["resume_tool_call"] == "g1" and cfg["configurable"]["resume_tool_call"] is None
        evs = list(events.stream(agent, rcfg, Command(resume={conf["id"]: {"decision": "approve", "card": card}})))
        assert [e["event"] for e in evs] == ["action", "token", "done"], evs
        act = evs[0]["data"]
        assert act["outcome"] == "approved" and act["tool_call_id"] == "g1" and act["action"] == "generate_storyboard"
        assert act["task"] == {"kind": "job", "chapter_id": cid, "version_id": "j1", "job_id": "j1"} and starts == [cid]
        assert graph.pending(agent, cfg) == []
        h = events.history(agent, cfg)
    assert h[-1]["cards"][0]["outcome"] == "approved" and h[-1]["cards"][0]["task"]["job_id"] == "j1"
    assert h[-1]["text"] == "开始了。"
    print("13. 恢复 ✓")

    # 14. 有待确认的卡时发新消息：卡补「已取消」（不调模型），新一轮模型看到取消结果与新问题
    model = ScriptedChat(script=[call("generate_storyboard", {}, "g2"), AIMessage("好的，不生成了。")])
    with store.saver(uid, nid) as cp:
        agent = graph.build_agent(model, cp)
        list(events.stream(agent, cfg, "再生成一次"))
        assert len(graph.pending(agent, cfg)) == 1
        calls_before = len(model.seen)
        assert graph.cancel_pending(agent, cfg) == 1
        assert len(model.seen) == calls_before, "取消不调模型"
        assert graph.pending(agent, cfg) == [] and graph.cancel_pending(agent, cfg) == 0
        evs = list(events.stream(agent, cfg, "算了，问个别的"))
        assert [e["event"] for e in evs] == ["token", "done"], evs
        last = model.seen[-1]
        assert any(isinstance(m, ToolMessage) and m.content == graph.CANCELLED for m in last)
        assert isinstance(last[-1], HumanMessage) and last[-1].content == "算了，问个别的"
        h = events.history(agent, cfg)
    assert h[-3]["cards"][0]["outcome"] == "rejected" and h[-1]["text"] == "好的，不生成了。"
    print("14. 发新消息取消待确认的卡 ✓")

    # 15. 操作工具报错：action 事件 outcome=failed 带原因；历史里同样；被停掉没结果的标「（已中断）」
    model = ScriptedChat(script=[call("film_run", {}, "f1"), AIMessage("没有可用版本。")])
    with store.saver(uid, nid) as cp:
        agent = graph.build_agent(model, cp)
        evs = list(events.stream(agent, cfg, "出片"))
        assert [e["event"] for e in evs] == ["action", "token", "done"], evs
        assert evs[0]["data"]["outcome"] == "failed" and "分镜版本" in evs[0]["data"]["error"]
        h = events.history(agent, cfg)
    assert h[-1]["cards"][0]["outcome"] == "failed"
    dangling = [HumanMessage("q"), call("film_run", {}, "f9")]
    with store.saver(uid, nid) as cp:
        agent = graph.build_agent(ScriptedChat(script=[]), cp)
        agent.update_state(cfg, {"messages": dangling}, as_node="agent")
        h = events.history(agent, cfg)
    assert h[-1]["cards"][-1] == {"tool_call_id": "f9", "action": "film_run", "outcome": "failed",
                                   "error": events.INTERRUPTED}, h[-1]
    print("15. 操作报错与被停掉 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
