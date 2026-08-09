"""分镜 IR → 渲染任务清单。

这里是「提示词组装」的唯一出处。`adapters/seedance.py` 的 Markdown 生产包与本模块
产出的机器可读清单，共用下面同一套 clip 打包与提示词拼装——两套分叉的话，人眼在
Markdown 里核对过的提示词，跟真正发给视频 API 的就不是同一句话了，审都白审。

清单不进 IR：IR 是交付物，渲染是它的下游消费方式之一。唯一会回写 IR 的是资产卡的
reference_images[].uri——那个字段本来就是为「出好的图反过来约束每一帧」存在的。
"""
import os
from typing import Optional

from pipeline.quality import DEFAULT_SPEECH_CPS, speech_seconds

SHOT_SIZE_ZH = {
    "extreme_wide": "大远景", "wide": "远景", "full": "全景",
    "medium": "中景", "medium_close": "中近景", "close_up": "近景特写",
    "extreme_close_up": "大特写", "insert": "插入特写",
}
MOVEMENT_ZH = {
    "static": "固定镜头", "push_in": "缓慢推近", "pull_out": "缓慢拉远",
    "pan": "横摇", "tilt": "俯仰摇", "track": "平移跟拍", "follow": "跟随",
    "orbit": "环绕", "crane": "升降", "handheld": "手持晃动", "zoom": "变焦",
}
ANGLE_ZH = {
    "eye_level": "平视", "high": "俯拍", "low": "仰拍", "overhead": "顶拍",
    "dutch": "倾斜构图", "pov": "主观视角", "over_shoulder": "过肩",
}
TIME_ZH = {"dawn": "黎明", "day": "白天", "dusk": "黄昏", "night": "夜晚"}
DIALOGUE_TYPE_ZH = {"dialogue": "台词", "inner_monologue": "内心独白",
                    "voiceover": "画外音"}

KIND_ZH = {"characters": "角色", "locations": "场景",
           "props": "道具", "creatures": "生物"}

DEFAULT_MAX_CLIP_SECONDS = 15.0

# ---- 费用估算 ----
#
# 这里的数字是**估算**，来源是二手报道而非官方定价页（官方定价页是前端渲染的，
# 抓不到价格表），且有两个变量根本没建模：
#   1. 分辨率——token 消耗与分辨率强相关，而「15 秒约 30.88 万 token」对应哪一档
#      并未公开，只能推测是 1080p；
#   2. mini 档的实际 token 消耗未见公开数据，这里沿用标准版的折算。
# 所以费率必须可覆盖，并且界面上要如实交代依据。真正靠谱的做法只有一个：
# 拿一次真实调用返回的 token usage 反标定，再把 STORYBOARD_RENDER_CNY_PER_SECOND 钉死。
RATE_SOURCE = "2026-03 公开报道的方舟资费，非官方定价页，未经账单核对"

TIERS = {
    "seedance-2.0": {
        "label": "Seedance 2.0（标准）",
        "cny_per_million_tokens": 46.0,   # 不含视频输入；我们是图生视频，走这一档
        "tokens_per_second": 20600,       # 由「15 秒约 30.88 万 token」折算
        "resolutions": "1080p 及以上",
        "caveat": "官方口径约「1 元 1 秒」。该 token 数对应的分辨率未公开，推测 1080p；"
                  "换低分辨率会明显便宜。",
    },
    "seedance-2.0-mini": {
        "label": "Seedance 2.0 mini",
        "cny_per_million_tokens": 23.0,   # 0.023 元/千 token
        "tokens_per_second": 20600,
        "resolutions": "480P / 720P，4–15 秒",
        "caveat": "资费为标准版一半。mini 的实际 token 消耗未见公开数据，"
                  "此处沿用标准版折算，误差可能更大。",
    },
}
DEFAULT_TIER = "seedance-2.0"

# AI 视频一次过的概率不高，给一个抽卡系数，别让人只看到最乐观的那个数
RETRY_FACTOR = 3.0


def _env_cny_per_second() -> Optional[float]:
    """用真实账单标定过就钉这个值，别再用推算的。"""
    raw = os.environ.get("STORYBOARD_RENDER_CNY_PER_SECOND", "").strip()
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def assets_index(doc: dict) -> dict:
    a = doc.get("assets") or {}
    return {kind: {c["id"]: c for c in (a.get(kind) or [])} for kind in KIND_ZH}


def pack_clips(shots: list, max_seconds: float) -> list:
    """把镜头顺序打包成总时长 ≤ max_seconds 的 clip（单镜头超限时独立成 clip）。"""
    clips, cur, cur_len = [], [], 0.0
    for shot in shots:
        d = shot.get("duration_sec", 3)
        if cur and cur_len + d > max_seconds:
            clips.append(cur)
            cur, cur_len = [], 0.0
        cur.append(shot)
        cur_len += d
    if cur:
        clips.append(cur)
    return clips


def collect_refs(shots: list) -> tuple:
    """收集一组镜头引用的资产 ID：(角色/生物, 场景+机位, 道具+状态)。"""
    chars, locs, props = [], [], []
    for s in shots:
        for c in s.get("characters", []):
            if c["ref"] not in [x[0] for x in chars]:
                chars.append((c["ref"], c.get("outfit")))
        loc = s.get("location_ref")
        key = (loc, s.get("location_angle", "front"))
        if loc and key not in locs:
            locs.append(key)
        for p in s.get("prop_refs", []):
            key = (p["ref"], p.get("state")) if isinstance(p, dict) else (p, None)
            if key not in props:
                props.append(key)
    return chars, locs, props


def shot_line(shot: dict, t0: float) -> tuple:
    """单镜头 → 时间轴一行。

    镜头若分了 beats（v0.5），逐拍展开——那正是"一镜到底里情绪与灯光逐级推进"
    的表达，压回一行就把这个信息丢了。
    """
    beats = shot.get("beats")
    if beats:
        lines, t = [], t0
        for b in beats:
            t1 = t + b.get("duration_sec", 0)
            parts = [b.get("action", "")]
            for key in ("expression", "lighting", "camera_note"):
                if b.get(key):
                    parts.append(b[key])
            body = "，".join(p.rstrip("。，； ") for p in parts if p)
            lines.append(f"{round(t, 1)}-{round(t1, 1)}秒：{body}。")
            t = t1
        return "\n".join(lines), t

    t1 = t0 + shot.get("duration_sec", 3)
    cam = shot.get("camera", {})
    parts = [
        f"{SHOT_SIZE_ZH.get(shot.get('shot_size'), '')}"
        f"{('，' + ANGLE_ZH[cam['angle']]) if cam.get('angle') in ANGLE_ZH else ''}"
        f"{('，' + MOVEMENT_ZH[cam['movement']]) if cam.get('movement') in MOVEMENT_ZH else ''}",
        shot.get("action", ""),
    ]
    if shot.get("atmosphere"):
        parts.append(shot["atmosphere"])
    for d in shot.get("dialogue", []):
        who = d.get("character_ref", "")
        parts.append(f"{DIALOGUE_TYPE_ZH.get(d.get('type'), '台词')}"
                     f"（{who}，{d.get('emotion', '')}）：“{d['text']}”")
    body = "，".join(p.rstrip("。，； ") for p in parts if p)
    return f"{round(t0, 1)}-{round(t1, 1)}秒：{body}。", t1


def clip_prompt(clip: list, doc: dict, assets_idx: dict) -> tuple:
    """一个 clip → Seedance 时间轴提示词块 + 它引用的资产 ID 列表。"""
    style = doc["meta"]["style"]["style_prefix"]
    ar = doc["meta"].get("video", {}).get("aspect_ratio", "9:16")
    total = round(sum(s.get("duration_sec", 3) for s in clip), 1)
    first = clip[0]
    tod = TIME_ZH.get(first.get("time_of_day", ""), "")
    weather = first.get("weather", "")

    chars, locs, props = collect_refs(clip)
    refs, ref_lines = [], []
    n = 1
    for cid, outfit in chars:
        if cid in assets_idx["creatures"]:
            name = assets_idx["creatures"][cid].get("name", cid)
            ref_lines.append(f"@图片{n} 生物参考：{name}（{cid}），锁定生物外观")
        else:
            name = assets_idx["characters"].get(cid, {}).get("name", cid)
            outfit_note = f"，着装 {outfit}" if outfit else ""
            ref_lines.append(f"@图片{n} 角色参考：{name}（{cid}{outfit_note}），锁定人物外观")
        refs.append(cid)
        n += 1
    for lid, angle in locs:
        name = assets_idx["locations"].get(lid, {}).get("name", lid)
        ref_lines.append(f"@图片{n} 场景参考：{name}（{lid}，{angle} 机位），锁定环境")
        refs.append(lid)
        n += 1
    for pid, state in props:
        name = assets_idx["props"].get(pid, {}).get("name", pid)
        state_note = f"，状态 {state}" if state else ""
        ref_lines.append(f"@图片{n} 道具参考：{name}（{pid}{state_note}）")
        refs.append(pid)
        n += 1

    sfx, constraints = [], []
    for s in clip:
        for x in s.get("sfx", []):
            if x not in sfx:
                sfx.append(x)
        for x in s.get("constraints", []):
            if x not in constraints:
                constraints.append(x)

    head = (f"{style}，{total}秒，{ar}竖屏"
            + (f"，{tod}" if tod else "") + (f"，{weather}" if weather else ""))
    lines = [head, ""]
    t = 0.0
    for s in clip:
        line, t = shot_line(s, t)
        lines.append(line)
    lines.append("")
    if sfx:
        lines.append(f"【声音】{'，'.join(sfx)}（仅音效，不要音乐，不要字幕）")
    # 负面约束是 v0.5 新增的镜头级禁令，出图质量的一半毁在没有约束上
    if constraints:
        lines.append(f"【不要】{'；'.join(constraints)}")
    for rl in ref_lines:
        lines.append(f"【参考】{rl}")
    return "\n".join(lines), refs


def _asset_entries(doc: dict, used: set) -> list:
    """出图清单：先出图、再垫图生视频，所以资产图是整条链的第一步。

    带上已回填的 uri 与变体归属，界面才能一眼看出「还差几张图」。
    """
    out = []
    a = doc.get("assets") or {}
    for kind in ("characters", "locations", "props", "creatures"):
        for c in a.get(kind) or []:
            if c["id"] not in used:
                continue
            imgs = c.get("reference_images") or []
            entry = {
                "id": c["id"],
                "kind": kind,
                "kind_zh": KIND_ZH[kind],
                "name": c.get("name", c["id"]),
                "image_prompt": c.get("visual_prompt", ""),
                "variants": [{"id": v["id"], "description": v.get("description", "")}
                             for v in (c.get("outfits") or c.get("states") or [])],
                "constraints": c.get("constraints") or [],
                "images": [{"view": i.get("view"), "uri": i.get("uri"),
                            "variant": i.get("outfit") or i.get("state")}
                           for i in imgs],
                # 没声明槽位不等于不需要图：任何被镜头引用到的卡，至少得有一张
                # 才谈得上垫图。算成 0 需求会让人以为图已经够了。
                "have_images": sum(1 for i in imgs if i.get("uri")),
                "need_images": max(len(imgs), 1),
            }
            if kind == "locations":
                # 场景的设定图槽位是 angles（每个机位一张），不是 reference_images
                angles = c.get("angles") or []
                entry["angles"] = [x.get("angle") for x in angles]
                entry["have_images"] = sum(1 for x in angles if x.get("uri"))
                entry["images"] = [{"view": x.get("angle"), "uri": x.get("uri"),
                                    "variant": None} for x in angles]
                entry["need_images"] = max(len(angles), 1)
            out.append(entry)
    return out


def estimate(clips: list, asset_entries: list, model: str = DEFAULT_TIER,
             cny_per_second: Optional[float] = None,
             speech_cps: float = DEFAULT_SPEECH_CPS) -> dict:
    """费用估算。给区间而不是单一数字——一次过和抽三次差着三倍钱。

    cny_per_second 显式传入 > 环境变量标定值 > 按档位折算，三级覆盖。
    """
    tier = TIERS.get(model) or TIERS[DEFAULT_TIER]
    derived = tier["tokens_per_second"] * tier["cny_per_million_tokens"] / 1_000_000
    override = cny_per_second if cny_per_second is not None else _env_cny_per_second()
    per_sec = override if override is not None else derived

    seconds = round(sum(c["duration_sec"] for c in clips), 1)
    playable = round(sum(c.get("playable_sec", c["duration_sec"]) for c in clips), 1)
    once = playable * per_sec
    missing = sum(max(0, a["need_images"] - a["have_images"]) for a in asset_entries)
    caveats = [
        "分辨率未建模：token 消耗与分辨率强相关，这里只按秒数线性折算。",]
    if playable > seconds + 0.05:
        caveats.append(
            f"按「能念完旁白台词」的实际时长 {playable:g}s 计价，比分镜标称的 "
            f"{seconds:g}s 多 {playable - seconds:.0f}s——短于自身旁白的镜头，"
            f"成片时必须拉长。")
    caveats += [
        tier["caveat"],
        "资产出图费用未计入。",
    ]
    if override is not None:
        caveats.insert(0, "当前使用的是你指定的费率，不是推算值。")
    return {
        "clips": len(clips),
        "seconds": seconds,
        "playable_seconds": playable,
        "speech_overflow_sec": round(playable - seconds, 1),
        "asset_images_total": sum(a["need_images"] for a in asset_entries),
        "asset_images_missing": missing,
        "model": model if model in TIERS else DEFAULT_TIER,
        "model_label": tier["label"],
        "resolutions": tier["resolutions"],
        "speech_cps": speech_cps,
        "cny_per_second": round(per_sec, 4),
        "cny_once": round(once, 1),
        "cny_with_retries": round(once * RETRY_FACTOR, 1),
        "retry_factor": RETRY_FACTOR,
        "calibrated": override is not None,
        "rate": {"tokens_per_second": tier["tokens_per_second"],
                 "cny_per_million_tokens": tier["cny_per_million_tokens"],
                 "source": RATE_SOURCE},
        "caveats": caveats,
        "note": f"依据：{RATE_SOURCE}。实际以控制台账单为准；"
                f"拿一次真实调用的 token usage 反标定后，"
                f"用 STORYBOARD_RENDER_CNY_PER_SECOND 钉死即可。",
    }


def tiers() -> list:
    """给界面用的档位表。"""
    return [{"id": k, "label": v["label"], "resolutions": v["resolutions"],
             "cny_per_second": round(v["tokens_per_second"]
                                     * v["cny_per_million_tokens"] / 1_000_000, 4)}
            for k, v in TIERS.items()]


def build_plan(doc: dict, max_clip_seconds: float = DEFAULT_MAX_CLIP_SECONDS,
               run_id: Optional[str] = None, model: str = DEFAULT_TIER,
               cny_per_second: Optional[float] = None,
               speech_cps: float = DEFAULT_SPEECH_CPS) -> dict:
    """IR → 渲染任务清单（机器可读）。"""
    assets_idx = assets_index(doc)
    meta = doc.get("meta") or {}
    clips_out, used = [], set()

    for ep in doc.get("episodes") or []:
        t0 = 0.0
        for i, clip in enumerate(pack_clips(ep.get("shots") or [], max_clip_seconds), 1):
            prompt, refs = clip_prompt(clip, doc, assets_idx)
            dur = round(sum(s.get("duration_sec", 3) for s in clip), 1)
            # 账要按能真正播出来的时长算：镜头短于它自己的旁白，成片时要么截断
            # 语音、要么被迫拉长，按名义时长做的预算当场失准
            playable = round(sum(max(s.get("duration_sec", 3),
                                     speech_seconds(s, speech_cps)) for s in clip), 1)
            narration = []
            for s in clip:
                n = s.get("narration") or {}
                if n.get("text"):
                    narration.append({"shot": s.get("id"), "text": n["text"],
                                      "order": n.get("order")})
            clips_out.append({
                "id": f"{ep['id']}-C{i:02d}",
                "episode": ep["id"],
                "shots": [s.get("id") for s in clip],
                "start_sec": round(t0, 1),
                "duration_sec": dur,
                "playable_sec": playable,
                "speech_overflow": round(playable - dur, 1),
                "prompt": prompt,
                "reference_assets": refs,
                "narration": narration,
            })
            t0 += dur
            used.update(refs)

    asset_entries = _asset_entries(doc, used)
    return {
        "plan_version": "1",
        "run_id": run_id,
        "work_title": meta.get("title", ""),
        "chapter": (doc.get("source") or {}).get("chapter", ""),
        "schema_version": meta.get("schema_version", ""),
        "style_prefix": (meta.get("style") or {}).get("style_prefix", ""),
        "video": meta.get("video") or {"aspect_ratio": "9:16"},
        "max_clip_seconds": max_clip_seconds,
        "assets": asset_entries,
        "clips": clips_out,
        "estimate": estimate(clips_out, asset_entries, model, cny_per_second,
                             speech_cps),
        "tiers": tiers(),
    }
