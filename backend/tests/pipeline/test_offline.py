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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline.config import Settings
from fakes import FakeChat
from langchain_core.messages import AIMessage, HumanMessage
from pipeline.chat import ChatInvoker
from pipeline.convert import ConvertParams, convert_text
from pipeline.graph import _REPORT_LOG_LINES
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


def user_msg(chat, i: int) -> str:
    """第 i 次请求里的**首条** HumanMessage——即 build_user_message 拼出的用户消息。"""
    humans = [m for m in chat.requests[i]["messages"]
              if isinstance(m, HumanMessage)]
    assert humans, f"第 {i} 次请求里没有 HumanMessage"
    return humans[0].content


def last_human(chat, i: int) -> str:
    """第 i 次请求里的**末条** HumanMessage——即回喂的校验报告或工具结果。"""
    humans = [m for m in chat.requests[i]["messages"]
              if isinstance(m, HumanMessage)]
    assert humans, f"第 {i} 次请求里没有 HumanMessage"
    return humans[-1].content


def tool_call(name, args, call_id):
    return AIMessage(content="", tool_calls=[
        {"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def review_invoker(responses):
    return ChatInvoker(Settings(api_key="k"), chat=FakeChat(responses=responses),
                       log=lambda m: None)


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
    mock = FakeChat(responses=[
        (YAO / "output_batch1.json").read_text(encoding="utf-8"),
        (YAO / "output_batch2.json").read_text(encoding="utf-8"),
    ])
    logs = []
    progress = {}
    partials = []
    # 归档由未清洗原文转换（units 保留 U+200B），关闭入口归一化以逐字回放
    doc = convert_text(full,
                       params=YAO_PARAMS,
                       settings=Settings(max_retries=0, normalize_input=False,
                                         freeze_source_units=False),
                       llm=mock, batches=[b1, b2],
                       log=logs.append, progress_out=progress,
                       on_partial=lambda d, k, n: partials.append((d, k, n)))
    # 分批先看：每批跑完（最后一批除外）把已完成的批次合并成部分产物交出去
    assert [(k, n) for _, k, n in partials] == [(1, 2)], "只在非末批之后交部分产物"
    part = partials[0][0]
    b1_doc = json.loads((YAO / "output_batch1.json").read_text(encoding="utf-8"))
    assert [u["id"] for u in part["source"]["units"]] == \
        [u["id"] for u in b1_doc["source"]["units"]], "部分产物只含已完成批次的句子"
    assert part["episodes"] and part["meta"]
    # 两批以上要先合并：拿两份归档批次模拟「3 批里跑完了 2 批」
    import tempfile as _tf      # main() 后面有局部 import tempfile，这里不能直接用那个名字
    from pipeline.convert import _emit_partial
    got2, plog = [], []
    with _tf.TemporaryDirectory() as td:
        _emit_partial(lambda d, k, n: got2.append((d, k, n)),
                      [YAO / "output_batch1.json", YAO / "output_batch2.json"],
                      Path(td), 2, 3, plog.append)
    assert [(k, n) for _, k, n in got2] == [(2, 3)], plog
    assert len(got2[0][0]["source"]["units"]) == 132, "两批合并后应含两批全部句子"
    # 预览回调出错不能拖垮转换
    with _tf.TemporaryDirectory() as td:
        _emit_partial(lambda d, k, n: 1 / 0, [YAO / "output_batch1.json"],
                      Path(td), 1, 2, plog.append)
    assert any("预览回调出错" in line for line in plog)
    assert progress["phase"] == "done" and progress["batches"] == 2
    assert progress["batch"] == 2 and progress["done_chars"] == progress["total_chars"]
    assert progress["max_attempts"] == 1 and progress["attempt"] == 1

    # 服务端的进度视图：第一批跑完之前不猜剩余时间；之后按已完成字数线性外推
    import time as _time
    from server.app import _progress_view
    now = _time.time()
    job = {"status": "running", "progress": {
        "batches": 2, "batch": 1, "total_chars": 1000, "done_chars": 0,
        "phase": "generating", "started_at": now - 60}}
    v = _progress_view(job)
    assert v["eta_sec"] is None and 59 <= v["elapsed_sec"] <= 61
    assert "started_at" not in v, "不把服务端时钟交给浏览器去减"
    job["progress"].update({"done_chars": 400, "batch": 2})
    assert 88 <= _progress_view(job)["eta_sec"] <= 92, "60s 完成 40%，剩余约 90s"
    job["status"] = "succeeded"
    assert _progress_view(job)["eta_sec"] is None
    assert _progress_view({"status": "queued", "progress": {}}) is None
    print("进度: 批次/尝试/阶段原地更新 / 剩余时间按字数外推且首批前不猜 ✓")

    # 服务端：轮询只带「已完成几批」，部分产物走单独接口取；整章成功后清掉
    from fastapi import HTTPException as _HE
    from server.app import _jobs, get_job, get_job_partial, _on_partial
    pj = {"id": "pj1", "user_id": "u1", "status": "running", "log": [], "progress": {},
          "partial": None}
    _jobs["pj1"] = pj
    try:
        _on_partial(pj, part, 1, 2)
        polled = get_job("pj1", user={"id": "u1"})
        assert polled["partial_batches"] == 1 and "partial" not in polled, \
            "轮询不能每 1.5 秒都把整份部分产物带一遍"
        got = get_job_partial("pj1", user={"id": "u1"})
        assert got["batches_done"] == 1 and got["batches"] == 2 and got["doc"] is part
        try:
            get_job_partial("pj1", user={"id": "someone-else"})
            raise AssertionError("别人的任务不能取")
        except _HE as e:
            assert e.status_code == 404
        pj["partial"] = None
        try:
            get_job_partial("pj1", user={"id": "u1"})
            raise AssertionError("没有部分产物时应 404")
        except _HE as e:
            assert e.status_code == 404
        assert get_job("pj1", user={"id": "u1"})["partial_batches"] == 0
    finally:
        _jobs.pop("pj1", None)
    print("分批先看: 非末批交部分产物 / 轮询只带批数 / 单独接口取且隔离用户 ✓")
    archived = json.loads((YAO / "output_merged.json").read_text(encoding="utf-8"))
    # 校验节点会把念不完旁白的镜头时长自动拉长；archived 留原样（后面的时长门
    # 用例要测的正是归档里念不完的镜头），比对用拉长后的副本
    from pipeline.quality import fit_durations
    expected = json.loads(json.dumps(archived))
    fit_durations(expected)
    assert doc == expected, "流水线合并结果与归档 output_merged.json（时长拉长后）不一致"
    assert len(doc["source"]["units"]) == 132
    print("回放: 2 批 → 逐批校验 → 合并 → 整章 lint+保真终检全通过，结果与归档逐字一致 ✓")

    # 4. 续批参数拼装（对照人肉实测 input_batch2.txt 的取值）
    msg2 = user_msg(mock, 1)
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
    # 回喂清单要分清「可直接移除」与「只靠旁白承载」：实测模型照清单删旁白，
    # 把没有画面引用的句子删成无人承载，修复轮反而掉进 COVERAGE-001 硬失败
    shots = degraded["episodes"][0]["shots"]
    for i in range(5):                       # 前 5 句另有镜头画面引用
        shots[i]["source"] = {"unit_refs": [f"u{i + 1:04d}"]}
    ok, report, _ = narration_density_gate(degraded, 0.6)
    safe, _, rest = report.partition("只靠旁白承载")
    assert "u0001" in safe and "u0005" in safe and "u0006" not in safe, report
    assert "u0006" in rest and "source.unit_refs" in rest, \
        "只靠旁白承载的句子要说明：移除前先加进画面镜头的 source.unit_refs"
    print("旁白密度门: 归档通过 / 100% 旁白拦截 / 关闭与模式豁免生效 / 清单分可删与需先补画面 ✓")

    # 程序裁剪旁白：只动模型标为动作/描写、且已有画面引用的句子，先动作后描写，
    # 按原文顺序裁到刚好不超阈值；旁白文本随之重建，空了就省略整个 narration
    from pipeline.quality import fix_known_slips, prune_narration
    kinds = ["action"] * 6 + ["description"] * 2 + ["psychology", "action"]
    pdoc = {"meta": {"narration": {"mode": "selective"}},
            "source": {"units": [{"id": f"u{i:04d}", "text": f"句{i}。", "kind": k}
                                 for i, k in enumerate(kinds, 1)]},
            "episodes": [{"shots": []}]}
    pshots = pdoc["episodes"][0]["shots"]
    # 镜头 1 的旁白引两句（u1+u2，文本严格拼接）；其余各一句；u10 没有画面引用
    pshots.append({"source": {"unit_refs": ["u0001", "u0002"]},
                   "narration": {"unit_refs": ["u0001", "u0002"], "text": "句1。句2。"}})
    for i in range(3, 11):
        sh = {"narration": {"unit_refs": [f"u{i:04d}"], "text": f"句{i}。"}}
        if i != 10:
            sh["source"] = {"unit_refs": [f"u{i:04d}"]}
        pshots.append(sh)
    assert prune_narration(pdoc, 0.6) == 4, "10 句全念、阈值 60%，应移出 4 句"
    left = [r for sh in pshots for r in (sh.get("narration") or {}).get("unit_refs", [])]
    assert left == ["u0005", "u0006", "u0007", "u0008", "u0009", "u0010"], left
    assert "narration" not in pshots[0], "镜头 1 两句都移出后整个 narration 应省略"
    assert pshots[1].get("narration") is None and pshots[3]["narration"]["text"] == "句5。"
    ok, _, ratio = narration_density_gate(pdoc, 0.6)
    assert ok and ratio == 0.6, "裁到刚好不超阈值"
    assert prune_narration(pdoc, 0.6) == 0, "裁剪应幂等"

    # 多句旁白里摘一句：严格拼接时重建；不严格拼接但该句原文只出现一次时摘掉子串
    two = {"meta": {"narration": {"mode": "selective"}},
           "source": {"units": [{"id": "u0001", "text": "他推门。", "kind": "action"},
                                {"id": "u0002", "text": "她心里一沉。", "kind": "psychology"}]},
           "episodes": [{"shots": [{"source": {"unit_refs": ["u0001", "u0002"]},
                                    "narration": {"unit_refs": ["u0001", "u0002"],
                                                  "text": "他推门，她心里一沉。"}}]}]}
    assert prune_narration(two, 0.5) == 0, "原文「他推门。」不在旁白里（改了标点）：不敢动"
    two["episodes"][0]["shots"][0]["narration"]["text"] = "他推门。　她心里一沉。"
    assert prune_narration(two, 0.5) == 1
    assert two["episodes"][0]["shots"][0]["narration"] == {
        "unit_refs": ["u0002"], "text": "　她心里一沉。"}
    # 非 selective 模式、或没超阈值：不动
    pdoc["meta"]["narration"]["mode"] = "original_text"
    assert prune_narration(pdoc, 0.1) == 0

    # 已知笔误：机位 reverse → over_shoulder；narration: null → 省略
    slips = {"episodes": [{"shots": [{"camera": {"angle": "reverse"}, "narration": None},
                                     {"camera": {"angle": "low", "movement": "whip_pan"}}]}]}
    assert fix_known_slips(slips) == 3
    assert slips["episodes"][0]["shots"][0] == {"camera": {"angle": "over_shoulder"}}
    assert slips["episodes"][0]["shots"][1]["camera"]["movement"] == "pan", "甩镜归入摇镜"
    assert fix_known_slips(slips) == 0
    print("旁白裁剪: 只动有画面承载的动作/描写句 / 裁到阈值即停 / 文本重建或不敢动 / 已知笔误修正 ✓")


    # 7. 评审阶段流程（mock：生成 1 次 + 评审 1 次通过）
    romance_text = extract_passage(
        (ROOT / "tests" / "genre_stability" / "input_romance.txt")
        .read_text(encoding="utf-8"))
    romance_json = (ROOT / "tests" / "genre_stability" / "output_romance.json"
                    ).read_text(encoding="utf-8")
    verdict = ('{"scores": {"narration_selection": 4, "shot_language": 4, '
               '"asset_quality": 4, "semantic_fidelity": 5}, '
               '"overall": 4.3, "issues": []}')
    mock2 = FakeChat(responses=[romance_json, verdict])
    manifest2 = {}
    doc2 = convert_text(
        romance_text,
        params=ConvertParams(work_title="橘子汽水", chapter="第七章 天台",
                             narration_mode="original_text"),
        # 这份归档是 original_text，语音超时率 64%（系统性问题），
        # 本组测的是评审流程，故关掉时长门放行
        settings=Settings(max_retries=0, review_enabled=True,
                          speech_overflow_max=1.0),
        llm=mock2, log=lambda m: None, manifest_out=manifest2)
    assert len(mock2.requests) == 2, "应有 1 次生成 + 1 次评审调用"
    assert "评审总分" not in json.dumps(doc2), "评审结果不应混入产物"
    assert manifest2["state"] == "verified" and \
        manifest2["verification"]["status"] == "verified"
    assert manifest2["scope"]["frozen"] and len(manifest2["scope"]["units"]) == 11
    assert manifest2["artifact_sha256"] and manifest2["attempts"][0]["status"] == "passed"
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
    orig_verify = convert_mod.verification.verify_document
    convert_mod.verification.verify_document = lambda *a, **kw: \
        convert_mod.verification.VerificationReport(coverage={
            "selected": [], "covered": [], "waived": [], "failed": [],
            "inferred_shot_ratio": 0,
        })
    convert_mod.validate.run_lint = lambda p: (True, "PASS（打桩）")
    convert_mod.validate.run_fidelity = lambda p, t, w: (True, "PASS（打桩）")
    try:
        warnings = []
        patch8 = tool_call("json_patch", {"patch": [{
            "op": "replace", "path": "/episodes/0/shots",
            "value": deg_doc(8)["episodes"][0]["shots"],
        }]}, "c-patch")
        mock3 = FakeChat(responses=[json.dumps(deg_doc(10)), patch8])
        doc3 = convert_text("他推门。", settings=Settings(max_retries=1),
                            llm=mock3, batches=["他推门。"],
                            log=lambda m: None, warnings_out=warnings)
        narrated = sum(len(s["narration"]["unit_refs"])
                       for s in doc3["episodes"][0]["shots"])
        assert narrated == 8, f"应择优交付 80% 那版，实际旁白句数 {narrated}"
        assert len(warnings) == 1 and "择优交付第 2 次生成" in warnings[0]
        assert "旁白占比 80%" in warnings[0]

        # 修复轮次可以先读取结构化工具结果，再提交受限补丁；仍只占一次修复 attempt。
        tool_manifest = {}
        mock_tools = FakeChat(responses=[
            json.dumps(deg_doc(10)), tool_call("coverage_query", {}, "c-cov"),
            patch8,
        ])
        convert_text("他推门。", settings=Settings(max_retries=1), llm=mock_tools,
                     batches=["他推门。"], log=lambda m: None,
                     manifest_out=tool_manifest)
        assert len(mock_tools.requests) == 3
        assert tool_manifest["attempts"][1]["tools"] == ["coverage_query", "json_patch"]

        # rewrite 模式：改造前的整份重写路径，保留下来做 A/B 标定；
        # 同时验证 token 账按尝试归属并汇总进清单——不然「补丁省不省」无从实测。
        rw_manifest = {}
        mock_rw = FakeChat(responses=[json.dumps(deg_doc(10)), json.dumps(deg_doc(8))])
        convert_text("他推门。", llm=mock_rw, batches=["他推门。"],
                     settings=Settings(max_retries=1, repair_mode="rewrite"),
                     log=lambda m: None, manifest_out=rw_manifest,
                     warnings_out=[])
        assert rw_manifest["contracts"]["repair_mode"] == "rewrite"
        assert rw_manifest["attempts"][1]["mode"] == "generate", "rewrite 不应发补丁"
        assert "重新输出完整 JSON" in last_human(mock_rw, 1)
        assert rw_manifest["attempts"][0]["usage"]["calls"] == 1
        assert rw_manifest["usage"]["calls"] == 2 and rw_manifest["usage"]["output"] > 0
        assert rw_manifest["usage"]["output"] == sum(
            a["usage"]["output"] for a in rw_manifest["attempts"])

        mock4 = FakeChat(responses=[json.dumps(deg_doc(10)), patch8])
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
    print("标定装置: rewrite 模式走整份重写 / token 按尝试归属并汇总 ✓")

    # 9. 入口归一化：零宽噪声在进 LLM 前被剔除（默认开启）
    from pipeline.splitter import normalize_source_text
    cleaned, n = normalize_source_text("徘徊；\u200b定睛\ufeff再看\u2060。")
    assert (cleaned, n) == ("徘徊；定睛再看。", 3)
    assert Settings().normalize_input, "归一化应默认开启"
    convert_mod.validate.run_lint = lambda p: (True, "PASS（打桩）")
    convert_mod.validate.run_fidelity = lambda p, t, w: (True, "PASS（打桩）")
    try:
        mock5 = FakeChat(responses=[json.dumps(deg_doc(1))])
        convert_text("他\u200b推门。", settings=Settings(max_retries=0),
                     llm=mock5, log=lambda m: None)
        assert "\u200b" not in user_msg(mock5, 0), \
            "零宽字符不应出现在发给 LLM 的原文里"
    finally:
        convert_mod.validate.run_lint = orig_lint
        convert_mod.validate.run_fidelity = orig_fid
    print("入口归一化: U+200B/BOM/U+2060 剔除，LLM 输入已清洗 ✓")

    # 11. 跨转换沿用资产库：首批就带【已有资产库】，且编号不走续批逻辑
    seed = {"characters": [{"id": "C01", "name": "华老栓"}],
            "locations": [{"id": "S01", "name": "古□亭口"}]}
    convert_mod.validate.run_lint = lambda p: (True, "PASS（打桩）")
    convert_mod.validate.run_fidelity = lambda p, t, w: (True, "PASS（打桩）")
    try:
        mock6 = FakeChat(responses=[json.dumps(deg_doc(1))])
        convert_text("他推门。", settings=Settings(max_retries=0),
                     llm=mock6, log=lambda m: None, seed_assets=seed)
        sent = user_msg(mock6, 0)
        assert "华老栓" in sent and '"C01"' in sent, "首批未注入历史资产库"
        assert "【续批参数】\n无" in sent, "沿用资产库不应触发续批编号（应从 u0001 起）"

        mock7 = FakeChat(responses=[json.dumps(deg_doc(1))])   # 不传则维持原样
        convert_text("他推门。", settings=Settings(max_retries=0),
                     llm=mock7, log=lambda m: None)
        assert "【已有资产库】\n无" in user_msg(mock7, 0)
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
        mock8 = FakeChat(responses=[json.dumps(deg_doc(1))])
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
        mock9 = FakeChat(responses=[json.dumps(deg_doc(1))])
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
        convert_mod.verification.verify_document = orig_verify
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

    # ---- 16. 渲染任务清单 ----
    # 最要命的一条：机器可读清单与人读版 Markdown 生产包必须是同一句提示词。
    # 分叉了的话，人眼在 Markdown 里逐条核对过的东西，跟真正发给视频 API 的
    # 就不是一回事——而那一步是要花钱的。
    from adapters import seedance as sd
    from render import plan as rp

    plan = rp.build_plan(archived, max_clip_seconds=15)
    assert plan["clips"], "应切出 clip"
    assert plan["work_title"] == "药"

    total = sum(c["duration_sec"] for c in plan["clips"])
    doc_total = sum(s.get("duration_sec", 0)
                    for ep in archived["episodes"] for s in ep["shots"])
    assert abs(total - doc_total) < 0.05, "clip 总时长必须等于分镜总时长，不能漏镜头"
    covered = [sid for c in plan["clips"] for sid in c["shots"]]
    all_shots = [s["id"] for ep in archived["episodes"] for s in ep["shots"]]
    assert covered == all_shots, "clip 必须按原顺序覆盖全部镜头，不重不漏"
    for c in plan["clips"]:
        assert c["duration_sec"] <= 15 or len(c["shots"]) == 1, \
            f"{c['id']} 超出单 clip 上限却不是单镜头独占"
        assert c["episode"] == c["id"].split("-C")[0], "clip 不得跨集"

    # 同一句提示词：清单里的每段 prompt 都应原样出现在对应集的 Markdown 里
    for ep in archived["episodes"]:
        md = sd.render_episode(archived, ep, 15)
        for c in plan["clips"]:
            if c["episode"] != ep["id"]:
                continue
            assert c["prompt"] in md, \
                f"{c['id']} 的提示词未逐字出现在 Markdown 生产包里——两套提示词已分叉"

    # 垫图引用必须是真实存在的资产
    ids = {x["id"] for k in ("characters", "locations", "props", "creatures")
           for x in archived["assets"].get(k, [])}
    for c in plan["clips"]:
        for ref in c["reference_assets"]:
            assert ref in ids, f"{c['id']} 垫图引用了不存在的资产 {ref}"

    # 出图清单只列被引用到的卡，且如实反映「还差几张图」
    assert all(a["id"] in ids for a in plan["assets"])
    assert plan["estimate"]["asset_images_missing"] == \
        plan["estimate"]["asset_images_total"], "归档件没有任何设定图，应全部计为待出"
    est = plan["estimate"]
    assert est["cny_with_retries"] > est["cny_once"] > 0, "费用必须给区间"
    assert abs(est["seconds"] - doc_total) < 0.05, "标称秒数应等于分镜总时长"

    # 费率是估算，必须可切档、可用真实账单覆盖，且如实交代依据
    assert est["calibrated"] is False, "默认应标为未标定"
    assert est["rate"]["source"] and est["caveats"], "必须交代依据与不确定性"
    assert any("分辨率" in c for c in est["caveats"]), "分辨率未建模这条必须说出来"
    mini = rp.build_plan(archived, model="seedance-2.0-mini")["estimate"]
    assert mini["cny_once"] < est["cny_once"], "mini 档应更便宜"
    pinned = rp.build_plan(archived, cny_per_second=1.0)["estimate"]
    assert pinned["calibrated"] is True
    assert abs(pinned["cny_once"] - pinned["playable_seconds"]) < 0.05, \
        "显式费率应直接生效（1 元/秒 → 费用等于可播秒数）"
    assert {t["id"] for t in plan["tiers"]} >= {"seedance-2.0", "seedance-2.0-mini"}

    # 切法变了，clip 数与切分都得跟着变
    short = rp.build_plan(archived, max_clip_seconds=5)
    assert len(short["clips"]) > len(plan["clips"]), "上限调小应切出更多 clip"

    # v0.5 的 beats 要逐拍展开，压成一行就把「一镜到底逐级推进」的信息丢了
    beat_doc = with_beats([{"duration_sec": 3.5, "action": "她垂着眼",
                            "lighting": "正面柔光"},
                           {"duration_sec": 2.5, "action": "猛地抬头",
                            "lighting": "右侧光"}],
                          ["画面内不出现任何灯具"])
    bp = rp.build_plan(beat_doc, max_clip_seconds=15)
    first = next(c for c in bp["clips"] if "E01-SH001" in c["shots"])
    assert "她垂着眼" in first["prompt"] and "猛地抬头" in first["prompt"], \
        "beats 应逐拍进提示词"
    assert "正面柔光" in first["prompt"] and "右侧光" in first["prompt"], \
        "每拍的灯光都要带上——灯光编排正是分拍的意义所在"
    assert "【不要】画面内不出现任何灯具" in first["prompt"], "负面约束应进提示词"

    print("渲染任务清单: 镜头不重不漏 / 与生产包逐字同一提示词 / 费用给区间 / beats 逐拍展开 ✓")

    # ---- 17. 时长自洽：镜头必须够念完自己的旁白与台词 ----
    # 不修这条，任何时长预算都是纸面数字：按标称时长算的钱，渲染时会被迫拉长。
    from pipeline.quality import playable_seconds, speech_fit_gate, speech_seconds

    nominal, actual = playable_seconds(archived)
    assert actual > nominal, "《药》归档存在念不完的镜头，实际时长应大于标称"
    ok, report, ratio = speech_fit_gate(archived, 0.1)
    assert not ok and 0.15 < ratio < 0.25, f"《药》超时比例应约 19%，实为 {ratio}"
    assert "E02-SH020" in report or "缺" in report, "报告要指名道姓列出念不完的镜头"
    assert "不得改动旁白与台词文本" in report, "报告必须划清可改与不可改的边界"
    ok, _, _ = speech_fit_gate(archived, 0.25)
    assert ok, "默认阈值 25% 下《药》应放行（只拦离谱的）"
    ok, _, _ = speech_fit_gate(archived, 1.0)
    assert ok, ">=1 应视为关闭该门"

    # 语速越快越念得完，判定必须跟着变
    _, _, slow = speech_fit_gate(archived, 0.0, cps=4.5)
    _, _, fast = speech_fit_gate(archived, 0.0, cps=6.0)
    assert fast < slow, "语速调快后念不完的镜头应变少"

    # 程序自动拉长：拉到念得完（0.5s 向上取整），封顶 15s；带 beats 的不动；
    # 封顶后仍念不完的镜头留给时长门拦下要求拆镜
    from pipeline.quality import MAX_SHOT_SECONDS, fit_durations, normalize_curve_refs
    fitted = json.loads(json.dumps(archived))
    n_fit = fit_durations(fitted)
    assert n_fit > 0
    for ep in fitted["episodes"]:
        for sh in ep["shots"]:
            if not sh.get("beats"):
                assert sh["duration_sec"] >= min(speech_seconds(sh), MAX_SHOT_SECONDS) - 0.05
                assert sh["duration_sec"] <= MAX_SHOT_SECONDS
    assert fit_durations(fitted) == 0, "拉长应幂等"
    ok, report, ratio = speech_fit_gate(fitted, 0.0)
    assert ratio < 0.05, f"拉长后只剩超过 15s 上限的镜头，实为 {ratio:.0%}"
    long_shot = {"narration": {"text": "字" * 90}, "duration_sec": 4}   # 需 20s
    assert fit_durations({"episodes": [{"shots": [long_shot]}]}) == 1
    assert long_shot["duration_sec"] == MAX_SHOT_SECONDS
    ok, report, _ = speech_fit_gate({"episodes": [{"shots": [long_shot]}]}, 0.0)
    assert not ok and "拆成多个镜头" in report, "超上限的镜头要回喂拆镜"
    beat_shot = {"narration": {"text": "字" * 45}, "duration_sec": 4,
                 "beats": [{"duration_sec": 2, "action": "a"},
                           {"duration_sec": 2, "action": "b"}]}
    assert fit_durations({"episodes": [{"shots": [beat_shot]}]}) == 0, \
        "带 beats 的镜头单改总长会破坏各拍之和"
    odd = {"narration": {"text": "字" * 10}, "duration_sec": 1}      # 需 2.22s
    fit_durations({"episodes": [{"shots": [odd]}]})
    assert odd["duration_sec"] == 2.5, "按 0.5s 向上取整"

    # music.curve 序号 → 镜头 ID；越界的截到本集首/末镜（实测模型数错镜头数，
    # 写出本集只有 40 镜时的第 41、44 镜）；本集不存在的同集镜头 ID 同样截到末镜
    curve_doc = {"episodes": [{"shots": [{"id": "E01-SH001"}, {"id": "E01-SH002"}],
                               "music": {"curve": [
                                   {"from_shot": 1, "to_shot": "2"},
                                   {"from_shot": "E01-SH001", "to_shot": 9},
                                   {"from_shot": 0, "to_shot": "E01-SH041"},
                                   {"from_shot": "E02-SH005", "to_shot": "E01-SH002"}]}}]}
    assert normalize_curve_refs(curve_doc) == 5
    segs = curve_doc["episodes"][0]["music"]["curve"]
    assert segs[0] == {"from_shot": "E01-SH001", "to_shot": "E01-SH002"}
    assert segs[1] == {"from_shot": "E01-SH001", "to_shot": "E01-SH002"}, "越界截到末镜"
    assert segs[2] == {"from_shot": "E01-SH001", "to_shot": "E01-SH002"}, \
        "序号 0 截到首镜；本集不存在的镜头 ID 截到末镜"
    assert segs[3]["from_shot"] == "E02-SH005", "别的集的 ID 不归这里管，留给 lint 报"
    assert normalize_curve_refs(curve_doc) == 0, "应幂等"

    one = {"narration": {"text": "十个字的旁白吧"}, "duration_sec": 5,
           "dialogue": [{"text": "八个字的台词"}]}
    assert abs(speech_seconds(one, 5.0) - 2.6) < 0.01, "旁白与台词字数应合并计时"

    # 渲染估算必须按可播时长计价，否则预算失真
    est = rp.build_plan(archived)["estimate"]
    assert est["playable_seconds"] > est["seconds"], "估算应给出可播时长"
    assert abs(est["cny_once"]
               - est["playable_seconds"] * est["cny_per_second"]) < 0.2, \
        "计价必须用可播时长，不是标称时长"
    assert any("念完旁白" in c for c in est["caveats"]), "差额要说清楚"
    assert all(c["playable_sec"] >= c["duration_sec"] for c in
               rp.build_plan(archived)["clips"]), "每条 clip 的可播时长不得小于标称"

    print("时长自洽: 念不完的镜头被逐条点名 / 阈值与语速可调 / 估算按可播时长计价 ✓")

    # ---- 18. 确定性范围 + 结构化证据 + 受限修复 + 独立后处理 ----
    from pipeline.source_units import build_frozen_units, prompt_units
    from pipeline.verification import verify_document, recompute_coverage_field
    from pipeline.repair import RepairError, apply_json_patch
    from pipeline.review import run_review

    scope_text = "第一句。\n他说：“第二句！”"
    frozen = build_frozen_units(scope_text, [scope_text])
    assert [u.id for u in frozen] == ["u0001", "u0002"]
    assert "".join(u.text for u in frozen).replace("\n", "") == scope_text.replace("\n", "")
    assert build_frozen_units(scope_text, [scope_text]) == frozen, "同一输入必须产生相同范围"
    assert prompt_units(frozen, 1)[0] == {"id": "u0001", "text": "第一句。", "para": 1}

    evidence_doc = json.loads((ROOT / "tests" / "genre_stability" /
                               "output_romance.json").read_text(encoding="utf-8"))
    expected = [{k: u.get(k) for k in ("id", "text", "para")}
                for u in evidence_doc["source"]["units"]]
    tampered = json.loads(json.dumps(evidence_doc))
    tampered["source"]["units"][0]["text"] += "篡改"
    report = verify_document(tampered, frozen_units=expected)
    assert any(f.rule_id == "SOURCE-FROZEN-002" and f.severity == "critical"
               for f in report.findings), "源证据改写必须是 critical"

    waived = json.loads(json.dumps(evidence_doc))
    waived["source"]["units"][0]["skipped"] = True
    report = verify_document(waived, frozen_units=expected)
    assert any(f.rule_id == "SOURCE-WAIVER-001" for f in report.findings), \
        "无理由跳过不得进入覆盖率豁免"

    wrong_coverage = json.loads(json.dumps(evidence_doc))
    wrong_coverage["coverage"] = {"unmapped_units": ["u9999"],
                                  "inferred_shot_ratio": 1}
    probe = verify_document(wrong_coverage)
    recompute_coverage_field(wrong_coverage, probe.coverage)
    report = verify_document(wrong_coverage)
    assert not any(f.rule_id.startswith("COVERAGE-DECLARED") for f in report.findings)
    assert wrong_coverage["coverage"]["unmapped_units"] == report.coverage["failed"]

    hallucinated = json.loads(json.dumps(evidence_doc))
    dialogue_item = next(d for ep in hallucinated["episodes"]
                         for shot in ep["shots"] for d in shot.get("dialogue") or [])
    dialogue_item["text"] = "原文里不存在的台词"
    report = verify_document(hallucinated)
    assert any(f.rule_id == "FID-DIALOGUE-001" for f in report.findings)

    try:
        apply_json_patch(evidence_doc, [{"op": "replace",
                                        "path": "/source/units/0/text",
                                        "value": "不可修改"}])
        raise AssertionError("修复 Agent 不得修改冻结证据")
    except RepairError:
        pass
    patched = apply_json_patch(evidence_doc, [{"op": "replace",
                                               "path": "/episodes/0/shots/0/action",
                                               "value": "受限修改"}])
    assert patched["episodes"][0]["shots"][0]["action"] == "受限修改"
    assert evidence_doc["episodes"][0]["shots"][0]["action"] != "受限修改", \
        "补丁应用不得原地污染候选"

    low_semantic = ('{"scores":{"narration_selection":5,"shot_language":5,'
                    '"asset_quality":5,"semantic_fidelity":3},"overall":5,"issues":[]}')
    ok, _, overall = run_review(review_invoker([low_semantic]), "原文", evidence_doc, 3.0, 3, 4)
    assert not ok and overall == 4.5, "服务端重算平均分，且语义忠实度独立设底线"
    ok, report_text, overall = run_review(review_invoker(['{"scores":{"x":5}}']),
                                          "原文", evidence_doc, 3.0)
    assert ok is None and overall is None and "不可验证" in report_text
    failing_review = review_invoker([])
    failing_review.invoke = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("offline"))
    ok, report_text, overall = run_review(failing_review, "原文", evidence_doc, 3.0)
    assert ok is None and overall is None and "服务不可用" in report_text
    print("可验证审查: 冻结范围 / 证据定位 / 覆盖率重算 / 受限补丁 / 语义独立门槛 ✓")

    # 无效人工编辑允许保存为草稿，但不能借此绕过渲染前验证；旧记录也要在
    # 第一次编辑时固化原始 source.units，不能拿篡改后的结果当新基线。
    from fastapi import HTTPException
    from server.app import history_update, render_plan as api_render_plan, RenderPlanRequest
    api_data = _Path(_tempfile.mkdtemp(prefix="storyboard_api_gate_"))
    old_auth_paths = auth.DATA_DIR, auth.USERS_FILE, auth.SECRET_FILE, auth.LEGACY_RUNS
    auth.DATA_DIR = api_data
    auth.USERS_FILE = api_data / "users.json"
    auth.SECRET_FILE = api_data / "secret.key"
    auth.LEGACY_RUNS = None
    try:
        gate_user = auth.register("gatecheck", "pw123456")
        store.save(gate_user["id"], "gate1", "succeeded", {}, evidence_doc)
        invalid_edit = json.loads(json.dumps(evidence_doc))
        invalid_edit["source"]["units"][0]["text"] += "篡改"
        saved = history_update("gate1", invalid_edit, gate_user)
        assert saved["status"] == "draft_invalid"
        persisted = store.get(gate_user["id"], "gate1")
        assert persisted["manifest"]["scope"]["units"][0]["text"] != \
            invalid_edit["source"]["units"][0]["text"], "旧记录原始证据必须固化"
        try:
            api_render_plan(RenderPlanRequest(result=invalid_edit, run_id="gate1",
                                              include_markdown=False), gate_user)
            raise AssertionError("无效草稿不得进入付费渲染")
        except HTTPException as exc:
            assert exc.status_code == 422
    finally:
        auth.DATA_DIR, auth.USERS_FILE, auth.SECRET_FILE, auth.LEGACY_RUNS = old_auth_paths
        shutil.rmtree(api_data, ignore_errors=True)
    print("API 验证门: 无效编辑标记 draft_invalid / 旧证据固化 / 渲染前阻断 ✓")

    # ---- 20. 覆盖率口径三方一致 + 讲述顺序 ----
    # 覆盖率现在有三处实现：pipeline/verification.py、tools/lint_storyboard.py、
    # tools/merge_storyboard.py。台词归属的口径本来就不同（按 unit.kind 还是按
    # 台词文本匹配），眼下三方结果一致，但没有任何测试钉住它们——改任意一处都
    # 不会有人发现，直到某天两个数对不上而没人知道该信谁。这一组就是那颗钉子。
    import importlib.util
    import tempfile
    from pipeline import validate as validate_mod
    from pipeline import verification

    spec = importlib.util.spec_from_file_location(
        "merge_tool", ROOT / "tools" / "merge_storyboard.py")
    merge_tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(merge_tool)

    checked = 0
    with tempfile.TemporaryDirectory() as td:
        for rel in ("real_text_yao/output_merged", "long_chapter/output_merged",
                    "genre_stability/output_romance"):
            raw = (ROOT / "tests" / f"{rel}.json").read_text(encoding="utf-8")
            for mode in ("selective", "original_text"):
                doc = json.loads(raw)
                doc["meta"]["narration"]["mode"] = mode
                cov = verification.verify_document(doc).coverage
                merged = merge_tool.recompute_coverage(json.loads(json.dumps(doc)))
                assert sorted(cov["failed"]) == sorted(merged["unmapped_units"]), (
                    f"{rel}/{mode}: verification 与 merge_storyboard 的未覆盖句不一致")
                assert cov["inferred_shot_ratio"] == merged["inferred_shot_ratio"], (
                    f"{rel}/{mode}: 两处算出的 inferred 比例不一致")

                # 把 verification 的结论写进文档再跑 lint：lint 若用的是另一套口径，
                # 就会报「声明的 unmapped_units 与实际不符」。这是最直接的等价性证据。
                verification.recompute_coverage_field(doc, cov)
                path = Path(td) / "cov.json"
                path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
                _, lint_out = validate_mod.run_lint(path)
                assert "与实际不符" not in lint_out, (
                    f"{rel}/{mode}: lint 的覆盖率口径与 verification 分叉了\n{lint_out}")
                assert ("以下句子未被任何镜头旁白覆盖" in lint_out) == bool(cov["failed"]), (
                    f"{rel}/{mode}: lint 与 verification 对「有没有漏句」判断相反")
                checked += 1
    assert checked == 6

    # 讲述顺序：原有的 EVIDENCE-RANGE-001 只看单镜头内部相不相邻，管不到镜头之间。
    order_doc = json.loads((YAO / "output_merged.json").read_text(encoding="utf-8"))
    assert not [f for f in verification.verify_document(order_doc).findings
                if f.rule_id == "ORDER-001"], "归档件本身不应触发顺序告警"
    shots = order_doc["episodes"][0]["shots"]
    shots[1], shots[3] = shots[3], shots[1]      # 把原文倒着讲
    order_findings = [f for f in verification.verify_document(order_doc).findings
                      if f.rule_id == "ORDER-001"]
    assert order_findings, "镜头回跳到更早的原文必须被点出来"
    assert all(f.severity == "medium" for f in order_findings), \
        "闪回是正当手法，只提醒不拦截"
    assert "回跳" in order_findings[0].message and order_findings[0].actual
    print("口径一致: 覆盖率三方同结果（3 份归档 × 2 种旁白模式）/ 倒叙镜头被点名 ✓")

    # ---- 21. verify 子命令：对已落盘的产物重新独立验证 + 契约漂移 ----
    # 清单一直在记输入哈希、提示词/schema 哈希、产物哈希，但在此之前没有任何东西
    # 读它。提示词改过一版之后回头编辑或渲染旧产物，是在静默混用两套契约。
    import contextlib
    import io
    from pipeline.__main__ import main as cli_main
    from pipeline.manifest import file_sha256, sha256_json

    def run_cli(*argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli_main(list(argv))
        return code, buf.getvalue()

    yao_doc = json.loads((YAO / "output_merged.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as td:
        # 裸 IR：能验，但要如实说明没有清单可比对
        bare = Path(td) / "bare.json"
        bare.write_text(json.dumps(yao_doc, ensure_ascii=False), encoding="utf-8")
        code, out = run_cli("verify", str(bare))
        assert code == 0 and "PASS" in out
        assert "DRIFT 未知" in out, "没有清单时不能假装校对过契约"

        # 带清单的 run 记录：提示词换过、产物被人改过，两条都要点出来
        record = {
            "id": "r1", "status": "succeeded", "result": yao_doc,
            "manifest": {
                "scope": {"frozen": True, "units": [
                    {k: u.get(k) for k in ("id", "text", "para")}
                    for u in yao_doc["source"]["units"]]},
                "contracts": {
                    "prompt_sha256": "0" * 64,      # 冒充「当时用的是另一版提示词」
                    "schema_sha256": file_sha256(
                        ROOT / "schema" / "storyboard.schema.json"),
                },
                "artifact_sha256": "1" * 64,        # 冒充「转换之后被人工编辑过」
            },
        }
        rec_path = Path(td) / "run.json"
        rec_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        code, out = run_cli("verify", str(rec_path))
        assert code == 0, "契约漂移只是警告，不改变验证结论"
        assert "novel_to_storyboard.md 已与生成这份产物时不同" in out
        assert "产物指纹与清单不符" in out
        assert "storyboard.schema.json" not in out, "没漂移的契约不该报"

        # 冻结证据被改：exit 非 0，并逐字段点名
        record["manifest"]["artifact_sha256"] = sha256_json(yao_doc)
        record["result"] = json.loads(json.dumps(yao_doc))
        record["result"]["source"]["units"][0]["text"] += "（篡改）"
        rec_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        code, out = run_cli("verify", str(rec_path))
        assert code == 1, "冻结证据被改必须以非零退出，好让 CI 拦得住"
        assert "SOURCE-FROZEN-002" in out and "u0001" in out

        # 带 --source 复验：convert 入口会剔除零宽字符，产物里的句单元是清洗后的；
        # 拿未清洗的原文去比会误报 FID-SOURCE-001。产物本身不含零宽字符时，
        # 原文按同一口径清洗后再比；产物保留了零宽字符（归档即如此）就按原样比
        import re as _re
        raw_source = YAO / "input_full.txt"
        assert _re.search("[\u200b\ufeff\u2060]", raw_source.read_text(encoding="utf-8")), \
            "原文里要真有零宽字符，否则这项测不到"
        cleaned = json.loads(_re.sub("[\u200b\ufeff\u2060]", "",
                                     json.dumps(yao_doc, ensure_ascii=False)))
        clean_path = Path(td) / "clean.json"
        clean_path.write_text(json.dumps(cleaned, ensure_ascii=False), encoding="utf-8")
        code, out = run_cli("verify", str(clean_path), "--source", str(raw_source))
        assert code == 0 and "FID-SOURCE-001" not in out, \
            f"清洗后的产物对未清洗原文不该误报：{out[-300:]}"
        assert "零宽字符" in out, "按清洗口径比对时要说一声"
        code, out = run_cli("verify", str(bare), "--source", str(raw_source))
        assert code == 0 and "FID-SOURCE-001" not in out, "保留零宽字符的归档按原样比对"
        assert "零宽字符" not in out
        # 产物被真改过时仍要拦住：清洗口径不能变成放水
        tampered = json.loads(json.dumps(cleaned))
        tampered["source"]["units"][-1]["text"] += "多"
        clean_path.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")
        code, out = run_cli("verify", str(clean_path), "--source", str(raw_source))
        assert code == 1 and "FID-SOURCE-001" in out

        # 不是 IR 也不是 run 记录：单独的退出码，别和验证不通过混为一谈
        junk = Path(td) / "junk.json"
        junk.write_text('{"hello": 1}', encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert cli_main(["verify", str(junk)]) == 2
    print("verify 子命令: 裸 IR 如实说明 / 提示词与产物指纹漂移点名 / 篡改非零退出 / 零宽字符口径一致 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
