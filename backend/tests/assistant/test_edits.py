#!/usr/bin/env python3
"""助手的改内容工具：改镜头（对比字段、编号后半段、白名单与枚举、旁白锁死、没变化报错、复验警告、应用、取消、
恢复时内容变了不应用、撤销与撤销被拒）、改资产卡（文字与列表字段、嵌套字段、锁死字段、应用与撤销）、
改剧情（全书梗概与章节梗概、应用与撤销）、撤销数据只含改动的镜头；
再保存采用版不把删掉的别名补回、恢复时重算报错仍可放弃、撤销剧情不留半截。复验与保存用替身（ops）。
用法: python3 tests/assistant/test_edits.py
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
# 测试不读真实的 backend/.env：load_settings 里的 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.prebuilt import ToolNode, create_react_agent  # noqa: E402
from langgraph.types import Command  # noqa: E402
from fake_model import ScriptedChat, call  # noqa: E402
from assistant import actions as A, edits as E, graph as G  # noqa: E402
from server import auth, novels  # noqa: E402

DOC = json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8"))
# 夹具里每个 SHxxx 后半段在各集都重复；把第一个镜头改成唯一的编号，才能测「编号后半段」
DOC["episodes"][0]["shots"][0]["id"] = "E01-SH901"
saves: list = []
check = {"ok": True, "warnings": []}


def fake_ops(uid):
    def version_save(user, nid, cid, vid, doc):
        saves.append((cid, vid))
        novels.update_version_result(uid, nid, cid, vid, doc, verification={}, status="succeeded")
        return {"id": vid, "status": "succeeded"}
    A.ops.update(version_check=lambda user, nid, cid, vid, doc: dict(check), version_save=version_save)


def agent_for(script):
    return create_react_agent(ScriptedChat(script=script), ToolNode(E.TOOLS, wrap_tool_call=G._with_artifact), checkpointer=InMemorySaver())


def run(agent, cfg, payload) -> list:
    out = []
    for chunk in agent.stream(payload, cfg, stream_mode="updates"):
        out += list(chunk.get("__interrupt__") or [])
    return out


def answer(it, decision="approve"):
    return Command(resume={it.id: {"decision": decision, "card": it.value}})


def result(agent, cfg) -> ToolMessage:
    return [m for m in agent.get_state(cfg).values["messages"] if isinstance(m, ToolMessage)][-1]


def shot(uid, nid, cid, sid):
    doc = novels.get_version(uid, nid, cid, "v1")["result"]
    return next(s for ep in doc["episodes"] for s in ep["shots"] if s["id"] == sid)


def main() -> int:
    uid = auth.register("alice", "secret1")["id"]
    nid = novels.create_novel(uid, "药")["id"]
    c1 = novels.create_chapter(uid, nid, "第一章 茶馆", text="原文")["id"]
    novels.create_version(uid, nid, c1, "v1", {}, "原文")
    novels.update_version_state(uid, nid, c1, "v1", "succeeded", result=copy.deepcopy(DOC))
    novels.adopt_version(uid, nid, c1, "v1")
    fake_ops(uid)
    first = DOC["episodes"][0]["shots"][0]
    sid, short = first["id"], first["id"].split("-")[-1]
    n = [0]

    def cfg(**extra):
        n[0] += 1
        return {"configurable": {"thread_id": f"t{n[0]}", "user_id": uid, "novel_id": nid,
                                 "where": {"chapter_id": c1}, **extra}}

    # 1. 改镜头：出卡（对比、编号后半段、没变化的不列），确认前不保存；应用后保存；撤销数据只含改动的镜头
    C = cfg()
    edits = [{"shot_id": short, "field": "action", "value": "新的画面"},
             {"shot_id": sid, "field": "duration_sec", "value": 7},
             {"shot_id": sid, "field": "shot_size", "value": first["shot_size"]}]
    ag = agent_for([call("shots_edit", {"edits": edits}, "s1"), AIMessage("改好了")])
    its = run(ag, C, {"messages": [HumanMessage("改第一个镜头")]})
    card = its[0].value
    assert card["action"] == "shots_edit" and card["chapter_id"] == c1 and card["version_id"] == "v1"
    assert card["amount"] is None and card["currency"] is None and card["warnings"] == []
    assert card["detail"] == {"edits": 2}, card
    assert card["diff"] == [
        {"target": sid, "field": "action", "before": first["action"], "after": "新的画面"},
        {"target": sid, "field": "duration_sec", "before": f"{first['duration_sec']:g}", "after": "7"}], card["diff"]
    assert saves == []
    run(ag, C, answer(its[0]))
    m = result(ag, C)
    assert saves == [(c1, "v1")] and shot(uid, nid, c1, sid)["action"] == "新的画面"
    assert shot(uid, nid, c1, sid)["duration_sec"] == 7
    assert m.artifact["outcome"] == "approved"
    assert m.artifact["task"] == {"kind": "edit", "chapter_id": c1, "version_id": "v1"}
    u = m.artifact["undo"]
    assert u["kind"] == "shots" and list(u["shots"]) == [sid] and u["shots"][sid]["before"] == first
    print("1. 改镜头并应用 ✓")

    # 2. 撤销：写回；再撤销（已经是改前的样子）被拒
    E.undo(uid, nid, u)
    assert shot(uid, nid, c1, sid) == first
    try:
        E.undo(uid, nid, u)
        raise AssertionError("改过之后不能再撤")
    except E.UndoError as e:
        assert sid in str(e)
    # 应用后别处又改了这个镜头：撤销被拒，点名镜头
    C = cfg()
    ag = agent_for([call("shots_edit", {"edits": [edits[0]]}, "s9"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("改")]})
    run(ag, C, answer(its[0]))
    u2 = result(ag, C).artifact["undo"]
    doc = copy.deepcopy(novels.get_version(uid, nid, c1, "v1")["result"])
    doc["episodes"][0]["shots"][0]["action"] = "别处又改的"
    novels.update_version_result(uid, nid, c1, "v1", doc, verification={}, status="succeeded")
    try:
        E.undo(uid, nid, u2)
        raise AssertionError("别处改过，不能撤")
    except E.UndoError as e:
        assert sid in str(e)
    novels.update_version_result(uid, nid, c1, "v1", copy.deepcopy(DOC), verification={}, status="succeeded")
    saves.clear()
    print("2. 改镜头撤销 ✓")

    # 3. 拒绝的情况：旁白锁死、不在白名单、枚举不对、时长越界、找不到镜头、没有变化 → 工具报错，不出卡
    for bad, word in [({"shot_id": sid, "field": "narration", "value": "x"}, "原文"),
                      ({"shot_id": sid, "field": "location_ref", "value": "S01"}, "不能改"),
                      ({"shot_id": sid, "field": "shot_size", "value": "huge"}, "shot_size"),
                      ({"shot_id": sid, "field": "duration_sec", "value": 30}, "0.5"),
                      ({"shot_id": "SH999", "field": "action", "value": "x"}, "SH999"),
                      ({"shot_id": "SH002", "field": "action", "value": "x"}, "唯一"),
                      ({"shot_id": sid, "field": "action", "value": first["action"]}, "不用改")]:
        C = cfg()
        ag = agent_for([call("shots_edit", {"edits": [bad]}, "sx"), AIMessage("好")])
        assert run(ag, C, {"messages": [HumanMessage("改")]}) == []
        m = result(ag, C)
        assert m.status == "error" and word in m.content, (bad, m.content)
        assert m.artifact and m.artifact["error"]["code"].startswith("assistant.edit."), (bad, m.artifact)
    print("3. 改镜头被拒 ✓")

    # 4. 复验警告写在卡上；取消不保存
    saves.clear()
    check.update(ok=False, warnings=["episodes[0]: 时长对不上"])
    C = cfg()
    ag = agent_for([call("shots_edit", {"edits": [edits[0]]}, "s2"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("改")]})
    assert its[0].value["warnings"] == ["episodes[0]: 时长对不上"]
    run(ag, C, answer(its[0], "reject"))
    assert saves == [] and result(ag, C).artifact["outcome"] == "rejected"
    check.update(ok=True, warnings=[])
    print("4. 复验警告与取消 ✓")

    # 5. 恢复时内容变了（别处改过这个镜头）：不应用
    C = cfg()
    ag = agent_for([call("shots_edit", {"edits": [edits[0]]}, "s3"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("改")]})
    doc = copy.deepcopy(novels.get_version(uid, nid, c1, "v1")["result"])
    doc["episodes"][0]["shots"][0]["action"] = "别处改的"
    novels.update_version_result(uid, nid, c1, "v1", doc, verification={}, status="succeeded")
    run(ag, C, answer(its[0]))
    m = result(ag, C)
    assert saves == [] and m.status == "error" and "变了" in m.content, m.content
    novels.update_version_result(uid, nid, c1, "v1", copy.deepcopy(DOC), verification={}, status="succeeded")
    print("5. 恢复时内容变了 ✓")

    # 6. 改资产卡：文字、列表、嵌套字段；锁死字段与不存在的字段被拒；应用与撤销
    novels.upsert_asset(uid, nid, "characters", copy.deepcopy(DOC["assets"]["characters"][0]))
    c0 = DOC["assets"]["characters"][0]
    C = cfg()
    fields = {"name": "华老栓（改）", "aliases": ["老栓", "栓叔"], "appearance.face": "圆脸"}
    ag = agent_for([call("asset_edit", {"card_id": c0["id"], "fields": fields}, "a1"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("改角色")]})
    v = its[0].value
    assert v["action"] == "asset_edit" and v["chapter_id"] is None and v["detail"] == {"edits": 3}
    assert {"target": f"{c0['id']} {c0['name']}", "field": "aliases", "before": "、".join(c0["aliases"]),
            "after": "老栓、栓叔"} in v["diff"], v["diff"]
    run(ag, C, answer(its[0]))
    m = result(ag, C)
    mem = novels.get_memory(uid, nid)["assets"]["characters"][0]
    assert mem["name"] == "华老栓（改）" and mem["aliases"] == ["老栓", "栓叔"] and mem["appearance"]["face"] == "圆脸"
    assert m.artifact["task"] == {"kind": "edit", "chapter_id": None, "version_id": None}
    E.undo(uid, nid, m.artifact["undo"])
    assert novels.get_memory(uid, nid)["assets"]["characters"][0] == c0
    sc = copy.deepcopy(DOC["assets"]["locations"][0])
    novels.upsert_asset(uid, nid, "locations", sc)
    C = cfg()
    ag = agent_for([call("asset_edit", {"card_id": sc["id"], "fields": {"interior_exterior": "outside"}}, "ae"),
                    AIMessage("好")])
    assert run(ag, C, {"messages": [HumanMessage("改")]}) == []
    m = result(ag, C)
    assert m.status == "error" and "interior" in m.content, m.content
    for bad, word in [({"id": "C99"}, "不能改"), ({"outfits": "x"}, "不能改"), ({"nickname": "x"}, "没有"),
                      ({"appearance": "x"}, "文字"), ({"name": " "}, "名称")]:
        C = cfg()
        ag = agent_for([call("asset_edit", {"card_id": c0["id"], "fields": bad}, "ax"), AIMessage("好")])
        assert run(ag, C, {"messages": [HumanMessage("改")]}) == []
        m = result(ag, C)
        assert m.status == "error" and word in m.content, (bad, m.content)
    C = cfg()
    ag = agent_for([call("asset_edit", {"card_id": "C99", "fields": {"name": "x"}}, "ay"), AIMessage("好")])
    run(ag, C, {"messages": [HumanMessage("改")]})
    assert "C99" in result(ag, C).content
    print("6. 改资产卡 ✓")

    # 7. 改剧情：全书梗概与本章梗概一起改；应用；撤销；别处改过之后撤销被拒
    novels.set_outline(uid, nid, "旧梗概")
    C = cfg()
    ag = agent_for([call("plot_edit", {"outline": "新梗概", "synopsis": "第一章新梗概"}, "p1"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("改剧情")]})
    v = its[0].value
    assert v["action"] == "plot_edit" and v["chapter_id"] == c1 and v["detail"] == {"edits": 2}
    assert [d["field"] for d in v["diff"]] == ["outline", "synopsis"] and v["diff"][1]["before"] == ""
    run(ag, C, answer(its[0]))
    m = result(ag, C)
    plot = novels.get_memory(uid, nid)["plot"]
    assert plot["outline"] == "新梗概" and plot["chapters"][0]["synopsis"] == "第一章新梗概"
    E.undo(uid, nid, m.artifact["undo"])
    plot = novels.get_memory(uid, nid)["plot"]
    assert plot["outline"] == "旧梗概" and plot["chapters"] == []
    novels.set_outline(uid, nid, "又改了")
    try:
        E.undo(uid, nid, {**m.artifact["undo"], "synopsis": None})
        raise AssertionError("梗概被别处改过，不能撤")
    except E.UndoError as e:
        assert "梗概" in str(e)
    C = cfg()
    long = "长" * (novels.SYNOPSIS_MAX + 1)
    ag = agent_for([call("plot_edit", {"outline": "不该生效", "synopsis": long}, "p3"), AIMessage("好")])
    assert run(ag, C, {"messages": [HumanMessage("改")]}) == []
    m = result(ag, C)
    assert m.status == "error" and str(novels.SYNOPSIS_MAX) in m.content, m.content
    assert novels.get_memory(uid, nid)["plot"]["outline"] == "又改了"
    C = cfg()
    ag = agent_for([call("plot_edit", {}, "p2"), AIMessage("好")])
    run(ag, C, {"messages": [HumanMessage("改")]})
    assert result(ag, C).status == "error"
    print("7. 改剧情 ✓")

    # 8. 改资产卡删掉别名后，再保存采用版（只改镜头）：长期记忆里的别名不被版本里的旧卡补回，撤销照常
    assert len(c0["aliases"]) > 1
    C = cfg()
    ag = agent_for([call("asset_edit", {"card_id": c0["id"], "fields": {"aliases": [c0["name"]]}}, "a9"),
                    AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("删别名")]})
    run(ag, C, answer(its[0]))
    u9 = result(ag, C).artifact["undo"]

    def aliases():
        return next(c for c in novels.get_memory(uid, nid)["assets"]["characters"] if c["id"] == c0["id"])["aliases"]
    assert aliases() == [c0["name"]]
    C = cfg()
    ag = agent_for([call("shots_edit", {"edits": [edits[0]]}, "s9b"), AIMessage("好")])
    its = run(ag, C, {"messages": [HumanMessage("改镜头")]})
    run(ag, C, answer(its[0]))
    assert result(ag, C).artifact["outcome"] == "approved"
    assert aliases() == [c0["name"]], aliases()
    E.undo(uid, nid, u9)
    assert aliases() == c0["aliases"]
    novels.update_version_result(uid, nid, c1, "v1", copy.deepcopy(DOC), verification={}, status="succeeded")
    print("8. 再保存采用版不补回资产卡 ✓")

    # 9. 出卡之后要改的地方变了（已是改后的样子，重算会报错）：点「放弃」照常算放弃，点「应用」才报错
    for decision, tcid in (("reject", "s10"), ("approve", "s11")):
        C = cfg()
        ag = agent_for([call("shots_edit", {"edits": [edits[0]]}, tcid), AIMessage("好")])
        its = run(ag, C, {"messages": [HumanMessage("改")]})
        doc = copy.deepcopy(novels.get_version(uid, nid, c1, "v1")["result"])
        doc["episodes"][0]["shots"][0]["action"] = edits[0]["value"]
        novels.update_version_result(uid, nid, c1, "v1", doc, verification={}, status="succeeded")
        saves.clear()
        R = {"configurable": {**C["configurable"], "resume_tool_call": tcid}}
        run(ag, R, answer(its[0], decision))
        m = result(ag, R)
        if decision == "reject":
            assert m.status != "error" and m.artifact["outcome"] == "rejected", (m.status, m.content)
            assert m.artifact["card"] == its[0].value
        else:
            assert m.status == "error" and "不用改" in m.content, m.content
        assert saves == []
        novels.update_version_result(uid, nid, c1, "v1", copy.deepcopy(DOC), verification={}, status="succeeded")
    print("9. 恢复时重算报错：放弃仍算放弃 ✓")

    # 10. 撤销剧情时写章节梗概失败：全书梗概也不动，报 UndoError
    novels.set_outline(uid, nid, "新的全书")
    novels.set_synopsis(uid, nid, c1, "新的本章")
    data = {"kind": "plot", "outline": {"before": "旧的全书", "after": "新的全书"},
            "synopsis": {"chapter_id": c1, "before": "旧的本章", "after": "新的本章"}}
    real = novels.set_synopsis

    def broken(*a, **k):
        raise novels.NotFound("章节不存在")
    novels.set_synopsis = broken
    try:
        E.undo(uid, nid, data)
        raise AssertionError("写梗概失败应报 UndoError")
    except E.UndoError as e:
        assert "章节不存在" in str(e)
    finally:
        novels.set_synopsis = real
    assert novels.get_memory(uid, nid)["plot"]["outline"] == "新的全书"
    r = E.undo(uid, nid, data)
    assert r["code"] == "assistant.undo.done_plot" and r["message"] == "已撤销剧情的修改", r
    try:
        E.undo(uid, nid, {"kind": "bogus"})
        raise AssertionError("未知类型应报 UndoError")
    except E.UndoError as e:
        assert e.code == "assistant.undo.unsupported", e.code
    assert novels.get_memory(uid, nid)["plot"]["outline"] == "旧的全书"
    print("10. 撤销剧情不留半截 ✓")

    # 11. 参数说明里没有 config、tool_call_id；EDITS 名单
    for t in E.TOOLS:
        props = t.tool_call_schema.model_json_schema().get("properties", {})
        assert "config" not in props and "tool_call_id" not in props, (t.name, props)
    assert E.EDITS == ("shots_edit", "asset_edit", "plot_edit")
    print("11. 参数说明 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
