"""静帧预演（animatic）：每个镜头一张关键帧图的出图提示词。

出图模型暂不接（用户在别处出图后上传），这里只负责把镜头 IR 组装成**静态单帧**的提示词：
和 plan.py 的视频 clip 提示词不同，静帧没有时间轴、运镜和台词，只描述「这一刻画面里有什么」。
人物外貌/服装、场景、道具状态取自资产卡——同一角色每镜都是同一套描述，形象才锁得住；
垫图（reference_assets）同时列出，出图工具支持参考图时一并喂进去。

只读、不落盘、不改 IR。
"""
from typing import Optional

from render.plan import ANGLE_ZH, SHOT_SIZE_ZH, TIME_ZH, assets_index

_APPEARANCE_KEYS = ("age", "gender", "body", "face", "hair")


def _character(card: dict, outfit: Optional[str]) -> str:
    look = card.get("appearance") or {}
    parts = [look[k] for k in _APPEARANCE_KEYS if look.get(k) and look[k] != "无"]
    outfits = {o.get("id"): o.get("description", "") for o in card.get("outfits") or []}
    wear = outfits.get(outfit or "default") or next(iter(outfits.values()), "")
    if wear:
        parts.append(f"穿{wear}")
    return f"{card.get('name', card.get('id'))}（{'，'.join(parts)}）" if parts else card.get("name", "")


def _creature(card: dict) -> str:
    desc = card.get("visual_prompt") or card.get("species") or ""
    return f"{card.get('name', card.get('id'))}（{desc}）" if desc else card.get("name", "")


def _location(card: dict) -> str:
    desc = (card.get("visual_prompt") or "").replace("，无人物", "").replace("无人物", "")
    return "，".join(p for p in (card.get("name", ""), desc.strip("，"),
                                 card.get("lighting_defaults", "")) if p)


def _prop(card: dict, state: Optional[str]) -> str:
    states = {s.get("id"): s.get("description", "") for s in card.get("states") or []}
    return states.get(state) or card.get("name", "")


def shot_keyframe(shot: dict, doc: dict, idx: Optional[dict] = None) -> dict:
    """一个镜头 → 关键帧出图提示词。镜头分了 beats 时取第一拍（关键帧是这一镜的开场画面）。"""
    idx = idx or assets_index(doc)
    meta = doc.get("meta") or {}
    style = (meta.get("style") or {})
    cam = shot.get("camera") or {}
    beats = shot.get("beats") or []
    action = (beats[0].get("action") if beats else None) or shot.get("action", "")

    framing = SHOT_SIZE_ZH.get(shot.get("shot_size"), "")
    if cam.get("angle") in ANGLE_ZH:
        framing += f"，{ANGLE_ZH[cam['angle']]}"
    people, refs = [], []
    for c in shot.get("characters") or []:
        ref = c.get("ref")
        if ref in idx["creatures"]:
            people.append(_creature(idx["creatures"][ref]))
        elif ref in idx["characters"]:
            desc = _character(idx["characters"][ref], c.get("outfit"))
            acting = "，".join(x for x in (c.get("expression"), c.get("action"), c.get("position")) if x)
            people.append(f"{desc}{('：' + acting) if acting else ''}")
        else:
            continue
        refs.append(ref)
    place = ""
    if shot.get("location_ref") in idx["locations"]:
        place = _location(idx["locations"][shot["location_ref"]])
        refs.append(shot["location_ref"])
    props = []
    for p in shot.get("prop_refs") or []:
        if p.get("ref") in idx["props"]:
            props.append(_prop(idx["props"][p["ref"]], p.get("state")))
            refs.append(p["ref"])

    when = "，".join(x for x in (TIME_ZH.get(shot.get("time_of_day", ""), ""),
                                 shot.get("weather", "")) if x)
    lines = [
        # 色调不再单列：风格前缀里通常已经写了，重复只会稀释权重
        "，".join(x for x in (style.get("style_prefix", ""), "电影静帧", framing) if x),
        f"画面：{action}",
    ]
    if place:
        lines.append(f"场景：{place}{('，' + when) if when else ''}")
    elif when:
        lines.append(f"时间：{when}")
    if people:
        lines.append("人物：" + "；".join(people))
    if props:
        lines.append("道具：" + "；".join(props))
    if shot.get("atmosphere"):
        lines.append(f"氛围：{shot['atmosphere']}")
    lines.append("单帧画面，无字幕，无文字，无水印")

    negative = [t for t in [style.get("negative_prompt", "")] + list(shot.get("constraints") or []) if t]
    return {
        "shot_id": shot.get("id"),
        "prompt": "\n".join(lines),
        "negative_prompt": "，".join(negative),
        "reference_assets": refs,
        "aspect_ratio": (meta.get("video") or {}).get("aspect_ratio", "9:16"),
    }


def keyframe_plan(doc: dict) -> list:
    idx = assets_index(doc)
    return [shot_keyframe(s, doc, idx)
            for ep in doc.get("episodes") or [] for s in ep.get("shots") or []]


# 出片（render/compose.py）给没有参考图的资产写文字描述，与静帧提示词同一套写法
describe_character, describe_creature = _character, _creature
describe_location, describe_prop = _location, _prop
