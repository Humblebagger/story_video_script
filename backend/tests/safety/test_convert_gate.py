#!/usr/bin/env python3
"""转换前的内容检查：原文拦截、用户手写的注入文本拦截、不可用都让版本失败且不进入转换；通过后同文本不再调分类器；
转换中的模型拒答记进拦截列表。假转换 + FakeChat。用法: python3 tests/safety/test_convert_gate.py"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests" / "pipeline"))
import _noenv  # noqa: E402,F401  测试不读真实 .env

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* 之前
os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"
os.environ["STORYBOARD_RENDER_RUNNER"] = "0"
os.environ["STORYBOARD_SAFETY"] = "1"

from fakes import FakeChat  # noqa: E402
from pipeline.chat import ChatInvoker, LLMError  # noqa: E402
from pipeline.config import Settings  # noqa: E402
from safety import gate, store  # noqa: E402
from server import app as app_mod  # noqa: E402
from server import novels  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao"
A = {"id": "c" * 12}
CLASSIFIED = []       # 分类器看到的每段文本


def classifier_chat():
    """假分类器：文本里有「禁写」就拦（sexual），有「坏输出」就给非法 JSON，其余通过。"""
    def answer(messages):
        text = messages[-1].content
        CLASSIFIED.append(text)
        if "坏输出" in text:
            return "不是 JSON"
        if "禁写" in text:
            return json.dumps({"blocked": True, "category": "sexual", "reason": "露骨"}, ensure_ascii=False)
        return json.dumps({"blocked": False, "category": None, "reason": ""})
    return ChatInvoker(Settings(api_key="k", transport_retries=0), chat=FakeChat(responses=[answer]))


def main() -> int:
    gate._make_chat = classifier_chat
    converted = []

    def fake_convert(text, params, settings=None, log=print, warnings_out=None,
                     seed_assets=None, manifest_out=None, progress_out=None,
                     on_partial=None, start_numbering=None, novel_context=None, on_event=None):
        converted.append(text)
        if "模型拒答" in text:
            raise LLMError.coded("llm.content_blocked")
        if manifest_out is not None:
            manifest_out.update({"verification": {"status": "passed"}})
        return json.loads((YAO / "output_batch1.json").read_text(encoding="utf-8"))

    app_mod.convert_text = fake_convert
    app_mod._digest_chat = lambda: (_ for _ in ()).throw(LLMError.coded("llm.not_configured"))
    app_mod.novel_user(A)
    nid = app_mod.novels_create(app_mod.NovelBody(title="书"), A)["id"]

    def run(text, title):
        ch = app_mod.chapters_create(nid, app_mod.ChapterBody(title=title, text=text), A)
        r = app_mod.versions_create(nid, ch["id"], app_mod.VersionRequest(), A)
        for _ in range(500):
            if app_mod._jobs[r["job_id"]]["status"] not in ("queued", "running"):
                break
            time.sleep(0.02)
        return ch["id"], r["version_id"], app_mod.get_job(r["job_id"], user=A)

    # 1. 通过：进入转换；发了检查进度事件；同文本第二次不再调分类器
    cid, vid, job = run("他推门进屋。", "一")
    assert job["status"] == "succeeded" and converted == ["他推门进屋。"], job
    assert any(e.get("code") == "job.event.safety_check" for e in job["log"]), job["log"]
    assert any("他推门进屋。" == c for c in CLASSIFIED), CLASSIFIED
    # 第一次转换后资产卡被采用；之后只有新增的卡是未缓存的
    seen = len(CLASSIFIED)
    _cid, _vid, job = run("他推门进屋。", "一续")
    assert job["status"] == "succeeded"
    new_calls = CLASSIFIED[seen:]
    assert len(new_calls) == 1 and "他推门进屋。" not in new_calls and "C01" in new_calls[0], new_calls
    seen = len(CLASSIFIED)
    _cid, _vid, job = run("他推门进屋。", "一再续")
    assert job["status"] == "succeeded" and len(CLASSIFIED) == seen, "没有任何变化：零次分类"
    print("1. 通过与缓存 ✓")

    # 2. 原文拦截：版本失败、消息带类别与编号、没有进入转换、有拦截记录
    n = len(converted)
    cid2, vid2, job = run("这一章有禁写内容。", "二")
    assert job["status"] == "failed" and len(converted) == n, "被拦的不进入转换"
    em = job["error_msg"]
    assert em["code"] == "safety.blocked" and em["params"]["category"] == {"t": "ref", "code": "safety.category.sexual"}
    row = store.find_block(em["ref"])
    assert row and (row["stage"], row["user_id"], row["novel_id"], row["chapter_id"], row["version_id"]) == \
        ("convert", A["id"], nid, cid2, vid2), row
    v = app_mod.versions_get(nid, cid2, vid2, A)
    assert v["status"] == "failed" and v["error_msg"]["code"] == "safety.blocked" and v["error_msg"]["ref"] == em["ref"]
    print("2. 原文拦截 ✓")

    # 3. 用户手写的注入文本（创作限制）拦截：原文干净也不进入转换
    k = novels.add_constraint(A["id"], nid, {"text": "画面要禁写风格"})
    n = len(converted)
    _c, _v, job = run("她走进院子。", "三")
    assert job["status"] == "failed" and job["error_msg"]["code"] == "safety.blocked" and len(converted) == n
    kid = next(c["id"] for c in novels.get_memory(A["id"], nid)["constraints"] if c["text"] == "画面要禁写风格")
    novels.delete_constraint(A["id"], nid, kid)
    _c, _v, job = run("她走进院子。", "三续")
    assert job["status"] == "succeeded", job.get("error_msg")
    print("3. 注入文本拦截 ✓")

    # 4. 不可用：版本失败，消息 safety.unavailable，不进入转换
    n = len(converted)
    _c, _v, job = run("这段会让分类器给坏输出。", "四")
    assert job["status"] == "failed" and job["error_msg"]["code"] == "safety.unavailable" and len(converted) == n
    print("4. 不可用 ✓")

    # 5. 转换过程中的模型拒答：照旧显示 llm.content_blocked，同时写一条不可放行的拦截记录
    cid5, vid5, job = run("这一章会遇到模型拒答。", "五")
    assert job["status"] == "failed" and job["error_msg"]["code"] == "llm.content_blocked", job["error_msg"]
    rows = [r for r in store.list_blocks() if r["chapter_id"] == cid5]
    assert len(rows) == 1 and rows[0]["category"] == "unspecified" and rows[0]["releasable"] is False
    assert rows[0]["stage"] == "convert" and rows[0]["version_id"] == vid5
    print("5. 转换中的模型拒答 ✓")

    # 6. 开关关掉：不检查、不发检查事件
    os.environ["STORYBOARD_SAFETY"] = "0"
    try:
        _c, _v, job = run("关掉以后有禁写内容也照转。", "六")
        assert job["status"] == "succeeded" and not any(e.get("code") == "job.event.safety_check" for e in job["log"])
    finally:
        os.environ["STORYBOARD_SAFETY"] = "1"
    print("6. 开关 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        _TMP.cleanup()
    sys.exit(code)
