#!/usr/bin/env python3
"""流水线离线回归测试：不调用真实 LLM。

用《药》测试归档做回放——mock LLM 依次返回归档的批 1/批 2 输出，
走完 convert_text 全流程（用户消息拼装 → 逐批校验 → 续批参数推算 →
合并 → 整章终检），验证编排逻辑与人肉实测完全一致。

用法: python3 tests/pipeline/test_offline.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.config import Settings
from pipeline.convert import ConvertParams, convert_text
from pipeline.prompt import load_system_prompt
from pipeline.splitter import split_batches

YAO = ROOT / "tests" / "real_text_yao"


def extract_passage(text: str) -> str:
    m = re.search(r"^章节：.*$", text, flags=re.M)
    return text[m.end():] if m else text


class MockLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, system, messages):
        self.calls.append(messages)
        return self.responses.pop(0)


def main() -> int:
    full = (YAO / "input_full.txt").read_text(encoding="utf-8")

    # 1. splitter：批拼接必须逐字节还原原文（split_batches 内部有断言）
    batches = split_batches(full, 2500, 3200)
    assert len(batches) >= 2, f"4584 字符应分出多批，实际 {len(batches)}"
    print(f"splitter: {len(full)} 字符 → {len(batches)} 批，拼接逐字节还原 ✓")

    # 2. 系统提示词提取
    system = load_system_prompt()
    assert system.startswith("你是一名资深影视分镜师"), "系统提示词提取起点错误"
    assert "输出要求" in system, "系统提示词提取不完整"
    print(f"prompt: 系统提示词提取 {len(system)} 字符 ✓")

    # 3. 全流程回放（按人肉实测的两批切法）
    b1 = extract_passage((YAO / "input_batch1.txt").read_text(encoding="utf-8"))
    b2 = extract_passage((YAO / "input_batch2.txt").read_text(encoding="utf-8"))
    mock = MockLLM([
        (YAO / "output_batch1.json").read_text(encoding="utf-8"),
        (YAO / "output_batch2.json").read_text(encoding="utf-8"),
    ])
    logs = []
    doc = convert_text(full,
                       params=ConvertParams(work_title="药", chapter="全文"),
                       settings=Settings(max_retries=0),
                       llm=mock, batches=[b1, b2],
                       log=logs.append)
    archived = json.loads((YAO / "output_merged.json").read_text(encoding="utf-8"))
    assert doc == archived, "流水线合并结果与归档 output_merged.json 不一致"
    assert len(doc["source"]["units"]) == 132
    print("回放: 2 批 → 逐批校验 → 合并 → 整章 lint+保真终检全通过，结果与归档逐字一致 ✓")

    # 4. 续批参数拼装（对照人肉实测 input_batch2.txt 的取值）
    msg2 = mock.calls[1][0]["content"]
    for expected in ("起始句子编号：u0068", "起始段落编号：29", "起始分集编号：E03",
                     '"C01"', "首批 meta（逐字沿用）"):
        assert expected in msg2, f"续批参数缺失: {expected}"
    assert "【已有资产库】\n无" not in msg2
    print("续批参数: u0068 / 段落 29 / E03 / 资产库注入，与人肉实测一致 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
