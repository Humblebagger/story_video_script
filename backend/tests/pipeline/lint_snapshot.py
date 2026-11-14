"""子计划 5b 改动前的快照：lint 的文本输出与它回喂模型的文字（在未改动的代码上跑出来的，不是手写）。
只放数据与造数据的函数，不导入 pipeline；test_lint_feed_snapshot.py 用旧接口核对，test_lint_msgs.py 复用。"""
import copy
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
YAO = ROOT / "tests" / "real_text_yao"
_BASE = json.loads((YAO / "output_batch1.json").read_text(encoding="utf-8"))


def base() -> dict:
    """《药》批 1 归档：lint、结构校验、保真全过。"""
    return copy.deepcopy(_BASE)


def batch_text() -> str:
    text = (YAO / "input_batch1.txt").read_text(encoding="utf-8")
    m = re.search(r"^章节：.*$", text, flags=re.M)
    return text[m.end():] if m else text


def shot(d, i=0, ep=0):
    return d["episodes"][ep]["shots"][i]


def card(d, kind, cid):
    return next(x for x in d["assets"][kind] if x["id"] == cid)


def curve(d):
    return d["episodes"][0]["music"]["curve"]


# (规则, 改坏文档)：每条只触发它自己这一种 ERROR（WARN 可能顺带出现）
CASES = [
    ("schema", lambda d: shot(d).update(shot_size="huge")),
    ("ref_image_outfit", lambda d: card(d, "characters", "C01").update(
        reference_images=[{"view": "front", "uri": "c.png", "outfit": "summer"}])),
    ("ref_image_state", lambda d: card(d, "props", "P01").update(
        reference_images=[{"view": "close_up", "uri": "p.png", "state": "melted"}])),
    ("asset_empty_constraint", lambda d: card(d, "characters", "C01").update(constraints=["  "])),
    ("curve_shot", lambda d: curve(d)[0].update(from_shot="E09-SH001")),
    ("curve_unit", lambda d: curve(d)[0].update(unit_refs=["u9999"])),
    ("curve_reversed", lambda d: curve(d)[0].update(from_shot="E01-SH010", to_shot="E01-SH001")),
    ("shot_unit", lambda d: shot(d)["source"]["unit_refs"].append("u9999")),
    ("inferred_no_note", lambda d: shot(d)["source"].update(derivation="inferred")),
    ("beats_duration", lambda d: shot(d).update(
        beats=[{"duration_sec": 2, "action": "推门"}, {"duration_sec": 2.5, "action": "抬头"}])),
    ("beat_no_action", lambda d: shot(d).update(
        beats=[{"duration_sec": 2.5, "action": "推门"}, {"duration_sec": 2.5, "action": " "}])),
    ("shot_empty_constraint", lambda d: shot(d).update(constraints=[""])),
    ("location_ref", lambda d: shot(d).update(location_ref="S99")),
    ("prop_ref", lambda d: shot(d).update(prop_refs=[{"ref": "P99"}])),
    ("prop_state_required", lambda d: shot(d).update(prop_refs=[{"ref": "P01"}])),
    ("prop_state_unknown", lambda d: shot(d).update(prop_refs=[{"ref": "P01", "state": "melted"}])),
    ("prop_state_unexpected", lambda d: shot(d).update(prop_refs=[{"ref": "P02", "state": "melted"}])),
    ("creature_outfit", lambda d: (
        d["assets"].setdefault("creatures", []).append({"id": "A01", "name": "乌鸦", "visual_prompt": "黑羽乌鸦"}),
        shot(d).update(characters=[{"ref": "A01", "outfit": "default"}]))),
    ("character_ref", lambda d: shot(d).update(characters=[{"ref": "C99"}])),
    ("outfit_unknown", lambda d: shot(d).update(characters=[{"ref": "C01", "outfit": "summer"}])),
    ("dialogue_character", lambda d: shot(d, 3)["dialogue"][0].update(character_ref="C99")),
    ("narration_unit", lambda d: shot(d)["narration"]["unit_refs"].append("u9999")),
    ("coverage_unmapped", lambda d: d["source"]["units"].append(
        {"id": "u0068", "text": "多出一句。", "para": 29, "kind": "action"})),
]


def warn_case(d):
    """只有 WARN、没有 ERROR：曲线缝隙、曲线没到最后一镜、镜头 ID 前缀、两项覆盖声明。"""
    curve(d)[1].update(from_shot="E01-SH012")
    curve(d).pop()
    d["episodes"][1]["shots"][1]["id"] = "E01-SH099"
    d["coverage"].update(unmapped_units=["u0001"], inferred_shot_ratio=0.5)


def feed_doc() -> dict:
    """结构校验与保真全过、只有 lint 报错（资产引用五条）：_check_batch 走到 lint 那一支。"""
    d = base()
    shot(d, 0).update(location_ref="S99")
    shot(d, 6).update(prop_refs=[{"ref": "P99"}])
    shot(d, 1).update(characters=[{"ref": "C99"}])
    shot(d, 2).update(characters=[{"ref": "C01", "outfit": "summer"}])
    shot(d, 3)["dialogue"][0].update(character_ref="C99")
    return d


SUMMARY = "旁白模式 selective；镜头 61 个（inferred 2 个，占比 0.03）；句子 67 个，已覆盖 67 个（旁白 9，台词承载 17，纯画面承载 43）。"

# 每种情形：(退出码, 文本输出的 sha256, 其中的 ERROR/WARN 行)
LINT = {
    "schema": (1, "908556b8bc6c845645f155cf3c43275c33abfa5144a77f9e5a57bda86914436b", ["ERROR [schema] episodes/0/shots/0/shot_size: 'huge' is not one of ['extreme_wide', 'wide', 'full', 'medium', 'medium_close', 'close_up', 'extreme_close_up', 'insert']"]),
    "ref_image_outfit": (1, "190301140218c6a975c742e1d9b21588d85f87ea6ea0991b4b4666530a68f6a6", ["ERROR [C01] 参考图标注的 outfit 'summer' 不存在（可选: ['default']）"]),
    "ref_image_state": (1, "b6eed9d380d8a28575ef81a01656c6e890b2faf9eb06bd09a7818e1f0aa0fc23", ["ERROR [P01] 参考图标注的 state 'melted' 不存在（可选: ['charred', 'fresh_bleeding', 'lotus_wrapped', 'paper_wrapped', 'split_open']）"]),
    "asset_empty_constraint": (1, "39dc9589257dc7d3e9950d2349adc6f8032cc6c309414733e4d49f8bb04d7d89", ["ERROR [C01] constraints 里有空约束项"]),
    "curve_shot": (1, "f9582cf6404dc5cf05e265e55683b1ea342cd6ab51dbd9e8122fbdd924420a17", ["WARN  [E01] music.curve 段落不连续（E01-SH011 之前有缝隙或重叠）", "ERROR [E01] music.curve 引用不存在于本集的镜头: E09-SH001"]),
    "curve_unit": (1, "be51e313d61ddef12494c243a74591609560e5c56108612f4638dd38fda8a3f6", ["ERROR [E01] music.curve.unit_refs 引用不存在的句子: u9999"]),
    "curve_reversed": (1, "20d944df03c1ea3cf32f6cdf68ce56f85f95dbd22c9e91a60fac5c2f4026bb4f", ["WARN  [E01] music.curve 段落不连续（E01-SH010 之前有缝隙或重叠）", "WARN  [E01] music.curve 段落不连续（E01-SH011 之前有缝隙或重叠）", "ERROR [E01] music.curve 区间倒序: E01-SH010 > E01-SH001"]),
    "shot_unit": (1, "79db6b47967928f07e4ecc9991eafe191bb63905b03c86aa5ae903a27b8a8338", ["ERROR [E01-SH001] source.unit_refs 引用不存在的句子: u9999"]),
    "inferred_no_note": (1, "e77eb4a8c52aec1130ab767980de7970c21f61614bdfb2c3329f36ccf86fea91", ["WARN  [coverage] inferred_shot_ratio 声明 0.03，实际 0.05", "ERROR [E01-SH001] derivation=inferred 但缺少 inference_note"]),
    "beats_duration": (1, "f2735227f9ae180ef2c35f04e2f064200e9a3fa7b366c30a6021f4b75967905d", ["ERROR [E01-SH001] beats 各拍时长之和 4.5s 与镜头 duration_sec 5s 不符"]),
    "beat_no_action": (1, "2fcbf60ea860daf385bdd71aa7e9d22528aa59ace24b6a5d379e0acbdc4f37a6", ["ERROR [E01-SH001] beats 第 2 拍缺少 action"]),
    "shot_empty_constraint": (1, "9908bda092549650785072c696be442082901b521d541228697e12699bbfb764", ["ERROR [E01-SH001] constraints 里有空约束项"]),
    "location_ref": (1, "e7d12f8a4724cdaad5e211521c1e9fd07237779b01b7f7a8de77fa67479e4a2f", ["ERROR [E01-SH001] location_ref 引用不存在的场景: S99"]),
    "prop_ref": (1, "8e0b7915e670f751681d81cbbbd99d8ec5be8a1cc829524dc4b66ea14919e2a0", ["ERROR [E01-SH001] prop_refs 引用不存在的道具: P99"]),
    "prop_state_required": (1, "dd5a99981febac48c266e445188567a3c07cb34342295820f69319a084c6cab2", ["ERROR [E01-SH001] 道具 P01 有状态集，引用必须填 state（可选: ['charred', 'fresh_bleeding', 'lotus_wrapped', 'paper_wrapped', 'split_open']）"]),
    "prop_state_unknown": (1, "e6f7d866c0b1a6372161d2a8637d00a453584838e1664be0a34fc41a38687823", ["ERROR [E01-SH001] 道具 P01 不存在 state 'melted'（可选: ['charred', 'fresh_bleeding', 'lotus_wrapped', 'paper_wrapped', 'split_open']）"]),
    "prop_state_unexpected": (1, "f2dc1a1fd73452f31dfe7e715e398674ea87ae41330df9aa6edff415ac1be72b", ["ERROR [E01-SH001] 道具 P02 无 states，引用不应填 state"]),
    "creature_outfit": (1, "0a4af08bf35c73d6f0711e4d987526121bdf485e2282904a529c24f2853c34e5", ["ERROR [E01-SH001] 生物 A01 引用不应填 outfit"]),
    "character_ref": (1, "0228e9ad74f8dcc96203b9d08a8791dff1a2bd57e05903b4fd35e2adc1d25a06", ["ERROR [E01-SH001] characters.ref 引用不存在的角色/生物: C99"]),
    "outfit_unknown": (1, "5ef650854cac3007f76af51a82bfc442f2d28054e22bad369d6d646ce841aeaf", ["ERROR [E01-SH001] 角色 C01 不存在 outfit 'summer'（可选: ['default']）"]),
    "dialogue_character": (1, "d92abf510e67c6a7288791ac47437ca5607d978228d73179b888eebaa81a0939", ["ERROR [E01-SH004] dialogue.character_ref 引用不存在的角色: C99"]),
    "narration_unit": (1, "a6cc0bd9dc0f9fefa64e9315932aa3841e09fccfd785a24469b4125b4b66d12f", ["ERROR [E01-SH001] narration.unit_refs 引用不存在的句子: u9999"]),
    "coverage_unmapped": (1, "65b5faf124c0713738912feaa9072d38b94c48bb4856da49e896135f90da3786", ["WARN  [coverage] 声明的 unmapped_units 与实际不符，实际: ['u0068']", "ERROR [coverage] 以下句子未被任何镜头旁白覆盖且未标 skipped: ['u0068']"]),
    "_warnings": (0, "a7df3165bd5a8e9e2fc47d0cf84a4c05c947a01f834c9c18b016381f097957c7", ["WARN  [E01] music.curve 段落不连续（E01-SH012 之前有缝隙或重叠）", "WARN  [E01] music.curve 未覆盖到本集最后一镜", "WARN  [E01-SH099] 镜头 ID 前缀与所属集 E02 不一致", "WARN  [coverage] 声明的 unmapped_units 与实际不符，实际: []", "WARN  [coverage] inferred_shot_ratio 声明 0.5，实际 0.03"]),
}
PASS_TEXT = f"\n{SUMMARY}\nPASS\n"
NO_JSONSCHEMA_TEXT = f"WARN  jsonschema 未安装，跳过结构校验（pip install jsonschema）\n\n{SUMMARY}\nPASS\n"

# feed_doc() 走 _check_batch：lint 未过时的报告（回喂模型、失败报告、尝试记录都用它）
FEED_REPORT = ("ERROR [E01-SH001] location_ref 引用不存在的场景: S99\n"
               "ERROR [E01-SH002] characters.ref 引用不存在的角色/生物: C99\n"
               "ERROR [E01-SH003] 角色 C01 不存在 outfit 'summer'（可选: ['default']）\n"
               "ERROR [E01-SH004] dialogue.character_ref 引用不存在的角色: C99\n"
               "ERROR [E01-SH007] prop_refs 引用不存在的道具: P99\n"
               f"\n{SUMMARY}\nFAIL（5 个错误）\n"
               "PASS 原文保真：67 个 unit 拼接后与原文逐字一致（1958 字符）")
FEED_SHA = {
    "repair_request": "5c1f7b09b4fb3f96c4a59af9657fba131883f4b28f86dadb49d100f3b71382f5",   # 补丁修复的回喂（= repair_request(structured, FEED_REPORT)）
    "rewrite": "4016c8d6af01aaebcc27f5edc8a977b000f1d6fb5e0398c3566bd4b94697725c",          # 整份重写的回喂
    "batch_failed": "35ed3b4c5a73aded462018e75ab9fbe2fd8d98b716c568b20c68b8312ef4f0d0",     # 重写模式重试耗尽时 ConversionError.report
    "batch_failed_patch": "bfa800e0d656b9422b77e5fd3f2f94c33a6a53d6041a3f2dbba3cb3766d69024",  # 补丁模式重试耗尽时 ConversionError.report（最后一轮是「没有发起工具调用」）
    "final_report": "f0caab61b293e78fa97584ed60985aaa76af02f81defc01f6832aef7092faab3",     # 整章终检 lint 未过：ConversionError.report（lint 原文 + 换行 + 保真原文）
    "final_log": "615a06a13d83f6e864c447708f0ec28ec546cc858c86712bad2efc85a23d2a3c",        # 整章终检写进调试日志的 lint 原文（strip 后的一整段）
}
