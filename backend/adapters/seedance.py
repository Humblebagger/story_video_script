#!/usr/bin/env python3
"""NovelStoryboard → Seedance 2.0 生产包 适配器（人读版）。

clip 打包与提示词组装共用 render/plan.py——机器可读的渲染任务清单与这份
Markdown 必须是同一句提示词，否则人眼在这里核对过的东西跟真发出去的不是一回事。

用法: python3 adapters/seedance.py <storyboard.json> [--out <dir>] [--max-clip-seconds 15]

对每个 episode 输出一份 Markdown 生产包（<out>/<E01>_seedance.md），结构按制作流程排序：
  速览   本集时长/镜头/资产/基调一览 + 四步使用指南（文档入口）
  一     素材出图清单 —— 角色/场景/生物/道具的出图提示词（先出图，再垫图生视频）
  二     分 clip 的 Seedance 2.0 时间轴提示词 —— 镜头自动打包为 ≤max 秒的 clip，
         标题带成片秒区间与场景，含【声音】音效行、【参考】垫图行；clip 2+ 附抽帧接力说明
  三     旁白与配音稿 —— 按镜头顺序、含 narration.order 排序的 TTS 稿
  四     BGM 提示 —— 主基调 + 秒级情绪曲线分段
  附     尾帧描述 —— 跨集衔接用
"""
import argparse
import json
import sys
from pathlib import Path

# 以脚本方式运行时 sys.path[0] 是 adapters/，要把仓库根加进来才 import 得到 render
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from render.plan import (  # noqa: E402
    ANGLE_ZH, DIALOGUE_TYPE_ZH, MOVEMENT_ZH, SHOT_SIZE_ZH, TIME_ZH,
    assets_index, clip_prompt, collect_refs, pack_clips, shot_line,
)

def overview_section(doc, ep, clips, assets_idx, used_ids):
    """本集速览：一屏看清本集是什么、有多少东西、怎么用这份文档。"""
    shots = ep.get("shots", [])
    total = sum(s.get("duration_sec", 3) for s in shots)
    mm, ss = int(total // 60), round(total % 60)
    names = lambda kind: "、".join(v["name"] for k, v in assets_idx[kind].items() if k in used_ids)
    mood = MOOD_ZH.get(ep.get("music", {}).get("mood"), "")
    out = ["## 本集速览", ""]
    if ep.get("summary"):
        out += [f"> {ep['summary']}", ""]
    out += ["| 项 | 值 |", "|---|---|"]
    out.append(f"| 成片时长 | 约 {mm} 分 {ss} 秒（{len(shots)} 个镜头，打包 {len(clips)} 个 clip） |")
    sr = ep.get("source_range", {})
    out.append(f"| 覆盖原文 | {doc['source'].get('work_title', '')} {sr.get('from_unit', '')}–{sr.get('to_unit', '')} |")
    if mood:
        out.append(f"| 情绪主基调 | {mood} |")
    for label, kind in (("出场角色", "characters"), ("场景", "locations"),
                        ("生物", "creatures"), ("关键道具", "props")):
        if names(kind):
            out.append(f"| {label} | {names(kind)} |")
    out += ["", "## 怎么用这份文档（按顺序四步）", ""]
    out += [
        "1. **出素材** → 第一节：先把本集全部角色/场景/道具参考图生成好——后面每个 clip 都靠这些图锁外观",
        "2. **逐 clip 生视频** → 第二节：从 Clip 1 起按顺序，把代码块整段发给 Seedance，按【参考】行上传对应参考图；clip 之间按\"衔接\"提示做尾帧接力",
        "3. **配音** → 第三节：旁白与台词逐条 TTS（已标角色、情绪、音色提示与先后顺序）",
        "4. **配乐混音** → 第四节：按秒级分段的情绪曲线选曲/生成 BGM，与成片对齐",
        "",
        "文末【附】是本集尾帧描述，供下一集开头抽帧接力，本集制作用不到。",
        "",
    ]
    return out


def asset_section(doc, used_ids):
    """素材生成清单：只列本集用到的资产。"""
    out = ["## 一、素材出图清单（先用出图模型生成，再作为参考图上传）", ""]
    a = doc["assets"]
    for c in a.get("characters", []):
        if c["id"] in used_ids:
            out.append(f"### {c['id']} {c['name']}（角色）")
            out.append(f"- 出图提示词：{c['visual_prompt']}")
            for o in c.get("outfits", []):
                out.append(f"- 着装[{o['id']}]：{o['description']}")
            out.append("")
    for s in a.get("locations", []):
        if s["id"] in used_ids:
            out.append(f"### {s['id']} {s['name']}（场景）")
            out.append(f"- 出图提示词：{s['visual_prompt']}")
            angles = "、".join(x.get("angle", "") for x in s.get("angles", []))
            if angles:
                out.append(f"- 需生成机位版本：{angles}")
            if s.get("lighting_defaults"):
                out.append(f"- 默认光线：{s['lighting_defaults']}")
            out.append("")
    for cr in a.get("creatures", []):
        if cr["id"] in used_ids:
            out.append(f"### {cr['id']} {cr['name']}（生物）")
            out.append(f"- 出图提示词：{cr['visual_prompt']}")
            if cr.get("notes"):
                out.append(f"- 备注：{cr['notes']}")
            out.append("")
    for p in a.get("props", []):
        if p["id"] in used_ids:
            out.append(f"### {p['id']} {p['name']}（道具）")
            out.append(f"- 出图提示词：{p['visual_prompt']}")
            for st in p.get("states", []):
                out.append(f"- 状态[{st['id']}]：{st['description']}")
            out.append("")
    return out


MOOD_ZH = {
    "calm": "平静", "warm": "温情", "playful": "轻快", "tense": "紧张",
    "ominous": "压抑不祥", "eerie": "诡异", "sorrow": "悲恸",
    "melancholy": "惆怅", "triumph": "激昂", "epic": "恢弘",
}
INTENSITY_ZH = {"low": "弱", "mid": "中", "high": "强"}


def music_section(ep):
    """BGM 提示：主基调 + 情绪曲线分段（选曲/AI 配乐依据）。"""
    music = ep.get("music")
    if not music:
        return []
    out = ["## 四、BGM 提示（选曲/配乐生成依据）", ""]
    out.append(f"- 本集主基调：{MOOD_ZH.get(music.get('mood'), music.get('mood', ''))}")
    if music.get("style_hint"):
        out.append(f"- 配器/风格：{music['style_hint']}")
    shots = {s.get("id"): s for s in ep.get("shots", [])}
    t = 0.0
    starts = {}
    for s in ep.get("shots", []):
        starts[s.get("id")] = t
        t += s.get("duration_sec", 3)
    for seg in music.get("curve", []):
        f, to = seg.get("from_shot"), seg.get("to_shot")
        t0 = starts.get(f)
        t1 = None
        if to in starts:
            t1 = starts[to] + shots[to].get("duration_sec", 3)
        span = f"{round(t0, 1)}–{round(t1, 1)}秒" if t0 is not None and t1 is not None else ""
        mood = MOOD_ZH.get(seg.get("mood"), seg.get("mood", ""))
        inten = INTENSITY_ZH.get(seg.get("intensity"), "")
        note = f" —— {seg['note']}" if seg.get("note") else ""
        out.append(f"- {f}–{to}（{span}）：{mood}·{inten}{note}")
    out.append("")
    return out


def narration_script(ep, units_idx, chars_idx):
    """旁白稿：按镜头顺序输出旁白句 + 台词（标注音色）。"""
    out = ["## 三、旁白与配音稿（TTS 用，逐条按序）", ""]
    for shot in ep.get("shots", []):
        narr = shot.get("narration", {})
        narr_line = f"- 〔旁白｜{shot['id']}〕{narr['text']}" if narr.get("text") else None
        if narr_line and narr.get("order") != "after_dialogue":
            out.append(narr_line)
        for d in shot.get("dialogue", []):
            who = chars_idx.get(d.get("character_ref", ""), {}).get("name", d.get("character_ref", ""))
            voice = chars_idx.get(d.get("character_ref", ""), {}).get("voice", {})
            tone = voice.get("tone", "")
            out.append(f"- 〔{DIALOGUE_TYPE_ZH.get(d.get('type'), '台词')}｜{who}｜{d.get('emotion', '')}"
                       + (f"｜音色提示：{tone}" if tone else "") + f"〕{d['text']}")
        if narr_line and narr.get("order") == "after_dialogue":
            out.append(narr_line)
    out.append("")
    return out


def render_episode(doc, ep, max_clip_seconds):
    assets_idx = assets_index(doc)
    units_idx = {u["id"]: u for u in doc.get("source", {}).get("units", [])}
    clips = pack_clips(ep.get("shots", []), max_clip_seconds)

    used = set()
    for shot in ep.get("shots", []):
        used.update(c["ref"] for c in shot.get("characters", []))
        if shot.get("location_ref"):
            used.add(shot["location_ref"])
        used.update(p["ref"] if isinstance(p, dict) else p for p in shot.get("prop_refs", []))

    md = [f"# {doc['meta']['title']} · {ep['id']} {ep.get('title', '')} —— Seedance 2.0 生产包", ""]
    md += overview_section(doc, ep, clips, assets_idx, used)
    md += asset_section(doc, used)

    md.append(f"## 二、Seedance 时间轴提示词（按 clip 依次生成，单 clip ≤{max_clip_seconds:g}s）")
    md.append("")
    t0 = 0.0
    for i, clip in enumerate(clips, 1):
        dur = round(sum(s.get("duration_sec", 3) for s in clip), 1)
        locs_in_clip = []
        for s in clip:
            name = assets_idx["locations"].get(s.get("location_ref"), {}).get("name")
            if name and name not in locs_in_clip:
                locs_in_clip.append(name)
        span = clip[0]["id"] if len(clip) == 1 else f"{clip[0]['id']}–{clip[-1]['id']}"
        loc = "/".join(locs_in_clip)
        md.append(f"### Clip {i}/{len(clips)}（{span} · "
                  f"成片 {round(t0, 1)}–{round(t0 + dur, 1)}s" + (f" · {loc}" if loc else "") + "）")
        t0 += dur
        md.append("")
        if i > 1:
            md.append("> 衔接：上传上一 clip 成片，使用「将@视频1延长」；或截取上一 clip 尾帧作为本 clip 首帧参考图上传。")
            md.append("")
        prompt, _ = clip_prompt(clip, doc, assets_idx)
        md.append("```")
        md.append(prompt)
        md.append("```")
        md.append("")

    md += narration_script(ep, units_idx, assets_idx["characters"])
    md += music_section(ep)
    md.append("## 附 · 尾帧描述（下一集抽帧接力用，本集制作不涉及）")
    md.append("")
    md.append(ep.get("tail_frame_description", "（未提供）"))
    md.append("")
    return "\n".join(md)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("storyboard")
    ap.add_argument("--out", default="out")
    ap.add_argument("--max-clip-seconds", type=float, default=15)
    args = ap.parse_args()

    src = Path(args.storyboard)
    doc = json.loads(src.read_text(encoding="utf-8"))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for ep in doc.get("episodes", []):
        path = out_dir / f"{src.stem}_{ep['id']}_seedance.md"
        path.write_text(render_episode(doc, ep, args.max_clip_seconds), encoding="utf-8")
        print(f"已生成 {path}")


if __name__ == "__main__":
    main()
