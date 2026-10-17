#!/usr/bin/env python3
"""小说长期记忆进入转换的离线测试：注入块 / 负面提示词 / 软核查 / 章后整理核验。

用法: python3 tests/pipeline/test_novel_memory.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import FakeChat  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402
from pipeline import novel_memory as nm  # noqa: E402
from pipeline.chat import ChatInvoker  # noqa: E402
from pipeline.config import Settings  # noqa: E402
from pipeline.convert import ConvertParams, convert_text  # noqa: E402
from pipeline.prompt import build_user_message  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao"
YAO_PARAMS = ConvertParams(
    work_title="药", chapter="全文（1919）",
    style_prefix="民国江南小镇写实风格，电影感光影，青灰冷色调",
    art_style="realistic", color_tone="青灰冷色调，晨昏低饱和",
    aspect_ratio="9:16", target_platform="抖音",
    narration_mode="selective", tts_voice="male_mature")

DEAD_C03 = {"id": "l_1", "character_id": "C03", "type": "deceased", "detail": "病死",
            "since": {"chapter_id": "c_1", "unit_ref": "u0112", "chapter_title": "第一章"},
            "status": "confirmed", "origin": "user"}
NO_BLOOD = {"id": "k_1", "text": "不出现血腥画面，暴力用侧面、遮挡或旁白交代",
            "negative_prompt": "血迹, 伤口特写，血腥", "keywords": ["血"], "enabled": True}


def extract_passage(text: str) -> str:
    m = re.search(r"^章节：.*$", text, flags=re.M)
    return text[m.end():] if m else text


def first_human(chat, i):
    return [m for m in chat.requests[i]["messages"] if isinstance(m, HumanMessage)][0].content


def main() -> int:
    # 1. 没有长期记忆时用户消息与以前逐字一致
    assert nm.memory_blocks(None) == "" and nm.memory_blocks(nm.NovelContext()) == ""
    plain = build_user_message(YAO_PARAMS, "他推门。")
    assert build_user_message(YAO_PARAMS, "他推门。", memory="") == plain
    print("注入: 无记忆时消息逐字不变 ✓")

    # 2. 三个块：人物状态 / 主线剧情（只用于理解）/ 创作限制（原文溯源优先）
    ctx = nm.NovelContext(lifecycle=[DEAD_C03], names={"C03": "华小栓"},
                          outline="华老栓买人血馒头救子，小栓终究病死。",
                          synopses=[("第一章", "老栓天未亮出门买药。")],
                          constraints=[NO_BLOOD])
    blocks = nm.memory_blocks(ctx)
    assert "【人物状态】" in blocks and "C03 华小栓：自第一章（u0112）起已死亡（病死）" in blocks
    assert "回忆" in blocks, "已故角色要说明回忆/梦境可以出场"
    assert "只用于理解" in blocks and "不得把主线剧情里有、本章原文里没有的情节画进镜头" in blocks
    assert "全书梗概：华老栓" in blocks and "第一章：老栓天未亮" in blocks
    assert "原文溯源优先于限制" in blocks and "不得为守限制而跳过句子" in blocks
    msg = build_user_message(YAO_PARAMS, "他推门。", memory=blocks)
    assert msg.index("【已有资产库】") < msg.index("【人物状态】") < msg.index("【续批参数】")
    perm = nm.memory_blocks(nm.NovelContext(lifecycle=[{
        **DEAD_C03, "type": "permanent_condition", "detail": "左腿残疾，拄拐"}],
        names={"C03": "华小栓"}))
    assert "左腿残疾，拄拐" in perm and "外貌与动作须体现" in perm
    print("注入: 人物状态 / 主线剧情只用于理解 / 创作限制原文优先 / 块位置 ✓")

    # 3. 主线剧情超 2000 字：梗概完整，最近 3 章完整，更早的只留首句
    long = [(f"第{i}章", f"第{i}章首句。" + "后文" * 120) for i in range(1, 9)]
    text = nm.plot_text("梗概" * 50, long)
    assert ("梗概" * 50) in text
    assert "第1章：第1章首句。\n" in text and ("第8章首句。" + "后文" * 120) in text
    assert ("第5章首句。" + "后文") not in text and ("第6章首句。" + "后文") in text
    short = nm.plot_text("", [("第一章", "很短。后面。")])
    assert short == "第一章：很短。后面。", "不超长不截"
    print("主线剧情: 2000 字上限 / 梗概完整 / 最近 3 章完整 / 更早留首句 ✓")

    # 4. 负面提示词：确定性并入，去重，保留模型自己写的
    doc = {"meta": {"style": {"negative_prompt": "文字水印，血迹"}}}
    terms = nm.negative_terms(ctx)
    assert terms == ["血迹", "伤口特写", "血腥"]
    assert nm.merge_negative_prompt(doc, terms) == 2
    assert doc["meta"]["style"]["negative_prompt"] == "文字水印，血迹，伤口特写，血腥"
    assert nm.merge_negative_prompt(doc, terms) == 0, "重复并入不重复写"
    print("负面提示词: 并入 meta.style / 去重 / 幂等 ✓")

    # 5. 软核查：只扫呈现层；已故角色无回忆标记出场才报
    shot = {"id": "E01-SH001", "action": "地上一摊血", "atmosphere": "阴冷",
            "dialogue": [{"text": "血！"}], "narration": {"text": "人血馒头"},
            "characters": [{"ref": "C03", "action": "咳嗽"}],
            "source": {"unit_refs": ["u0001"]}}
    flash = {**shot, "id": "E01-SH002", "action": "回忆里小栓在灶下吃馒头"}
    found = nm.soft_findings({"episodes": [{"shots": [shot, flash]}]}, ctx)
    kinds = [(f.rule_id, f.object_path) for f in found]
    assert ("NOVEL-CONSTRAINT-001", "/episodes/0/shots/0/action") in kinds
    assert not any("dialogue" in p or "narration" in p for _, p in kinds), "台词旁白是原文，不扫"
    life = [f for f in found if f.rule_id == "NOVEL-LIFECYCLE-001"]
    assert len(life) == 1 and "E01-SH001" in life[0].message, "带回忆标记的镜头不报"
    assert all(f.severity == "medium" for f in found), "软核查只记 MEDIUM"
    print("软核查: 关键词只扫呈现层 / 已故角色出场（闪回除外）/ 只记 MEDIUM ✓")

    # 6. 整章回放：两批都带记忆块，产物负面提示词落地，软核查进终检报告但不打回
    b1 = extract_passage((YAO / "input_batch1.txt").read_text(encoding="utf-8"))
    b2 = extract_passage((YAO / "input_batch2.txt").read_text(encoding="utf-8"))
    full = (YAO / "input_full.txt").read_text(encoding="utf-8")
    mock = FakeChat(responses=[(YAO / "output_batch1.json").read_text(encoding="utf-8"),
                               (YAO / "output_batch2.json").read_text(encoding="utf-8")])
    manifest, logs = {}, []
    out = convert_text(full, params=YAO_PARAMS,
                       settings=Settings(max_retries=0, normalize_input=False,
                                         freeze_source_units=False),
                       llm=mock, batches=[b1, b2], log=logs.append,
                       manifest_out=manifest, novel_context=ctx)
    assert all("【创作限制】" in first_human(mock, i) for i in range(2)), "每批都要注入"
    neg = out["meta"]["style"]["negative_prompt"]
    assert "血腥" in neg and "伤口特写" in neg and "现代元素" in neg
    rules = {f["rule_id"] for f in manifest["verification"]["findings"]}
    assert "NOVEL-LIFECYCLE-001" in rules, "第一章里小栓还活着，标成已故时应提示"
    assert manifest["verification"]["status"] == "verified", "软核查不打回"
    assert any("长期记忆软核查" in line for line in logs)
    print("整章回放: 每批注入 / 负面提示词进产物 / 软核查进报告不打回 ✓")

    # 7. 章后整理：证据由程序核验，编造的、引错句的、名单外的全丢
    units = [{"id": "u0111", "text": "华大妈跟了他指头看去。"},
             {"id": "u0112", "text": "那坟与小栓的坟，一字儿排着，中间只隔一条小路。"}]
    chars = [{"id": "C03", "name": "华小栓"}, {"id": "C11", "name": "夏四奶奶"}]
    raw = {"lifecycle": [
        {"character_id": "C03", "type": "deceased", "detail": "病死", "unit_ref": "u0112",
         "evidence_quote": "小栓的坟"},
        {"character_id": "C03", "type": "deceased", "unit_ref": "u0111",
         "evidence_quote": "小栓的坟"},                     # 引错句
        {"character_id": "C11", "type": "deceased", "unit_ref": "u0112",
         "evidence_quote": "夏四奶奶死了"},                  # 编的
        {"character_id": "C99", "type": "deceased", "unit_ref": "u0112",
         "evidence_quote": "小栓的坟"},                     # 名单外
        {"character_id": "C03", "type": "injured", "unit_ref": "u0112",
         "evidence_quote": "小栓的坟"},                     # 类型不对
    ], "synopsis": "摘" * 300}
    kept, synopsis, dropped = nm.check_digest(raw, units, chars)
    assert [(k["character_id"], k["unit_ref"]) for k in kept] == [("C03", "u0112")]
    assert len(dropped) == 4 and len(synopsis) == nm.SYNOPSIS_MAX
    chat = FakeChat(responses=["```json\n" + json.dumps(
        {"lifecycle": raw["lifecycle"][:1], "synopsis": "清明上坟。"}, ensure_ascii=False)
        + "\n```"])
    kept, synopsis, _ = nm.run_digest(ChatInvoker(Settings(), chat=chat), units, chars)
    assert kept and synopsis == "清明上坟。"
    sent = first_human(chat, 0)
    assert "u0112 那坟与小栓的坟" in sent and "C03 华小栓" in sent
    print("章后整理: 证据逐字核验 / 名单与类型核验 / 摘要截 200 字 / 一次调用 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
