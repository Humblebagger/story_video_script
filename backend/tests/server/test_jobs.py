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
REVIEW_MODEL = "secret-review-q3"                       # 特征评审模型名：同样不得出现在普通用户接口里
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
        manifest_out.update({"contracts": {"model": settings.model, "review_model": REVIEW_MODEL,
                                         "temperature": 0.2},
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

    # 子计划 5：ConversionError 带逐条消息 → report 参数是 lines；逐条里的数据目录换成 <data>；不再用报告原文
    from server.messages import compact, lines_of
    shown = [compact(msg("verify.report.tool")),
             compact(msg("verify.report.tool_error", text=vendor(f"路径 {auth.DATA_DIR}/users/x")))]
    job = new_job(nid, cid, "v_lines")
    v = run(job, fake_raise(ConversionError.of("job.batch_failed", "原文报告", shown, batch=1, retries=0)))
    rep = v["error_msg"]["params"]["report"]
    assert rep["t"] == "lines" and rep["items"][0]["code"] == "verify.report.tool", rep
    assert str(auth.DATA_DIR) not in json.dumps(rep, ensure_ascii=False)
    assert rep["items"][1]["params"]["text"]["text"] == "路径 <data>/users/x"
    assert v["error"] == "批 1 重试 0 次后仍未通过校验\n工具报告的错误（原文）：\n  路径 <data>/users/x", v["error"]
    assert any("原文报告" in x for x in v["debug_log"]), "报告原文另记进调试日志，管理员能看到（审查 Minor 11）"

    # 降级警告里的原文（评审意见等）也经 scrub_deep：数据目录换成 <data>，中文兜底一起换（审查 Minor 3）
    warn2 = msg("job.quality.degraded", batch=1, retries=2, attempt=2, candidates=2,
                report=lines_of([msg("verify.review.issue", where=vendor("E01"),
                                     problem=vendor(f"见 {auth.DATA_DIR}/users/x"), fix=vendor("改"))]))
    job = new_job(nid, cid, "v_warn2")
    v = run(job, fake_ok(warn2))
    blob = json.dumps(v["quality_msg"], ensure_ascii=False) + v["quality_report"]
    assert str(auth.DATA_DIR) not in blob and "<data>/users/x" in v["quality_report"], blob

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
    # 首次溢出：5001 行 → 恰好 DEBUG_MEM 行，第一行是标记，其后从 l2 起；再溢出仍稳定
    one = {"debug_log": []}
    for i in range(app_mod.DEBUG_MEM + 1):
        app_mod._job_debug(one, f"l{i}")
    assert len(one["debug_log"]) == app_mod.DEBUG_MEM and "截断" in one["debug_log"][0]
    assert one["debug_log"][1] == "l2" and one["debug_log"][-1] == f"l{app_mod.DEBUG_MEM}"
    app_mod._job_debug(one, "next")
    assert len(one["debug_log"]) == app_mod.DEBUG_MEM and one["debug_log"][1] == "l3" and one["debug_log"][-1] == "next"
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


def part_digest(nid, cid):
    # 章后整理的模型服务错误（设计审查 I2）：映射类不记编号，needs_ref 的保留代码并带编号
    req = httpx2.Request("POST", "http://127.0.0.1:9/v1/messages")
    real_in, real_run = novels.digest_input, app_mod.novel_memory.run_digest
    novels.digest_input = lambda *a, **k: ("v_d", [], [])

    def run_with(exc):
        def boom(*a, **k):
            raise exc
        app_mod.novel_memory.run_digest = boom
        try:
            app_mod._run_digest(U, nid, cid)
        finally:
            app_mod.novel_memory.run_digest = real_run
        return novels.get_chapter(U, nid, cid)["digest"]

    try:
        body = {"type": "error", "error": {"type": "rate_limit_error", "message": f"{MODEL} quota {LLM_KEY}"}}
        before = len(error_refs.recent(1000))
        d = run_with(llm_error(anthropic.RateLimitError("x", body=body, response=httpx2.Response(429, request=req))))
        assert d["status"] == "failed" and d["error_msg"] == {"code": "llm.busy", "params": {}}
        assert len(error_refs.recent(1000)) == before and MODEL not in json.dumps(d, ensure_ascii=False)

        raw400 = anthropic.BadRequestError("x", body={"type": "error", "error": {
            "type": "invalid_request_error", "message": f"bad role {MODEL} {LLM_KEY}"}},
            response=httpx2.Response(400, request=req))
        e = llm_error(raw400)
        e.__cause__ = raw400
        d = run_with(e)
        assert d["status"] == "failed" and d["error_msg"]["code"] == "llm.bad_request"
        assert len(d["error_msg"]["ref"]) == 8
        dumped = json.dumps(d, ensure_ascii=False)
        assert MODEL not in dumped and LLM_KEY not in dumped and "chapter.digest.failed" not in dumped
        row = error_refs.find(d["error_msg"]["ref"])
        assert row and "BadRequestError" in row["detail"] and LLM_KEY not in row["detail"]
    finally:
        novels.digest_input = real_in
        app_mod.novel_memory.run_digest = real_run
    print("1b. 章后整理：映射不记编号 / needs_ref 保留代码带编号 ✓")


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
    # 尝试记录里的报告：普通用户视图把主机路径换成占位（验收 G1）
    m = {"attempts": [{"report": f"lint 失败：{auth.DATA_DIR}/users/x/out.json", "batch": 1}, "旧格式"]}
    pub = app_mod._public_manifest(m)
    assert str(auth.DATA_DIR) not in pub["attempts"][0]["report"] and "<data>" in pub["attempts"][0]["report"]
    assert pub["attempts"][1] == "旧格式" and str(auth.DATA_DIR) in m["attempts"][0]["report"], "存储不动"


def part_no_model(nid, cid):
    """spec 子计划 4 E：普通用户接口里没有模型名；管理员能看到。"""
    from fastapi.testclient import TestClient
    c = TestClient(app_mod.app)
    tok = auth.issue_token(U)
    H = {"Authorization": f"Bearer {tok}"}
    h = c.get("/healthz").json()
    assert set(h) == {"status", "first_run"} and h["first_run"] is False, h
    # 走一遍真实的提交路径（convert_text 打桩），等它结束
    real = app_mod.convert_text
    app_mod.convert_text = fake_ok()
    try:
        r = c.post(f"/novels/{nid}/chapters/{cid}/versions", headers=H, json={})
        assert r.status_code == 200, r.text
        vid = r.json()["job_id"]
        for _ in range(200):
            if c.get(f"/jobs/{vid}", headers=H).json()["status"] not in ("queued", "running"):
                break
            time.sleep(0.02)
    finally:
        app_mod.convert_text = real
    stored = novels.get_version(U, nid, cid, vid)
    assert stored["manifest"]["contracts"]["model"] == MODEL and stored["debug_log"], "存储不动"
    assert stored["manifest"]["contracts"]["review_model"] == REVIEW_MODEL, "评审模型名也留在存储里"
    assert REVIEW_MODEL not in json.dumps(app_mod.get_job(vid, user={"id": U})), "任务响应不带评审模型"
    from server import usage
    usage.record(user_id=U, purpose="convert", model=MODEL, usage={"calls": 1, "input": 1, "output": 1},
                 ok=True, novel_id=nid, chapter_id=cid)
    urls = ["/healthz", "/auth/me", "/jobs", f"/jobs/{vid}", f"/novels/{nid}",
            f"/novels/{nid}/chapters/{cid}", f"/novels/{nid}/chapters/{cid}/versions/{vid}",
            f"/novels/{nid}/summary"]
    for u in urls:
        r = c.get(u, headers=H)
        assert r.status_code == 200, (u, r.status_code)
        assert MODEL not in r.text and REVIEW_MODEL not in r.text and "debug_log" not in r.json(), u
    v = c.get(f"/novels/{nid}/chapters/{cid}/versions/{vid}", headers=H).json()
    assert "model" not in v["manifest"]["contracts"] and "review_model" not in v["manifest"]["contracts"]
    assert v["manifest"]["contracts"]["temperature"] == 0.2
    assert c.get("/admin/service", headers=H).status_code == 403, "普通用户看不到服务信息"
    print("3. 普通用户接口不透出模型名、存储不动 ✓")
    return vid


def part_admin(nid, cid, vid):
    from fastapi.testclient import TestClient
    from server import audit
    c = TestClient(app_mod.app)
    admin = auth.register("jobadmin", "secret1")
    auth.update_user(admin["id"], role="admin")
    HA = {"Authorization": f"Bearer {auth.issue_token(admin['id'])}"}
    s = c.get("/admin/service", headers=HA).json()
    assert s["model"] == MODEL and s["api_key_configured"] is True and s["review_model"] is None, s
    # 评审：关 / 开且同一模型 / 开且不同模型
    keys = ("STORYBOARD_REVIEW", "STORYBOARD_REVIEW_MODEL")
    saved = {k: os.environ.get(k) for k in keys}
    try:
        os.environ["STORYBOARD_REVIEW_MODEL"] = REVIEW_MODEL
        os.environ.pop("STORYBOARD_REVIEW", None)
        assert c.get("/admin/service", headers=HA).json()["review_model"] is None, "评审关着不报"
        os.environ["STORYBOARD_REVIEW"] = "1"
        os.environ["STORYBOARD_REVIEW_MODEL"] = MODEL
        assert c.get("/admin/service", headers=HA).json()["review_model"] is None, "与转换同模型不报"
        os.environ["STORYBOARD_REVIEW_MODEL"] = REVIEW_MODEL
        assert c.get("/admin/service", headers=HA).json()["review_model"] == REVIEW_MODEL
    finally:
        for k, x in saved.items():
            if x is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = x

    def views():
        return [a for a in audit.read(1000) if a["action"] == "view_job_debug"]
    n0 = len(views())
    r = c.get(f"/admin/jobs/{vid}/debug", params={"user_id": U}, headers=HA)
    assert r.status_code == 200 and r.json()["lines"], r.text
    rows = views()
    assert len(rows) == n0 + 1, "每次查看恰好一条审计"
    assert rows[0]["after"] == {"version_id": vid} and rows[0]["target_id"] == U and rows[0]["target"] == "jobuser"
    # 内存里没有了（服务重启后）：从版本记录读回落盘的日志
    app_mod._jobs.pop(vid, None)
    r2 = c.get(f"/admin/jobs/{vid}/debug", params={"user_id": U}, headers=HA)
    assert r2.status_code == 200 and r2.json()["lines"], r2.text
    assert r2.json()["lines"] == novels.get_version(U, nid, cid, vid)["debug_log"], "磁盘回退返回落盘的日志"
    rows = views()
    assert len(rows) == n0 + 2 and rows[0]["target_id"] == U, "回退读取同样记一条审计，对象是任务所属用户"
    r = c.get("/admin/jobs/nope/debug", params={"user_id": U}, headers=HA)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "admin.job.not_found"
    r = c.get(f"/admin/jobs/{vid}/debug", params={"user_id": "../x"}, headers=HA)
    assert r.status_code == 404, "非法用户 id 不得 500"
    r = c.get(f"/admin/jobs/{vid}/debug", params={"user_id": "0123456789ab"}, headers=HA)
    assert r.status_code == 404, "不存在的用户"
    tokU = auth.issue_token(U)
    assert c.get(f"/admin/jobs/{vid}/debug", params={"user_id": U},
                 headers={"Authorization": f"Bearer {tokU}"}).status_code == 403
    print("4. 管理员：服务信息带模型名 / 调试日志接口写审计 / 普通用户 403 ✓")


def part_gate():
    """验证门 422 的附加字段 verification：每条 finding 带 msg（spec 子计划 5 C）；名字与其余内容不变。"""
    from fastapi import HTTPException
    bad = {"source": {"units": []},
           "episodes": [{"id": "E01", "shots": [{"id": "E01-SH001", "source": {"unit_refs": ["u0099"]}}]}]}
    try:
        app_mod._render_gate(bad, None)
        raise AssertionError("应被验证门拦下")
    except HTTPException as e:
        fs = e.detail["verification"]["findings"]
        assert e.detail["code"] == "verify.gate.blocked" and e.detail["verification"]["status"] == "failed" and fs
        assert all(f["msg"]["code"] == "verify.rule." + f["rule_id"] and f["message"] for f in fs)
        assert any(f["msg"] == {"code": "verify.rule.REF-UNIT-001", "params": {"unit": "u0099"}} for f in fs)
    print("验证门：422 的逐条带消息对象 ✓")


def main() -> int:
    global U
    U = auth.register("jobuser", "secret1")["id"]
    nid = novels.create_novel(U, "药")["id"]
    cid = novels.create_chapter(U, nid, "第一章", text="他推门。")["id"]
    part_execute(nid, cid)
    part_gate()
    part_digest(nid, cid)
    part_views(nid, cid)
    vid = part_no_model(nid, cid)
    part_admin(nid, cid, vid)
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
