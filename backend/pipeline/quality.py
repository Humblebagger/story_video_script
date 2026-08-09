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


def narration_density_gate(doc: dict, max_ratio: float) -> Tuple[bool, str, float]:
    """selective 模式下"能拍出来的不念"的机器兜底。

    人工基准的旁白占比在 18%–36%（《药》0.18、《玉佩》0.36）；弱模型常退化成
    逐句朗读（100%）。占比超过 max_ratio 即不通过，报告列出可拍句清单供模型
    逐句重新裁决。max_ratio >= 1 视为关闭该门。
    返回 (是否通过, 报告, 实际占比)——占比供重试耗尽后择优降级交付时比较。
    """
    mode = doc.get("meta", {}).get("narration", {}).get("mode")
    if mode != "selective" or max_ratio >= 1.0:
        return True, "", 0.0

    units = [u for u in doc.get("source", {}).get("units", []) if not u.get("skipped")]
    if not units:
        return True, "", 0.0
    narrated = set()
    for ep in doc.get("episodes", []):
        for shot in ep.get("shots", []):
            narrated.update(shot.get("narration", {}).get("unit_refs", []))
    ratio = len(narrated & {u["id"] for u in units}) / len(units)
    if ratio <= max_ratio:
        return True, "", ratio

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
    return False, report, ratio


# 中文 TTS 的常见语速区间是 4–6 字/秒。取 4.5 作缺省偏保守：宁可判"念不完"，
# 也别让人拿着一个念不完的分镜去渲染——那笔钱是真花出去的。
DEFAULT_SPEECH_CPS = 4.5


def speech_seconds(shot: dict, cps: float = DEFAULT_SPEECH_CPS) -> float:
    """本镜头要念完的字数所需秒数（旁白 + 台词）。"""
    n = len((shot.get("narration") or {}).get("text") or "")
    n += sum(len(d.get("text") or "") for d in shot.get("dialogue") or [])
    return n / cps if n else 0.0


def playable_seconds(doc: dict, cps: float = DEFAULT_SPEECH_CPS) -> Tuple[float, float]:
    """(名义总时长, 要让语音都念完的实际时长)。

    两者不等就说明分镜里的秒数是纸面数字：按名义时长做的预算，渲染时会被迫拉长。
    """
    nominal = actual = 0.0
    for ep in doc.get("episodes", []):
        for shot in ep.get("shots", []):
            d = shot.get("duration_sec", 0) or 0
            nominal += d
            actual += max(d, speech_seconds(shot, cps))
    return round(nominal, 1), round(actual, 1)


def speech_fit_gate(doc: dict, max_overflow_ratio: float,
                    cps: float = DEFAULT_SPEECH_CPS) -> Tuple[bool, str, float]:
    """镜头时长必须够念完它承载的旁白与台词。

    这是"时长可控"的地基：念不完的镜头在成片时要么截断旁白（破坏保真的听感），
    要么被迫拉长（预算失准）。作为软门而非硬门，是因为产物本身结构合法、逐字保真，
    只是呈现层的秒数没配平——重试耗尽仍可择优降级交付。
    max_overflow_ratio >= 1 视为关闭。
    返回 (是否通过, 报告, 超时比例)。
    """
    if max_overflow_ratio >= 1.0:
        return True, "", 0.0
    over = []
    for ep in doc.get("episodes", []):
        for shot in ep.get("shots", []):
            need = speech_seconds(shot, cps)
            have = shot.get("duration_sec", 0) or 0
            if need > have + 0.05:
                over.append((shot.get("id"), have, need))
    total = sum(len(ep.get("shots", [])) for ep in doc.get("episodes", []))
    if not total:
        return True, "", 0.0
    ratio = len(over) / total
    if ratio <= max_overflow_ratio:
        return True, "", ratio

    lines = [f"  {sid} 时长 {have:g}s，念完需 {need:.1f}s（缺 {need - have:.1f}s）"
             for sid, have, need in over[:40]]
    nominal, actual = playable_seconds(doc, cps)
    report = (
        f"[quality] {len(over)}/{total} 个镜头（{ratio:.0%}）的时长不够念完自己的"
        f"旁白与台词（按 {cps:g} 字/秒），超过阈值 {max_overflow_ratio:.0%}。\n"
        f"名义总时长 {nominal:g}s，要让语音都念完实际需要 {actual:g}s。\n"
        f"请调整这些镜头的 duration_sec 使其不短于语音时长；若因此过长，"
        f"应把该镜头拆成多个镜头分担旁白，或把画面承载得了的句子从 "
        f"narration.unit_refs 移除（不得改动旁白与台词文本、也不得改 source.unit_refs）：\n"
        + "\n".join(lines))
    return False, report, ratio
