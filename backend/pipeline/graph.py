"""单批转换的状态图：生成 → 校验 →（修复）→ 重试/择优降级。

对应改造前 convert.py 里 _convert_batch 的 for 循环。校验节点不调 LLM，
它只是把现有的确定性审查链路（verification / validate / quality / review）
原样串起来。
"""
import json
from pathlib import Path
from typing import Annotated, Any, List, Optional, TypedDict

from langchain_core.messages import (AIMessage, AnyMessage, HumanMessage,
                                     RemoveMessage, SystemMessage, ToolMessage)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import REMOVE_ALL_MESSAGES, add_messages
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolInvocationError

from . import novel_memory, quality, repair, review, validate, verification
from .chat import check_truncation, extract_json, is_truncated
from .config import Settings
from .errors import ConversionError
from .events import make_say
from .prompt import load_system_prompt
from server.messages import REPORT_MAX, msg, vendor
from .tools import REPAIR_TOOLS

_REPORT_LOG_LINES = 60
_DOC_WRITERS = {"json_patch", "task_done"}
_MAX_TOOL_STEPS = 8          # 与改造前 `for _ in range(8)` 等价


class BatchState(TypedDict):
    """单批转换的状态。

    messages 用 add_messages reducer 累加；其余字段由节点整体覆写。
    每批一个实例，批号/原文/冻结句单元都在这里，而 settings / workdir /
    attempt_records 这些跨批不变的东西由 build_batch_graph 闭包持有。
    """
    messages: Annotated[List[AnyMessage], add_messages]
    user: str
    batch_text: str
    idx: int
    frozen_units: Optional[list]
    attempt: int
    mode: str                 # "generate" | "patch"
    doc: Optional[dict]
    report: str
    structured: Any
    candidates: list
    tool_steps: int
    used_tools: List[str]     # 本次尝试用过的工具名，写进 attempt_records 供审计
    repair_failed: bool       # 本轮补丁修复没产出新底稿（超步数 / 没发起工具调用）
    patch_applied: bool
    task_done: bool
    usage_mark: Optional[dict]
    result: Optional[dict]
    warnings: List[dict]      # 降级交付的质量警告（job.quality.degraded 消息对象）


def _log_report(log, report: str, workdir: Path, idx: int, attempt: int) -> None:
    """把校验/质量门的失败原因逐行打进日志。

    用户看不到工作目录，光说"未通过"等于没说；报告可能很长，
    截断后指向落盘的完整报告，不让日志被单个批次淹掉。
    """
    lines = report.strip().splitlines()
    if not lines:
        log("  （校验器未给出细节）")
        return
    for line in lines[:_REPORT_LOG_LINES]:
        log(f"  {line}")
    if len(lines) > _REPORT_LOG_LINES:
        path = workdir / f"batch{idx}_attempt{attempt}_report.txt"
        try:
            path.write_text(report + "\n", encoding="utf-8")
            log(f"  …还有 {len(lines) - _REPORT_LOG_LINES} 行，完整报告见 {path}")
        except OSError:
            log(f"  …还有 {len(lines) - _REPORT_LOG_LINES} 行未显示")


def _check_batch(doc: dict, batch_text: str, settings: Settings,
                 workdir: Path, idx: int, attempt: int,
                 review_chat, log, frozen_units=None):
    """结构校验 → 质量门 → 可选评审。返回 (是否通过, 硬失败?, 报告, 择优键, 结构化报告)。

    从 convert.py 原样搬来，逻辑未改：硬失败（schema/lint/保真不过）的产物合同
    已破坏，不可交付；软失败（密度门/评审分不过）的产物合法可用，仅质量不达标，
    择优键（越大越接近达标）供重试耗尽后降级交付时挑最优一版。
    """
    # coverage 是后处理结果，不信任模型声明。先计算再覆写，然后从干净状态复验。
    probe = verification.verify_document(
        doc, frozen_units=frozen_units, original_text=batch_text)
    verification.recompute_coverage_field(doc, probe.coverage)
    structured = verification.verify_document(
        doc, frozen_units=frozen_units, original_text=batch_text)

    tmp = workdir / f"batch{idx}_attempt{attempt}.json"
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    if not structured.ok:
        return False, True, structured.render(), None, structured
    lint_ok, lint_out = validate.run_lint(tmp)
    fid_ok, fid_out = validate.run_fidelity(tmp, batch_text, workdir)
    if not (lint_ok and fid_ok):
        return (False, True, lint_out.strip() + "\n" + fid_out.strip(), None,
                structured)

    gate_ok, gate_report, ratio = quality.narration_density_gate(
        doc, settings.narration_density_max)
    if not gate_ok:
        return False, False, gate_report, (1, -ratio), structured

    # 时长必须够念完旁白与台词，否则成片时要么截断语音、要么被迫拉长镜头，
    # 按名义时长做的预算当场失准。排在密度门之后择优（它已多过一道门）。
    fit_ok, fit_report, over = quality.speech_fit_gate(
        doc, settings.speech_overflow_max, settings.speech_cps)
    if not fit_ok:
        return False, False, fit_report, (2, -over), structured

    if settings.review_enabled and review_chat is not None:
        rev_ok, rev_report, overall = review.run_review(
            review_chat, batch_text, doc, settings.review_min_score,
            settings.review_dimension_min, settings.semantic_fidelity_min)
        if rev_ok is None:
            log(f"批 {idx} {rev_report}")
            return False, False, rev_report, (3, -1.0), structured
        else:
            log(rev_report.splitlines()[0])
            if not rev_ok:
                # 评审失败排在前两道门之后择优（它已多过两道门）
                return False, False, rev_report, (3, overall), structured
    return True, False, structured.render(), None, structured


def build_batch_graph(*, chat, review_chat, settings: Settings, params,
                      workdir: Path, attempt_records: list, log=print,
                      progress=None, negative_terms=(), on_event=None):
    """编译单批状态图。跨批不变的依赖由闭包持有，不进状态。

    progress(phase, attempt) 在每个节点开工时被调用，供界面显示「第几次尝试、
    在干什么」。phase ∈ generating / regenerating / checking / repairing。
    on_event(消息对象) 收给用户看的进度事件（pipeline/events.py）；细节仍直接 log。
    """
    say = make_say(log, on_event)
    def emit(phase: str, attempt: int) -> None:
        if progress is not None:
            progress(phase, attempt)

    # 22KB 系统提示词每次调用都发（整份生成与补丁修复都带，改造前即如此），
    # 缓存标记丢了等于每次多付一次全价
    system_msg = SystemMessage(content=[{
        "type": "text", "text": load_system_prompt(),
        "cache_control": {"type": "ephemeral"}}])

    def _record(state: BatchState, status: str, structured=None,
                report: str = "") -> None:
        after = chat.usage_totals()
        before = state.get("usage_mark") or {}
        usage = {k: after[k] - before.get(k, 0) for k in after}
        rec = {"batch": state["idx"], "attempt": state["attempt"],
               "mode": state["mode"], "status": status,
               "report": report, "tools": list(state.get("used_tools") or []),
               "usage": usage}
        if structured is not None:
            rec["verification"] = structured.to_dict()
        attempt_records.append(rec)

    def generate(state: BatchState) -> dict:
        """整份输出：文本 JSON 协议 + 容错解析。"""
        emit("generating" if state["attempt"] == 0 else "regenerating",
             state["attempt"] + 1)
        mark = chat.usage_totals()
        msg = chat.invoke([system_msg] + list(state["messages"]))
        # 截断时 chat.text 抛 LLMError，让它直接冒出去——那是配置问题，重试解决不了
        raw = chat.text(msg)
        try:
            doc = extract_json(raw)
        except ValueError as e:
            return {"messages": [msg], "doc": None, "usage_mark": mark,
                    "report": f"输出无法解析为 JSON：{e}"}
        return {"messages": [msg], "doc": doc, "usage_mark": mark, "report": ""}

    def check(state: BatchState) -> dict:
        """确定性审查。本节点不调 LLM（评审阶段除外，由 settings 显式开启）。"""
        attempt = state["attempt"] + 1
        idx = state["idx"]
        emit("checking", attempt)
        if state["repair_failed"]:
            # 这一轮补丁修复没产出新底稿。底稿与结构化报告原样保留：
            # 下一次尝试仍从同一份底稿打补丁，与改造前一致
            report = state["report"]
            say("job.event.repair_failed", batch=idx, attempt=attempt)
            log(f"  {report}")
            _record({**state, "attempt": attempt}, "unparseable", report=report)
            return {"attempt": attempt, "report": report, "doc": state["doc"],
                    "used_tools": []}
        if state["doc"] is None:
            report = state["report"] or "输出无法解析为 JSON"
            say("job.event.unparseable", batch=idx, attempt=attempt)
            log(f"  {report}")
            _record({**state, "attempt": attempt}, "unparseable", report=report)
            # 没有可打补丁的底稿，下一轮只能整份重写
            return {"attempt": attempt, "mode": "generate", "report": report,
                    "doc": None, "used_tools": []}

        doc = state["doc"]
        quality.apply_meta_overrides(doc, params)
        # 小说创作限制的负面提示词与制作参数同性质：程序确定性写入，不靠模型记得
        novel_memory.merge_negative_prompt(doc, list(negative_terms))
        # 程序算得对的呈现层字段直接改，不为它们花一轮修复
        fixed = quality.normalize_curve_refs(doc)
        if fixed:
            say("job.event.fixed_curve", batch=idx, n=fixed)
        slips = quality.fix_known_slips(doc)
        if slips:
            say("job.event.fixed_slips", batch=idx, n=slips)
        if settings.auto_prune_narration:
            # 先裁旁白再拉时长：旁白变短，镜头就不必拉那么长
            pruned = quality.prune_narration(doc, settings.narration_density_max)
            if pruned:
                say("job.event.pruned", batch=idx, max=f"{settings.narration_density_max:.0%}", n=pruned)
        if settings.auto_fit_duration:
            fitted = quality.fit_durations(doc, settings.speech_cps)
            if fitted:
                say("job.event.fitted", batch=idx, n=fitted, cap=f"{quality.MAX_SHOT_SECONDS:g}")
        ok, hard, report, key, structured = _check_batch(
            doc, state["batch_text"], settings, workdir, idx, attempt,
            review_chat, log, state["frozen_units"])
        _record({**state, "attempt": attempt},
                "passed" if ok else ("hard_failed" if hard else "soft_failed"),
                structured=structured, report=report)
        if ok:
            say("job.event.passed", batch=idx, attempt=attempt)
            return {"attempt": attempt, "report": report, "doc": doc,
                    "structured": structured, "result": doc, "used_tools": []}
        candidates = list(state["candidates"])
        if not hard:
            candidates.append((key, attempt, doc, report))
        say("job.event.check_failed" if hard else "job.event.gate_failed", batch=idx, attempt=attempt)
        log("  原因如下：")
        _log_report(log, report, workdir, idx, attempt)
        return {"attempt": attempt, "report": report, "doc": doc,
                "structured": structured, "candidates": candidates,
                "used_tools": []}

    def finalize(state: BatchState) -> dict:
        """重试耗尽：有合法候选就择优降级交付，否则落盘报告并抛错。"""
        idx = state["idx"]
        if state["candidates"] and not settings.strict:
            key, best_attempt, doc, report = max(state["candidates"],
                                                 key=lambda c: c[0])
            say("job.event.degraded", batch=idx, attempt=best_attempt)
            log("  （产物结构合法、逐字保真；--strict 可改为直接失败）")
            warning = msg("job.quality.degraded", batch=idx, retries=settings.max_retries,
                          attempt=best_attempt, candidates=len(state["candidates"]),
                          report=vendor(report, limit=REPORT_MAX))
            return {"result": doc, "warnings": [warning]}
        (workdir / f"batch{idx}_failure_report.txt").write_text(
            state["report"] + "\n", encoding="utf-8")
        log(f"批 {idx} 已通过批次与失败报告保留在 {workdir}")
        raise ConversionError.of("job.batch_failed", state["report"],
                                 batch=idx, retries=settings.max_retries)

    def route_after_check(state: BatchState) -> str:
        if state["result"] is not None:
            return END
        if state["attempt"] > settings.max_retries:
            return "finalize"
        return "plan_repair"

    def plan_repair(state: BatchState) -> dict:
        """新一次尝试的起点：按 repair_mode 拼消息。有底稿就打补丁，否则整份重写。"""
        idx, attempt = state["idx"], state["attempt"]
        # 每次尝试都从这里开始：token 计数起点、工具步数与各类标记在此一并重置，
        # 否则上一次尝试的 token 会串进这一次的账里
        reset = {"tool_steps": 0, "patch_applied": False, "task_done": False,
                 "repair_failed": False, "used_tools": [],
                 "usage_mark": chat.usage_totals()}
        if state["doc"] is not None and settings.repair_mode == "patch":
            say("job.event.repair_patch", batch=idx, n=attempt + 1, total=settings.max_retries + 1)
            return {**reset, "mode": "patch", "messages": [
                # 每轮补丁修复都从干净的三条消息开始，与改造前逐字一致。
                # add_messages 默认是追加，要清空历史得先发一条 REMOVE_ALL_MESSAGES
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                HumanMessage(state["user"]),
                AIMessage(content=json.dumps(state["doc"], ensure_ascii=False)),
                HumanMessage(repair.repair_request(state["structured"],
                                                   state["report"])),
            ]}
        # rewrite 模式，或从未解析出过 JSON（没有可打补丁的底稿）。这条路上历史里
        # 只有整份生成的往返、不含工具调用，直接追加回喂即可
        say("job.event.repair_rewrite", batch=idx, n=attempt + 1, total=settings.max_retries + 1)
        return {**reset, "mode": "generate", "messages": [HumanMessage(
            "你的输出未通过自动校验，报告如下：\n\n" + state["report"] +
            "\n\n请修正全部问题后重新输出完整 JSON"
            "（只输出一个 JSON 对象，不要解释文字，不要代码块标记）。")]}

    def repair_agent(state: BatchState) -> dict:
        """修复代理：带工具调模型。每轮算一个工具步骤，上限与改造前一致。"""
        steps = state["tool_steps"] + 1
        emit("repairing", state["attempt"] + 1)
        if steps > _MAX_TOOL_STEPS:
            report = f"修复工具调用无效：单轮修复超过 {_MAX_TOOL_STEPS} 个工具步骤"
            log(f"批 {state['idx']} {report}")
            return {"repair_failed": True, "report": report, "tool_steps": steps}
        # 修复阶段同样带系统提示词——模型得知道分镜规则才补得对
        msg = chat.invoke([system_msg] + list(state["messages"]),
                          tools=REPAIR_TOOLS, max_tokens=settings.repair_max_tokens)
        calls = list(msg.tool_calls)
        invalid = list(msg.invalid_tool_calls or [])
        # 先做截断诊断再用 tool_calls：被截断的工具参数会被 parse_partial_json
        # 补成「合法」值。补丁截断是补丁太大，打回要求拆小（不应用、不整批报错）
        if is_truncated(msg) and (calls or invalid):
            log(f"批 {state['idx']} 补丁输出撞上 {settings.repair_max_tokens} token"
                "上限被截断，未应用，要求拆小重交")
            return {"messages": [msg] + [ToolMessage(
                content=(f"输出在 {settings.repair_max_tokens} token 上限处被截断，本步未执行："
                         "补丁过大。只改报告点名的字段，不要整段替换 shots，"
                         "拆成更小的补丁重新提交"),
                tool_call_id=c["id"], name=c["name"], status="error")
                for c in calls + invalid],
                "tool_steps": steps,
                "used_tools": list(state["used_tools"]) + [c["name"] for c in calls]}
        # 没有工具调用的截断（推理块烧光预算等）照旧按原因报错
        check_truncation(msg, settings)
        if not calls and not invalid:
            report = "修复工具调用无效：模型没有发起任何工具调用"
            log(f"批 {state['idx']} {report}")
            return {"messages": [msg], "repair_failed": True, "report": report,
                    "tool_steps": steps}
        used = list(state["used_tools"]) + [c["name"] for c in calls]
        writers = [c for c in calls if c["name"] in _DOC_WRITERS]
        if invalid:
            # 参数 JSON 解析失败的调用：ToolNode 看不见它们，但每个 tool_use
            # 仍必须有 tool_result。整步作废，让模型重新提交
            return {"messages": [msg] + [ToolMessage(
                content="工具调用参数不是合法 JSON，本步未执行，请重新提交",
                tool_call_id=c["id"], name=c["name"], status="error")
                for c in calls + invalid],
                "tool_steps": steps, "used_tools": used}
        if len(writers) > 1:
            # 同一步里两个写 doc 的 Command 会让 LangGraph 抛 InvalidUpdateError。
            # 不进 ToolNode；每个 tool_use 都必须有 tool_result，否则下一次请求非法
            return {"messages": [msg] + [ToolMessage(
                content="一次只能提交一个 json_patch / task_done，请只提交一个补丁",
                tool_call_id=c["id"], name=c["name"], status="error")
                for c in calls],
                "tool_steps": steps, "used_tools": used}
        return {"messages": [msg], "tool_steps": steps, "used_tools": used}

    def route_after_repair(state: BatchState) -> str:
        if state["repair_failed"]:
            return "check"
        # 末尾已是 ToolMessage：并行写 doc 被拦下，错误已就位，直接回模型
        if isinstance(state["messages"][-1], ToolMessage):
            return "repair_agent"
        return "tools"

    def route_after_tools(state: BatchState) -> str:
        # json_patch / task_done 用 Command 置了标记，说明这一轮修复产出了新底稿
        if state["patch_applied"] or state["task_done"]:
            return "check"
        return "repair_agent"

    builder = StateGraph(BatchState)
    builder.add_node("generate", generate)
    builder.add_node("check", check)
    builder.add_node("plan_repair", plan_repair)
    builder.add_node("repair_agent", repair_agent)
    builder.add_node("tools", ToolNode(
        REPAIR_TOOLS,
        # 补丁违规（锁定前缀、路径不存在）与参数不合 schema 都回给模型当 status=error
        # 的 ToolMessage，让它在同一轮里看着报错改正（仍受单轮 8 步上限约束）；
        # 其余异常是程序 bug，照常冒出去。不能只写 (RepairError,)：那会覆盖掉默认
        # 处理器，模型把 patch 传成字符串时就会以 ToolInvocationError 崩图
        handle_tool_errors=(repair.RepairError, ToolInvocationError)))
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "generate")
    builder.add_edge("generate", "check")
    builder.add_conditional_edges("check", route_after_check,
                                  {END: END, "finalize": "finalize",
                                   "plan_repair": "plan_repair"})
    builder.add_conditional_edges(
        "plan_repair",
        lambda s: "repair_agent" if s["mode"] == "patch" else "generate",
        {"repair_agent": "repair_agent", "generate": "generate"})
    builder.add_conditional_edges("repair_agent", route_after_repair,
                                  {"tools": "tools", "check": "check",
                                   "repair_agent": "repair_agent"})
    builder.add_conditional_edges("tools", route_after_tools,
                                  {"check": "check", "repair_agent": "repair_agent"})
    builder.add_edge("finalize", END)
    # 每次补丁尝试约 2*_MAX_TOOL_STEPS+4 个超步，再加首次生成与收尾，留足余量
    limit = (settings.max_retries + 1) * (2 * _MAX_TOOL_STEPS + 6) + 10
    return builder.compile().with_config(recursion_limit=limit)


def run_batch(graph, *, user: str, batch_text: str, idx: int,
              frozen_units=None):
    """跑一批，返回 (产物, 质量警告列表)。警告是 job.quality.degraded 消息对象，非空即降级交付。"""
    state: BatchState = {
        "messages": [HumanMessage(user)], "user": user,
        "batch_text": batch_text, "idx": idx, "frozen_units": frozen_units,
        "attempt": 0, "mode": "generate", "doc": None, "report": "",
        "structured": verification.VerificationReport(), "candidates": [],
        "tool_steps": 0,
        "used_tools": [], "repair_failed": False,
        "patch_applied": False, "task_done": False,
        "usage_mark": None, "result": None, "warnings": [],
    }
    final = graph.invoke(state)
    return final["result"], final["warnings"]
