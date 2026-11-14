#!/usr/bin/env python3
"""回喂模型的文字不得改动（spec 子计划 5 F）：只用子计划 5 之前就有的接口，逐字核对 feed_snapshot 里的快照。
本文件在子计划 5 的任何后端改动之前单独提交并通过，之后每个 Task 都必须照样通过。不调模型、不联网。
用法: python3 tests/pipeline/test_llm_feed_snapshot.py"""
import hashlib
import json
import os
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

import anthropic  # noqa: E402
import httpx2  # noqa: E402
import feed_snapshot as SNAP  # noqa: E402
from pipeline import novel_memory as nm, quality, repair, review, verification as V  # noqa: E402


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    # 1. 多条规则的一份文档：render()、validation_list、repair_request 逐字不变
    d, frozen = SNAP.snapshot_doc()
    r = V.verify_document(d, frozen_units=frozen)
    assert sorted({f.rule_id for f in r.findings}) == SNAP.SNAPSHOT_RULES
    assert r.render() == SNAP.RENDER, r.render()
    assert sha(r.render()) == SNAP.SHA["render"]
    vl = json.dumps(repair.validation_list(r), ensure_ascii=False)
    assert sha(vl) == SNAP.SHA["validation_list"], vl
    req = repair.repair_request(r, "x")
    assert sha(req) == SNAP.SHA["repair_request"], req
    print("1. render / validation_list / repair_request 逐字不变 ✓")

    # 2. 每条规则的 message（回喂模型）
    for rule, mutate, kw in SNAP.CASES:
        dd = SNAP.doc()
        mutate(dd)
        got = next(f.message for f in V.verify_document(dd, **kw).findings if f.rule_id == rule)
        assert got == SNAP.RULE_MESSAGES[rule], (rule, got)
    saved = sys.modules.get("jsonschema")
    sys.modules["jsonschema"] = None          # import jsonschema 会抛 ImportError
    try:
        eng = V.verify_document(SNAP.doc()).findings[0]
    finally:
        if saved is None:
            sys.modules.pop("jsonschema", None)
        else:
            sys.modules["jsonschema"] = saved
    assert (eng.rule_id, eng.message) == ("SCHEMA-ENGINE-001", SNAP.ENGINE_MESSAGE)
    doc_soft, ctx = SNAP.soft_case()
    found = nm.soft_findings(doc_soft, nm.NovelContext(**ctx))
    assert {f.rule_id: f.message for f in found} == SNAP.SOFT_MESSAGES, [f.message for f in found]
    print("2. 23 条规则的 message 不变 ✓")

    # 3. 质量门与评审回喂模型的报告
    assert quality.narration_density_gate(SNAP.chatty(), 0.6) == (False, SNAP.DENSITY, 1.0)
    assert quality.speech_fit_gate(SNAP.chatty(2), 0.1) == (False, SNAP.SPEECH, 1.0)
    empty = {"episodes": []}
    assert review.run_review(SNAP.Stub(SNAP.LOW_RAW), "原文", empty, 3.5) == (False, SNAP.REV_LOW, 3.2)
    assert review.run_review(SNAP.Stub(SNAP.HIGH_RAW), "原文", empty, 3.5) == (True, SNAP.REV_HIGH, 5.0)
    assert review.run_review(SNAP.Stub(SNAP.BAD_RAW), "原文", empty, 3.5) == (None, SNAP.REV_BAD, None)
    req401 = httpx2.Request("POST", "http://127.0.0.1:9/v1/messages")
    e401 = anthropic.AuthenticationError(
        "x", body={"type": "error", "error": {"type": "authentication_error", "message": "bad key"}},
        response=httpx2.Response(401, request=req401))
    assert review.run_review(SNAP.Stub(raise_=e401), "原文", empty, 3.5) == (None, SNAP.REV_AUTH, None)
    assert review.run_review(SNAP.Stub(raise_=RuntimeError("boom")), "原文", empty, 3.5) == \
        (None, SNAP.REV_CALL_FAILED, None)
    print("3. 质量门与评审的报告不变 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
