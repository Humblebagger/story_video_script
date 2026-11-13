#!/usr/bin/env python3
"""转换任务（spec 子计划 4 B、E）：_execute 的成功、降级、各类失败；版本记录的 error_msg、quality_msg、debug_log；
任务视图不给调试日志；管理员调试日志接口；普通用户接口不透出模型名。所有模型调用都打桩，不联网。
用法: python3 tests/server/test_jobs.py"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "pipeline"))

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name          # 必须在导入 server.* 之前
os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"  # 保险：漏了桩也到不了真实模型服务
LLM_KEY = "sk-test-llm-0123456789"
os.environ["ANTHROPIC_API_KEY"] = LLM_KEY              # 只为验证脱敏
MODEL = "secret-model-x9"
os.environ["STORYBOARD_MODEL"] = MODEL                  # 特征模型名：普通用户接口里不得出现
os.environ["STORYBOARD_CHAPTER_DIGEST"] = "0"           # 不排章后整理（它会调模型）
os.environ["STORYBOARD_RENDER_RUNNER"] = "0"
import pipeline.config as _pc  # noqa: E402
_pc._load_dotenv = lambda *_a, **_k: None               # 不读真实的 backend/.env

import anthropic  # noqa: E402
import httpx2  # noqa: E402
from pipeline.chat import LLMError, llm_error  # noqa: E402
from pipeline.errors import ConversionError  # noqa: E402
from server import app as app_mod, auth, error_refs, novels  # noqa: E402

U = None


def new_job(nid, cid, vid):
    job = {"id": vid, "user_id": U, "status": "queued", "log": [], "debug_log": [], "result": None,
           "quality_report": None, "quality_msg": None, "error": None, "error_msg": None, "persisted": True,
           "created_at": "2026-11-13T00:00:00+00:00", "work_title": "药", "chapter": "第一章", "chars": 4,
           "progress": {}, "partial": None, "novel_id": nid, "chapter_id": cid, "version_id": vid}
    novels.create_version(U, nid, cid, vid, {}, "他推门。")
    return job


def run(job, fake):
    """用打桩的 convert_text 跑一次 _execute（同步，不经线程池）。"""
    real = app_mod.convert_text
    app_mod.convert_text = fake
    try:
        app_mod._execute(job, "他推门。", app_mod.ConvertParams(), False, None,
                         lambda status, **f: novels.update_version_state(
                             U, job["novel_id"], job["chapter_id"], job["id"], status, **f),
                         lambda job, note: note("job.event.archived"))
    finally:
        app_mod.convert_text = real
    return novels.get_version(U, job["novel_id"], job["chapter_id"], job["id"])


def fake_ok(warn=None):
    def f(text, params, settings=None, log=print, on_event=None, warnings_out=None, manifest_out=None, **kw):
        log("调试细节 工作目录 /tmp/storyboard_x")
        on_event({"code": "job.event.verified", "params": {}, "message": "整章终检通过"})
        manifest_out.update({"contracts": {"model": settings.model, "temperature": 0.2},
                             "attempts": [], "verification": {"status": "verified", "findings": []}})
        if warn:
            warnings_out.append(warn)
        return {"episodes": []}
    return f


def fake_raise(exc):
    def f(text, params, settings=None, log=print, on_event=None, manifest_out=None, **kw):
        manifest_out.update({"contracts": {"model": settings.model}, "attempts": [],
                             "verification": {"status": "failed", "findings": []}})
        raise exc
    return f


def part_execute(nid, cid):
    # 成功 + 降级：quality_msg 与 quality_report 同源；事件带时间；调试日志只在内存与版本里
    from server.messages import REPORT_MAX, msg, vendor
    warn = msg("job.quality.degraded", batch=1, retries=2, attempt=2, candidates=2,
               report=vendor("[quality] 旁白占比 80%", limit=REPORT_MAX))
    job = new_job(nid, cid, "v_ok")
    v = run(job, fake_ok(warn))
    assert job["status"] == "completed_with_warnings" and v["quality_msg"] == [warn]
    assert v["quality_report"] == warn["message"] and v["error"] is None and v["error_msg"] is None
    assert [e["code"] for e in job["log"]] == ["job.event.verified", "job.event.archived"], job["log"]
    assert all(e.get("at") for e in job["log"])
    assert any("调试细节" in x for x in v["debug_log"]), "convert_text 的 log 进调试日志并随版本落盘"
    assert any("仅存档" in x for x in job["debug_log"]), "app 自己记的事件（note）同时进调试日志"

    # ConversionError 带报告：error_msg = job.failed_report；中文兜底等于「原因\n报告」；报告里的数据目录换成 <data>
    report = f"FAIL: E01-SH003 引用了不存在的资产 C09\n路径 {auth.DATA_DIR}/users/x"
    job = new_job(nid, cid, "v_conv")
    v = run(job, fake_raise(ConversionError.of("job.batch_failed", report, batch=2, retries=3)))
    m = v["error_msg"]
    assert m["code"] == "job.failed_report" and "ref" not in m
    assert m["params"]["reason"] == {"code": "job.batch_failed", "params": {"batch": 2, "retries": 3}}
    assert m["params"]["report"]["t"] == "vendor" and str(auth.DATA_DIR) not in m["params"]["report"]["text"]
    assert v["error"].startswith("批 2 重试 3 次后仍未通过校验\nFAIL: E01-SH003") and v["status"] == "failed"
    assert v["verification"] == {"status": "failed", "findings": []}, "ConversionError 照旧保存验证报告"

    # 已映射的模型服务错误：代码，不带编号；hint 进调试日志；error 里没有模型名与原文
    req = httpx2.Request("POST", "http://127.0.0.1:9/v1/messages")
    body = {"type": "error", "error": {"type": "rate_limit_error", "message": f"{MODEL} quota {LLM_KEY}"}}
    e = llm_error(anthropic.RateLimitError("x", body=body, response=httpx2.Response(429, request=req)))
    job = new_job(nid, cid, "v_llm")
    before = len(error_refs.recent(1000))
    v = run(job, fake_raise(e))
    assert v["error_msg"] == {"code": "llm.busy", "params": {}} and MODEL not in v["error"]
    assert len(error_refs.recent(1000)) == before, "映射类错误不记编号"
    assert any("status=429" in x for x in v["debug_log"]) and not any(LLM_KEY in x for x in v["debug_log"])

    # needs_ref 的模型错误：保留 llm.bad_request 并带编号（设计审查 I2）；意外异常：job.crashed 带编号；不再存 repr(e)
    raw400 = anthropic.BadRequestError("x", body={"type": "error", "error": {"type": "invalid_request_error",
                                                                            "message": f"bad role {MODEL}"}},
                                       response=httpx2.Response(400, request=req))
    e = llm_error(raw400)
    e.__cause__ = raw400
    job = new_job(nid, cid, "v_ref")
    v = run(job, fake_raise(e))
    assert v["error_msg"]["code"] == "llm.bad_request" and len(v["error_msg"]["ref"]) == 8
    assert MODEL not in v["error"] and "参考编号" in v["error"]
    assert "BadRequestError" in error_refs.find(v["error_msg"]["ref"])["detail"], "错误记录里是接口原异常"
    # 成功后的 note（自动采用等）也随版本落盘（设计审查 M5）
    assert any("仅存档" in x for x in novels.get_version(U, nid, cid, "v_ok")["debug_log"])
    # 内存里的调试日志有上限（设计审查 M6）
    big = {"debug_log": []}
    for i in range(app_mod.DEBUG_MEM + 10):
        app_mod._job_debug(big, f"l{i}")
    assert len(big["debug_log"]) == app_mod.DEBUG_MEM and "截断" in big["debug_log"][0]
    assert big["debug_log"][-1] == f"l{app_mod.DEBUG_MEM + 9}"
    job = new_job(nid, cid, "v_boom")
    v = run(job, fake_raise(RuntimeError(f"disk on fire {LLM_KEY}")))
    ref = v["error_msg"]["ref"]
    assert v["error_msg"]["code"] == "job.crashed" and "RuntimeError" not in v["error"] and "参考编号" in v["error"]
    row = error_refs.find(ref)
    assert row and row["where"] == f"convert {nid}/{cid}/v_boom" and row["user_id"] == U
    assert "RuntimeError" in row["detail"] and LLM_KEY not in row["detail"]
    # 没有代码的 ConversionError（分批范围不确定，程序错误）同样按意外处理
    job = new_job(nid, cid, "v_split")
    v = run(job, fake_raise(ConversionError("分批范围不确定")))
    assert v["error_msg"]["code"] == "job.crashed" and v["error_msg"].get("ref")
    print("1. _execute：降级 / 带报告 / 映射 / 带编号 / 版本写全 ✓")


def part_views(nid, cid):
    # /jobs 摘要：last_log 是事件对象；助手 jobs_running 拿中文兜底字符串
    job = new_job(nid, cid, "v_view")
    app_mod._jobs["v_view"] = job
    try:
        app_mod._job_note(job, "job.event.split", chars=4, batches=1)
        rows = app_mod.list_jobs(user={"id": U})["jobs"]
        row = next(r for r in rows if r["id"] == "v_view")
        assert row["last_log"]["code"] == "job.event.split" and row["log_lines"] == 1
        assert app_mod._jobs_view(U)[-1]["last_log"] == "输入 4 字符 → 1 批"
    finally:
        app_mod._jobs.pop("v_view", None)
    print("2. 任务摘要 / 助手的 last_log ✓")


def main() -> int:
    global U
    U = auth.register("jobuser", "secret1")["id"]
    nid = novels.create_novel(U, "药")["id"]
    cid = novels.create_chapter(U, nid, "第一章", text="他推门。")["id"]
    part_execute(nid, cid)
    part_views(nid, cid)
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
