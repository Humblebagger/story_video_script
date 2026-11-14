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
    # 校验节点会把念不完旁白的镜头时长自动拉长（quality.fit_durations），
    # 归档产物里本就有这类镜头，所以「与归档一致」比的是拉长后的归档
    from pipeline.quality import fit_durations
    expected = json.loads(archived)
    assert fit_durations(expected) > 0, "归档里应有念不完的镜头，否则这条规则没测到"

    # 1. 一次就过：图跑完，result 是产物，没有降级警告
    with tempfile.TemporaryDirectory() as d:
        records = []
        logs = []
        events = []
        chat = ChatInvoker(settings, chat=FakeChat(responses=[archived]),
                           log=logs.append)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=settings,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs.append,
                                  on_event=events.append)
        doc, warnings = run_batch(graph, user="【小说原文】" + batch,
                                  batch_text=batch, idx=1, frozen_units=None)
        assert doc == expected, "一次就过时产物应与归档一致"
        # 归档里有念不完的镜头，校验节点先拉长再通过
        assert [e["code"] for e in events] == ["job.event.fitted", "job.event.passed"]
        assert events[-1]["code"] == "job.event.passed"
        assert events[-1]["params"] == {"batch": 1, "attempt": 1}
        assert warnings == []
        assert [r["status"] for r in records] == ["passed"]
        assert records[0]["mode"] == "generate" and records[0]["attempt"] == 1
        assert records[0]["usage"]["output"] > 0, "token 要归到这次尝试上"
        print("graph: 一次就过 → result + attempt_records ✓")

    # 2. 首次输出不是 JSON：记 unparseable，重试一次后通过
    with tempfile.TemporaryDirectory() as d:
        records = []
        logs = []
        events = []
        s2 = Settings(api_key="k", max_retries=1, normalize_input=False,
                      freeze_source_units=False, repair_mode="rewrite")
        chat = ChatInvoker(s2, chat=FakeChat(responses=["我不输出 JSON", archived]),
                           log=logs.append)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=s2,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs.append,
                                  on_event=events.append)
        doc, warnings = run_batch(graph, user="【小说原文】" + batch,
                                  batch_text=batch, idx=1, frozen_units=None)
        assert doc == expected
        assert [e["code"] for e in events] == [
            "job.event.unparseable", "job.event.repair_rewrite", "job.event.fitted", "job.event.passed"], [e["code"] for e in events]
        assert [r["status"] for r in records] == ["unparseable", "passed"]
        print("graph: 不可解析 → 重试 → 通过 ✓")

    # 3. 重试耗尽且无合法候选：抛 ConversionError，失败报告落盘
    with tempfile.TemporaryDirectory() as d:
        records = []
        logs3 = []
        chat = ChatInvoker(settings, chat=FakeChat(responses=["坏输出"]),
                           log=lambda _: None)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=settings,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs3.append)
        try:
            run_batch(graph, user="u", batch_text=batch, idx=7, frozen_units=None)
            raise AssertionError("重试耗尽应抛 ConversionError")
        except ConversionError as e:
            assert e.code == "job.batch_failed" and e.params == {"batch": 7, "retries": settings.max_retries}
            assert isinstance(e.lines, list), "ConversionError 带逐条消息（spec 子计划 5 C）"
            assert e.report and d not in str(e) and "保留在" not in str(e), "工作目录只进调试日志"
            assert (Path(d) / "batch7_failure_report.txt").exists()
        assert any(d in line for line in logs3), "工作目录仍在调试日志里"
        print("graph: 重试耗尽 → ConversionError + 报告落盘 ✓")

    e = ConversionError.of("job.merge_failed", "原文", [{"code": "common.unknown", "params": {"message": "x"}}])
    assert e.report == "原文" and e.lines == [{"code": "common.unknown", "params": {"message": "x"}}] and e.code == "job.merge_failed"
    assert ConversionError("无代码").lines == []

    # 3b. 软质量门耗尽降级：评审原文里的密钥不进警告对象、事件与调试日志
    import os
    import pipeline.graph as graph_mod
    from pipeline import verification
    secret = "sk-synthetic-secret-0123456789"
    bearer = "Bearer abcDEF123token456"
    os.environ["ANTHROPIC_API_KEY"] = secret
    orig_check = graph_mod._check_batch
    graph_mod._check_batch = lambda *a, **kw: (
        False, False, f"评审意见：请核对。key={secret} Authorization: {bearer}", (0,),
        verification.VerificationReport())
    try:
        with tempfile.TemporaryDirectory() as d:
            logs3b, events3b, records = [], [], []
            chat = ChatInvoker(settings, chat=FakeChat(responses=[archived]), log=logs3b.append)
            graph = build_batch_graph(chat=chat, review_chat=chat, settings=settings,
                                      params=params, workdir=Path(d), attempt_records=records,
                                      log=logs3b.append, on_event=events3b.append)
            _, warns = run_batch(graph, user="u", batch_text=batch, idx=1, frozen_units=None)
            assert len(warns) == 1 and warns[0]["code"] == "job.quality.degraded"
            blob = json.dumps(warns[0], ensure_ascii=False) + json.dumps(events3b, ensure_ascii=False) \
                + "\n".join(logs3b)
            assert secret not in blob and "abcDEF123token456" not in blob, "密钥不得进警告、事件与日志"
            assert "评审意见" in warns[0]["params"]["report"]["text"]
            rblob = json.dumps(records, ensure_ascii=False)
            assert secret not in rblob and "abcDEF123token456" not in rblob, "密钥不得进尝试记录（清单）"
            assert records and "评审意见" in rblob
    finally:
        graph_mod._check_batch = orig_check
        os.environ.pop("ANTHROPIC_API_KEY", None)
    print("graph: 降级警告与调试日志脱敏 ✓")

    # ---- 修复循环 ----
    from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
    from pipeline.graph import _check_batch

    bad = json.loads(archived)
    # 删掉必填字段才是硬失败（SCHEMA-001）；置空串会全部通过——已实测
    bad["episodes"][0]["shots"][0].pop("action")
    good_action = json.loads(archived)["episodes"][0]["shots"][0]["action"]
    user_msg = "【小说原文】" + batch

    # 先验证这个造假产物真的硬失败——否则后面的用例都是空跑，测不到修复路径
    with tempfile.TemporaryDirectory() as d:
        ok, hard, rep_text, _, _ = _check_batch(
            json.loads(json.dumps(bad)), batch, settings, Path(d), 99, 1,
            None, lambda _: None, None)
        assert not ok and hard, f"造假产物没有硬失败：{rep_text[:200]}"

    def add_action(call_id):
        """修复补丁：字段已被删，所以用 add 而不是 replace（replace 要求目标已存在）。"""
        return AIMessage(content="", tool_calls=[
            {"name": "json_patch", "id": call_id, "args": {"patch": [
                {"op": "add", "path": "/episodes/0/shots/0/action",
                 "value": good_action}]}}])

    def look(call_id):
        """修复轮里先查校验条目。每次都要新建对象：add_messages 按 id 去重，
        同一个消息对象再返回一次会被当成「更新」而不是追加。"""
        return AIMessage(content="", tool_calls=[
            {"name": "validation_list", "args": {}, "id": call_id}])

    def patch_settings(max_retries):
        return Settings(api_key="k", max_retries=max_retries, normalize_input=False,
                        freeze_source_units=False, repair_mode="patch")

    # 4. 硬失败 → 受限补丁修复 → 通过
    with tempfile.TemporaryDirectory() as d:
        records, logs = [], []
        s4 = patch_settings(1)
        fake = FakeChat(responses=[json.dumps(bad, ensure_ascii=False),
                                   look("c1"), add_action("c2")])
        chat = ChatInvoker(s4, chat=fake, log=logs.append)
        phases = []
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=s4,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs.append,
                                  progress=lambda ph, a: phases.append((ph, a)))
        doc, warnings = run_batch(graph, user=user_msg, batch_text=batch,
                                  idx=1, frozen_units=None)
        assert doc == expected, "打完补丁应与归档一致"
        assert [r["status"] for r in records] == ["hard_failed", "passed"]
        # 进度回调：界面靠它显示「第几次尝试、在干什么」
        assert phases == [("generating", 1), ("checking", 1),
                          ("repairing", 2), ("repairing", 2), ("checking", 2)], phases
        assert records[1]["mode"] == "patch"
        assert records[1]["tools"] == ["validation_list", "json_patch"], \
            "用过哪些工具要进清单，不然修复过程没法审计"
        assert any("受限 JSON Patch 修复" in line for line in logs)
        # token 按尝试归账：生成 1 次调用，修复轮 2 次调用，互不串账
        assert records[0]["usage"]["calls"] == 1
        assert records[1]["usage"]["calls"] == 2, "上一次尝试的 token 串进了这一次"
        # 补丁轮带系统提示词，且历史从干净的三条消息开始
        first_repair = fake.requests[1]["messages"]
        assert isinstance(first_repair[0], SystemMessage), "修复阶段丢了系统提示词"
        assert [type(m).__name__ for m in first_repair[1:]] == [
            "HumanMessage", "AIMessage", "HumanMessage"], \
            "补丁轮的历史没清空，上一轮的整份原始输出被带了进来"
        assert first_repair[1].content == user_msg
        # 生成请求与修复请求都要带 system prompt 的缓存标记，否则每次多付全价
        for i in (0, 1, 2):
            sys_blocks = fake.requests[i]["messages"][0].content
            assert sys_blocks[0]["cache_control"] == {"type": "ephemeral"}, \
                f"第 {i + 1} 次请求的 system prompt 丢了 cache_control"
        print("graph: 硬失败 → 补丁修复 → 通过；工具轨迹入清单、token 不串账、"
              "历史从零开始 ✓")

    # 5. 工具步数超上限：记为失败，不让单轮修复无限打转
    with tempfile.TemporaryDirectory() as d:
        records, logs = [], []
        s5 = patch_settings(1)
        fake5 = FakeChat(responses=[json.dumps(bad, ensure_ascii=False)]
                         + [look(f"s{i}") for i in range(8)])
        chat = ChatInvoker(s5, chat=fake5, log=logs.append)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=s5,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs.append)
        try:
            run_batch(graph, user=user_msg, batch_text=batch, idx=2,
                      frozen_units=None)
            raise AssertionError("重试耗尽且无合法候选应抛 ConversionError")
        except ConversionError:
            pass
        assert [r["status"] for r in records] == ["hard_failed", "unparseable"]
        assert "8 个工具步骤" in records[1]["report"], \
            "超过 8 步要明说，与改造前 for _ in range(8) 等价"
        assert len(fake5.requests) == 1 + 8, "单轮修复最多调模型 8 次"
        print("graph: 单轮修复超 8 步即中断 ✓")

    # 6. 补丁违规不崩图：错误以 ToolMessage 回给模型，模型看着报错改正后通过
    with tempfile.TemporaryDirectory() as d:
        records, logs = [], []
        s6 = patch_settings(1)
        fake6 = FakeChat(responses=[
            json.dumps(bad, ensure_ascii=False),
            # 第一次补丁碰锁定前缀 /meta
            AIMessage(content="", tool_calls=[
                {"name": "json_patch", "id": "c1", "args": {"patch": [
                    {"op": "replace", "path": "/meta/title", "value": "篡改"}]}}]),
            add_action("c2"),
        ])
        chat = ChatInvoker(s6, chat=fake6, log=logs.append)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=s6,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs.append)
        doc, warnings = run_batch(graph, user=user_msg, batch_text=batch,
                                  idx=1, frozen_units=None)
        assert doc == expected
        assert [r["status"] for r in records] == ["hard_failed", "passed"]
        assert records[1]["tools"] == ["json_patch", "json_patch"]
        # 第 3 次模型请求（下标 2）里必须带着那条报错——模型是看着它改正的
        errs = [m for m in fake6.requests[2]["messages"]
                if isinstance(m, ToolMessage) and m.status == "error"]
        assert errs and "锁定" in errs[0].content, "违规补丁的报错要回给模型"
        print("graph: 违规补丁不崩图，报错回给模型后改正通过 ✓")

    # 7. 一轮补丁失败（超步数）后保留底稿，下一次尝试再补一次，而不是退化成整份重写
    with tempfile.TemporaryDirectory() as d:
        records, logs = [], []
        s7 = patch_settings(2)
        fake7 = FakeChat(responses=[json.dumps(bad, ensure_ascii=False)]
                         + [look(f"s{i}") for i in range(8)]
                         + [add_action("p1")])
        chat = ChatInvoker(s7, chat=fake7, log=logs.append)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=s7,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs.append)
        doc, warnings = run_batch(graph, user=user_msg, batch_text=batch,
                                  idx=1, frozen_units=None)
        assert doc == expected
        assert [(r["mode"], r["status"]) for r in records] == [
            ("generate", "hard_failed"), ("patch", "unparseable"),
            ("patch", "passed")], \
            "补丁轮失败后应保留底稿再补一次，而不是丢掉底稿整份重写"
        # 第 3 次尝试的修复请求里，模型被告知上一轮工具调用无效
        assert "8 个工具步骤" in fake7.requests[-1]["messages"][-1].content
        print("graph: 补丁轮失败后保留底稿再补一次 ✓")

    # 8. 同一条回复里两个 json_patch：不进 ToolNode（否则并行写 doc 崩图），
    #    每个 tool_use 都补一条错误 ToolMessage，模型改成单个补丁后通过
    with tempfile.TemporaryDirectory() as d:
        records, logs = [], []
        s8 = patch_settings(1)
        two = AIMessage(content="", tool_calls=[
            {"name": "json_patch", "id": "a1", "args": {"patch": [
                {"op": "add", "path": "/episodes/0/shots/0/action",
                 "value": good_action}]}},
            {"name": "json_patch", "id": "a2", "args": {"patch": [
                {"op": "add", "path": "/episodes/0/shots/0/action",
                 "value": good_action}]}}])
        fake8 = FakeChat(responses=[json.dumps(bad, ensure_ascii=False),
                                    two, add_action("a3")])
        chat = ChatInvoker(s8, chat=fake8, log=logs.append)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=s8,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs.append)
        doc, warnings = run_batch(graph, user=user_msg, batch_text=batch,
                                  idx=1, frozen_units=None)
        assert doc == expected
        assert [r["status"] for r in records] == ["hard_failed", "passed"]
        errs = [m for m in fake8.requests[2]["messages"]
                if isinstance(m, ToolMessage)]
        assert sorted(m.tool_call_id for m in errs) == ["a1", "a2"], \
            "每个 tool_use 都得有 tool_result"
        assert all(m.status == "error" and "一次只能提交一个" in m.content
                   for m in errs)
        print("graph: 并行双补丁被拦下，错误回给模型后单补丁通过 ✓")

    # 9. 工具路径绑定时关闭并行工具调用
    tool_reqs = [r for r in fake8.requests if "tool_names" in r["kwargs"]]
    assert tool_reqs and all(r["kwargs"].get("parallel_tool_calls") is False
                             for r in tool_reqs), "工具路径没传 parallel_tool_calls=False"
    assert "tool_names" not in fake8.requests[0]["kwargs"]
    print("graph: 工具路径 parallel_tool_calls=False ✓")

    # 10. 模型没发起任何工具调用：本轮记失败、底稿保留，下一次尝试再补
    with tempfile.TemporaryDirectory() as d:
        records, logs = [], []
        s10 = patch_settings(2)
        fake10 = FakeChat(responses=[json.dumps(bad, ensure_ascii=False),
                                     "我觉得没问题", add_action("n1")])
        chat = ChatInvoker(s10, chat=fake10, log=logs.append)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=s10,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs.append)
        doc, warnings = run_batch(graph, user=user_msg, batch_text=batch,
                                  idx=1, frozen_units=None)
        assert doc == expected
        assert [(r["mode"], r["status"]) for r in records] == [
            ("generate", "hard_failed"), ("patch", "unparseable"),
            ("patch", "passed")]
        assert "没有发起任何工具调用" in records[1]["report"]
        print("graph: 无工具调用 → 保留底稿，下一次再补 ✓")

    # 11. 修复回复撞 max_tokens：补丁参数可能被 parse_partial_json 截成「合法」值，
    #     绝不能应用。补丁截断说明补丁太大：打回要求拆小，同一轮里重交即可，
    #     不整批报错。修复调用要带上独立的输出上限
    from pipeline.chat import LLMError
    with tempfile.TemporaryDirectory() as d:
        records, logs = [], []
        s11 = patch_settings(1)
        trunc = AIMessage(
            content="", tool_calls=[
                {"name": "json_patch", "id": "t1", "args": {"patch": [
                    {"op": "add", "path": "/episodes/0/shots/0/action",
                     "value": good_action[:3]}]}}],
            response_metadata={"stop_reason": "max_tokens"})
        fake11 = FakeChat(responses=[json.dumps(bad, ensure_ascii=False),
                                     trunc, add_action("t2")])
        chat = ChatInvoker(s11, chat=fake11, log=logs.append)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=s11,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs.append)
        doc, warnings = run_batch(graph, user=user_msg, batch_text=batch, idx=1,
                                  frozen_units=None)
        assert doc == expected, "截断的残缺补丁不得被应用；拆小重交后的补丁才算数"
        assert [r["status"] for r in records] == ["hard_failed", "passed"]
        assert len(records) == 2, "截断打回发生在同一轮内，不另起一次尝试"
        errs = [m for m in fake11.requests[2]["messages"]
                if isinstance(m, ToolMessage)]
        assert [m.tool_call_id for m in errs] == ["t1"] and errs[0].status == "error"
        assert "截断" in errs[0].content and "拆成更小的补丁" in errs[0].content
        assert "kwargs" in fake11.requests[1] and \
            fake11.requests[1]["kwargs"].get("max_tokens") == s11.repair_max_tokens, \
            "修复调用要带独立的输出上限"
        assert "max_tokens" not in fake11.requests[0]["kwargs"], \
            "整份生成仍用 settings.max_tokens，不得被修复上限误伤"
        print("graph: 补丁撞 max_tokens → 不应用、打回拆小，同轮重交通过 ✓")

    # 11b. 没有工具调用的截断（推理块烧光预算）仍按原因报错——那是配置问题
    with tempfile.TemporaryDirectory() as d:
        records, logs = [], []
        s11b = patch_settings(1)
        burned = AIMessage(content=[{"type": "thinking", "thinking": "想" * 500}],
                           response_metadata={"stop_reason": "max_tokens"})
        fake11b = FakeChat(responses=[json.dumps(bad, ensure_ascii=False), burned])
        chat = ChatInvoker(s11b, chat=fake11b, log=logs.append)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=s11b,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs.append)
        try:
            run_batch(graph, user=user_msg, batch_text=batch, idx=1, frozen_units=None)
            raise AssertionError("推理块烧光预算应抛 LLMError")
        except LLMError as e:
            assert e.code == "llm.truncated" and "推理块" in e.hint
        print("graph: 修复轮推理块烧光预算 → 仍报补偿 2 的诊断 ✓")

    # 11c. music.curve 镜号写成序号：程序换成镜头 ID，不为它花一轮修复
    with tempfile.TemporaryDirectory() as d:
        records, logs = [], []
        s11c = patch_settings(1)
        numbered = json.loads(archived)
        ep0 = numbered["episodes"][0]
        ids = [sh["id"] for sh in ep0["shots"]]
        curve = ep0["music"]["curve"]
        orig = [(seg["from_shot"], seg["to_shot"]) for seg in curve]
        for seg in curve:
            seg["from_shot"] = ids.index(seg["from_shot"]) + 1
            seg["to_shot"] = str(ids.index(seg["to_shot"]) + 1)
        fake11c = FakeChat(responses=[json.dumps(numbered, ensure_ascii=False)])
        chat = ChatInvoker(s11c, chat=fake11c, log=logs.append)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=s11c,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs.append)
        doc, warnings = run_batch(graph, user=user_msg, batch_text=batch, idx=1,
                                  frozen_units=None)
        assert [r["status"] for r in records] == ["passed"], "首次生成就该通过"
        assert [(seg["from_shot"], seg["to_shot"])
                for seg in doc["episodes"][0]["music"]["curve"]] == orig
        assert any("music.curve" in line for line in logs), "修正要在日志里说一声"
        print("graph: music.curve 序号 → 镜头 ID，首次生成即通过 ✓")

    # 13. 逐句朗读式退化：程序把有画面承载的动作/描写句移出旁白，首次生成即通过，
    #     不为旁白密度花一轮修复
    with tempfile.TemporaryDirectory() as d:
        records, logs = [], []
        # 归档里不少句子是对白/心理，全念动作描写也只到约 54%；阈值压到 40% 才测得到
        s13 = Settings(api_key="k", max_retries=1, normalize_input=False,
                       freeze_source_units=False, repair_mode="patch",
                       narration_density_max=0.4)
        chatty = json.loads(archived)
        units13 = {u["id"]: u for u in chatty["source"]["units"]}
        for sh in chatty["episodes"][0]["shots"]:
            refs = [r for r in sh["source"]["unit_refs"]
                    if units13[r].get("kind") in ("action", "description")]
            if refs and not sh.get("narration"):
                sh["narration"] = {"unit_refs": refs,
                                   "text": "".join(units13[r]["text"] for r in refs)}
        from pipeline.quality import narration_density_gate
        ok13, _, before = narration_density_gate(json.loads(json.dumps(chatty)),
                                                 s13.narration_density_max)
        assert not ok13, f"造出来的产物旁白占比 {before:.0%}，没超阈值就测不到裁剪"
        fake13 = FakeChat(responses=[json.dumps(chatty, ensure_ascii=False)])
        chat = ChatInvoker(s13, chat=fake13, log=logs.append)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=s13,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs.append)
        doc, warnings = run_batch(graph, user=user_msg, batch_text=batch, idx=1,
                                  frozen_units=None)
        assert [r["status"] for r in records] == ["passed"], \
            [r["report"][:200] for r in records]
        ok13, _, after = narration_density_gate(doc, s13.narration_density_max)
        assert ok13 and after <= s13.narration_density_max
        assert any("移出旁白" in line for line in logs)
        print(f"graph: 旁白 {before:.0%} → 程序裁到 {after:.0%}，首次生成即通过 ✓")

    # 12. invalid_tool_calls 与多写工具同样处理：每个 id 都回一条 error ToolMessage
    with tempfile.TemporaryDirectory() as d:
        records, logs = [], []
        s12 = patch_settings(1)
        mixed = AIMessage(
            content="", tool_calls=[
                {"name": "validation_list", "args": {}, "id": "m1"}],
            invalid_tool_calls=[
                {"name": "json_patch", "args": '{"patch": [', "id": "m2",
                 "error": "bad json", "type": "invalid_tool_call"}])
        fake12 = FakeChat(responses=[json.dumps(bad, ensure_ascii=False),
                                     mixed, add_action("m3")])
        chat = ChatInvoker(s12, chat=fake12, log=logs.append)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=s12,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs.append)
        doc, warnings = run_batch(graph, user=user_msg, batch_text=batch,
                                  idx=1, frozen_units=None)
        assert doc == expected
        errs = [m for m in fake12.requests[2]["messages"]
                if isinstance(m, ToolMessage)]
        assert sorted(m.tool_call_id for m in errs) == ["m1", "m2"], \
            "tool_call 与 invalid_tool_call 的每个 id 都得有 tool_result"
        assert all(m.status == "error" for m in errs)
        print("graph: invalid_tool_calls 逐个回 error ToolMessage ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
