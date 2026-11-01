"""导出剪辑工程（FCPXML 1.10）：纯函数生成 XML 与说明；export 负责预渲染提速配音、打包。"""
import xml.etree.ElementTree as ET


def tf(n: int, fps: int = 30) -> str:
    """帧数 -> FCPXML 时间写法。"""
    return "0s" if n == 0 else f"{n}/{fps}s"


def tc(sec: float, fps: int = 30) -> str:
    return tf(round(sec * fps), fps)


def build_fcpxml(timeline: dict, media: dict, *, event: str = "Storyboard") -> str:
    fps = timeline["fps"]
    w, h = timeline["size"]
    root = ET.Element("fcpxml", version="1.10")
    res = ET.SubElement(root, "resources")
    ET.SubElement(res, "format", id="r1", frameDuration=f"1/{fps}s", width=str(w), height=str(h))
    ids = {}

    def asset(path: str) -> str:
        if path not in ids:
            m = media[path]
            ids[path] = f"a{len(ids) + 1}"
            a = ET.SubElement(res, "asset", id=ids[path], name=m["rel"].rsplit("/", 1)[-1].rsplit(".", 1)[0],
                              start="0s", duration=tc(m["seconds"], fps),
                              hasVideo="1" if m["video"] else "0", hasAudio="1" if m["audio"] else "0")
            if m["video"]:
                a.set("format", "r1")
            if m["audio"]:
                a.set("audioSources", "1")
                a.set("audioChannels", "2")
                a.set("audioRate", "48000")
            ET.SubElement(a, "media-rep", kind="original-media", src=m["rel"])
        return ids[path]

    lib = ET.SubElement(root, "library")
    ev = ET.SubElement(lib, "event", name=event)
    for ep in timeline["episodes"]:
        proj = ET.SubElement(ev, "project", name=ep["episode"])
        segs = ep["segments"]
        # 段边界按帧累计取整：相邻段首尾相接，不留缝也不重叠
        bounds = [round(sg["start"] * fps) for sg in segs]
        total_f = round(ep["total"] * fps)
        bounds.append(max(total_f, bounds[-1]) if bounds else total_f)
        seq = ET.SubElement(proj, "sequence", format="r1", duration=tf(bounds[-1], fps), tcStart="0s",
                            tcFormat="NDF", audioLayout="stereo", audioRate="48k")
        spine = ET.SubElement(seq, "spine")
        clips = []
        for i, seg in enumerate(segs):
            c = ET.SubElement(spine, "asset-clip", ref=asset(seg["file"]), name=seg["clip"],
                              offset=tf(bounds[i], fps), start="0s", duration=tf(bounds[i + 1] - bounds[i], fps),
                              format="r1", tcFormat="NDF")
            clips.append(c)
        for sp in ep["speech"]:
            if not clips:
                raise ValueError(f"{ep['episode']} 有配音但没有视频段")
            f = round(sp["start"] * fps)
            i = next((k for k in range(len(clips)) if bounds[k] <= f < bounds[k + 1]), len(clips) - 1)
            ET.SubElement(clips[i], "asset-clip", ref=asset(sp["file"]), name=sp["line"], lane="-1",
                          offset=tf(f - bounds[i], fps), start="0s",
                          duration=tf(max(1, round(sp["duration"] * fps)), fps))
        if ep.get("bgm") and clips:
            b = ET.SubElement(clips[0], "asset-clip", ref=asset(ep["bgm"]), name=f"BGM {ep['episode']}",
                              lane="-2", offset="0s", start="0s", duration=tf(bounds[-1], fps))
            ET.SubElement(b, "adjust-volume", amount=f"{timeline['bgm_db']}dB")
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + ET.tostring(root, encoding="unicode") + "\n"


def readme(timeline: dict, title: str) -> str:
    ph = [f"{ep['episode']}/{s['clip']}" for ep in timeline["episodes"] for s in ep["segments"] if s.get("placeholder")]
    zh = [
        f"《{title}》剪辑工程说明",
        "",
        "- Final Cut Pro 导入：文件 -> 导入 -> XML，选择本包里的 .fcpxml。",
        "- DaVinci Resolve 导入：文件 -> 导入 -> 时间线，选择本包里的 .fcpxml。",
        "- 若素材显示离线，请把整个 media/ 文件夹重新链接上。",
        "- 字幕在 subtitles/*.srt，需要手动导入。",
        "- 最终导出时请自己做响度归一，目标 -16 LUFS。",
    ]
    en = [
        f"{title} - edit project notes",
        "",
        "- Final Cut Pro: File -> Import -> XML, and pick the .fcpxml in this package.",
        "- DaVinci Resolve: File -> Import -> Timeline, and pick the .fcpxml in this package.",
        "- If media shows as offline, relink the whole media/ folder.",
        "- Subtitles are in subtitles/*.srt and must be imported manually.",
        "- Normalize loudness yourself on final export; target -16 LUFS.",
    ]
    if ph:
        zh.append("- 这些段用的是关键帧静帧占位：" + " ".join(ph))
        en.append("- These segments use keyframe stills as placeholders: " + " ".join(ph))
    return "\n".join(zh) + "\n\n----\n\n" + "\n".join(en) + "\n"
