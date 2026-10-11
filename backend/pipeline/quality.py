"""质量层：确定性 meta 覆写 + 机器可查的质量门（不通过则喂进重试闭环）。

与 tools/lint_storyboard.py 的分工：lint 管结构正确性（归档件的硬校验），
这里管转换质量口径（弱模型执行不到位时的兜底），只在流水线内生效。
"""
import json
import math
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
    # 已被某镜头画面引用的句子，从旁白里拿掉仍有人承载；只靠旁白承载的，直接删
    # 就成了未覆盖——实测模型照单删旁白，修复轮反而掉进 COVERAGE-001 硬失败
    pictured = set()
    for ep in doc.get("episodes", []):
        for shot in ep.get("shots", []):
            pictured.update((shot.get("source") or {}).get("unit_refs") or [])
    safe = [u for u in candidates if u["id"] in pictured]
    bare = [u for u in candidates if u["id"] not in pictured]

    def fmt(us):
        return [f"  {u['id']} [{u['kind']}] {u['text'][:30]}" for u in us[:40]]

    report = (
        f"[quality] selective 模式下旁白占比 {ratio:.0%}，超过阈值 {max_ratio:.0%}"
        f"——「能拍出来的不念」未执行（人工基准约 20%–35%）。\n"
        f"以下被旁白朗读的句子多为可拍内容，请逐句重新裁决，只保留画面承载不了的"
        f"信息——时间跳跃、人名身份交代、因果前史、心理核心语义、点题句。\n")
    if safe:
        report += ("已有镜头画面引用、可直接从 narration.unit_refs 中移除的：\n"
                   + "\n".join(fmt(safe)) + "\n")
    if bare:
        report += ("只靠旁白承载的（没有任何镜头的 source.unit_refs 引用它们）：若要移除，"
                   "须先把它加进呈现该内容的镜头的 source.unit_refs，否则就成了未覆盖：\n"
                   + "\n".join(fmt(bare)) + "\n")
    return False, report.rstrip("\n"), ratio


# 程序裁剪旁白时，只动模型自己标成这两类的句子，先动作后描写（描写更可能是
# 带文学性的点题句）。心理、交代类与对白一律不动——对白进旁白时要剔除引号部分，
# 程序重建不了那段文本
_PRUNABLE_KINDS = ("action", "description")


def _narration_ratio(doc: dict) -> Tuple[float, set, list]:
    units = [u for u in doc.get("source", {}).get("units", []) if not u.get("skipped")]
    narrated = set()
    for ep in doc.get("episodes", []):
        for shot in ep.get("shots", []):
            narrated.update((shot.get("narration") or {}).get("unit_refs") or [])
    ids = {u["id"] for u in units}
    return (len(narrated & ids) / len(units) if units else 0.0), narrated, units


def _drop_from_narration(shot: dict, uid: str, texts: dict) -> bool:
    """把 uid 从该镜头旁白里摘掉并重建旁白文本；重建不了就不动，返回是否摘掉。"""
    nar = shot.get("narration") or {}
    refs = nar.get("unit_refs") or []
    if uid not in refs:
        return False
    rest = [r for r in refs if r != uid]
    text = nar.get("text") or ""
    if text == "".join(texts.get(r, "") for r in refs):
        new_text = "".join(texts.get(r, "") for r in rest)
    elif texts.get(uid) and text.count(texts[uid]) == 1:
        new_text = text.replace(texts[uid], "", 1)
    else:
        return False
    if not rest:
        shot.pop("narration", None)       # schema 允许省略；空旁白对象反而不合法
    else:
        nar["unit_refs"], nar["text"] = rest, new_text
    return True


def prune_narration(doc: dict, max_ratio: float) -> int:
    """selective 模式旁白占比超阈值时，由程序裁到刚好不超。返回移出旁白的句数。

    实测弱模型首次生成旁白占比 93%–100%，给具体句数预算也不改；回喂清单重修
    每次多一轮整份输入，还常删出未覆盖的句子。裁剪只取模型自己标为动作/描写、
    且已被某镜头 source.unit_refs 引用（画面承载）的句子——移出旁白后仍有人承载，
    覆盖率不变。按 _PRUNABLE_KINDS 的顺序、原文顺序逐句移出，到阈值即停。
    """
    mode = doc.get("meta", {}).get("narration", {}).get("mode")
    if mode != "selective" or max_ratio >= 1.0:
        return 0
    ratio, narrated, units = _narration_ratio(doc)
    if ratio <= max_ratio or not units:
        return 0
    pictured = set()
    shots = [sh for ep in doc.get("episodes", []) for sh in ep.get("shots", [])]
    for sh in shots:
        pictured.update((sh.get("source") or {}).get("unit_refs") or [])
    texts = {u["id"]: u.get("text") or "" for u in units}
    order = [u for kind in _PRUNABLE_KINDS for u in units
             if u.get("kind") == kind and u["id"] in narrated and u["id"] in pictured]
    budget = math.floor(len(units) * max_ratio + 1e-9)
    count = len(narrated & set(texts))
    removed = 0
    for u in order:
        if count <= budget:
            break
        holders = [sh for sh in shots
                   if u["id"] in ((sh.get("narration") or {}).get("unit_refs") or [])]
        # 一句可能被多个镜头的旁白引用：必须全部摘掉才算移出，否则一处都不动
        snapshot = [json.dumps(sh.get("narration"), ensure_ascii=False) for sh in holders]
        if all(_drop_from_narration(sh, u["id"], texts) for sh in holders):
            count -= 1
            removed += 1
        else:
            for sh, snap in zip(holders, snapshot):
                if snap != "null":
                    sh["narration"] = json.loads(snap)
    return removed


# 运镜枚举之外、但语义归属无歧义的写法（实测出现过的才收）
_MOVEMENT_ALIASES = {"whip_pan": "pan"}


def fix_known_slips(doc: dict) -> int:
    """模型反复出现、语义无歧义的结构笔误，校验前直接改掉。返回修正处数。

    - camera.angle 写成 reverse：那是场景卡机位的枚举（反打），镜头机位里对应
      过肩拍 over_shoulder
    - camera.movement 写成 whip_pan（甩镜）：枚举里归 pan
    - narration 写成 null：没有旁白就该省略这个字段
    """
    n = 0
    for ep in doc.get("episodes", []):
        for shot in ep.get("shots", []):
            cam = shot.get("camera")
            if isinstance(cam, dict) and cam.get("angle") == "reverse":
                cam["angle"] = "over_shoulder"
                n += 1
            if isinstance(cam, dict) and cam.get("movement") in _MOVEMENT_ALIASES:
                cam["movement"] = _MOVEMENT_ALIASES[cam["movement"]]
                n += 1
            if "narration" in shot and shot["narration"] is None:
                del shot["narration"]
                n += 1
    return n


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


# 与 schema 的 duration_sec.maximum 一致：单镜超过它就该拆，而不是继续拉长
MAX_SHOT_SECONDS = 15.0


def fit_durations(doc: dict, cps: float = DEFAULT_SPEECH_CPS,
                  max_sec: float = MAX_SHOT_SECONDS) -> int:
    """把念不完旁白/台词的镜头时长确定性拉长到念得完（按 0.5s 向上取整，封顶 max_sec）。

    镜头时长属于「呈现」一侧，程序能算对的不交给模型：实测弱模型为配平秒数会
    整段替换 shots，一轮补丁烧掉 49k 输出 token 还改坏了台词。封顶之后仍念不完的
    镜头留给 speech_fit_gate 拦下、回喂要求拆镜。带 beats 的镜头不动——各拍时长
    之和必须等于镜头时长，单改总长会破坏它。返回拉长的镜头数。
    """
    import math
    n = 0
    for ep in doc.get("episodes", []):
        for shot in ep.get("shots", []):
            if shot.get("beats"):
                continue
            need = speech_seconds(shot, cps)
            have = shot.get("duration_sec", 0) or 0
            if need > have + 0.05 and have < max_sec:
                shot["duration_sec"] = min(max_sec, math.ceil(need * 2) / 2)
                n += 1
    return n


def normalize_curve_refs(doc: dict) -> int:
    """music.curve 的镜头引用规整成本集真实存在的镜头 ID。返回修正处数。

    - 写成序号（1 / "3"）的换成本集第 n 镜的 ID：实测三批首次生成全部因此硬失败
    - 越界的截到本集首/末镜：实测模型数错镜头数，本集 40 镜却写第 41、44 镜
    - 本集前缀、但本集不存在的镜头 ID（E01-SH041）同样截到末镜
    别的集的 ID 不归这里管，留给 lint 报。情绪曲线是呈现层，截到边界只是让
    该段落在本集末尾，不影响任何溯源。
    """
    n = 0
    for ep in doc.get("episodes", []):
        ids = [s.get("id") for s in ep.get("shots", []) if isinstance(s.get("id"), str)]
        if not ids:
            continue
        known = set(ids)
        prefix = ids[0].split("-SH")[0] + "-SH" if "-SH" in ids[0] else None
        for seg in (ep.get("music") or {}).get("curve") or []:
            for key in ("from_shot", "to_shot"):
                v = seg.get(key)
                if isinstance(v, bool):
                    continue
                if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
                    i = min(max(int(v), 1), len(ids))
                    seg[key] = ids[i - 1]
                    n += 1
                elif (isinstance(v, str) and prefix and v.startswith(prefix)
                      and v not in known):
                    seg[key] = ids[-1]
                    n += 1
    return n


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
        f"上限 {MAX_SHOT_SECONDS:g}s 以内的缺口程序会自动拉长 duration_sec；"
        f"超出上限的镜头必须拆成多个镜头分担旁白，或把画面承载得了的句子从 "
        f"narration.unit_refs 移除（不得改动旁白与台词文本、也不得改 source.unit_refs）：\n"
        + "\n".join(lines))
    return False, report, ratio
