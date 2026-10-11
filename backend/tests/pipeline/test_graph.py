#!/usr/bin/env python3
"""单批图的测试。用法: python3 tests/pipeline/test_graph.py"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import FakeChat
from pipeline.chat import ChatInvoker
from pipeline.config import Settings
from pipeline.convert import ConvertParams
from pipeline.errors import ConversionError
from pipeline.graph import build_batch_graph, run_batch

YAO = ROOT / "tests" / "real_text_yao"


def _fixture():
    """取《药》归档的批 1 作为「一次就过」的输入与产物。"""
    import re
    text = (YAO / "input_batch1.txt").read_text(encoding="utf-8")
    m = re.search(r"^章节：.*$", text, flags=re.M)
    batch = text[m.end():] if m else text
    return batch, (YAO / "output_batch1.json").read_text(encoding="utf-8")


def main() -> int:
    batch, archived = _fixture()
    # 与《药》归档 meta 逐字一致的制作参数。九个字段必须全给：
    # quality.apply_meta_overrides 会用 params 覆写 doc["meta"]["style"] 等字段，
    # 少给一个（如 style_prefix）就会落到 ConvertParams 的默认值上，
    # 导致 doc == archived 的断言必然失败。
    params = ConvertParams(
        work_title="药", chapter="全文（1919）",
        style_prefix="民国江南小镇写实风格，电影感光影，青灰冷色调",
        art_style="realistic", color_tone="青灰冷色调，晨昏低饱和",
        aspect_ratio="9:16", target_platform="抖音",
        narration_mode="selective", tts_voice="male_mature")
    settings = Settings(api_key="k", max_retries=0, normalize_input=False,
                        freeze_source_units=False)

    # 1. 一次就过：图跑完，result 是产物，没有降级警告
    with tempfile.TemporaryDirectory() as d:
        records = []
        logs = []
        chat = ChatInvoker(settings, chat=FakeChat(responses=[archived]),
                           log=logs.append)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=settings,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs.append)
        doc, warnings = run_batch(graph, user="【小说原文】" + batch,
                                  batch_text=batch, idx=1, frozen_units=None)
        assert doc == json.loads(archived), "一次就过时产物应与归档一致"
        assert warnings == []
        assert [r["status"] for r in records] == ["passed"]
        assert records[0]["mode"] == "generate" and records[0]["attempt"] == 1
        assert records[0]["usage"]["output"] > 0, "token 要归到这次尝试上"
        print("graph: 一次就过 → result + attempt_records ✓")

    # 2. 首次输出不是 JSON：记 unparseable，重试一次后通过
    with tempfile.TemporaryDirectory() as d:
        records = []
        logs = []
        s2 = Settings(api_key="k", max_retries=1, normalize_input=False,
                      freeze_source_units=False, repair_mode="rewrite")
        chat = ChatInvoker(s2, chat=FakeChat(responses=["我不输出 JSON", archived]),
                           log=logs.append)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=s2,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs.append)
        doc, warnings = run_batch(graph, user="【小说原文】" + batch,
                                  batch_text=batch, idx=1, frozen_units=None)
        assert doc == json.loads(archived)
        assert [r["status"] for r in records] == ["unparseable", "passed"]
        print("graph: 不可解析 → 重试 → 通过 ✓")

    # 3. 重试耗尽且无合法候选：抛 ConversionError，失败报告落盘
    with tempfile.TemporaryDirectory() as d:
        records = []
        chat = ChatInvoker(settings, chat=FakeChat(responses=["坏输出"]),
                           log=lambda _: None)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=settings,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=lambda _: None)
        try:
            run_batch(graph, user="u", batch_text=batch, idx=7, frozen_units=None)
            raise AssertionError("重试耗尽应抛 ConversionError")
        except ConversionError as e:
            assert e.report
            assert (Path(d) / "batch7_failure_report.txt").exists()
        print("graph: 重试耗尽 → ConversionError + 报告落盘 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
