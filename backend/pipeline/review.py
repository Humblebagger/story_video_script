"""可选的 LLM 评审阶段：对分镜按评分卡打分，低于阈值时把问题清单喂回重试。

针对写不成机器规则的判断力差距（镜头语言呆板、情绪曲线依据牵强、
inference_note 敷衍）。默认关闭（STORYBOARD_REVIEW=1 开启），
建议生成用便宜档模型时，评审用更强档（STORYBOARD_REVIEW_MODEL）。
"""
import json
import logging
import math
from typing import Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

from server.messages import compact, msg, ref, vendor

from .chat import extract_json
from render.providers.base import scrub_secrets

REVIEW_SYSTEM = """你是资深分镜审片人。用户给你一段小说原文和由它转换出的 NovelStoryboard 分镜 JSON（忠实转换模式：剧情属于小说，呈现属于转换器）。

按评分卡独立打分，1–5 整数（3=勉强可用，4=合格，5=优秀）：
1. narration_selection 旁白取舍：selective 模式下「能拍出来的不念」是否执行；旁白是否与画面/台词重复；该念的（时间跳跃、身份交代、因果前史、点题句）有没有漏
2. shot_language 镜头语言：景别/运镜是否服务内容；有无连续同景别的呆板段落；情绪递进处景别是否递进；对话戏正反打是否成立
3. asset_quality 资产卡质量：外貌补全是否具体到可出图；visual_prompt 是否符合出图规范；资产卡之间形象是否冲突
4. semantic_fidelity 语义忠实：镜头画面有没有扭曲、夸大或发明原文没有的内容；inferred 镜头的 inference_note 是否真有原文依据

只输出一个 JSON 对象，不要解释文字：
{"scores": {"narration_selection": N, "shot_language": N, "asset_quality": N, "semantic_fidelity": N},
 "overall": <四项均值，保留一位小数>,
 "issues": [{"where": "<镜头ID或资产ID>", "problem": "<具体问题>", "fix": "<可执行的修改建议>"}]}
issues 只列 3 分以下维度里的具体问题，每条给出可直接执行的修改建议；全部 4 分以上时 issues 为空数组。"""

SCORE_KEYS = (
    "narration_selection", "shot_language", "asset_quality", "semantic_fidelity",
)


def run_review(chat, batch_text: str, doc: dict,
               min_score: float, dimension_min: int = 3,
               semantic_min: int = 4,
               lines_out: Optional[list] = None) -> Tuple[Optional[bool], str, Optional[float]]:
    """返回 (是否通过, 报告, 服务端重算总分)。

    chat 是 chat.ChatInvoker；评审是一次性打分，不入图。

    None 表示评审器自身不可用；调用方必须把它记为未验证，不能当作通过。
    lines_out（可选）收同一份报告给用户看的逐条消息（spec 子计划 5 D）；评审意见是模型输出，作厂商原文参数原样显示；
    给模型的重试指示不进逐条。
    """
    out = lines_out if lines_out is not None else []
    user = (f"【小说原文】\n{batch_text}\n\n【分镜 JSON】\n"
            f"{json.dumps(doc, ensure_ascii=False)}")
    try:
        raw = chat.text(chat.invoke([SystemMessage(REVIEW_SYSTEM),
                                     HumanMessage(user)]))
    except Exception as e:
        # 原文（可能带模型名、厂商报错）只进日志；报告会进质量报告与界面
        from .chat import llm_error
        mapped = llm_error(e)
        logging.getLogger("pipeline.review").warning("评审调用失败：%s", scrub_secrets(repr(e))[:500])  # i18n: internal
        m = mapped.as_msg() if mapped is not None else None
        out.append(compact(msg("verify.review.unavailable",
                               cause=compact(m) if m else compact(msg("verify.review.call_failed")))))
        return None, f"[review] 评审服务不可用：{mapped if mapped is not None else '调用出错'}", None
    try:
        verdict = extract_json(raw)
        scores = verdict["scores"]
        if not isinstance(scores, dict) or set(scores) != set(SCORE_KEYS):
            raise ValueError(f"scores 必须且只能包含 {', '.join(SCORE_KEYS)}")  # i18n: llm
        if any(isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 5
               for v in scores.values()):
            raise ValueError("所有评分必须是 1-5 的整数")  # i18n: llm
        overall = round(sum(scores[k] for k in SCORE_KEYS) / len(SCORE_KEYS), 1)
        if not math.isfinite(overall):
            raise ValueError("总分不是有限数值")  # i18n: llm
    except (ValueError, KeyError, TypeError, ZeroDivisionError) as e:
        out.append(compact(msg("verify.review.unverifiable")))
        return None, f"[review] 评审输出不可验证（{e}）", None

    score_line = "；".join(f"{k} {v}" for k, v in scores.items())
    issues = verdict.get("issues") or []
    issue_lines = [f"  [{i.get('where', '?')}] {i.get('problem', '')} → 建议：{i.get('fix', '')}"
                   for i in issues]
    report = (f"[review] 评审总分 {overall}（阈值 {min_score}）：{score_line}\n"
              + ("\n".join(issue_lines) if issue_lines else "  无具体问题"))
    out.append(compact(msg("verify.review.scored", overall=f"{overall}", min=f"{min_score}",
                           scores=[compact(msg("verify.review.dim_score", dim=ref(f"verify.review.dim.{k}"), score=v))
                                   for k, v in scores.items()])))
    def _raw(x):
        # 先完整字符串化、再脱敏、最后由 vendor 截断：截断会把密钥切成抹不掉的半截（含对象的键）
        return vendor(scrub_secrets(x if isinstance(x, str) else str(x)))

    out.extend([compact(msg("verify.review.issue", where=_raw(i.get("where", "?")),
                            problem=_raw(i.get("problem", "")), fix=_raw(i.get("fix", ""))))
                for i in issues] or [compact(msg("verify.review.no_issues"))])
    weak = [k for k in SCORE_KEYS if scores[k] < dimension_min]
    semantic_ok = scores["semantic_fidelity"] >= semantic_min
    if overall >= min_score and not weak and semantic_ok:
        return True, report, overall
    gates = []
    if overall < min_score:
        gates.append(f"总分 {overall} < {min_score}")
    if weak:
        gates.append("低分维度：" + ", ".join(weak))
    if not semantic_ok:
        gates.append(f"semantic_fidelity {scores['semantic_fidelity']} < {semantic_min}")
    shown_gates = []
    if overall < min_score:
        shown_gates.append(compact(msg("verify.review.gate.overall", overall=f"{overall}", min=f"{min_score}")))
    if weak:
        shown_gates.append(compact(msg("verify.review.gate.weak", dims=[ref(f"verify.review.dim.{k}") for k in weak])))
    if not semantic_ok:
        shown_gates.append(compact(msg("verify.review.gate.semantic", score=scores["semantic_fidelity"], min=semantic_min)))
    out.append(compact(msg("verify.review.gates", gates=shown_gates)))
    return False, (report + "\n  未通过独立门槛：" + "；".join(gates)
                   + "\n\n请针对上述 issues 逐条修改后重新输出完整 JSON"
                            "（只输出一个 JSON 对象）。"), overall
