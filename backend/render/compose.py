"""出片：分镜 → 片段 → 厂商无关提示词 → 厂商请求。

提示词分两层：这里产出厂商无关的结构，参考图写成占位符 {ref:资产ID}；厂商模块再改写成自己
的语法（Seedance：@图片n）。生产包（plan.py / adapters/seedance.py）走 mode=LEGACY 的同一套
组装，两边不会分叉。
"""
import base64
import hashlib
import json
from pathlib import Path
from typing import Optional

from pipeline.quality import DEFAULT_SPEECH_CPS, speech_seconds
from render import keyframes as kf
from render.plan import DIALOGUE_TYPE_ZH, TIME_ZH, assets_index, collect_refs, shot_line
from render.providers.base import ClipRequest, RefImage

LEGACY = "legacy"          # 生产包写法：台词进提示词，只要音效
AUDIO_MODES = ("tts_all", "dialogue_native", "all_native", "silent")
STYLE_ID = "__style__"    # 风格参考图占用参考位时的占位 id
STYLE_TEXT = "画风参考：沿用它的色调、线条与光影，不要照搬其中的人物或场景内容"
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
    beats = shot.get("beats")
    if timing == "playable":
        target = round(playable(shot, cps), 1)
        s["duration_sec"] = target
        total = sum(b.get("duration_sec", 0) for b in beats) if beats else 0
        if total > 0:
            # 逐拍时长按比例放到可播时长；末拍吸收取整误差，保证拍子加起来等于可播时长
            scaled = [dict(b, duration_sec=round(b.get("duration_sec", 0) * target / total, 1))
                      for b in beats]
            scaled[-1]["duration_sec"] = round(
                target - sum(b["duration_sec"] for b in scaled[:-1]), 1)
            s["beats"] = scaled
    if mode in ("tts_all", "silent") and s.get("dialogue"):
        # 台词交给 TTS（或不要声音）：画面里人物照样说话，但不让模型发声
        s["dialogue"] = []
        if not beats:
            # 分了 beats 的镜头由 neutral_prompt 追加这句（shot_line 不读 action）
            base = (s.get("action") or "").rstrip("。，； ")
            s["action"] = f"{base}，人物交谈但不发声" if base else "人物交谈但不发声"
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
        extras = []
        if raw.get("beats") and mode != LEGACY and raw.get("dialogue"):
            # shot_line 逐拍展开时不读 dialogue，所以台词与“不发声”在这里补到末行
            if mode in ("tts_all", "silent"):
                extras.append("人物交谈但不发声")
            else:
                extras += [f"{DIALOGUE_TYPE_ZH.get(d.get('type'), '台词')}"
                           f"（{d.get('character_ref', '')}，{d.get('emotion', '')}）：“{d['text']}”"
                           for d in raw["dialogue"]]
        if extras:
            line = line.rstrip("。") + "，" + "，".join(extras) + "。"
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


# ---------- 切段 ----------

def cut_clips(doc: dict, caps, cps: float = DEFAULT_SPEECH_CPS) -> list:
    """按镜头顺序装箱：每段可播时长 ≤ caps.max_clip_sec。

    单镜超上限独立成段并标 truncated；不足 min_clip_sec 的段并入相邻段（并得进去的话）。
    返回 [{"id", "episode", "shots": [镜头 dict], "duration", "truncated"}]。
    """
    out = []
    for ep in doc.get("episodes") or []:
        segs, cur, cur_len = [], [], 0.0
        for s in ep.get("shots") or []:
            d = playable(s, cps)
            if d > caps.max_clip_sec:
                if cur:
                    segs.append([cur, cur_len, False])
                    cur, cur_len = [], 0.0
                segs.append([[s], d, True])
                continue
            if cur and cur_len + d > caps.max_clip_sec + 1e-9:
                segs.append([cur, cur_len, False])
                cur, cur_len = [], 0.0
            cur.append(s)
            cur_len += d
        if cur:
            segs.append([cur, cur_len, False])
        for i, (shots, d, trunc) in enumerate(_merge_short(segs, caps), 1):
            out.append({"id": f"{ep['id']}-C{i:02d}", "episode": ep["id"], "shots": shots,
                        "duration": round(d, 1), "truncated": trunc})
    return out


def _merge_short(segs: list, caps) -> list:
    out = []
    for shots, d, trunc in segs:
        prev = out[-1] if out else None
        if (prev and not trunc and not prev[2]
                and (d < caps.min_clip_sec or prev[1] < caps.min_clip_sec)
                and prev[1] + d <= caps.max_clip_sec + 1e-9):
            prev[0] = prev[0] + shots
            prev[1] += d
        else:
            out.append([list(shots), d, trunc])
    return out


# ---------- 参考图 ----------

def _usable(uri) -> bool:
    return isinstance(uri, str) and uri.startswith(("http://", "https://", "data:image/"))


def image_for(slot: dict, assets_idx: dict) -> Optional[str]:
    """资产卡上这个参考位的图（http(s) 地址或 data URI）；没有返回 None。

    角色按着装、道具按状态、场景按机位挑图，挑不到用该卡的第一张。
    """
    role, aid, var = slot["role"], slot["asset_id"], slot["variant"]
    if role == "location":
        card = assets_idx["locations"].get(aid) or {}
        imgs = [a for a in card.get("angles") or [] if _usable(a.get("uri"))]
        key = "angle"
    else:
        kind = {"character": "characters", "creature": "creatures", "prop": "props"}[role]
        card = assets_idx[kind].get(aid) or {}
        imgs = [i for i in card.get("reference_images") or [] if _usable(i.get("uri"))]
        key = "outfit" if role == "character" else "state"
    hit = next((i for i in imgs if var and i.get(key) == var), None) or (imgs[0] if imgs else None)
    return hit["uri"] if hit else None


def pick_refs(clip: list, assets_idx: dict, max_refs: int) -> dict:
    """参考位按优先级保留：本段主要角色 > 场景 > 次要角色与生物 > 道具。

    主要角色 = 本段出镜镜头数最多的角色（并列都算）。保留的按出场顺序排列（占位符编号
    与请求里的图片顺序一致）。返回 {"kept": 带 source 的参考位, "dropped": 有图但被裁的,
    "missing": 没有图的}。
    """
    slots = ref_slots(clip, assets_idx)
    counts = {}
    for s in clip:
        for c in s.get("characters") or []:
            counts[c["ref"]] = counts.get(c["ref"], 0) + 1
    top = max((counts.get(sl["asset_id"], 0) for sl in slots if sl["role"] == "character"),
              default=0)

    def tier(sl):
        if sl["role"] == "character" and counts.get(sl["asset_id"], 0) == top:
            return 0
        return {"location": 1, "character": 2, "creature": 2}.get(sl["role"], 3)

    found = [(i, sl, image_for(sl, assets_idx)) for i, sl in enumerate(slots)]
    ranked = sorted((x for x in found if x[2]), key=lambda x: (tier(x[1]), x[0]))
    keep = {i for i, _, _ in ranked[:max(max_refs, 0)]}
    return {"kept": [{**sl, "source": src, "main": tier(sl) == 0}
                     for i, sl, src in found if i in keep],
            "dropped": [sl for i, sl, src in found if src and i not in keep],
            "missing": [sl for i, sl, src in found if not src]}


def free_slots_needed(refs: list, first_frame: Optional[str], caps) -> int:
    """自由节点要占几个参考位：参考图各一个；带首帧、又有参考图、厂商不能首帧与参考图同用时，
    首帧再占一个（与剧本段 frame_mode="ref" 同规则）。"""
    return len(refs) + (1 if first_frame and refs and not caps.frame_with_refs else 0)


ASSET_ROLES = {"characters": "character", "creatures": "creature", "locations": "location", "props": "prop"}


def asset_slot(assets_idx: dict, asset_id: str) -> Optional[dict]:
    """自由节点按资产 id 取参考位：类别由 id 所在的那一类决定，不分着装 / 机位（image_for 取第一张可用图）。"""
    for kind, role in ASSET_ROLES.items():
        card = assets_idx[kind].get(asset_id)
        if card is not None:
            return {"asset_id": asset_id, "role": role, "variant": None, "name": card.get("name", asset_id)}
    return None


def describe(slot: dict, assets_idx: dict) -> str:
    """没有参考图（或被裁掉）的资产：用资产卡的文字描述代替。"""
    aid, role, var = slot["asset_id"], slot["role"], slot["variant"]
    if role == "character" and aid in assets_idx["characters"]:
        return "人物：" + kf.describe_character(assets_idx["characters"][aid], var)
    if role == "creature" and aid in assets_idx["creatures"]:
        return "生物：" + kf.describe_creature(assets_idx["creatures"][aid])
    if role == "location" and aid in assets_idx["locations"]:
        return "场景：" + kf.describe_location(assets_idx["locations"][aid])
    if role == "prop" and aid in assets_idx["props"]:
        return "道具：" + kf.describe_prop(assets_idx["props"][aid], var)
    return ""


# ---------- 指纹与整段组装 ----------

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def fingerprint(**parts) -> str:
    """输入指纹：镜头内容、提示词、参考图、首帧来源、厂商、档位、分辨率、声音模式。"""
    blob = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return _sha(blob.encode("utf-8"))


def build_clips(doc: dict, caps, *, provider: str, model: str, resolution: str,
                audio_mode: str, keyframes: dict, rewrite, cps: float = DEFAULT_SPEECH_CPS,
                style: Optional[dict] = None) -> list:
    """分镜 → 出片段（session.json 的 clips，不含状态）。

    keyframes：镜头 id → 关键帧图路径。首帧：段首镜头有关键帧用关键帧；否则在本段没有参考图、
    厂商能返回尾帧时，用同一集上一段的尾帧接力；都不满足就不带首帧。厂商不能首帧与参考图同用
    时（frame_with_refs=False），关键帧占第一个参考位（frame_mode="ref"）。
    下划线开头的键只在内存里用，不落盘。
    """
    if audio_mode not in AUDIO_MODES:
        raise ValueError(f"未知的声音模式：{audio_mode}")
    idx = assets_index(doc)
    out, prev = [], None
    for c in cut_clips(doc, caps, cps):
        shots = c["shots"]
        refs = pick_refs(shots, idx, caps.max_refs)
        sid = shots[0].get("id")
        first, kf_hash = None, None
        if caps.first_frame and sid in keyframes:
            try:
                kf_hash = _sha(Path(keyframes[sid]).read_bytes())
                first = f"keyframe:{sid}"
            except OSError:
                kf_hash = None      # 关键帧文件丢了：当作没有关键帧
        if not first and (caps.first_frame and caps.returns_last_frame and prev is not None
              and prev["episode"] == c["episode"] and (caps.frame_with_refs or not refs["kept"])):
            first = f"relay:{prev['id']}"
        frame_mode = None
        if first:
            frame_mode = "ref" if refs["kept"] and not caps.frame_with_refs else "frame"
        if frame_mode == "ref" and len(refs["kept"]) >= caps.max_refs:
            refs = pick_refs(shots, idx, caps.max_refs - 1)
            if not refs["kept"]:
                frame_mode = "frame"
        described = [describe(sl, idx) for sl in refs["missing"] + refs["dropped"]]
        text, _ = neutral_prompt(shots, doc, idx, mode=audio_mode, slots=refs["kept"],
                                 described=described, first_frame=frame_mode == "ref",
                                 timing="playable", cps=cps)
        prompt = rewrite(text)
        fp = fingerprint(shots=shots, prompt=prompt,
                         refs=[_sha(sl["source"].encode("utf-8")) for sl in refs["kept"]],
                         first=first, keyframe=kf_hash, provider=provider, model=model,
                         resolution=resolution, audio_mode=audio_mode)
        style_state, style_hash, slots = None, None, refs["kept"]
        if style:
            cap = caps.max_refs - (1 if frame_mode == "ref" else 0)
            if frame_mode == "frame" and not caps.frame_with_refs:
                style_state = "first_frame"
            elif len(refs["kept"]) < cap or any(not sl.get("main") for sl in refs["kept"]):
                if len(refs["kept"]) >= cap:
                    refs = pick_refs(shots, idx, cap - 1)
                    described = [describe(sl, idx) for sl in refs["missing"] + refs["dropped"]]
                last_main = max((i for i, sl in enumerate(refs["kept"]) if sl.get("main")), default=-1)
                slot = {"asset_id": STYLE_ID, "role": "style", "variant": None,
                        "text": STYLE_TEXT, "source": style["source"]}
                slots = refs["kept"][:last_main + 1] + [slot] + refs["kept"][last_main + 1:]
                text, _ = neutral_prompt(shots, doc, idx, mode=audio_mode, slots=slots,
                                         described=described, first_frame=frame_mode == "ref",
                                         timing="playable", cps=cps)
                prompt = rewrite(text)
                style_state, style_hash = "used", style["hash"]
            else:
                style_state = "full"
        out.append({"id": c["id"], "episode": c["episode"],
                    "shots": [s.get("id") for s in shots],
                    "duration": c["duration"], "truncated": c["truncated"], "prompt": prompt,
                    "refs": [sl["asset_id"] for sl in slots],
                    "dropped_refs": [sl["asset_id"] for sl in refs["dropped"]],
                    "missing_refs": [sl["asset_id"] for sl in refs["missing"]],
                    "first_frame": first, "frame_mode": frame_mode, "fingerprint": fp,
                    "style": style_state, "style_hash": style_hash, "_slots": slots})
        prev = c
    return out


# ---------- 厂商请求 ----------

_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def data_uri_bytes(data: bytes, path: Path) -> str:
    """已读到的字节 + 文件名定格式 → data URI（风格图用：哈希与发出的是同一份字节）。"""
    mime = _MIME.get(Path(path).suffix.lower(), "image/jpeg")
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def data_uri(path: Path) -> str:
    return data_uri_bytes(Path(path).read_bytes(), path)


class Stale(Exception):
    """分镜、关键帧或设置变了：这一段的指纹与会话里的对不上，不能按旧的确认去花钱。"""


class FreeInvalid(Exception):
    """自由节点提交前复查没过（参考图或尾帧没了、参考位不够、提示词为空）：记失败、不提交、不花钱。"""


def request_for(doc: dict, session: dict, clip: dict, *, keyframes: dict, relay_frame,
                caps, rewrite, cps: float = DEFAULT_SPEECH_CPS,
                style: Optional[dict] = None) -> tuple:
    """按已保存的分镜重建这一段的厂商请求。返回 (ClipRequest, 实际使用的首帧来源或 None)。

    relay_frame：上一段采用那次的尾帧文件（没有就是 None，此时不带首帧照常提交）。
    """
    built = build_clips(doc, caps, provider=session["provider"], model=session["model"],
                        resolution=session["resolution"], audio_mode=session["audio_mode"],
                        keyframes=keyframes, rewrite=rewrite, cps=cps, style=style)
    c = next((b for b in built if b["id"] == clip["id"]), None)
    if c is None or c["fingerprint"] != clip["fingerprint"]:
        raise Stale(clip["id"])
    refs = [RefImage(sl["asset_id"], sl["role"], sl["source"]) for sl in c["_slots"]]
    image, used = None, None
    if c["first_frame"] and c["first_frame"].startswith("keyframe:"):
        image, used = data_uri(Path(keyframes[c["shots"][0]])), c["first_frame"]
    elif c["first_frame"] and relay_frame is not None and Path(relay_frame).exists():
        image, used = data_uri(Path(relay_frame)), c["first_frame"]
    if c["frame_mode"] == "ref" and image:
        refs.insert(0, RefImage(FIRST, "first_frame", image))
        image = None
    aspect = (doc.get("meta") or {}).get("video", {}).get("aspect_ratio", "9:16")
    req = ClipRequest(prompt=c["prompt"], model=session["model"], duration=c["duration"],
                      resolution=session["resolution"], aspect=aspect,
                      audio=session["audio_mode"] != "silent" and caps.native_audio,
                      refs=refs, first_frame=image, style_ref=c["style_hash"])
    return req, used


def request_for_free(doc: dict, session: dict, node: dict, *, keyframes: dict, tail_frame,
                     caps, rewrite, style: Optional[dict] = None) -> tuple:
    """自由节点 → 厂商请求。返回 (ClipRequest, 实际使用的首帧来源或 None)。

    node["prompt"] 只是正文；这里按 refs 顺序补【首帧】/【参考】行再整体改写，占位符编号与请求里
    图片的顺序一致（Seedance 按出现顺序编 @图片n）。tail_frame：首帧为 tail:<id> 时那次尝试的尾帧文件。
    """
    if not (node.get("prompt") or "").strip():
        raise FreeInvalid("提示词是空的")
    idx = assets_index(doc)
    slots = []
    for aid in node.get("refs") or []:
        if aid == STYLE_ID:
            if not style:
                raise FreeInvalid("风格图已删除，请从参考里去掉它")
            slots.append({"asset_id": STYLE_ID, "role": "style", "text": STYLE_TEXT, "source": style["source"]})
            continue
        slot = asset_slot(idx, aid)
        src = image_for(slot, idx) if slot else None
        if not src:
            raise FreeInvalid(f"{aid} 没有可用的参考图了")
        slots.append({**slot, "text": slot["name"], "source": src})
    ff = node.get("first_frame")
    image, used = None, None
    if ff:
        if not caps.first_frame:
            raise FreeInvalid("当前厂商不支持指定首帧")
        if ff.startswith("keyframe:"):
            path = keyframes.get(ff[len("keyframe:"):])
            if not path or not Path(path).is_file():
                raise FreeInvalid(f"首帧用的关键帧没了：{ff[len('keyframe:'):]}")
        elif ff.startswith("tail:"):
            path = tail_frame
            if path is None or not Path(path).is_file():
                raise FreeInvalid(f"首帧用的尾帧找不到了：{ff[len('tail:'):]}")
        else:
            raise FreeInvalid(f"看不懂的首帧来源：{ff}")
        image, used = data_uri(Path(path)), ff
    frame_mode = ("ref" if slots and not caps.frame_with_refs else "frame") if image else None
    need = len(slots) + (1 if frame_mode == "ref" else 0)
    if need > caps.max_refs:
        raise FreeInvalid(f"参考超出当前厂商上限（{need} / {caps.max_refs}）")
    lines, refs = [node["prompt"].strip()], []
    if frame_mode == "ref":
        lines.append(f"【首帧】{ref(FIRST)} 本段开场画面，保持构图与人物位置")
        refs.append(RefImage(FIRST, "first_frame", image))
        image = None
    for sl in slots:
        lines.append(f"【参考】{ref(sl['asset_id'])} {sl['text']}")
        refs.append(RefImage(sl["asset_id"], sl["role"], sl["source"]))
    aspect = (doc.get("meta") or {}).get("video", {}).get("aspect_ratio", "9:16")
    req = ClipRequest(prompt=rewrite("\n".join(lines)), model=session["model"], duration=node["duration"],
                      resolution=session["resolution"], aspect=aspect,
                      audio=session["audio_mode"] != "silent" and caps.native_audio,
                      refs=refs, first_frame=image,
                      style_ref=style["hash"] if style and STYLE_ID in (node.get("refs") or []) else None)
    return req, used
