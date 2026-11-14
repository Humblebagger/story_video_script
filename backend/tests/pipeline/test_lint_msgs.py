#!/usr/bin/env python3
"""分镜检查（lint）逐条（spec 子计划 5b B、C、E）：verify.lint.* 的代码与中文兜底、源码与登记一一对应、
认不出时退回原文、先脱敏再截断、与保真输出的组合、流水线接入。回喂模型的原文见 test_lint_feed_snapshot.py。
不调模型、不联网。用法: python3 tests/pipeline/test_lint_msgs.py"""
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

import lint_snapshot as SNAP  # noqa: E402
from fakes import FakeChat  # noqa: E402
from pipeline import graph, validate, verification as V  # noqa: E402
from pipeline.chat import ChatInvoker  # noqa: E402
from pipeline.config import Settings  # noqa: E402
from pipeline.errors import ConversionError  # noqa: E402
from server import messages as M  # noqa: E402
from test_lint_json import EXPECT_PARAMS, lint_json, source_rules  # noqa: E402
from test_lint_feed_snapshot import PARAMS as CONVERT_PARAMS  # noqa: E402

ZH_P01 = "charred、fresh_bleeding、lotus_wrapped、paper_wrapped、split_open"
# 每条规则逐条消息（verify.report.tool_error 套 verify.lint.<rule>）的中文兜底
EXPECT_ZH = {
    "schema": "  不符合分镜结构定义（/episodes/0/shots/0/shot_size）：'huge' is not one of ['extreme_wide', 'wide', 'full', 'medium', 'medium_close', 'close_up', 'extreme_close_up', 'insert']",
    "ref_image_outfit": "  [C01] 参考图标注的 outfit「summer」不存在（可选：default）",
    "ref_image_state": f"  [P01] 参考图标注的 state「melted」不存在（可选：{ZH_P01}）",
    "asset_empty_constraint": "  [C01] constraints 里有空的约束项",
    "curve_shot": "  [E01] music.curve 引用了本集没有的镜头：E09-SH001",
    "curve_unit": "  [E01] music.curve.unit_refs 引用了不存在的句子：u9999",
    "curve_reversed": "  [E01] music.curve 区间倒序：E01-SH010 在 E01-SH001 之后",
    "shot_unit": "  [E01-SH001] source.unit_refs 引用了不存在的句子：u9999",
    "inferred_no_note": "  [E01-SH001] derivation=inferred 但缺少 inference_note",
    "beats_duration": "  [E01-SH001] beats 各拍时长之和 4.5s 与镜头 duration_sec 5s 不符",
    "beat_no_action": "  [E01-SH001] beats 第 2 拍缺少 action",
    "shot_empty_constraint": "  [E01-SH001] constraints 里有空的约束项",
    "location_ref": "  [E01-SH001] location_ref 引用了不存在的场景：S99",
    "prop_ref": "  [E01-SH001] prop_refs 引用了不存在的道具：P99",
    "prop_state_required": f"  [E01-SH001] 道具 P01 有状态集，引用时必须填 state（可选：{ZH_P01}）",
    "prop_state_unknown": f"  [E01-SH001] 道具 P01 没有 state「melted」（可选：{ZH_P01}）",
    "prop_state_unexpected": "  [E01-SH001] 道具 P02 没有状态集，引用时不应填 state",
    "creature_outfit": "  [E01-SH001] 生物 A01 的引用不应填 outfit",
    "character_ref": "  [E01-SH001] characters.ref 引用了不存在的角色或生物：C99",
    "outfit_unknown": "  [E01-SH001] 角色 C01 没有 outfit「summer」（可选：default）",
    "dialogue_character": "  [E01-SH004] dialogue.character_ref 引用了不存在的角色：C99",
    "narration_unit": "  [E01-SH001] narration.unit_refs 引用了不存在的句子：u9999",
    "coverage_unmapped": "  [coverage] 有 1 句原文没有被任何镜头的旁白覆盖，也没有标 skipped：u0068",
}
FAKE = "ark-" + "Q7v2" * 6                     # 假密钥（不是任何真实密钥）
ERRS = [{"rule": "location_ref", "params": {"shot": "E01-SH001", "location": "S99"}, "text": "t"}]


def zh(line: dict) -> str:
    return M.render_zh(line["code"], line["params"])


def main() -> int:
    # 1. 23 条规则各一条触发用例：逐条消息的代码与中文兜底；jsonschema 原文作厂商原文
    assert list(EXPECT_ZH) == list(EXPECT_PARAMS)
    for rule, mutate in SNAP.CASES:
        d = SNAP.base()
        mutate(d)
        _, data, _ = lint_json(d)
        lines = V.lint_lines(data["errors"])
        assert lines[0] == {"code": "verify.report.lint", "params": {}}
        assert lines[1]["code"] == "verify.report.tool_error" and lines[1]["params"]["text"]["code"] == f"verify.lint.{rule}"
        assert zh(lines[1]) == EXPECT_ZH[rule], (rule, zh(lines[1]))
    sch = V.lint_lines([{"rule": "schema", "params": EXPECT_PARAMS["schema"], "text": "x"}])[1]["params"]["text"]["params"]
    assert sch["detail"] == {"t": "vendor", "text": EXPECT_PARAMS["schema"]["detail"]}, "jsonschema 原文作厂商原文"
    print("1. 23 条规则的逐条消息与中文兜底 ✓")

    # 2. 源码里的错误规则名 ↔ 登记的 verify.lint.* 一一对应；WARN 不登记
    rules = source_rules()
    registered = sorted(c[len("verify.lint."):] for c in M._REG if c.startswith("verify.lint."))
    assert sorted(rules["errors"]) == registered and len(registered) == 23, (rules["errors"], registered)
    assert not set(rules["warnings"]) & set(registered)
    print("2. 源码规则名 ↔ 登记一一对应 ✓")

    # 3. WARN 不进给用户的逐条：lint 通过、保真通过时没有逐条
    d = SNAP.base()
    SNAP.warn_case(d)
    _, data, _ = lint_json(d)
    assert data["warnings"] and V.checker_lines(True, data["text"], data["errors"], True, "PASS") == []
    print("3. WARN 不进逐条 ✓")

    # 4. 认不出的一条：没登记的规则、参数对不上、形状不对，都退回该条原文（厂商原文）
    for item in ({"rule": "future_rule", "params": {}, "text": "[E01] 新规则"},
                 {"rule": "location_ref", "params": {"shot": "E01-SH001"}, "text": "[E01] 少参数"},
                 {"rule": "location_ref", "params": "坏", "text": "[E01] 坏参数"},
                 "裸字符串"):
        got = V.lint_lines([item])[1]["params"]["text"]
        want = item["text"] if isinstance(item, dict) else item
        assert got == {"t": "vendor", "text": want}, (item, got)
    got = V.lint_lines([{"rule": "future_rule", "params": {}}])[1]["params"]["text"]
    assert got == {"t": "vendor", "text": "future_rule"}, "缺原文时退回规则名，不显示空行"
    print("4. 认不出的一条退回原文；缺原文时退回规则名 ✓")

    # 5. 脱敏：参数与退回的原文都先脱敏再截断，结果一律过 clean()。每类注明它挡住的回退写法（设计审查 I4）
    leaks = ["Bearer abc.def-123", "x-api-key: sk-zzz999"]

    def clean(x, label):
        t = json.dumps(x, ensure_ascii=False)
        assert FAKE[:8] not in t and FAKE[-8:] not in t and "abc.def-123" not in t and "sk-zzz999" not in t, (label, t)

    def one(rule, params, text="x"):
        return V.lint_lines([{"rule": rule, "params": params, "text": text}])[1]

    os.environ["ARK_API_KEY"] = FAKE
    try:
        # 5a 字符串参数，密钥横跨 300 字的截断位置：挡住「先截断再脱敏」（scrub_secrets(v[:300])）
        line = one("location_ref", {"shot": "E01-SH001", "location": "S" * 290 + FAKE})
        clean(line, "5a")
        assert line["params"]["text"]["params"]["location"] == ("S" * 290 + "***")[:300]
        # 5b 列表项，密钥横跨截断位置：挡住列表分支不递归脱敏（v[:20]）或逐项先截再抹
        line = one("outfit_unknown", {"shot": "E01-SH001", "character": "C01", "outfit": "x",
                                      "options": ["a", "S" * 290 + FAKE]})
        clean(line, "5b")
        # 5c 字典（模型把编号写成了对象），值与键都带密钥：挡住「其它类型」分支漏掉 scrub_secrets（只 json.dumps 再截断）
        line = one("location_ref", {"shot": "E01-SH001", "location": {"k": FAKE, FAKE: 1}})
        clean(line, "5c")
        # 5d 退回原文，密钥横跨截断位置：挡住退回分支写成 vendor(text)（不脱敏）或 vendor(scrub_secrets(text[:300]))（先截再抹）
        line = one("future_rule", {}, text="x" * 290 + FAKE)
        clean(line, "5d")
        assert line["params"]["text"] == {"t": "vendor", "text": ("x" * 290 + "***")[:300]}
        # 5e Bearer 与 x-api-key: 两种形态（参数与退回原文各一）：挡住把 scrub_secrets 换成只抹环境密钥的替换
        clean(one("location_ref", {"shot": "E01-SH001", "location": leaks[0]}), "5e 参数")
        clean(one("future_rule", {}, text="坏 " + leaks[1]), "5e 原文")
        # 回喂模型的原文不脱敏（与 render() 相同，spec 子计划 5 F）；给界面的逐条脱敏
        d = SNAP.base()
        d["episodes"][0]["shots"][0]["location_ref"] = "S9" + FAKE
        _, data, _ = lint_json(d)
        assert FAKE in data["text"]
        clean(V.lint_lines(data["errors"]), "5f 真实 lint")
    finally:
        del os.environ["ARK_API_KEY"]
    print("5. 先脱敏再截断：字符串、列表、字典、退回原文、Bearer 与 x-api-key ✓")

    # 6. 列表上限与省略提示；可选项为空写成「无」；单条 1000 字上限；值的写法
    d = SNAP.base()
    d["source"]["units"].extend({"id": f"u{i:04d}", "text": "多。", "para": 29, "kind": "action"} for i in range(68, 93))
    _, data, _ = lint_json(d)
    line = V.lint_lines(data["errors"])[1]
    p = line["params"]["text"]["params"]
    assert p["n"] == 25 and p["units"] == [f"u{i:04d}" for i in range(68, 88)] + ["…"], p
    assert zh(line).endswith("u0086、u0087、…"), zh(line)
    d = SNAP.base()
    next(c for c in d["assets"]["characters"] if c["id"] == "C06")["reference_images"] = [
        {"view": "front", "uri": "c.png", "outfit": "summer"}]
    next(c for c in d["assets"]["props"] if c["id"] == "P02")["reference_images"] = [
        {"view": "close_up", "uri": "p.png", "state": "melted"}]
    _, data, _ = lint_json(d)
    got = [zh(x) for x in V.lint_lines(data["errors"])[1:]]
    assert got == ["  [C06] 参考图标注的 outfit「summer」不存在（可选：无）",
                   "  [P02] 参考图标注的 state「melted」不存在（可选：无）"], got
    for x in V.lint_lines(data["errors"])[1:]:
        assert x["params"]["text"]["params"]["options"] == {"t": "ref", "code": "verify.report.lint_none"}
    big = one("outfit_unknown", {"shot": "E01-SH001", "character": "C01", "outfit": "x",
                                 "options": [f"o{i}" + "z" * 290 for i in range(20)]})
    m = big["params"]["text"]
    assert len(M.render_zh(m["code"], m["params"])) <= 1000, "单条超 1000 字时按紧的口径重来"
    assert len(m["params"]["options"]) == 11 and m["params"]["options"][-1] == "…"
    assert all(len(o) <= 40 for o in m["params"]["options"])
    small = one("location_ref", {"shot": "E01-SH001", "location": "S" * 300})["params"]["text"]["params"]
    assert small["location"] == "S" * 300, "不超 1000 字时照常 300 字"
    assert V._lint_value(True) == "True" and V._lint_value(1.0) == "1.0" and V._lint_value(None) == "None"
    assert V._lint_value(3) == 3 and V._lint_value({"a": 1}) == '{"a": 1}'
    print("6. 列表上限与省略、可选项为空（outfit 与 state）、单条上限、值的写法 ✓")

    # 7. checker_lines：lint 有结构化错误就翻译；没有（None 或空列表）就退回按行拆分原文；lint 与保真各自拆分、依次追加（R8）
    fid_fail = "FAIL 原文保真：unit 拼接与原文不一致\n  首个差异位置 3"
    assert V.checker_lines(False, "ERROR t", ERRS, True, "PASS") == V.lint_lines(ERRS)
    assert V.checker_lines(False, "ERROR t", ERRS, False, fid_fail) == V.lint_lines(ERRS) + V.tool_lines(fid_fail)
    assert V.checker_lines(False, "ERROR 原文一条\n", None, True, "PASS") == V.tool_lines("ERROR 原文一条")
    assert V.checker_lines(False, "ERROR 原文一条\n", [], True, "PASS") == V.tool_lines("ERROR 原文一条")
    assert V.checker_lines(True, "PASS", None, False, fid_fail) == V.tool_lines(fid_fail)
    for errs in (None, []):                        # 非结构化 lint 与保真同时失败：两段都列，保真的 FAIL 与差异行不被 ERROR 行挤掉（R8）
        both = V.checker_lines(False, "ERROR 原文一条\n", errs, False, fid_fail)
        assert both == V.tool_lines("ERROR 原文一条") + V.tool_lines(fid_fail), both
        flat = json.dumps(both, ensure_ascii=False)
        assert "原文一条" in flat and "FAIL 原文保真" in flat and "首个差异位置 3" in flat, flat
    print("7. checker_lines 的七种组合 ✓")

    # 8. 流水线：_check_batch 的逐条按规则翻译、报告仍是原文；重试耗尽时 ConversionError.lines 同样
    shown = []
    with tempfile.TemporaryDirectory() as w:
        ok, hard, report, _, _ = graph._check_batch(SNAP.feed_doc(), SNAP.batch_text(), Settings(), Path(w), 1, 1,
                                                    None, lambda _: None, lines_out=shown)
    assert (ok, hard, report) == (False, True, SNAP.FEED_REPORT)
    codes = [x["params"]["text"]["code"] for x in shown[1:]]
    assert shown[0]["code"] == "verify.report.lint" and codes == [
        "verify.lint.location_ref", "verify.lint.character_ref", "verify.lint.outfit_unknown",
        "verify.lint.dialogue_character", "verify.lint.prop_ref"], codes
    settings = Settings(api_key="k", max_retries=0, normalize_input=False, freeze_source_units=False)
    with tempfile.TemporaryDirectory() as w:
        chat = ChatInvoker(settings, chat=FakeChat(responses=[json.dumps(SNAP.feed_doc(), ensure_ascii=False)]),
                           log=lambda _: None)
        g = graph.build_batch_graph(chat=chat, review_chat=None, settings=settings, params=CONVERT_PARAMS,
                                    workdir=Path(w), attempt_records=[], log=lambda _: None)
        try:
            graph.run_batch(g, user="原文", batch_text=SNAP.batch_text(), idx=1, frozen_units=None)
            raise AssertionError("应抛 ConversionError")
        except ConversionError as e:
            assert e.code == "job.batch_failed" and e.report == SNAP.FEED_REPORT
            assert e.lines == shown, e.lines
            text = M.render_zh("job.failed_report", {"reason": {"code": e.code, "params": e.params},
                                                      "report": M.lines_of(e.lines)})
            assert "ERROR" not in text and "location_ref 引用了不存在的场景：S99" in text, text
    print("8. 流水线：逐条按规则、报告与回喂仍是原文 ✓")

    # 9. 整章终检：lint 未过时用同一套逐条（批内那次用真的 lint，只让终检那次失败）
    import pipeline.convert as convert_mod
    real_lint = validate.run_lint_report
    calls = []

    def final_fails(path):
        calls.append(path)
        return real_lint(path) if len(calls) == 1 else validate.LintReport(False, "ERROR 原文\n", ERRS)
    validate.run_lint_report = final_fails
    try:
        archived = json.dumps(SNAP.base(), ensure_ascii=False)
        with tempfile.TemporaryDirectory() as w:
            try:
                convert_mod.convert_text(SNAP.batch_text(), CONVERT_PARAMS, settings=settings,
                                         llm=FakeChat(responses=[archived]), batches=[SNAP.batch_text()],
                                         workdir=Path(w), log=lambda _: None)
                raise AssertionError("终检 lint 未过应抛 ConversionError")
            except ConversionError as e:
                assert e.code == "job.final_check_failed" and e.report.startswith("ERROR 原文\n\n"), e.report
                assert e.lines == V.lint_lines(ERRS), e.lines
    finally:
        validate.run_lint_report = real_lint
    print("9. 整章终检的逐条 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
