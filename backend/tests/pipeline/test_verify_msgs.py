#!/usr/bin/env python3
"""验证报告逐条（spec 子计划 5）：每条规则的代码与参数、给用户的逐条消息。回喂模型的原文见 test_llm_feed_snapshot.py。
不调模型、不联网。用法: python3 tests/pipeline/test_verify_msgs.py"""
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

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
