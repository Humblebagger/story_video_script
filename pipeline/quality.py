"""质量层：确定性 meta 覆写 + 机器可查的质量门（不通过则喂进重试闭环）。

与 tools/lint_storyboard.py 的分工：lint 管结构正确性（归档件的硬校验），
这里管转换质量口径（弱模型执行不到位时的兜底），只在流水线内生效。
"""
from typing import Tuple


def apply_meta_overrides(doc: dict, params) -> None:
    """用户传入的制作参数是标准答案，直接覆写 meta 对应字段，防模型缩写/漂移。

    模型自行补写的字段（negative_prompt、resolution 等）保持原样。
    """
    meta = doc.setdefault("meta", {})
    meta["title"] = params.work_title
    meta["fidelity_mode"] = "faithful"
    style = meta.setdefault("style", {})
    style["style_prefix"] = params.style_prefix
    style["art_style"] = params.art_style
    style["color_tone"] = params.color_tone
    video = meta.setdefault("video", {})
    video["aspect_ratio"] = params.aspect_ratio
    video["target_platform"] = params.target_platform
    narration = meta.setdefault("narration", {})
    narration["mode"] = params.narration_mode
    narration["tts_voice"] = params.tts_voice


def narration_density_gate(doc: dict, max_ratio: float) -> Tuple[bool, str]:
    """selective 模式下"能拍出来的不念"的机器兜底。

    人工基准的旁白占比在 18%–36%（《药》0.18、《玉佩》0.36）；弱模型常退化成
    逐句朗读（100%）。占比超过 max_ratio 即不通过，报告列出可拍句清单供模型
    逐句重新裁决。max_ratio >= 1 视为关闭该门。
    """
    mode = doc.get("meta", {}).get("narration", {}).get("mode")
    if mode != "selective" or max_ratio >= 1.0:
        return True, ""

    units = [u for u in doc.get("source", {}).get("units", []) if not u.get("skipped")]
    if not units:
        return True, ""
    narrated = set()
    for ep in doc.get("episodes", []):
        for shot in ep.get("shots", []):
            narrated.update(shot.get("narration", {}).get("unit_refs", []))
    ratio = len(narrated & {u["id"] for u in units}) / len(units)
    if ratio <= max_ratio:
        return True, ""

    candidates = [u for u in units
                  if u["id"] in narrated
                  and u.get("kind") in ("action", "description", "dialogue")]
    lines = [f"  {u['id']} [{u['kind']}] {u['text'][:30]}" for u in candidates[:40]]
    report = (
        f"[quality] selective 模式下旁白占比 {ratio:.0%}，超过阈值 {max_ratio:.0%}"
        f"——「能拍出来的不念」未执行（人工基准约 20%–35%）。\n"
        f"以下被旁白朗读的句子多为可拍内容，请逐句重新裁决：画面或台词已完整承载的，"
        f"从 narration.unit_refs 中移除（保持 source.unit_refs 不变）；只保留画面承载"
        f"不了的信息——时间跳跃、人名身份交代、因果前史、心理核心语义、点题句：\n"
        + "\n".join(lines))
    return False, report
