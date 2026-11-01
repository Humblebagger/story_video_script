#!/usr/bin/env python3
"""助手接口：未登录 401、别人的小说 404、空历史、发消息流式返回事件、历史接上、清空、每日上限 429、
同一部小说并发 409、用量记 purpose=assistant、正文过长 422、where.step 非法 422、流里没有服务器路径。
假模型（tests/assistant/fake_model.py），不调真实模型。
用法: python3 tests/server/test_assistant.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "assistant"))
_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"
os.environ["STORYBOARD_TTS_PROVIDER"] = "fake"
os.environ["STORYBOARD_RENDER_RUNNER"] = "0"

from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from fake_model import ScriptedChat, call  # noqa: E402
from assistant import store  # noqa: E402
from server import app as app_mod  # noqa: E402
from server import auth, novels, usage  # noqa: E402


def events_of(res) -> list:
    out = []
    for block in res.text.strip().split("\n\n"):
        lines = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l)
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def main() -> int:
    c = TestClient(app_mod.app)
    uid = auth.register("alice", "secret1")["id"]
    bob = auth.register("bob", "secret1")["id"]
    H = {"Authorization": f"Bearer {auth.issue_token(uid)}"}
    HB = {"Authorization": f"Bearer {auth.issue_token(bob)}"}
    nid = novels.create_novel(uid, "药")["id"]
    cid = novels.create_chapter(uid, nid, "第一章 茶馆", text="原文")["id"]
    A = f"/novels/{nid}/assistant"
    script: list = []
    app_mod._assistant_model = lambda: ScriptedChat(script=script)

    # 1. 鉴权
    assert c.get(A).status_code == 401
    assert c.get(A, headers=HB).status_code == 404
    assert c.post(A + "/messages", headers=HB, json={"text": "hi", "lang": "zh"}).status_code == 404
    assert c.delete(A, headers=HB).status_code == 404
    print("1. 鉴权 ✓")

    # 2. 空历史，且不因读取而建出存档文件
    assert c.get(A, headers=H).json() == {"messages": []}
    assert not store.exists(uid, nid)
    print("2. 空历史 ✓")

    # 3. 发消息：SSE 事件与 content-type
    script[:] = [call("chapter_status", {}, "t1"), call("goto", {"step": "render"}, "t2"), AIMessage("还没出片。")]
    r = c.post(A + "/messages", headers=H, json={"text": "第一章怎样了", "lang": "zh",
                                                 "where": {"chapter_id": cid, "step": "review"}})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    evs = events_of(r)
    assert [e for e, _ in evs] == ["tool_start", "tool_end", "tool_start", "tool_end", "goto", "token", "done"], evs
    assert evs[4][1] == {"chapter_id": cid, "step": "render"}
    assert _TMP.name not in r.text
    print("3. 流式事件 ✓")

    # 4. 历史
    h = c.get(A, headers=H).json()["messages"]
    assert [m["role"] for m in h] == ["user", "assistant"] and h[1]["text"] == "还没出片。"
    assert h[1]["goto"] == [{"chapter_id": cid, "step": "render"}]
    print("4. 历史 ✓")

    # 5. 用量：每轮一条 purpose=assistant，带 novel_id
    rows = [r for r in usage.read(user_id=uid) if r["purpose"] == "assistant"]
    assert len(rows) == 1 and rows[0]["novel_id"] == nid and rows[0]["ok"] is True
    print("5. 用量 ✓")

    # 6. 校验：正文为空或过长、step 非法 → 422
    assert c.post(A + "/messages", headers=H, json={"text": "  ", "lang": "zh"}).status_code == 422
    assert c.post(A + "/messages", headers=H, json={"text": "字" * 2001, "lang": "zh"}).status_code == 422
    assert c.post(A + "/messages", headers=H,
                  json={"text": "hi", "lang": "zh", "where": {"step": "publish"}}).status_code == 422
    print("6. 校验 ✓")

    # 7. 并发：同一部小说已在跑时 409
    assert store.try_begin(uid, nid)
    try:
        r = c.post(A + "/messages", headers=H, json={"text": "hi", "lang": "zh"})
        assert r.status_code == 409, r.status_code
        assert c.delete(A, headers=H).status_code == 409
    finally:
        store.end(uid, nid)
    print("7. 并发 409 ✓")

    # 8. 每日上限：用满后 429，计数不再增加
    os.environ["STORYBOARD_ASSISTANT_DAILY"] = "2"
    script[:] = [AIMessage("好。")]
    assert c.post(A + "/messages", headers=H, json={"text": "再来", "lang": "zh"}).status_code == 200
    r = c.post(A + "/messages", headers=H, json={"text": "还来", "lang": "zh"})
    assert r.status_code == 429 and "今天" in r.json()["detail"]
    assert store.used_today(uid) == 2
    del os.environ["STORYBOARD_ASSISTANT_DAILY"]
    print("8. 每日上限 429 ✓")

    # 9. 模型出错：error 事件、记一条 ok=False 的用量、锁已释放
    class Boom(ScriptedChat):
        def _generate(self, *a, **k):
            raise RuntimeError("网关炸了")
    app_mod._assistant_model = lambda: Boom(script=[])
    evs = events_of(c.post(A + "/messages", headers=H, json={"text": "hi", "lang": "zh"}))
    assert evs[-1][0] == "error"
    assert [r["ok"] for r in usage.read(user_id=uid) if r["purpose"] == "assistant"][-1] is False
    assert store.try_begin(uid, nid)
    store.end(uid, nid)
    print("9. 出错 ✓")

    # 10. 清空
    assert c.delete(A, headers=H).status_code == 200
    assert c.get(A, headers=H).json() == {"messages": []} and not store.exists(uid, nid)
    assert c.delete(A, headers=H).status_code == 200
    print("10. 清空 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
