#!/usr/bin/env python3
"""助手的操作工具：出卡字段、确认后执行、取消不执行、金额变了重新出卡（以服务端给的卡为准）、连变 3 次不执行、
合成金额为 0 不出卡、生成分镜（没原文报错、无金额、本章已有采用版）、导出直接放下载按钮、执行函数的 HTTP 报错转述、
工具参数说明里没有 config 与 tool_call_id。执行函数用替身（ops），不碰出片与模型。
用法: python3 tests/assistant/test_actions.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name

from fastapi import HTTPException  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402
from langgraph.types import Command  # noqa: E402
from fake_model import ScriptedChat, call  # noqa: E402
from assistant import actions as A  # noqa: E402
from server import auth, novels  # noqa: E402

DOC = json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8"))
calls: list = []
film = {"amount": 1.5, "clips": ["C1", "C2"]}
comp = {"amount": 0.0, "chars": 0}


def fake_ops():
    def film_quote(user, nid, cid, vid, ids):
        if callable(film.get("next")):
            film["amount"] = film["next"]()
        return {"amount": film["amount"], "clips": list(film["clips"])}

    A.ops.update(
        start_version=lambda user, nid, cid, ov, strict: calls.append(("start", cid)) or {"job_id": "j1", "version_id": "j1"},
        film_quote=film_quote,
        film_run=lambda user, nid, cid, vid, ids, exp: calls.append(("film", vid, ids, exp)) or {},
        compose_quote=lambda user, nid, cid, vid, draft: dict(comp),
        compose_start=lambda user, nid, cid, vid, draft, exp: calls.append(("compose", draft, exp)) or {},
        export_check=lambda user, nid, cid, vid: calls.append(("export", vid)) or (None, None),
    )


def agent_for(script: list):
    return create_react_agent(ScriptedChat(script=script), A.TOOLS, checkpointer=InMemorySaver())


def run(agent, cfg, payload) -> list:
    """跑到停（结束或中断），返回这次出的中断。"""
    out = []
    for chunk in agent.stream(payload, cfg, stream_mode="updates"):
        out += list(chunk.get("__interrupt__") or [])
    return out


def answer(it, decision="approve"):
    """模拟 resume 接口：卡取自存档（中断的原值），不是前端传的。"""
    return Command(resume={it.id: {"decision": decision, "card": it.value}})


def result(agent, cfg) -> ToolMessage:
    return [m for m in agent.get_state(cfg).values["messages"] if isinstance(m, ToolMessage)][-1]


def main() -> int:
    uid = auth.register("alice", "secret1")["id"]
    nid = novels.create_novel(uid, "药")["id"]
    c1 = novels.create_chapter(uid, nid, "第一章 茶馆", text="原文")["id"]
    c2 = novels.create_chapter(uid, nid, "第二章 刑场", text="")["id"]
    novels.create_version(uid, nid, c1, "v1", {}, "原文")
    novels.update_version_state(uid, nid, c1, "v1", "succeeded", result=copy.deepcopy(DOC))
    novels.adopt_version(uid, nid, c1, "v1")
    fake_ops()
    n = [0]

    def cfg():
        n[0] += 1
        return {"configurable": {"thread_id": f"t{n[0]}", "user_id": uid, "novel_id": nid,
                                 "where": {"chapter_id": c1}}}

    # 1. 出片：出卡字段；确认前不执行；确认后带卡上金额执行，结果带任务
    C = cfg()
    ag = agent_for([call("film_run", {}, "f1"), AIMessage("开始了")])
    its = run(ag, C, {"messages": [HumanMessage("出片")]})
    assert len(its) == 1 and calls == []
    card = its[0].value
    assert card == {"tool_call_id": "f1", "action": "film_run", "chapter_id": c1, "chapter": "第一章 茶馆",
                    "version_id": "v1", "amount": 1.5, "currency": "cny", "detail": {"clips": 2}}, card
    assert run(ag, C, answer(its[0])) == []
    assert calls == [("film", "v1", None, 1.5)], calls
    m = result(ag, C)
    assert m.status != "error" and m.artifact == {"card": card, "outcome": "approved",
                                                  "task": {"kind": "film", "chapter_id": c1, "version_id": "v1"}}
    print("1. 出片确认后执行 ✓")

    # 2. 取消：不执行，结果说明取消
    calls.clear()
    C = cfg()
    ag = agent_for([call("film_run", {"clip_ids": ["C1"]}, "f2"), AIMessage("好的")])
    its = run(ag, C, {"messages": [HumanMessage("出 C1")]})
    run(ag, C, answer(its[0], "reject"))
    m = result(ag, C)
    assert calls == [] and m.artifact["outcome"] == "rejected" and "取消" in m.content
    print("2. 取消不执行 ✓")

    # 3. 金额变了：重新出卡（带原金额），再确认才按新金额执行
    C = cfg()
    ag = agent_for([call("film_run", {}, "f3"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("出片")]})
    film["amount"] = 2.0
    its2 = run(ag, C, answer(its[0]))
    assert calls == [] and len(its2) == 1
    assert its2[0].value["amount"] == 2.0 and its2[0].value["changed"] is True and its2[0].value["previous_amount"] == 1.5
    run(ag, C, answer(its2[0]))
    assert calls == [("film", "v1", None, 2.0)], calls
    print("3. 金额变了重新出卡 ✓")

    # 4. 连变 3 次：不执行，工具报错
    calls.clear()
    seq = iter(range(10, 100))
    film["next"] = lambda: float(next(seq))
    C = cfg()
    ag = agent_for([call("film_run", {}, "f4"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("出片")]})
    shown = 1
    while its:
        its = run(ag, C, answer(its[0]))
        shown += bool(its)
    film.pop("next")
    film["amount"] = 1.5
    m = result(ag, C)
    assert shown == 3 and calls == [] and m.status == "error" and "一直在变" in m.content, (shown, m.content)
    print("4. 连变 3 次不执行 ✓")

    # 5. 合成：金额为 0 不出卡直接执行；大于 0 出卡，确认后带金额
    C = cfg()
    ag = agent_for([call("compose", {}, "m1"), AIMessage("好")])
    assert run(ag, C, {"messages": [HumanMessage("合成")]}) == []
    m = result(ag, C)
    assert calls == [("compose", True, None)] and m.artifact["outcome"] == "done"
    assert m.artifact["task"] == {"kind": "compose", "chapter_id": c1, "version_id": "v1"}
    calls.clear()
    comp.update(amount=0.3, chars=120)
    C = cfg()
    ag = agent_for([call("compose", {"draft": False}, "m2"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("合成")]})
    assert its[0].value["detail"] == {"chars": 120, "draft": False} and its[0].value["amount"] == 0.3
    run(ag, C, answer(its[0]))
    assert calls == [("compose", False, 0.3)], calls
    print("5. 合成 ✓")

    # 6. 生成分镜：没原文报错不出卡；有原文出卡（无金额、已有采用版），确认后开任务
    calls.clear()
    C = cfg()
    ag = agent_for([call("generate_storyboard", {"chapter": c2}, "g1"), AIMessage("好")])
    assert run(ag, C, {"messages": [HumanMessage("生成第二章")]}) == []
    m = result(ag, C)
    assert m.status == "error" and "原文" in m.content and calls == []
    C = cfg()
    ag = agent_for([call("generate_storyboard", {}, "g2"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("生成")]})
    v = its[0].value
    assert v["amount"] is None and v["currency"] == "usd" and v["version_id"] is None
    assert v["detail"] == {"chars": 2, "archived": True}, v
    run(ag, C, answer(its[0]))
    m = result(ag, C)
    assert calls == [("start", c1)]
    assert m.artifact["task"] == {"kind": "job", "chapter_id": c1, "version_id": "j1", "job_id": "j1"}
    print("6. 生成分镜 ✓")

    # 7. 导出：不出卡，检查后放下载按钮
    calls.clear()
    C = cfg()
    ag = agent_for([call("export_fcpxml", {}, "e1"), AIMessage("好")])
    assert run(ag, C, {"messages": [HumanMessage("导出")]}) == []
    m = result(ag, C)
    assert calls == [("export", "v1")] and m.artifact["outcome"] == "done"
    assert m.artifact["task"] == {"kind": "export", "chapter_id": c1, "version_id": "v1"}
    assert m.artifact["card"]["amount"] is None and m.artifact["card"]["currency"] is None
    print("7. 导出 ✓")

    # 8. 执行函数的 HTTP 报错转成工具报错（带说明，不中断对话）
    def boom(*a):
        raise HTTPException(409, detail={"message": "预估金额已变为 ¥9.00，请重新确认", "expected_cny": 9.0})
    A.ops["film_run"] = boom
    C = cfg()
    ag = agent_for([call("film_run", {}, "f5"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("出片")]})
    run(ag, C, answer(its[0]))
    m = result(ag, C)
    assert m.status == "error" and "¥9.00" in m.content, m.content
    fake_ops()
    print("8. 报错转述 ✓")

    # 9. 参数说明里没有 config、tool_call_id
    for t in A.TOOLS:
        props = t.tool_call_schema.model_json_schema().get("properties", {})
        assert "config" not in props and "tool_call_id" not in props, (t.name, props)
    assert A.ACTIONS == ("generate_storyboard", "film_run", "compose", "export_fcpxml")
    print("9. 参数说明 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
