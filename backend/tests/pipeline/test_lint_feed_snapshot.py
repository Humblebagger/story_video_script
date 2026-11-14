#!/usr/bin/env python3
"""lint 的文本输出与它回喂模型的文字不得改动（spec 子计划 5b D）：只用子计划 5b 之前就有的接口，逐字核对 lint_snapshot 里的快照。
本文件在子计划 5b 的任何改动之前单独提交并通过，之后每个 Task 都必须照样通过。不调模型、不联网。
用法: python3 tests/pipeline/test_lint_feed_snapshot.py"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
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

import lint_snapshot as SNAP  # noqa: E402
from fakes import FakeChat  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from pipeline import convert, graph, repair, validate, verification  # noqa: E402
from pipeline.chat import ChatInvoker  # noqa: E402
from pipeline.config import Settings  # noqa: E402
from pipeline.convert import ConvertParams  # noqa: E402
from pipeline.errors import ConversionError  # noqa: E402

LINT = ROOT / "tools" / "lint_storyboard.py"
PARAMS = ConvertParams(
    work_title="药", chapter="全文（1919）", style_prefix="民国江南小镇写实风格，电影感光影，青灰冷色调",
    art_style="realistic", color_tone="青灰冷色调，晨昏低饱和", aspect_ratio="9:16", target_platform="抖音",
    narration_mode="selective", tts_voice="male_mature")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dump(doc: dict, d: str) -> Path:
    p = Path(d) / "doc.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return p


def lint_text(doc: dict):
    """命令行默认（文本）模式：返回 (退出码, stdout, stderr)。"""
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run([sys.executable, str(LINT), str(dump(doc, d))], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def main() -> int:
    # 1. 命令行文本输出逐字不变：23 条错误规则各一种情形，加只有 WARN、全部通过两种
    cases = SNAP.CASES + [("_warnings", SNAP.warn_case)]
    for rule, mutate in cases:
        d = SNAP.base()
        mutate(d)
        rc, out, err = lint_text(d)
        want_rc, want_sha, want_lines = SNAP.LINT[rule]
        got_lines = [ln for ln in out.splitlines() if ln.startswith(("ERROR", "WARN"))]
        assert (rc, got_lines, err) == (want_rc, want_lines, ""), (rule, rc, got_lines, err)
        assert sha(out) == want_sha, (rule, out)
    assert len(SNAP.CASES) == 23
    rc, out, err = lint_text(SNAP.base())
    assert (rc, out, err) == (0, SNAP.PASS_TEXT, ""), out
    print("1. 命令行文本输出逐字不变（23 条错误规则、只有 WARN、全过） ✓")

    # 2. 进程内调用：jsonschema 缺失时的 WARN 与汇总
    spec = importlib.util.spec_from_file_location("lint_storyboard_snap", LINT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    saved = sys.modules.get("jsonschema")
    sys.modules["jsonschema"] = None          # import jsonschema 会抛 ImportError
    buf = io.StringIO()
    try:
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(buf):
            rc = mod.main(str(dump(SNAP.base(), d)))
    finally:
        if saved is None:
            sys.modules.pop("jsonschema", None)
        else:
            sys.modules["jsonschema"] = saved
    assert (rc, buf.getvalue()) == (0, SNAP.NO_JSONSCHEMA_TEXT), buf.getvalue()
    print("2. jsonschema 缺失时的输出不变 ✓")

    # 3. validate.run_lint：退出码与「stdout + stderr」原样
    for rule in ("location_ref", "coverage_unmapped"):
        d = SNAP.base()
        dict(SNAP.CASES)[rule](d)
        with tempfile.TemporaryDirectory() as w:
            ok, out = validate.run_lint(dump(d, w))
        assert ok is False and sha(out) == SNAP.LINT[rule][1], (rule, out)
    with tempfile.TemporaryDirectory() as w:
        assert validate.run_lint(dump(SNAP.base(), w)) == (True, SNAP.PASS_TEXT)
    print("3. run_lint 的返回不变 ✓")

    # 4. _check_batch：结构校验过、lint 未过时的报告与补丁修复请求逐字不变
    with tempfile.TemporaryDirectory() as w:
        ok, hard, report, key, structured = graph._check_batch(
            SNAP.feed_doc(), SNAP.batch_text(), Settings(), Path(w), 1, 1, None, lambda _: None)
    assert (ok, hard, key, structured.ok) == (False, True, None, True)
    assert report == SNAP.FEED_REPORT, report
    assert sha(repair.repair_request(structured, report)) == SNAP.FEED_SHA["repair_request"]
    print("4. _check_batch 的 lint 报告与修复请求不变 ✓")

    # 5. 整张图：两种修复模式真正发给模型的回喂，与重试耗尽时的失败报告
    bad = json.dumps(SNAP.feed_doc(), ensure_ascii=False)
    no_call = AIMessage(content="不调工具", response_metadata={"stop_reason": "end_turn"})
    for mode, second in (("rewrite", bad), ("patch", no_call)):
        settings = Settings(api_key="k", max_retries=1, normalize_input=False,
                            freeze_source_units=False, repair_mode=mode)
        fake = FakeChat(responses=[bad, second])
        with tempfile.TemporaryDirectory() as w:
            chat = ChatInvoker(settings, chat=fake, log=lambda _: None)
            g = graph.build_batch_graph(chat=chat, review_chat=None, settings=settings, params=PARAMS,
                                        workdir=Path(w), attempt_records=[], log=lambda _: None)
            try:
                graph.run_batch(g, user="【小说原文】" + SNAP.batch_text(), batch_text=SNAP.batch_text(),
                                idx=1, frozen_units=None)
                raise AssertionError("lint 未过、重试耗尽应抛 ConversionError")
            except ConversionError as e:
                fed = fake.requests[1]["messages"][-1].content
                if mode == "rewrite":
                    assert sha(fed) == SNAP.FEED_SHA["rewrite"], fed
                    assert sha(e.report) == SNAP.FEED_SHA["batch_failed"], e.report
                    assert SNAP.FEED_REPORT in fed
                else:
                    assert sha(fed) == SNAP.FEED_SHA["repair_request"], fed
                    assert sha(e.report) == SNAP.FEED_SHA["batch_failed_patch"], e.report
    print("5. 两种修复模式的回喂与失败报告不变 ✓")

    # 6. 整章终检：批内校验换成恒通过的替身，让终检跑真的 lint；失败报告与调试日志里的 lint 原文不变
    real_check = graph._check_batch
    graph._check_batch = lambda doc, *a, **k: (True, False, "", None, verification.verify_document(doc))
    try:
        settings = Settings(api_key="k", max_retries=0, normalize_input=False, freeze_source_units=False)
        logs = []
        with tempfile.TemporaryDirectory() as w:
            try:
                convert.convert_text(SNAP.batch_text(), PARAMS, settings=settings, llm=FakeChat(responses=[bad]),
                                     batches=[SNAP.batch_text()], workdir=Path(w), log=logs.append)
                raise AssertionError("整章终检 lint 未过应抛 ConversionError")
            except ConversionError as e:
                assert e.code == "job.final_check_failed", e.code
                assert sha(e.report) == SNAP.FEED_SHA["final_report"], e.report
                assert e.report.startswith(SNAP.FEED_REPORT.split("\nPASS 原文保真")[0] + "\n"), e.report
        assert [x for x in logs if sha(x) == SNAP.FEED_SHA["final_log"]], "调试日志里应有整段 lint 原文"
    finally:
        graph._check_batch = real_check
    print("6. 整章终检的失败报告与调试日志不变 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
