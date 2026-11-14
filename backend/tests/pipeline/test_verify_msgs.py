#!/usr/bin/env python3
"""验证报告逐条（spec 子计划 5）：每条规则的代码与参数、给用户的逐条消息。回喂模型的原文见 test_llm_feed_snapshot.py。
不调模型、不联网。用法: python3 tests/pipeline/test_verify_msgs.py"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name           # 必须在导入 server.* / pipeline.* 之前
os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"  # 保险：漏了桩也到不了真实模型服务
os.environ["ANTHROPIC_API_KEY"] = "sk-test-not-real"
import pipeline.config as _pc  # noqa: E402
_pc._load_dotenv = lambda *_a, **_k: None                # 不读真实的 backend/.env

import feed_snapshot as SNAP  # noqa: E402
from pipeline import novel_memory as nm, repair, verification as V  # noqa: E402
from server import messages as M  # noqa: E402

# 每条规则期望的 params（None：单独断言）
PARAMS = {
    "SOURCE-FROZEN-001": {"expected": 3, "actual": 2},
    "SOURCE-FROZEN-002": {"unit": "u0001", "field": "text"},
    "SOURCE-WAIVER-001": {"unit": "u0003"},
    "ID-UNIT-001": {"id": "u0001"},
    "ID-EPISODE-001": {"id": "E01"},
    "ID-SHOT-001": {"id": "E01-SH001"},
    "ID-ASSET-001": {"id": "C01"},
    "REF-UNIT-001": {"unit": "u0099"},
    "EVIDENCE-INFERENCE-001": {},
    "EVIDENCE-SHOT-001": {},
    "EVIDENCE-RANGE-001": {},
    "ORDER-001": {"prev": "E01-SH001", "unit": "u0002"},
    "FID-DIALOGUE-001": {},
    "REF-NARRATION-001": {"unit": "u0099"},
    "FID-NARRATION-001": {},
    "COVERAGE-001": {"n": 1},
    "COVERAGE-DECLARED-001": {},
    "COVERAGE-DECLARED-002": {},
    "FID-SOURCE-001": {},
    "SCHEMA-001": None,
}


def main() -> int:
    # 0. 最小分镜只有结构问题，下面每条用例触发的都是它自己改坏的那一处
    assert {f.rule_id for f in V.verify_document(SNAP.doc()).findings} <= {"SCHEMA-001"}

    # 1. 每条规则：代码、参数、存档形状
    seen = set()
    for rule, mutate, kw in SNAP.CASES:
        d = SNAP.doc()
        mutate(d)
        f = next(f for f in V.verify_document(d, **kw).findings if f.rule_id == rule)
        assert f.as_msg() == {"code": f"verify.rule.{rule}", "params": f.params}
        if PARAMS[rule] is not None:
            assert f.params == PARAMS[rule], (rule, f.params)
        out = f.to_dict()
        assert out["msg"] == f.as_msg() and "params" not in out, rule
        assert "msg" not in f.to_dict(shown=False), rule
        zh = M.render_zh(f"verify.rule.{rule}", f.params)
        assert zh and "{" not in zh, (rule, zh)
        seen.add(rule)
    sch = next(f for f in V.verify_document(SNAP.doc()).findings if f.rule_id == "SCHEMA-001")
    assert sch.params == {"detail": {"t": "vendor", "text": sch.message[:M.VENDOR_MAX]}}, "jsonschema 原文作厂商原文参数"
    print("1. 20 条规则逐条：代码、参数、存档带 msg、回喂形状不带 ✓")

    # 2. 结构校验组件缺失
    saved = sys.modules.get("jsonschema")
    sys.modules["jsonschema"] = None          # import jsonschema 会抛 ImportError
    try:
        eng = V.verify_document(SNAP.doc()).findings[0]
    finally:
        if saved is None:
            sys.modules.pop("jsonschema", None)
        else:
            sys.modules["jsonschema"] = saved
    assert eng.as_msg() == {"code": "verify.rule.SCHEMA-ENGINE-001", "params": {}}
    seen.add("SCHEMA-ENGINE-001")
    print("2. SCHEMA-ENGINE-001 ✓")

    # 3. 软核查两条：参数结构化（message 与旧写法一字不差由快照测试守护）
    doc_soft, ctx = SNAP.soft_case()
    found = {f.rule_id: f for f in nm.soft_findings(doc_soft, nm.NovelContext(**ctx))}
    assert found["NOVEL-CONSTRAINT-001"].params == {"shot": "E01-SH001", "keywords": ["血"], "constraint": "不出现血腥画面"}
    assert found["NOVEL-LIFECYCLE-001"].params == {
        "shot": "E01-SH001", "state": {"t": "ref", "code": "verify.lifecycle.deceased"}, "character": "C03小栓"}
    seen |= set(found)
    print("3. 软核查：参数结构化 ✓")

    # 4. 源码里的规则编号与登记表一一对应，且每条都有触发用例
    src = "".join((ROOT / "pipeline" / n).read_text(encoding="utf-8") for n in ("verification.py", "novel_memory.py"))
    in_src = set(re.findall(r'"([A-Z]+(?:-[A-Z]+)*-\d{3})"', src))
    registered = {c[len("verify.rule."):] for c in M.dump_codes() if c.startswith("verify.rule.")}
    assert in_src == registered and len(registered) == 23, sorted(in_src ^ registered)
    assert seen == registered, sorted(registered - seen)
    print("4. 23 条规则全部登记、全部有用例 ✓")

    # 5. 两种存档形状：接口与版本记录带 msg；回喂模型与尝试记录不带（逐字由快照测试守护）
    d, frozen = SNAP.snapshot_doc()
    r = V.verify_document(d, frozen_units=frozen)
    assert all("msg" in f for f in r.to_dict()["findings"])
    assert all("msg" not in f for f in r.to_dict(shown=False)["findings"])
    assert all("msg" not in x and "params" not in x for x in repair.validation_list(r))
    assert "verify.rule" not in repair.repair_request(r, "x")
    print("5. 存档形状 ✓")

    # 6. lines()：汇总在第一行（截断时不丢），然后覆盖统计、逐条；中文兜底
    ls = r.lines()
    assert ls[0] == {"code": "verify.report.fail", "params": {"n": len(r.errors)}} and len(r.errors) == 15
    assert ls[1]["code"] == "verify.report.coverage" and len(ls) == len(r.findings) + 2
    order = next(x for x in ls if x["code"] == "verify.report.finding" and x["params"]["rule"] == "ORDER-001")
    assert order["params"] == {"severity": {"t": "ref", "code": "verify.severity.medium"}, "rule": "ORDER-001",
                               "path": "/episodes/0/shots/1/source/unit_refs",
                               "detail": {"code": "verify.rule.ORDER-001", "params": {"prev": "E01-SH001", "unit": "u0002"}}}
    txt = M.render_zh("common.unknown", {"message": M.lines_of(ls)})
    assert txt.startswith("未通过（15 条硬性问题）\n覆盖：选中 3 句，已承载 1，豁免 0，未承载 2\n"), txt
    assert "提醒 [ORDER-001] /episodes/0/shots/1/source/unit_refs：镜头回跳到更早的原文（上一处 E01-SH001 引至 u0002）" in txt
    assert V.VerificationReport().lines() == [{"code": "verify.report.pass", "params": {}}], "没有条目、没有覆盖统计时只有一行通过"
    print("6. lines()：汇总、覆盖、逐条 ✓")

    # 7. 旁白密度门：带 lines_out 时报告照旧；逐条只有现象与清单
    import anthropic
    import httpx2
    from pipeline import quality, review

    out = []
    assert quality.narration_density_gate(SNAP.chatty(), 0.6, lines_out=out) == (False, SNAP.DENSITY, 1.0)

    def unit(i):
        return {"code": "verify.quality.unit", "params": {"id": f"u{i:04d}", "kind": "action", "text": f"第{i}句动作描写。"}}
    assert out == [{"code": "verify.quality.density", "params": {"ratio": "100%", "max": "60%"}},
                   {"code": "verify.quality.density_safe", "params": {}}, unit(1), unit(3),
                   {"code": "verify.quality.density_bare", "params": {}}, unit(2), unit(4)], out
    txt = M.render_zh("common.unknown", {"message": M.lines_of(out)})
    assert txt.startswith("旁白占比 100%，超过阈值 60%") and "请逐句重新裁决" not in txt, "给用户的没有给模型的操作指示"
    out = []
    assert quality.narration_density_gate(SNAP.chatty(), 1.0, lines_out=out)[0] and out == [], "通过时不写逐条"
    print("7. 旁白密度门：报告照旧、逐条 ✓")

    # 8. 时长门
    out = []
    assert quality.speech_fit_gate(SNAP.chatty(2), 0.1, lines_out=out) == (False, SNAP.SPEECH, 1.0)

    def sh(i):
        return {"code": "verify.quality.speech_shot",
                "params": {"shot": f"E01-SH{i:03d}", "have": "1", "need": "5.3", "gap": "4.3"}}
    assert out == [{"code": "verify.quality.speech", "params": {"over": 2, "total": 2, "ratio": "100%", "cps": "4.5",
                                                                "max": "10%", "nominal": "2", "actual": "10.7"}},
                   sh(1), sh(2)], out
    print("8. 时长门：报告照旧、逐条 ✓")

    # 9. 评审：报告照旧；评审意见是厂商原文；调用失败的原因是映射后的 llm.*
    empty = {"episodes": []}
    out = []
    assert review.run_review(SNAP.Stub(SNAP.LOW_RAW), "原文", empty, 3.5, lines_out=out) == (False, SNAP.REV_LOW, 3.2)

    def dim(k, v):
        return {"code": "verify.review.dim_score",
                "params": {"dim": {"t": "ref", "code": f"verify.review.dim.{k}"}, "score": v}}
    assert out == [
        {"code": "verify.review.scored", "params": {"overall": "3.2", "min": "3.5", "scores": [
            dim("narration_selection", 2), dim("shot_language", 4), dim("asset_quality", 4), dim("semantic_fidelity", 3)]}},
        {"code": "verify.review.issue", "params": {"where": {"t": "vendor", "text": "E01-SH002"},
                                                   "problem": {"t": "vendor", "text": "旁白重复画面"},
                                                   "fix": {"t": "vendor", "text": "删掉旁白"}}},
        {"code": "verify.review.gates", "params": {"gates": [
            {"code": "verify.review.gate.overall", "params": {"overall": "3.2", "min": "3.5"}},
            {"code": "verify.review.gate.weak",
             "params": {"dims": [{"t": "ref", "code": "verify.review.dim.narration_selection"}]}},
            {"code": "verify.review.gate.semantic", "params": {"score": 3, "min": 4}}]}}], out
    txt = M.render_zh("common.unknown", {"message": M.lines_of(out)})
    assert txt.startswith("评审总分 3.2（阈值 3.5）：旁白取舍 2、镜头语言 4、资产卡质量 4、语义忠实 3\n"), txt
    assert "请针对上述 issues" not in txt

    out = []
    assert review.run_review(SNAP.Stub(SNAP.HIGH_RAW), "原文", empty, 3.5, lines_out=out) == (True, SNAP.REV_HIGH, 5.0)
    assert [x["code"] for x in out] == ["verify.review.scored", "verify.review.no_issues"]

    out = []
    assert review.run_review(SNAP.Stub(SNAP.BAD_RAW), "原文", empty, 3.5, lines_out=out) == (None, SNAP.REV_BAD, None)
    assert out == [{"code": "verify.review.unverifiable", "params": {}}], "细节（对模型输出的格式检查）不给用户"

    req = httpx2.Request("POST", "http://127.0.0.1:9/v1/messages")
    e401 = anthropic.AuthenticationError(
        "x", body={"type": "error", "error": {"type": "authentication_error", "message": "bad key"}},
        response=httpx2.Response(401, request=req))
    out = []
    assert review.run_review(SNAP.Stub(raise_=e401), "原文", empty, 3.5, lines_out=out) == (None, SNAP.REV_AUTH, None)
    assert out == [{"code": "verify.review.unavailable", "params": {"cause": {"code": "llm.auth", "params": {}}}}], out
    out = []
    assert review.run_review(SNAP.Stub(raise_=RuntimeError("boom")), "原文", empty, 3.5, lines_out=out) == \
        (None, SNAP.REV_CALL_FAILED, None)
    assert out == [{"code": "verify.review.unavailable",
                    "params": {"cause": {"code": "verify.review.call_failed", "params": {}}}}], out
    print("9. 评审：报告照旧、逐条、意见原样、失败原因映射 ✓")

    # 10. 脱敏（Codex 审查）：给界面的参数、旧 message 都不带密钥；回喂模型的原文不动
    import hashlib  # noqa: F401
    FAKE = "fake-provider-key-0123456789"
    os.environ["ARK_API_KEY"] = FAKE
    leaks = [FAKE, "Bearer abc.def-123", "x-api-key: sk-zzz999"]
    blob = " ".join(leaks)

    def clean(x, label):
        t = json.dumps(x, ensure_ascii=False)
        assert FAKE not in t and "abc.def-123" not in t and "sk-zzz999" not in t, (label, t)

    d = SNAP.doc()
    d["meta"] = {"narration": {"mode": blob}}
    rep = V.verify_document(d)
    sch = next(f for f in rep.findings if f.rule_id == "SCHEMA-001" and "narration" in f.object_path)
    clean(sch.as_msg(), "schema msg")
    clean(rep.to_dict(), "report to_dict")
    clean(rep.lines(), "lines")
    assert FAKE in json.dumps(rep.to_dict(shown=False)), "回喂模型的原文照旧（模型侧不在本任务脱敏）"
    doc_soft, ctx = SNAP.soft_case()
    ctx["constraints"][0]["text"] = "不出现血腥画面 " + blob
    ctx["names"]["C03"] = "小栓 " + blob
    soft = nm.soft_findings(doc_soft, nm.NovelContext(**ctx))
    assert len(soft) == 2
    for f in soft:
        clean(f.as_msg(), "soft msg")
        clean(f.to_dict(), "soft dict")
        clean(f.message, "soft message")

    class _Chat:
        def invoke(self, _m):
            return SNAP.LOW_RAW.replace("删掉旁白", blob)

        def text(self, r):
            return r
    out = []
    review.run_review(_Chat(), "原文", {"episodes": []}, 3.5, lines_out=out)
    assert any(x["code"] == "verify.review.issue" for x in out)
    clean(out, "review lines")
    u = SNAP.chatty()
    u["source"]["units"][0]["text"] = blob
    out = []
    quality.narration_density_gate(u, 0.6, lines_out=out)
    clean(out, "quality lines")

    # 身份哈希不因 msg 变化（控制器裁定保留 shown=False）
    d2, fz = SNAP.snapshot_doc()
    r2 = V.verify_document(d2, frozen_units=fz)
    assert V.verification_identity(r2) == V._hash_json(r2.to_dict(shown=False))
    assert "msg" in r2.to_dict()["findings"][0] and V._hash_json(r2.to_dict()) != V.verification_identity(r2)
    del os.environ["ARK_API_KEY"]
    print("10. 脱敏与身份哈希 ✓")

    # 11. 检查工具输出：标题 + 每条 ERROR 行（原文）；WARN、汇总、PASS 不要；没有 ERROR 行时取 FAIL 与缩进的差异行
    lint = ("WARN  [E01] music.curve 未覆盖到本集最后一镜\n"
            "ERROR [E01-SH001] location_ref 引用不存在的场景: L09\n\n"
            "旁白模式 selective；镜头 3 个\nFAIL（1 个错误）\n"
            "PASS 原文保真：3 个 unit 拼接后与原文逐字一致（9 字符）")
    assert V.tool_lines(lint) == [
        {"code": "verify.report.tool", "params": {}},
        {"code": "verify.report.tool_error",
         "params": {"text": {"t": "vendor", "text": "[E01-SH001] location_ref 引用不存在的场景: L09"}}}]
    fid = "PASS\nFAIL 原文保真：unit 拼接与原文不一致\n  首个差异位置 3"
    assert [x["params"]["text"]["text"] for x in V.tool_lines(fid)[1:]] == ["FAIL 原文保真：unit 拼接与原文不一致", "首个差异位置 3"]
    assert [x["params"]["text"]["text"] for x in V.tool_lines("怪输出")[1:]] == ["怪输出"], "认不出格式时整段作一项"
    print("11. 检查工具输出按 ERROR 行拆分 ✓")

    # 11. 整份对外报告脱敏：unit_refs、actual、coverage 等其余字段也不漏
    os.environ["ARK_API_KEY"] = FAKE
    d = SNAP.doc()
    d["episodes"] = [{"id": "E01", "shots": [{"id": "E01-SH001", "source": {"unit_refs": [FAKE_REF := "Bearer " + "abc.def-123 " + FAKE]},
                                              "dialogue": [{"text": "x-api-key: sk-zzz999"}]}]}]
    d["source"] = {"units": [{"id": "u0001", "text": "他说话", "para": 1}]}
    rep = V.verify_document(d)
    got = {f.rule_id for f in rep.findings}
    assert "REF-UNIT-001" in got, got
    clean(rep.to_dict(), "report all fields")
    assert FAKE in json.dumps(rep.to_dict(shown=False)), "回喂模型的不脱敏"
    rep.coverage = {"selected": [blob], "failed": [FAKE]}
    clean(rep.to_dict(), "coverage")
    d["episodes"][0]["shots"][0]["source"]["unit_refs"] = ["u0001"]
    d["episodes"][0]["shots"][0]["dialogue"] = [{"text": blob}]
    rep = V.verify_document(d)
    assert any(f.rule_id == "FID-DIALOGUE-001" for f in rep.findings)
    clean(rep.to_dict(), "FID-DIALOGUE actual")
    del os.environ["ARK_API_KEY"]

    # 12. 跨截断边界：密钥横跨截断位置，先截断再脱敏会留下抹不掉的前半截
    KEY = "sk-" + "Q" * 40
    os.environ["ARK_API_KEY"] = KEY

    def no_prefix(x, label):
        t = json.dumps(x, ensure_ascii=False)
        assert "QQQQQ" not in t and KEY[:10] not in t, (label, t)
    u = SNAP.chatty()
    u["source"]["units"][0]["text"] = "字" * 20 + KEY
    out = []
    quality.narration_density_gate(u, 0.6, lines_out=out)
    no_prefix(out, "quality 30 cut")
    pad = "字" * 280

    class _Chat2:
        def invoke(self, _m):
            return SNAP.LOW_RAW.replace("E01-SH002", pad + KEY).replace("旁白重复画面", pad + KEY).replace("删掉旁白", pad + KEY)

        def text(self, r):
            return r
    out = []
    review.run_review(_Chat2(), "原文", {"episodes": []}, 3.5, lines_out=out)
    assert any(x["code"] == "verify.review.issue" for x in out)
    no_prefix(M.lines_of(out), "review 300 cut")
    d = SNAP.doc()
    d["meta"] = {"narration": {"mode": pad + KEY}}
    sch = next(f for f in V.verify_document(d).findings if f.rule_id == "SCHEMA-001" and "narration" in f.object_path)
    no_prefix(sch.as_msg(), "schema 300 cut")
    del os.environ["ARK_API_KEY"]
    print("11-12. 整份报告脱敏与跨截断边界 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
