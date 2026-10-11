"""单批转换的状态图：生成 → 校验 →（修复）→ 重试/择优降级。

对应改造前 convert.py 里 _convert_batch 的 for 循环。校验节点不调 LLM，
它只是把现有的确定性审查链路（verification / validate / quality / review）
原样串起来。
"""
import json
from pathlib import Path
from typing import Annotated, Any, List, Optional, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from . import quality, repair, review, validate, verification
from .chat import extract_json
from .config import Settings
from .errors import ConversionError
from .prompt import load_system_prompt

_REPORT_LOG_LINES = 60
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
    patch_applied: bool
    task_done: bool
    usage_mark: Optional[dict]
    result: Optional[dict]
    warnings: List[str]


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
                      workdir: Path, attempt_records: list, log=print):
    """编译单批状态图。跨批不变的依赖由闭包持有，不进状态。"""
    system = load_system_prompt()

    def _record(state: BatchState, status: str, used_tools: list,
                structured=None, report: str = "") -> None:
        after = chat.usage_totals()
        before = state.get("usage_mark") or {}
        usage = ({k: after[k] - before.get(k, 0) for k in after}
                 if before else None)
        rec = {"batch": state["idx"], "attempt": state["attempt"],
               "mode": state["mode"], "status": status,
               "report": report, "tools": used_tools, "usage": usage}
        if structured is not None:
            rec["verification"] = structured.to_dict()
        attempt_records.append(rec)

    def generate(state: BatchState) -> dict:
        """整份输出：文本 JSON 协议 + 容错解析。"""
        messages = [SystemMessage(content=[{
            # 22KB 系统提示词每批都发，缓存标记丢了等于每批多付一次全价
            "type": "text", "text": system,
            "cache_control": {"type": "ephemeral"}}])] + list(state["messages"])
        mark = chat.usage_totals()
        msg = chat.invoke(messages)
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
        if state["doc"] is None:
            report = state["report"] or "输出无法解析为 JSON"
            log(f"批 {idx} 第 {attempt} 次生成：{report}")
            _record({**state, "attempt": attempt}, "unparseable", [],
                    report=report)
            # 没有可打补丁的底稿，下一轮只能整份重写
            return {"attempt": attempt, "mode": "generate", "report": report}

        doc = state["doc"]
        quality.apply_meta_overrides(doc, params)
        ok, hard, report, key, structured = _check_batch(
            doc, state["batch_text"], settings, workdir, idx, attempt,
            review_chat, log, state["frozen_units"])
        _record({**state, "attempt": attempt},
                "passed" if ok else ("hard_failed" if hard else "soft_failed"),
                [], structured=structured, report=report)
        if ok:
            log(f"批 {idx} 校验通过（第 {attempt} 次生成）")
            return {"attempt": attempt, "report": report,
                    "structured": structured, "result": doc}
        candidates = list(state["candidates"])
        if not hard:
            candidates.append((key, attempt, doc, report))
        log(f"批 {idx} 第 {attempt} 次生成未通过"
            f"{'校验' if hard else '质量门'}，原因如下：")
        _log_report(log, report, workdir, idx, attempt)
        return {"attempt": attempt, "report": report, "structured": structured,
                "candidates": candidates}

    def finalize(state: BatchState) -> dict:
        """重试耗尽：有合法候选就择优降级交付，否则落盘报告并抛错。"""
        idx = state["idx"]
        if state["candidates"] and not settings.strict:
            key, best_attempt, doc, report = max(state["candidates"],
                                                 key=lambda c: c[0])
            log(f"批 {idx} 软质量门重试耗尽，择优降级交付第 {best_attempt} 次生成"
                f"（产物结构合法、逐字保真；--strict 可改为直接失败）")
            warning = (f"批 {idx} 软质量门重试 {settings.max_retries} 次后仍未达标，"
                       f"择优交付第 {best_attempt} 次生成"
                       f"（共 {len(state['candidates'])} 个合法候选）。"
                       f"产物结构合法、逐字保真，仅转换质量未达阈值：\n{report}")
            return {"result": doc, "warnings": [warning]}
        (workdir / f"batch{idx}_failure_report.txt").write_text(
            state["report"] + "\n", encoding="utf-8")
        raise ConversionError(
            f"批 {idx} 重试 {settings.max_retries} 次后仍未通过校验"
            f"（已通过批次与失败报告保留在 {workdir}）", state["report"])

    def route_after_check(state: BatchState) -> str:
        if state["result"] is not None:
            return END
        if state["attempt"] > settings.max_retries:
            return "finalize"
        return "plan_repair"

    def plan_repair(state: BatchState) -> dict:
        """占位：Task 8 接上受限补丁路径。当前一律整份重写。"""
        idx, attempt = state["idx"], state["attempt"]
        log(f"批 {idx} 回喂校验报告重新输出整份"
            f"（{attempt + 1}/{settings.max_retries + 1}）…")
        return {"mode": "generate", "tool_steps": 0, "patch_applied": False,
                "task_done": False,
                "messages": [HumanMessage(
                    "你的输出未通过自动校验，报告如下：\n\n" + state["report"] +
                    "\n\n请修正全部问题后重新输出完整 JSON"
                    "（只输出一个 JSON 对象，不要解释文字，不要代码块标记）。")]}

    builder = StateGraph(BatchState)
    builder.add_node("generate", generate)
    builder.add_node("check", check)
    builder.add_node("plan_repair", plan_repair)
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "generate")
    builder.add_edge("generate", "check")
    builder.add_conditional_edges("check", route_after_check,
                                  {END: END, "finalize": "finalize",
                                   "plan_repair": "plan_repair"})
    builder.add_edge("plan_repair", "generate")
    builder.add_edge("finalize", END)
    return builder.compile()


def run_batch(graph, *, user: str, batch_text: str, idx: int,
              frozen_units=None, recursion_limit: Optional[int] = None):
    """跑一批，返回 (产物, 质量警告列表)。警告非空即降级交付。"""
    state: BatchState = {
        "messages": [HumanMessage(user)], "user": user,
        "batch_text": batch_text, "idx": idx, "frozen_units": frozen_units,
        "attempt": 0, "mode": "generate", "doc": None, "report": "",
        "structured": verification.VerificationReport(), "candidates": [],
        "tool_steps": 0, "patch_applied": False, "task_done": False,
        "usage_mark": None, "result": None, "warnings": [],
    }
    final = graph.invoke(state, config={"recursion_limit": recursion_limit or 200})
    return final["result"], final["warnings"]
