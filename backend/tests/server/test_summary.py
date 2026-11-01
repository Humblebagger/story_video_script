#!/usr/bin/env python3
"""小说汇总接口的逻辑测试。用法: python3 tests/server/test_summary.py

全程使用临时数据目录，不碰真实 data/。
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "pipeline"))

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* 之前

from render import session  # noqa: E402
from server import novels, summary, usage  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao"
U = "a" * 12


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def batch_doc(n: int) -> dict:
    return json.loads((YAO / f"output_batch{n}.json").read_text(encoding="utf-8"))


def main() -> int:
    # 1. 两章：第一章采用版，第二章只有原文
    nid = novels.create_novel(U, "药")["id"]
    c1 = novels.create_chapter(U, nid, "一", "原文一")["id"]
    c2 = novels.create_chapter(U, nid, "二", "原文二")["id"]
    doc = batch_doc(1)
    novels.create_version(U, nid, c1, "v1", {}, "原文一")
    novels.update_version_state(U, nid, c1, "v1", "succeeded", result=doc)
    novels.adopt_version(U, nid, c1, "v1")
    s = summary.novel_summary(U, nid)
    assert len(s["chapters"]) == 2
    a, b = s["chapters"]
    assert (a["id"], b["id"]) == (c1, c2)
    assert a["shots"] == sum(len(e["shots"]) for e in doc["episodes"]) and a["version"] == "v1"
    assert a["duration_s"] and a["duration_s"] > 0
    assert a["film"] is None and a["final"] == "none"
    assert b["version"] is None and b["shots"] is None and b["film"] is None and b["final"] == "none"
    assert s["cost"]["render_cny"] is None and s["cost"]["budget_cny"] is None
    print("汇总: 两章 / 采用版 / 无版本章节 ✓")

    # 1b. 未采用时，带警告完成的版本也算可用版本
    c3 = novels.create_chapter(U, nid, "三", "原文三")["id"]
    novels.create_version(U, nid, c3, "w1", {}, "原文三")
    novels.update_version_state(U, nid, c3, "w1", "completed_with_warnings", result=doc)
    w = summary.novel_summary(U, nid)["chapters"][2]
    assert w["version"] == "w1" and w["shots"] == a["shots"]
    print("汇总: 未采用时取带警告完成的版本 ✓")

    # 2. 出片会话：3 段 2 done，已花 1.2
    rd = novels.render_dir(U, nid, c1, "v1")
    rd.mkdir(parents=True)
    sess = {"version": 1, "spent_cny": 1.2, "budget_cny": 20.0, "final": None,
            "clips": [{"id": "k1", "state": "done"}, {"id": "k2", "state": "done"},
                      {"id": "k3", "state": "idle"}]}
    session._save(rd, sess)
    s = summary.novel_summary(U, nid)
    assert s["chapters"][0]["film"] == {"done": 2, "total": 3, "failed": 0, "running": 0}
    assert s["cost"]["render_cny"] == 1.2 and s["chapters"][0]["cost"]["render_cny"] == 1.2
    assert s["cost"]["budget_cny"] == 20.0 and s["chapters"][1]["cost"]["render_cny"] is None
    sess["clips"][2]["state"] = "running"
    sess["clips"].append({"id": "k4", "state": "failed"})
    session._save(rd, sess)
    assert summary.novel_summary(U, nid)["chapters"][0]["film"] == {
        "done": 2, "total": 4, "failed": 1, "running": 1}
    print("汇总: 出片段计数 / 配音已花合计 ✓")

    # 3. 大模型花费：只计这部小说；没定价的模型进 unpriced
    tok = {"input": 1_000_000, "output": 0, "cache_read": 0, "cache_write": 0}
    usage.record(user_id=U, purpose="convert", model="claude-sonnet-5", usage=tok, ok=True,
                 novel_id=nid, chapter_id=c1, version_id="v1")
    usage.record(user_id=U, purpose="convert", model="claude-sonnet-5", usage=tok, ok=True,
                 novel_id="other", chapter_id="x", version_id="y")
    s = summary.novel_summary(U, nid)
    assert abs(s["cost"]["llm_usd"] - 2.0) < 1e-9 and s["unpriced"] == []
    assert abs(s["chapters"][0]["cost"]["llm_usd"] - 2.0) < 1e-9
    assert s["chapters"][1]["cost"]["llm_usd"] == 0
    usage.record(user_id=U, purpose="convert", model="mystery-model", usage=tok, ok=True,
                 novel_id=nid, chapter_id=c2, version_id="v9")
    s = summary.novel_summary(U, nid)
    assert abs(s["cost"]["llm_usd"] - 2.0) < 1e-9 and s["unpriced"] == ["mystery-model"]
    print("汇总: 按小说与章节计大模型花费 / 未定价模型 ✓")

    # 4. 成片状态（会话不存「过期」标记，故无 stale）
    for state, want in (("done", "fresh"), ("queued", "busy"), ("running", "busy"),
                        ("failed", "none")):
        sess["final"] = {"state": state}
        session._save(rd, sess)
        assert summary.novel_summary(U, nid)["chapters"][0]["final"] == want, state
    (rd / session.SESSION_FILE).write_text("{坏", encoding="utf-8")
    c = summary.novel_summary(U, nid)["chapters"][0]
    assert c["film"] is None and c["final"] == "none"
    print("汇总: 成片状态映射 / 损坏会话当作没有 ✓")

    # 5. 别的用户读不到
    must_raise(novels.NotFound, summary.novel_summary, "b" * 12, nid)
    print("汇总: 他人读取抛 NotFound ✓")
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
