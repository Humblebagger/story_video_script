"""出片：分镜 → 片段 → 厂商无关提示词 → 厂商请求。

提示词分两层：这里产出厂商无关的结构，参考图写成占位符 {ref:资产ID}；厂商模块再改写成自己
的语法（Seedance：@图片n）。生产包（plan.py / adapters/seedance.py）走 mode=LEGACY 的同一套
组装，两边不会分叉。
"""
from pipeline.quality import DEFAULT_SPEECH_CPS, speech_seconds
from render.plan import TIME_ZH, collect_refs, shot_line

LEGACY = "legacy"          # 生产包写法：台词进提示词，只要音效
AUDIO_MODES = ("tts_all", "dialogue_native", "all_native", "silent")
FIRST = "__first__"        # 首帧图占用参考位时的占位 id


def ref(asset_id: str) -> str:
    return "{ref:" + asset_id + "}"


def playable(shot: dict, cps: float = DEFAULT_SPEECH_CPS) -> float:
    """可播时长：镜头时长与念完旁白台词所需的较大者（与 timeline.ts、quality 同一口径）。"""
    return max(shot.get("duration_sec", 3), speech_seconds(shot, cps))


def ref_slots(clip: list, assets_idx: dict) -> list:
    """一组镜头的参考位，按出场顺序：角色/生物、场景+机位、道具+状态。

    同一场景的两个机位是两个参考位（两张图）。
    """
    chars, locs, props = collect_refs(clip)
    out = []
    for cid, outfit in chars:
        if cid in assets_idx["creatures"]:
            name = assets_idx["creatures"][cid].get("name", cid)
            out.append({"asset_id": cid, "role": "creature", "variant": None,
                        "text": f"生物参考：{name}（{cid}），锁定生物外观"})
        else:
            name = assets_idx["characters"].get(cid, {}).get("name", cid)
            note = f"，着装 {outfit}" if outfit else ""
            out.append({"asset_id": cid, "role": "character", "variant": outfit,
                        "text": f"角色参考：{name}（{cid}{note}），锁定人物外观"})
    for lid, angle in locs:
        name = assets_idx["locations"].get(lid, {}).get("name", lid)
        out.append({"asset_id": lid, "role": "location", "variant": angle,
                    "text": f"场景参考：{name}（{lid}，{angle} 机位），锁定环境"})
    for pid, state in props:
        name = assets_idx["props"].get(pid, {}).get("name", pid)
        note = f"，状态 {state}" if state else ""
        out.append({"asset_id": pid, "role": "prop", "variant": state,
                    "text": f"道具参考：{name}（{pid}{note}）"})
    return out


def _shot_for(shot: dict, mode: str, timing: str, cps: float) -> dict:
    s = dict(shot)
    if timing == "playable":
        s["duration_sec"] = round(playable(shot, cps), 1)
    if mode in ("tts_all", "silent") and s.get("dialogue"):
        # 台词交给 TTS（或不要声音）：画面里人物照样说话，但不让模型发声
        s["dialogue"] = []
        s["action"] = (s.get("action") or "").rstrip("。，； ") + "，人物交谈但不发声"
    return s


def _sound(mode: str, sfx: list):
    s = "，".join(sfx)
    if mode == LEGACY:
        return f"【声音】{s}（仅音效，不要音乐，不要字幕）" if sfx else None
    if mode == "silent":
        return "【声音】无声"
    if mode == "tts_all":
        return (f"【声音】{s}（仅环境音效，无人声，无音乐，无字幕）" if sfx
                else "【声音】仅环境音，无人声，无音乐，无字幕")
    spoken = "台词逐字念出，不要旁白" if mode == "dialogue_native" else "旁白与台词逐字念出"
    return f"【声音】{s + '；' if s else ''}{spoken}，不要音乐，不要字幕"


def _orientation(ar: str) -> str:
    try:
        w, h = (float(x) for x in ar.split(":"))
    except ValueError:
        return "画幅"
    return "竖屏" if h > w else "横屏" if w > h else "方形画面"


def neutral_prompt(clip: list, doc: dict, assets_idx: dict, *, mode: str = LEGACY,
                   slots=None, described=(), first_frame: bool = False,
                   timing: str = "nominal", cps: float = DEFAULT_SPEECH_CPS) -> tuple:
    """一组镜头 → (带 {ref:ID} 占位符的提示词, 占位符依次对应的资产 id)。

    slots=None 列出全部参考位（生产包）；出片时传裁剪后的参考位，没有图或被裁掉的资产
    以 described 的文字描述代替。first_frame=True 时首帧图占第一个参考位。
    timing="playable" 按可播时长写时间轴（出片），"nominal" 按分镜标称时长（生产包）。
    """
    meta = doc["meta"]
    style = meta["style"]["style_prefix"]
    ar = meta.get("video", {}).get("aspect_ratio", "9:16")
    shots = [_shot_for(s, mode, timing, cps) for s in clip]
    total = round(sum(s.get("duration_sec", 3) for s in shots), 1)
    first = clip[0]
    tod = TIME_ZH.get(first.get("time_of_day", ""), "")
    weather = first.get("weather", "")
    if slots is None:
        slots = ref_slots(clip, assets_idx)

    sfx, constraints = [], []
    for s in clip:
        for x in s.get("sfx", []):
            if x not in sfx:
                sfx.append(x)
        for x in s.get("constraints", []):
            if x not in constraints:
                constraints.append(x)

    orient = "竖屏" if mode == LEGACY else _orientation(ar)
    head = (f"{style}，{total}秒，{ar}{orient}"
            + (f"，{tod}" if tod else "") + (f"，{weather}" if weather else ""))
    lines = [head, ""]
    t = 0.0
    for raw, s in zip(clip, shots):
        line, t = shot_line(s, t)
        narration = (raw.get("narration") or {}).get("text")
        if mode == "all_native" and narration:
            line = line.rstrip("。") + f"，旁白：“{narration}”。"
        lines.append(line)
    lines.append("")
    sound = _sound(mode, sfx)
    if sound:
        lines.append(sound)
    # 负面约束是 v0.5 新增的镜头级禁令，出图质量的一半毁在没有约束上
    if constraints:
        lines.append(f"【不要】{'；'.join(constraints)}")
    ids = []
    if first_frame:
        lines.append(f"【首帧】{ref(FIRST)} 本段开场画面，保持构图与人物位置")
        ids.append(FIRST)
    for sl in slots:
        lines.append(f"【参考】{ref(sl['asset_id'])} {sl['text']}")
        ids.append(sl["asset_id"])
    for d in described:
        if d:
            lines.append(f"【描述】{d}")
    return "\n".join(lines), ids
