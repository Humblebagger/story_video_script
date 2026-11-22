#!/usr/bin/env python3
"""助手只读工具：章节解析（编号、第N章、中文数字、标题片段、候选）、各工具返回字段、条数与长度截断、
别人的小说拿不到、出错时 ToolMessage 为 error 不中断、goto 的 artifact、没有服务器路径。
用法: python3 tests/assistant/test_tools.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"
# 测试不读真实的 backend/.env：load_settings 里的 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None

from langchain_core.tools import ToolException  # noqa: E402
from assistant import tools as T  # noqa: E402
from render import session as render_session  # noqa: E402
from server import auth, novels, public  # noqa: E402

DOC = json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8"))


def cfg(uid, nid, **where):
    return {"configurable": {"user_id": uid, "novel_id": nid, "where": where}}


def call(tool, config, **args):
    """直接调工具函数体（绕过 ToolNode），拿原始返回或异常。"""
    return tool.func(config=config, **args)


def main() -> int:
    uid = auth.register("alice", "secret1")["id"]
    other = auth.register("bob", "secret1")["id"]
    nid = novels.create_novel(uid, "药")["id"]
    c1 = novels.create_chapter(uid, nid, "第一章 茶馆", text="原文")["id"]
    c2 = novels.create_chapter(uid, nid, "第二章 刑场", text="原文二")["id"]
    c3 = novels.create_chapter(uid, nid, "第三章 坟地", text="")["id"]
    novels.create_version(uid, nid, c1, "v1", {}, "原文")
    novels.update_version_state(uid, nid, c1, "v1", "succeeded", result=copy.deepcopy(DOC))
    novels.adopt_version(uid, nid, c1, "v1")
    C = cfg(uid, nid, chapter_id=c1, step="review")

    # 1. 章节解析
    chs = T._chapters(uid, nid)
    assert T.resolve_chapter(chs, c2, None)["id"] == c2
    assert T.resolve_chapter(chs, "第二章", None)["id"] == c2
    assert T.resolve_chapter(chs, "第2章", None)["id"] == c2
    assert T.resolve_chapter(chs, "3", None)["id"] == c3
    assert T.resolve_chapter(chs, "刑场", None)["id"] == c2
    assert T.resolve_chapter(chs, None, c1)["id"] == c1
    assert T._cn_num("十二") == 12 and T._cn_num("二十") == 20 and T._cn_num("九") == 9
    for bad in ("章", "第九章", None):
        try:
            T.resolve_chapter(chs, bad, None)
            raise AssertionError(f"{bad!r} 应报错")
        except ToolException as e:
            assert "第一章 茶馆" in str(e), "报错里要列出候选章节"
            want = {"章": "assistant.tool.ambiguous_chapter", "第九章": "assistant.tool.no_such_chapter",
                    None: "assistant.tool.pick_chapter"}[bad]
            assert isinstance(e, T.ToolError) and e.code == want, (bad, e.code)
            assert "第一章 茶馆" in e.params["options"]
    try:
        T.resolve_chapter([], "x", None)
        raise AssertionError("没有章节应报错")
    except ToolException as e:
        assert e.params["options"] == {"t": "ref", "code": "assistant.tool.no_chapters"}, e.params
        assert "（还没有章节）" in str(e)
    print("1. 章节解析 ✓")

    # 2. novel_overview：各章与所在步骤
    ov = json.loads(call(T.novel_overview, C))
    assert ov["title"] == "药" and [c["title"] for c in ov["chapters"]][:2] == ["第一章 茶馆", "第二章 刑场"]
    stages = {c["id"]: c["stage"] for c in ov["chapters"]}
    assert stages[c1] == "render" and stages[c2] == "storyboard" and stages[c3] == "import", stages
    # _stage 与前端 chapterStage 对齐：检查没过归 review；会话里没有段归 render；全出完看成片
    base = {"chars": 10, "latest_status": "succeeded", "adopted_version": None,
            "versions": [{"id": "v1", "status": "succeeded"}]}
    full = {"clips": [{"state": "done"}], "final": {"state": "done"}}
    assert T._stage({**base, "versions": [{"id": "v1", "status": "succeeded", "verification_status": "failed"}]}, None) == "review"
    assert T._stage({**base, "latest_status": "draft_invalid", "versions": [{"id": "v1", "status": "draft_invalid"}]}, None) == "review"
    assert T._stage({**base, "latest_status": "failed", "versions": [{"id": "v1", "status": "failed"}]}, None) == "storyboard"
    assert T._stage({**base, "latest_status": "running"}, full) == "storyboard"
    assert T._stage(base, {"clips": [], "final": {}}) == "render"
    assert T._stage(base, {"clips": [{"state": "done"}, {"state": "planned"}], "final": {}}) == "render"
    assert T._stage(base, {"clips": [{"state": "done"}], "final": {}}) == "compose"
    assert T._stage(base, full) == "download"
    print("2. novel_overview ✓")

    # 3. chapter_status：缺省取当前章
    st = json.loads(call(T.chapter_status, C))
    assert st["id"] == c1 and st["adopted_version"] == "v1" and st["stage"] == "render"
    assert st["versions"][0]["id"] == "v1" and st["versions"][0]["shots"] > 0
    print("3. chapter_status ✓")

    # 4. shots_get：最多 20 个、带 more；指定编号；要点字段
    sh = json.loads(call(T.shots_get, C))
    total = sum(len(e["shots"]) for e in DOC["episodes"])
    assert len(sh["shots"]) == min(20, total)
    if total > 20:
        assert sh["more"] == total - 20
    first = DOC["episodes"][0]["shots"][0]
    one = json.loads(call(T.shots_get, C, shot_ids=[first["id"]]))["shots"]
    assert len(one) == 1 and one[0]["id"] == first["id"]
    assert set(one[0]) >= {"id", "episode", "shot_size", "duration_sec", "action", "narration", "dialogue"}
    print("4. shots_get ✓")

    # 5. assets_find：按名字、别名、类型；设定截到 200 字
    a = json.loads(call(T.assets_find, C, query="老栓"))["assets"]
    assert a and a[0]["name"] == "华老栓" and a[0]["kind"] == "characters"
    assert all(len(x["notes"]) <= 200 for x in a)
    locs = json.loads(call(T.assets_find, C, kind="locations"))["assets"]
    assert locs and all(x["kind"] == "locations" for x in locs)
    try:
        call(T.assets_find, C, kind="weapons")
        raise AssertionError("未知类型应报错")
    except ToolException as e:
        assert e.code == "assistant.tool.bad_kind", e.code
    print("5. assets_find ✓")

    # 6. plot_get、film_status（没会话）、jobs_running
    novels.set_outline(uid, nid, "老栓买药救子。")
    p = json.loads(call(T.plot_get, C))
    assert p["outline"] == "老栓买药救子。"
    f = json.loads(call(T.film_status, C))
    assert f["session"] is None
    # 6b. 失败原因出口：旧的带厂商名的文字与旧代码，给模型的输出里没有厂商词、有中性中文原因
    root = novels.render_dir(uid, nid, c1, "v1")
    render_session.build(root, copy.deepcopy(DOC), owner={"user_id": uid, "nid": nid, "cid": c1, "vid": "v1"},
                         patch={}, keyframes={})
    with render_session.mutate(root) as ss:
        ss["clips"][0]["state"] = "failed"
        ss["clips"][0]["error"] = "MiniMax 账户余额不足"
        ss["clips"][0]["error_msg"] = {"code": "film.minimax.insufficient_balance", "params": {}}
    out = call(T.film_status, C)
    f = json.loads(out)
    assert public.find_vendor_words(f["session"]["pending"]) == [], f["session"]["pending"]
    err = next(x for x in f["session"]["pending"] if x["state"] == "failed")["error"]
    assert "余额不足" in err and "联系管理员" in err, err
    print("6b. film_status 失败原因不带厂商名 ✓")

    T.jobs_source = lambda u: [
        {"id": "j1", "status": "running", "novel_id": nid, "chapter": "第二章 刑场", "progress": {"done_chars": 5, "total_chars": 10}, "last_log": "第 1 批"},
        {"id": "j2", "status": "succeeded", "novel_id": nid, "chapter": "x", "progress": None, "last_log": None},
        {"id": "j3", "status": "running", "novel_id": "other", "chapter": "y", "progress": None, "last_log": None}]
    j = json.loads(call(T.jobs_running, C))["jobs"]
    assert [x["id"] for x in j] == ["j1"] and j[0]["percent"] == 50
    print("6. plot_get / film_status / jobs_running ✓")

    # 7. goto：artifact 带目标；步骤非法报错
    content, art = call(T.goto, C, step="render", chapter="第二章")
    assert art == {"chapter_id": c2, "step": "render"} and isinstance(content, str)
    content, art = call(T.goto, C, step="compose")
    assert art == {"chapter_id": c1, "step": "compose"}
    try:
        call(T.goto, C, step="publish")
        raise AssertionError("非法步骤应报错")
    except ToolException:
        pass
    print("7. goto ✓")

    # 8. 别人的小说：每个工具都拿不到
    X = cfg(other, nid)
    for tool, args in ((T.novel_overview, {}), (T.chapter_status, {"chapter": c1}), (T.shots_get, {"chapter": c1}),
                       (T.assets_find, {}), (T.plot_get, {}), (T.film_status, {"chapter": c1})):
        try:
            call(tool, X, **args)
            raise AssertionError(f"{tool.name} 不该拿到别人的小说")
        except ToolException as e:
            assert "不存在" in str(e)
    print("8. 归属 ✓")

    # 9. 截断：超长输出不超过 MAX_CHARS，并且注明截断；没有服务器路径
    s = T._dump({"x": "字" * 9000})
    assert len(s) <= T.MAX_CHARS and s.endswith("（已截断）")
    for tool in (T.novel_overview, T.chapter_status, T.shots_get, T.assets_find, T.plot_get, T.film_status):
        assert _TMP.name not in call(tool, C)
    print("9. 截断与路径 ✓")

    # 10. 工具都设了 handle_tool_error，且给模型的参数说明里没有 config
    for tool in T.TOOLS:
        assert tool.handle_tool_error is T._tool_error_text, tool.name
        assert "config" not in tool.tool_call_schema.model_json_schema().get("properties", {}), tool.name
    print("10. 工具约定 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
