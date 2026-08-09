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
from pipeline.convert import _REPORT_LOG_LINES, ConvertParams, convert_text
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

    # 10. LLM 传输层重试：瞬时断连自动重试，确定性错误直接抛
    import httpx
    from pipeline import llm as llm_mod
    from pipeline.llm import LLMClient, LLMError
    client = LLMClient(Settings(api_key="offline-test"))
    calls = []

    def flaky(system, messages):
        calls.append(1)
        if len(calls) < 3:
            raise httpx.RemoteProtocolError("peer closed connection")
        return "ok"

    client._stream_once = flaky
    orig_sleep = llm_mod.time.sleep
    llm_mod.time.sleep = lambda s: None
    try:
        assert client.complete("sys", []) == "ok" and len(calls) == 3
        client._stream_once = lambda s, m: (_ for _ in ()).throw(
            LLMError("输出被 max_tokens 截断"))
        try:
            client.complete("sys", [])
            raise AssertionError("确定性错误不应被传输重试吞掉")
        except LLMError:
            pass
    finally:
        llm_mod.time.sleep = orig_sleep
    print("传输重试: 断连 2 次后第 3 次成功 / 确定性错误直抛 ✓")

    # 11. 跨转换沿用资产库：首批就带【已有资产库】，且编号不走续批逻辑
    seed = {"characters": [{"id": "C01", "name": "华老栓"}],
            "locations": [{"id": "S01", "name": "古□亭口"}]}
    convert_mod.validate.run_lint = lambda p: (True, "PASS（打桩）")
    convert_mod.validate.run_fidelity = lambda p, t, w: (True, "PASS（打桩）")
    try:
        mock6 = MockLLM([json.dumps(deg_doc(1))])
        convert_text("他推门。", settings=Settings(max_retries=0),
                     llm=mock6, log=lambda m: None, seed_assets=seed)
        sent = mock6.calls[0][0]["content"]
        assert "华老栓" in sent and '"C01"' in sent, "首批未注入历史资产库"
        assert "【续批参数】\n无" in sent, "沿用资产库不应触发续批编号（应从 u0001 起）"

        mock7 = MockLLM([json.dumps(deg_doc(1))])   # 不传则维持原样
        convert_text("他推门。", settings=Settings(max_retries=0),
                     llm=mock7, log=lambda m: None)
        assert "【已有资产库】\n无" in mock7.calls[0][0]["content"]
    finally:
        convert_mod.validate.run_lint = orig_lint
        convert_mod.validate.run_fidelity = orig_fid
    print("资产库沿用: 首批注入历史资产 / 编号仍从头 / 不传则不变 ✓")

    # 12. 用户隔离 + 历史落盘 + 资产库：全部在临时数据目录里跑，不碰真实数据
    import shutil
    import tempfile as _tempfile
    from pathlib import Path as _Path
    tmp_data = _Path(_tempfile.mkdtemp(prefix="storyboard_data_"))
    from server import auth, library, store
    orig_data, orig_users, orig_secret, orig_legacy = (
        auth.DATA_DIR, auth.USERS_FILE, auth.SECRET_FILE, auth.LEGACY_RUNS)
    auth.DATA_DIR = tmp_data
    auth.USERS_FILE = tmp_data / "users.json"
    auth.SECRET_FILE = tmp_data / "secret.key"
    auth.LEGACY_RUNS = tmp_data / "legacy_runs"

    # 旧数据归属：单用户时代的 runs/ 应移交给首个注册用户
    auth.LEGACY_RUNS.mkdir(parents=True)
    (auth.LEGACY_RUNS / "old.json").write_text(
        json.dumps({"id": "old", "created_at": "2026-01-01T00:00:00+00:00",
                    "status": "succeeded", "params": {"work_title": "旧作"},
                    "result": {}}), encoding="utf-8")
    try:
        yao = json.loads((YAO / "output_merged.json").read_text(encoding="utf-8"))

        alice = auth.register("alice", "pw123456")
        bob = auth.register("bob", "pw654321")
        assert alice["id"] != bob["id"]
        assert [r["id"] for r in store.list_runs(alice["id"])] == ["old"], \
            "首个注册用户应接管旧的单用户历史记录"
        assert not store.list_runs(bob["id"]), "后注册的用户不该看到别人的旧数据"

        # 口令与 token
        assert auth.authenticate("ALICE", "pw123456")["id"] == alice["id"], "用户名不区分大小写"
        for bad in (("alice", "wrong"), ("nobody", "pw123456")):
            try:
                auth.authenticate(*bad)
                raise AssertionError(f"错误凭据未被拒绝：{bad}")
            except auth.AuthError:
                pass
        for dup in ("alice", "ALICE"):
            try:
                auth.register(dup, "pw123456")
                raise AssertionError("重名注册未被拒绝")
            except auth.AuthError:
                pass
        raw = json.loads(auth.USERS_FILE.read_text(encoding="utf-8"))
        assert all("pw123456" not in json.dumps(u) for u in raw), "明文口令不得落盘"
        tok = auth.issue_token(alice["id"])
        assert auth.verify_token(tok)["id"] == alice["id"]
        assert auth.verify_token(tok[:-1] + ("0" if tok[-1] != "0" else "1")) is None, \
            "被篡改的 token 必须验签失败"
        assert auth.verify_token("garbage") is None

        # 历史记录：存取改删，且用户之间互不可见
        store.save(alice["id"], "run1", "succeeded", {"work_title": "药"}, yao)
        store.save(alice["id"], "run2", "completed_with_warnings",
                   {"work_title": "药"}, yao, "旁白占比 62%")
        store.save(bob["id"], "run1", "succeeded", {"work_title": "鲍勃的书"}, yao)
        runs = store.list_runs(alice["id"])
        assert len(runs) == 3 and runs[0]["units"] == 132 and runs[0]["shots"] == 133
        assert any(r["has_quality_report"] for r in runs)
        assert len(store.list_runs(bob["id"])) == 1, "用户之间的历史记录必须隔离"
        assert store.get(bob["id"], "run1")["params"]["work_title"] == "鲍勃的书", \
            "同名 run_id 在不同用户下互不覆盖"

        created_before = store.get(alice["id"], "run1")["created_at"]
        edited = json.loads(json.dumps(yao))
        edited["episodes"][0]["shots"][0]["action"] = "改过的画面描述"
        rec = store.update_result(alice["id"], "run1", edited)
        after = store.get(alice["id"], "run1")
        assert rec["edited_at"] and \
            after["result"]["episodes"][0]["shots"][0]["action"] == "改过的画面描述"
        assert after["created_at"] == created_before, "编辑不应改动创建时间"
        assert after["params"] == {"work_title": "药"}, "编辑不应丢失制作参数"
        assert store.update_result(alice["id"], "missing", edited) is None
        assert store.get(bob["id"], "run1")["result"]["episodes"][0]["shots"][0]["action"] \
            != "改过的画面描述", "改自己的记录不该动到别人的"

        assert store.delete(alice["id"], "run2") and not store.delete(alice["id"], "run2")
        assert len(store.list_runs(alice["id"])) == 2
        for bad in ("../etc/passwd", "a/b"):
            try:
                store.get(alice["id"], bad)
                raise AssertionError(f"非法记录 ID 未被拦截：{bad}")
            except ValueError:
                pass
        for bad_uid in ("../../etc", "alice"):
            try:
                auth.user_dir(bad_uid)
                raise AssertionError(f"非法用户 ID 未被拦截：{bad_uid}")
            except auth.AuthError:
                pass

        # 旧数据接管只发生在「原地升级」：LEGACY_RUNS 为 None（显式指定了数据目录）
        # 时绝不能去搬别处的真实数据——搬错一次就是用户产物凭空消失，实测踩过
        keep, auth.LEGACY_RUNS = auth.LEGACY_RUNS, None
        try:
            probe = auth.register("erin", "pw123456")
            assert not store.list_runs(probe["id"]), "关闭迁移后不应接管任何旧数据"
        finally:
            auth.LEGACY_RUNS = keep
        assert (keep / "old.json").exists() is False, "已迁移的文件不应残留在原处"
    finally:
        auth.DATA_DIR, auth.USERS_FILE, auth.SECRET_FILE, auth.LEGACY_RUNS = (
            orig_data, orig_users, orig_secret, orig_legacy)
        shutil.rmtree(tmp_data, ignore_errors=True)
    print("用户隔离: 旧数据归首个用户 / 口令哈希与 token 验签 / 历史互不可见 ✓")

    # 12b. 资产库：一等实体的增删改 + 入库合并 + 注入转换
    tmp_data2 = _Path(_tempfile.mkdtemp(prefix="storyboard_lib_"))
    auth.DATA_DIR, auth.USERS_FILE, auth.SECRET_FILE = (
        tmp_data2, tmp_data2 / "users.json", tmp_data2 / "secret.key")
    auth.LEGACY_RUNS = tmp_data2 / "nope"
    try:
        u = auth.register("carol", "pw123456")["id"]
        yao = json.loads((YAO / "output_merged.json").read_text(encoding="utf-8"))

        other = auth.register("dave", "pw123456")["id"]
        assert library.list_works(u) == [] and library.seed_for(u, "药") is None

        r = library.import_assets(u, "药", yao["assets"])
        assert r["added"] == 25 and r["merged"] == 0, f"首次入库应全为新增，实际 {r}"
        works = library.list_works(u)
        assert len(works) == 1 and works[0]["counts"]["characters"] == 12

        # 人工改一张卡，再次入库不得覆盖人工编辑，但要吸收新别名/新服装
        card = dict(next(c for c in library.get_work(u, "药")["assets"]["characters"]
                         if c["id"] == "C01"))
        card["name"] = "华老栓（人工改名）"
        library.upsert_card(u, "药", "characters", card)
        incoming = json.loads(json.dumps(yao["assets"]))
        c01 = next(c for c in incoming["characters"] if c["id"] == "C01")
        c01["aliases"] = list(c01.get("aliases") or []) + ["新别称"]
        c01["outfits"] = list(c01.get("outfits") or []) + [{"id": "winter", "name": "冬衣"}]
        r2 = library.import_assets(u, "药", incoming)
        assert r2["added"] == 0 and r2["merged"] == 25
        got = next(c for c in library.get_work(u, "药")["assets"]["characters"]
                   if c["id"] == "C01")
        assert got["name"] == "华老栓（人工改名）", "入库不得覆盖人工编辑过的字段"
        assert "新别称" in got["aliases"], "新别名应被吸收"
        assert any(o["id"] == "winter" for o in got["outfits"]), "新服装应被追加"

        # 从零建一部空作品：没有它，资产库为空时就无处下手
        assert library.create_work(u, "新书") and not library.create_work(u, "新书")
        assert library.get_work(u, "新书")["counts"] == {
            "characters": 0, "locations": 0, "props": 0, "creatures": 0}
        library.upsert_card(u, "新书", "characters", {"id": "C01", "name": "赵老三"})
        assert library.seed_for(u, "新书")["characters"][0]["name"] == "赵老三", \
            "手工建的卡同样能注入转换"
        for bad in ("", "   "):
            try:
                library.create_work(u, bad)
                raise AssertionError("空作品名未被拒绝")
            except ValueError:
                pass
        assert library.delete_work(u, "新书")

        # 凭空新建 / 删除（聚合视图做不到的两件事）
        library.upsert_card(u, "药", "props", {"id": "P99", "name": "手工新建的道具"})
        assert any(c["id"] == "P99" for c in library.get_work(u, "药")["assets"]["props"])
        assert library.delete_card(u, "药", "props", "P99")
        assert not library.delete_card(u, "药", "props", "P99")
        for bad in ({"name": "无 ID"}, {"id": "X1"}):
            try:
                library.upsert_card(u, "药", "props", bad)
                raise AssertionError(f"非法卡片未被拒绝：{bad}")
            except ValueError:
                pass
        try:
            library.upsert_card(u, "药", "weapons", {"id": "W1", "name": "刀"})
            raise AssertionError("未知资产类别未被拒绝")
        except ValueError:
            pass

        # 从历史记录回填：迁移过来的旧产物、以及关掉入库的转换，资产都不在库里
        library.delete_work(u, "药")
        assert library.list_works(u) == []
        store.save(u, "r1", "succeeded", {"work_title": "药"}, yao)
        filled = library.backfill_from_runs(u)
        assert filled and filled[0]["work_title"] == "药" and filled[0]["added"] == 25, \
            f"回填应把历史产物的资产卡补进库，实际 {filled}"
        # 回填必须可重复执行：同 ID 走合并而非重复新增
        again = library.backfill_from_runs(u)
        assert again[0]["added"] == 0 and again[0]["merged"] == 25, \
            f"重复回填不应重复新增，实际 {again}"
        assert library.list_works(u)[0]["counts"]["characters"] == 12
        # 且不覆盖人工编辑
        c = dict(next(x for x in library.get_work(u, "药")["assets"]["characters"]
                      if x["id"] == "C01"))
        c["name"] = "改过的名字"
        library.upsert_card(u, "药", "characters", c)
        library.backfill_from_runs(u)
        assert next(x for x in library.get_work(u, "药")["assets"]["characters"]
                    if x["id"] == "C01")["name"] == "改过的名字", "回填不得覆盖人工编辑"
        assert library.backfill_from_runs(other) == [], "回填只看本人的历史记录"

        seed = library.seed_for(u, "药")
        assert seed and len(seed["characters"]) == 12
        assert library.seed_for(u, "别的书") is None, "资产库按作品隔离"
        assert library.list_works(other) == [], "资产库必须按用户隔离"
        assert library.delete_work(u, "药") and not library.delete_work(u, "药")
    finally:
        auth.DATA_DIR, auth.USERS_FILE, auth.SECRET_FILE, auth.LEGACY_RUNS = (
            orig_data, orig_users, orig_secret, orig_legacy)
        shutil.rmtree(tmp_data2, ignore_errors=True)
    print("资产库: 增删改 / 入库合并不覆盖人工编辑 / 按用户与作品隔离 ✓")

    # 13. 失败原因必须进日志：光说"未通过"等于没说，用户看不到工作目录
    convert_mod.validate.run_lint = lambda p: (
        False, "FAIL: E01-SH003 引用了不存在的资产 C09\nFAIL: u0007 未被任何镜头覆盖")
    convert_mod.validate.run_fidelity = lambda p, t, w: (True, "PASS（打桩）")
    try:
        logs13 = []
        mock8 = MockLLM([json.dumps(deg_doc(1))])
        try:
            convert_text("他推门。", settings=Settings(max_retries=0),
                         llm=mock8, log=logs13.append)
            raise AssertionError("硬校验失败应抛 ConversionError")
        except ConversionError as e:
            assert "C09" in e.report
        blob = "\n".join(logs13)
        assert "原因如下" in blob, "日志未给出失败原因的引导句"
        assert "不存在的资产 C09" in blob and "u0007 未被任何镜头覆盖" in blob, \
            "校验报告的每一行都应进日志"

        # 超长报告：截断但保留完整报告的落盘路径，不让单批淹掉整个日志
        long_report = "\n".join(f"FAIL: 第 {i} 个问题" for i in range(200))
        convert_mod.validate.run_lint = lambda p: (False, long_report)
        logs14 = []
        mock9 = MockLLM([json.dumps(deg_doc(1))])
        try:
            convert_text("他推门。", settings=Settings(max_retries=0),
                         llm=mock9, log=logs14.append)
        except ConversionError:
            pass
        blob = "\n".join(logs14)
        assert "FAIL: 第 0 个问题" in blob and "FAIL: 第 199 个问题" not in blob
        m = re.search(r"…还有 (\d+) 行，完整报告见 (\S+)", blob)
        assert m, "超长报告应给出截断提示与完整报告路径"
        assert int(m.group(1)) > 0 and Path(m.group(2)).read_text(
            encoding="utf-8").count("\n") > _REPORT_LOG_LINES, "落盘的应是完整报告"
    finally:
        convert_mod.validate.run_lint = orig_lint
        convert_mod.validate.run_fidelity = orig_fid
    print("失败可诊断: 校验报告逐行进日志 / 超长截断并指向完整报告 ✓")

    # ---- 14. v0.5 镜头内阶段与负面约束 ----
    # beats 承载「一个不切的长镜头里情绪/灯光逐级推进」。既然镜头时长与各拍时长
    # 同时存在，两者就必须自洽——否则下游按哪个走全凭猜。
    import subprocess
    import tempfile

    archived = json.loads((ROOT / "tests/real_text_yao/output_merged.json")
                          .read_text(encoding="utf-8"))

    def lint_doc(doc: dict) -> str:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
            path = f.name
        r = subprocess.run([sys.executable, str(ROOT / "tools/lint_storyboard.py"), path],
                           capture_output=True, text=True)
        Path(path).unlink(missing_ok=True)
        return r.stdout + r.stderr

    # 归档件仍声明 0.4，一个字不改也必须照常通过——新字段全是可选的
    assert "PASS" in lint_doc(archived), "v0.4 归档件在新 schema 下必须原样合法"

    def with_beats(beats, constraints=None, dur=6) -> dict:
        d = json.loads(json.dumps(archived))
        d["meta"]["schema_version"] = "0.5"
        s = d["episodes"][0]["shots"][0]
        s["duration_sec"] = dur
        s["beats"] = beats
        if constraints is not None:
            s["constraints"] = constraints
        return d

    good = [{"duration_sec": 3.5, "action": "她垂着眼，强忍泪水",
             "expression": "下唇发抖", "lighting": "正面柔光"},
            {"duration_sec": 2.5, "action": "猛地抬头",
             "lighting": "右侧光，左半张脸沉入阴影"}]
    out = lint_doc(with_beats(good, ["画面内不出现任何灯具", "无镜头光晕"]))
    assert "PASS" in out, f"合规的 beats 应通过：{out}"

    out = lint_doc(with_beats([{**good[0], "duration_sec": 3},
                               {**good[1], "duration_sec": 2}]))
    assert "时长之和" in out and "FAIL" in out, "各拍时长之和对不上镜头时长必须报错"

    out = lint_doc(with_beats([good[0], {"duration_sec": 2.5, "action": "  "}]))
    assert "缺少 action" in out, "空 action 的拍必须报错"

    out = lint_doc(with_beats(good, ["画面内不出现任何灯具", ""]))
    assert "空约束项" in out, "空的负面约束必须报错"

    out = lint_doc(with_beats([{"duration_sec": 6, "action": "只有一拍"}]))
    assert "too short" in out or "FAIL" in out, "只分一拍等于没分，schema 应拦住"

    print("v0.5 镜头内阶段: 归档件仍合法 / 时长自洽 / 空拍与空约束被拦 / 单拍不成立 ✓")

    # ---- 15. 设定图归属变体 + 资产卡级负面约束 ----
    # 设定图是「画师修正稿反过来约束后续每一帧」这条链的锚点。它属于某一套 outfit
    # 而非整个角色——标错了就会拿着另一套衣服的脸去垫图，等于白垫。
    def with_sheet(outfit_tag: str, state_tag: str, constraints=None) -> dict:
        d = json.loads(json.dumps(archived))
        d["meta"]["schema_version"] = "0.5"
        c = next(x for x in d["assets"]["characters"] if x["id"] == "C04")
        p = next(x for x in d["assets"]["props"] if x["id"] == "P01")
        c["reference_images"] = [
            {"view": "front", "uri": "assets/C04_front.png", "outfit": outfit_tag},
            {"view": "three_quarter", "uri": "assets/C04_tq.png", "outfit": outfit_tag},
            {"view": "close_up", "uri": "assets/C04_face.png", "outfit": outfit_tag},
        ]
        p["reference_images"] = [
            {"view": "close_up", "uri": "assets/P01.png", "state": state_tag}]
        if constraints is not None:
            c["constraints"] = constraints
        return d

    out = lint_doc(with_sheet("loose_black", "charred",
                              ["不要平滑笔触", "不要加照片级细节", "不要改画风"]))
    assert "PASS" in out, f"合法的设定图与卡级约束应通过：{out}"

    out = lint_doc(with_sheet("summer_wrap", "charred"))
    assert "outfit 'summer_wrap' 不存在" in out, "设定图指向不存在的 outfit 必须报错"

    out = lint_doc(with_sheet("loose_black", "melted"))
    assert "state 'melted' 不存在" in out, "设定图指向不存在的 state 必须报错"

    out = lint_doc(with_sheet("loose_black", "charred", ["不要平滑笔触", "  "]))
    assert "空约束项" in out, "资产卡上的空约束必须报错"

    # close_up 是本轮新加的视图（对方的设定表是 全身正面 + 四分之三侧 + 面部特写）
    d15 = with_sheet("loose_black", "charred")
    next(x for x in d15["assets"]["characters"]
         if x["id"] == "C04")["reference_images"][2]["view"] = "portrait"
    assert "FAIL" in lint_doc(d15), "view 是受控词表，写出词表外的值应被拦"

    print("设定图归属: 三视图含特写 / 标错 outfit·state 被拦 / 卡级负面约束生效 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
