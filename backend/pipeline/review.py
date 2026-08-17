"""可选的 LLM 评审阶段：对分镜按评分卡打分，低于阈值时把问题清单喂回重试。

针对写不成机器规则的判断力差距（镜头语言呆板、情绪曲线依据牵强、
inference_note 敷衍）。默认关闭（STORYBOARD_REVIEW=1 开启），
建议生成用便宜档模型时，评审用更强档（STORYBOARD_REVIEW_MODEL）。
"""
import json
import math
from typing import Optional, Tuple

from .llm import extract_json

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


def run_review(llm, batch_text: str, doc: dict,
               min_score: float, dimension_min: int = 3,
               semantic_min: int = 4) -> Tuple[Optional[bool], str, Optional[float]]:
    """返回 (是否通过, 报告, 服务端重算总分)。

    None 表示评审器自身不可用；调用方必须把它记为未验证，不能当作通过。
    """
    user = (f"【小说原文】\n{batch_text}\n\n【分镜 JSON】\n"
            f"{json.dumps(doc, ensure_ascii=False)}")
    try:
        raw = llm.complete(REVIEW_SYSTEM, [{"role": "user", "content": user}])
    except Exception as e:
        return None, f"[review] 评审服务不可用（{type(e).__name__}: {e}）", None
    try:
        verdict = extract_json(raw)
        scores = verdict["scores"]
        if not isinstance(scores, dict) or set(scores) != set(SCORE_KEYS):
            raise ValueError(f"scores 必须且只能包含 {', '.join(SCORE_KEYS)}")
        if any(isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 5
               for v in scores.values()):
            raise ValueError("所有评分必须是 1-5 的整数")
        overall = round(sum(scores[k] for k in SCORE_KEYS) / len(SCORE_KEYS), 1)
        if not math.isfinite(overall):
            raise ValueError("总分不是有限数值")
    except (ValueError, KeyError, TypeError, ZeroDivisionError) as e:
        return None, f"[review] 评审输出不可验证（{e}）", None

    score_line = "；".join(f"{k} {v}" for k, v in scores.items())
    issues = verdict.get("issues") or []
    issue_lines = [f"  [{i.get('where', '?')}] {i.get('problem', '')} → 建议：{i.get('fix', '')}"
                   for i in issues]
    report = (f"[review] 评审总分 {overall}（阈值 {min_score}）：{score_line}\n"
              + ("\n".join(issue_lines) if issue_lines else "  无具体问题"))
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
    return False, (report + "\n  未通过独立门槛：" + "；".join(gates)
                   + "\n\n请针对上述 issues 逐条修改后重新输出完整 JSON"
                            "（只输出一个 JSON 对象）。"), overall
