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
from pipeline.quality import apply_meta_overrides, narration_density_gate
from pipeline.splitter import split_batches

YAO = ROOT / "tests" / "real_text_yao"

# 与《药》归档 meta 逐字一致的制作参数（meta 覆写后合并结果才能与归档比对）
YAO_PARAMS = ConvertParams(
    work_title="药", chapter="全文（1919）",
    style_prefix="民国江南小镇写实风格，电影感光影，青灰冷色调",
    art_style="realistic", color_tone="青灰冷色调，晨昏低饱和",
    aspect_ratio="9:16", target_platform="抖音",
    narration_mode="selective", tts_voice="male_mature")


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
    # 归档由未清洗原文转换（units 保留 U+200B），关闭入口归一化以逐字回放
    doc = convert_text(full,
                       params=YAO_PARAMS,
                       settings=Settings(max_retries=0, normalize_input=False),
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

    # 5. meta 确定性覆写：模型缩写/漂移的字段被参数值纠正
    drifted = {"meta": {"style": {"style_prefix": "民国风"},
                        "narration": {"mode": "original_text"}}}
    apply_meta_overrides(drifted, YAO_PARAMS)
    assert drifted["meta"]["style"]["style_prefix"] == YAO_PARAMS.style_prefix
    assert drifted["meta"]["narration"]["mode"] == "selective"
    assert drifted["meta"]["title"] == "药"
    print("meta 覆写: 缩写的 style_prefix / 漂移的 mode 被纠正 ✓")

    # 6. 旁白密度质量门：《药》人工基准通过；逐句朗读式退化被拦截
    ok, _, ratio = narration_density_gate(doc, 0.6)
    assert ok, "《药》归档（旁白占比 0.18）不应触发质量门"
    assert 0.15 < ratio < 0.25, f"《药》归档旁白占比应约 0.18，实际 {ratio}"
    degraded = {
        "meta": {"narration": {"mode": "selective"}},
        "source": {"units": [{"id": f"u{i:04d}", "text": "他推门。", "kind": "action"}
                             for i in range(1, 11)]},
        "episodes": [{"shots": [{"narration": {"unit_refs": [f"u{i:04d}"]}}
                                for i in range(1, 11)]}]}
    ok, report, ratio = narration_density_gate(degraded, 0.6)
    assert not ok and "100%" in report and "u0001" in report and ratio == 1.0
    ok, _, _ = narration_density_gate(degraded, 1.0)   # >=1 关闭
    assert ok
    degraded["meta"]["narration"]["mode"] = "original_text"
    ok, _, _ = narration_density_gate(degraded, 0.6)   # 非 selective 不适用
    assert ok
    degraded["meta"]["narration"]["mode"] = "selective"
    print("旁白密度门: 归档通过 / 100% 旁白拦截 / 关闭与模式豁免生效 ✓")

    # 7. 评审阶段流程（mock：生成 1 次 + 评审 1 次通过）
    romance_text = extract_passage(
        (ROOT / "tests" / "genre_stability" / "input_romance.txt")
        .read_text(encoding="utf-8"))
    romance_json = (ROOT / "tests" / "genre_stability" / "output_romance.json"
                    ).read_text(encoding="utf-8")
    verdict = ('{"scores": {"narration_selection": 4, "shot_language": 4, '
               '"asset_quality": 4, "semantic_fidelity": 5}, '
               '"overall": 4.3, "issues": []}')
    mock2 = MockLLM([romance_json, verdict])
    doc2 = convert_text(
        romance_text,
        params=ConvertParams(work_title="橘子汽水", chapter="第七章 天台",
                             narration_mode="original_text"),
        settings=Settings(max_retries=0, review_enabled=True),
        llm=mock2, log=lambda m: None)
    assert len(mock2.calls) == 2, "应有 1 次生成 + 1 次评审调用"
    assert "评审总分" not in json.dumps(doc2), "评审结果不应混入产物"
    print("评审阶段: 生成 → 评审通过 → 产物返回，调用序列正确 ✓")

    # 8. 软质量门重试耗尽：择优降级交付（strict 时改为直接失败）
    #    硬校验打桩为通过，只让密度门失败——两次尝试 100% → 80%，应交付 80% 那版
    from pipeline import convert as convert_mod
    from pipeline.convert import ConversionError

    def deg_doc(n_narrated):
        return {"meta": {"narration": {"mode": "selective"}},
                "source": {"units": [{"id": f"u{i:04d}", "text": "他推门。",
                                      "kind": "action"} for i in range(1, 11)]},
                "episodes": [{"shots": [{"narration": {"unit_refs": [f"u{i:04d}"]}}
                                        for i in range(1, n_narrated + 1)]}]}

    orig_lint = convert_mod.validate.run_lint
    orig_fid = convert_mod.validate.run_fidelity
    convert_mod.validate.run_lint = lambda p: (True, "PASS（打桩）")
    convert_mod.validate.run_fidelity = lambda p, t, w: (True, "PASS（打桩）")
    try:
        warnings = []
        mock3 = MockLLM([json.dumps(deg_doc(10)), json.dumps(deg_doc(8))])
        doc3 = convert_text("他推门。", settings=Settings(max_retries=1),
                            llm=mock3, batches=["他推门。"],
                            log=lambda m: None, warnings_out=warnings)
        narrated = sum(len(s["narration"]["unit_refs"])
                       for s in doc3["episodes"][0]["shots"])
        assert narrated == 8, f"应择优交付 80% 那版，实际旁白句数 {narrated}"
        assert len(warnings) == 1 and "择优交付第 2 次生成" in warnings[0]
        assert "旁白占比 80%" in warnings[0]

        mock4 = MockLLM([json.dumps(deg_doc(10)), json.dumps(deg_doc(8))])
        try:
            convert_text("他推门。", settings=Settings(max_retries=1, strict=True),
                         llm=mock4, batches=["他推门。"], log=lambda m: None)
            raise AssertionError("strict 模式下软门重试耗尽应抛 ConversionError")
        except ConversionError:
            pass
    finally:
        convert_mod.validate.run_lint = orig_lint
        convert_mod.validate.run_fidelity = orig_fid
    print("降级交付: 软门耗尽择优交付+警告 / strict 直接失败 ✓")

    # 9. 入口归一化：零宽噪声在进 LLM 前被剔除（默认开启）
    from pipeline.splitter import normalize_source_text
    cleaned, n = normalize_source_text("徘徊；\u200b定睛\ufeff再看\u2060。")
    assert (cleaned, n) == ("徘徊；定睛再看。", 3)
    assert Settings().normalize_input, "归一化应默认开启"
    convert_mod.validate.run_lint = lambda p: (True, "PASS（打桩）")
    convert_mod.validate.run_fidelity = lambda p, t, w: (True, "PASS（打桩）")
    try:
        mock5 = MockLLM([json.dumps(deg_doc(1))])
        convert_text("他\u200b推门。", settings=Settings(max_retries=0),
                     llm=mock5, log=lambda m: None)
        assert "\u200b" not in mock5.calls[0][0]["content"], \
            "零宽字符不应出现在发给 LLM 的原文里"
    finally:
        convert_mod.validate.run_lint = orig_lint
        convert_mod.validate.run_fidelity = orig_fid
    print("入口归一化: U+200B/BOM/U+2060 剔除，LLM 输入已清洗 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
