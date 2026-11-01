"""导出剪辑工程（FCPXML 1.10）：纯函数生成 XML 与说明；export 负责预渲染提速配音、打包。"""
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from urllib.parse import quote

from render import mix


class ExportError(Exception):
    def __init__(self, msg: str, stderr: str = ""):
        super().__init__(msg)
        self.stderr = stderr


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
    ids, els, used = {}, {}, {}      # used：素材被时间轴用到的最大结束帧，素材时长不得短于它

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
            ET.SubElement(a, "media-rep", kind="original-media", src=quote(m["rel"]))
            els[path] = a
        return ids[path]

    def use(path: str, end_f: int) -> None:
        used[path] = max(used.get(path, 0), end_f)

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
            use(seg["file"], bounds[i + 1] - bounds[i])
        for sp in ep["speech"]:
            if not clips:
                raise ValueError(f"{ep['episode']} 有配音但没有视频段")
            f = round(sp["start"] * fps)
            i = next((k for k in range(len(clips)) if bounds[k] <= f < bounds[k + 1]), len(clips) - 1)
            d = max(1, round(sp["duration"] * fps))
            ET.SubElement(clips[i], "asset-clip", ref=asset(sp["file"]), name=sp["line"], lane="-1",
                          offset=tf(f - bounds[i], fps), start="0s", duration=tf(d, fps))
            use(sp["file"], d)
        if ep.get("bgm") and clips:
            b = ET.SubElement(clips[0], "asset-clip", ref=asset(ep["bgm"]), name=f"BGM {ep['episode']}",
                              lane="-2", offset="0s", start="0s", duration=tf(bounds[-1], fps))
            ET.SubElement(b, "adjust-volume", amount=f"{timeline['bgm_db']}dB")
            use(ep["bgm"], bounds[-1])
    for path, a in els.items():
        a.set("duration", tf(max(round(media[path]["seconds"] * fps), used.get(path, 0)), fps))
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


def _fast_voice(src: Path, speed: float, cache: Path, line: str, ffmpeg: str) -> Path:
    """speed > 1 的配音用 atempo 预渲染成独立文件（剪辑软件里没有这个提速）；按源文件与倍速缓存。"""
    st = src.stat()
    key = hashlib.sha256(f"{src}|{st.st_size}|{st.st_mtime_ns}|{speed}".encode()).hexdigest()[:16]
    out = cache / f"{key}.wav"
    if out.exists():
        return out
    cache.mkdir(parents=True, exist_ok=True)
    tmp = cache / f"{key}.part.wav"
    r = subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(src), "-filter:a", f"atempo={speed}",
                        "-ar", "48000", str(tmp)], capture_output=True, text=True)
    if r.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise ExportError(f"预渲染配音 {line} 失败", (r.stderr or "")[-4000:])
    tmp.replace(out)
    return out


def export(root, *, title: str, tools: tuple) -> Path:
    """读 final/timeline.json，准备素材（提速配音预渲染并缓存），打包成 final/export/<安全名>.zip。"""
    root = Path(root)
    ffmpeg, ffprobe = tools
    tl_path = root / "final" / "timeline.json"
    if not tl_path.is_file():
        raise ExportError("这份成片是旧版合成的，重新合成一次即可导出（会复用已有配音与规整结果，不花钱）")
    tl = json.loads(tl_path.read_text(encoding="utf-8"))
    export_dir = root / "final" / "export"
    media, files = {}, {}     # media：时间轴原路径 -> 描述；files：包内相对路径 -> 磁盘文件

    def put(key: str, rel: str, disk: Path, *, video: bool) -> None:
        if key in media:
            return
        media[key] = {"rel": rel, "seconds": mix.media_seconds(disk, ffprobe), "audio": True, "video": video}
        files[rel] = disk

    for ep in tl["episodes"]:
        for sg in ep["segments"]:
            put(sg["file"], f"media/clips/{sg['clip']}.mp4", root / sg["file"], video=True)
        for sp in ep["speech"]:
            src = root / sp["file"]
            disk = src if sp["speed"] == 1 else _fast_voice(src, sp["speed"], export_dir / "voice",
                                                            sp["line"], ffmpeg)
            put(sp["file"], f"media/voice/{sp['line']}.wav", disk, video=False)
        if ep.get("bgm"):
            put(ep["bgm"], f"media/bgm/{ep['episode']}{Path(ep['bgm']).suffix}", root / ep["bgm"], video=False)

    xml = build_fcpxml(tl, media, event=title)
    text = readme(tl, title)
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", title)[:80]
    export_dir.mkdir(parents=True, exist_ok=True)
    out = export_dir / f"{safe}.zip"
    tmp = export_dir / f"{safe}.zip.part"
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
            z.writestr(f"{safe}/project.fcpxml", xml)
            z.writestr(f"{safe}/README.txt", text)
            for ep in tl["episodes"]:
                srt = root / "final" / f"{ep['episode']}.srt"
                if srt.is_file():
                    z.write(srt, f"{safe}/subtitles/{ep['episode']}.srt")
            for rel, disk in files.items():
                z.write(disk, f"{safe}/{rel}")
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
    return out
