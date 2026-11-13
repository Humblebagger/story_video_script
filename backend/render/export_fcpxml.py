"""导出剪辑工程（FCPXML 1.10）：纯函数生成 XML 与说明；export 负责预渲染提速配音、打包。"""
import hashlib
import json
import re
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from urllib.parse import quote

from render import mix
from server.messages import UserError


class ExportError(UserError, Exception):
    """导出失败：message 给用户看（带代码，见 UserError）；stderr 是 ffmpeg 的错误输出（截尾）。"""

    def __init__(self, msg: str, stderr: str = ""):
        super().__init__(msg)
        self.stderr = stderr


def tf(n: int, fps: int = 30) -> str:
    """帧数 -> FCPXML 时间写法。"""
    return "0s" if n == 0 else f"{n}/{fps}s"


def tc(sec: float, fps: int = 30) -> str:
    return tf(round(sec * fps), fps)


def speech_key(sp: dict) -> str:
    """配音在 media 里的键：同一个源文件不同倍速是不同的素材。"""
    return sp["file"] if sp["speed"] == 1 else f"{sp['file']}@{sp['speed']}"


def build_fcpxml(timeline: dict, media: dict, *, event: str = "Storyboard") -> str:
    fps = timeline["fps"]
    w, h = timeline["size"]
    root = ET.Element("fcpxml", version="1.10")
    res = ET.SubElement(root, "resources")
    ET.SubElement(res, "format", id="r1", frameDuration=f"1/{fps}s", width=str(w), height=str(h))
    bgms: set[str] = set()
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
                raise ValueError(f"{ep['episode']} 有配音但没有视频段")  # i18n: internal
            f = round(sp["start"] * fps)
            i = next((k for k in range(len(clips)) if bounds[k] <= f < bounds[k + 1]), len(clips) - 1)
            d = max(1, round(sp["duration"] * fps))
            ET.SubElement(clips[i], "asset-clip", ref=asset(speech_key(sp)), name=sp["line"], lane="-1",
                          offset=tf(f - bounds[i], fps), start="0s", duration=tf(d, fps))
            use(speech_key(sp), d)
        if ep.get("bgm") and clips:
            # 成片里 BGM 是 -stream_loop 循环再裁到总长：工程里也首尾相接地重复，最后一段裁到总长
            bgms.add(ep["bgm"])
            bl = max(1, round(media[ep["bgm"]]["seconds"] * fps))
            aid = asset(ep["bgm"])
            for k in range(-(-bounds[-1] // bl)):
                b = ET.SubElement(clips[0], "asset-clip", ref=aid, name=f"BGM {ep['episode']}",
                                  lane="-2", offset=tf(k * bl, fps), start="0s",
                                  duration=tf(min(bl, bounds[-1] - k * bl), fps))
                ET.SubElement(b, "adjust-volume", amount=f"{timeline['bgm_db']}dB")
    for path, a in els.items():
        # BGM 素材时长就是实测值（循环铺满，不拉长）；其余素材不得短于用到的帧数
        n = round(media[path]["seconds"] * fps)
        a.set("duration", tf(n if path in bgms else max(n, used.get(path, 0)), fps))
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + ET.tostring(root, encoding="unicode") + "\n"


def readme(timeline: dict, title: str, extras=(), lang=None) -> str:
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
    if extras:
        zh.append("- 补拍素材（不在时间线上，请自己摆位置）：")
        en.append("- Extra footage (not on the timeline; place it yourself):")
        for rel, line in extras:
            zh.append(f"  - {rel}  {line}")
            en.append(f"  - {rel}  {line}")
    if lang == "zh":
        return "\n".join(zh) + "\n"
    if lang == "en":
        return "\n".join(en) + "\n"
    return "\n".join(zh) + "\n\n----\n\n" + "\n".join(en) + "\n"


def extra_media(root) -> list:
    """独立素材（没挂靠的自由节点）采用的那次视频：[(包内路径, 磁盘文件, 提示词首行)]。
    文件缺了就不附带，不拦导出；挂靠节点的结果已是剧本段的尝试，不重复导出。"""
    try:
        s = json.loads((Path(root) / "session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for n in s.get("free") or []:
        # 会话文件被改坏时跳过这一个节点，不拦导出
        if not isinstance(n, dict) or not isinstance(n.get("id"), str):
            continue
        k, atts = n.get("chosen"), n.get("attempts")
        if n.get("target") or isinstance(k, bool) or not isinstance(k, int) or not isinstance(atts, list) \
                or not (0 <= k < len(atts)):
            continue
        a = atts[k]
        if not isinstance(a, dict) or not isinstance(a.get("file"), str) or not a["file"]:
            continue
        disk = Path(root) / a["file"]
        if a.get("state") != "succeeded" or not disk.is_file():
            continue
        lines = str(n.get("prompt") or "").strip().splitlines()
        out.append((f"media/extra/{n['id']}.mp4", disk, lines[0] if lines else ""))
    return out


def _fast_voice(src: Path, speed: float, cache: Path, line: str, ffmpeg: str) -> Path:
    """speed > 1 的配音用 atempo 预渲染成独立文件（剪辑软件里没有这个提速）；按源文件与倍速缓存。"""
    st = src.stat()
    key = hashlib.sha256(f"{src}|{st.st_size}|{st.st_mtime_ns}|{speed}".encode()).hexdigest()[:16]
    out = cache / f"{key}.wav"
    if out.exists():
        return out
    cache.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(suffix=".wav", prefix=f"{key}.part.", dir=cache)
    os.close(fd)
    tmp = Path(name)
    try:
        r = subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(src), "-filter:a", f"atempo={speed}",
                            "-ar", "48000", str(tmp)], capture_output=True, text=True)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise ExportError.of("export.voice_prerender", str(e), line=line)
    if r.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise ExportError.of("export.voice_prerender", (r.stderr or "")[-4000:], line=line)
    tmp.replace(out)
    return out


def export(root, *, title: str, tools: tuple, lang=None) -> Path:
    """读 final/timeline.json，准备素材（提速配音预渲染并缓存），打包成 final/export/<安全名>.zip。"""
    root = Path(root)
    lang = lang if lang in ("zh", "en") else None
    ffmpeg, ffprobe = tools
    tl_path = root / "final" / "timeline.json"
    if not tl_path.is_file():
        raise ExportError.of("export.no_timeline")
    tl = json.loads(tl_path.read_text(encoding="utf-8"))
    export_dir = root / "final" / "export"
    media, files = {}, {}     # media：时间轴原路径 -> 描述；files：包内相对路径 -> 磁盘文件

    def put(key: str, rel: str, disk: Path, *, video: bool) -> None:
        if key in media:
            return
        if not disk.is_file():
            raise ExportError.of("export.missing_file", file=rel)
        media[key] = {"rel": rel, "seconds": mix.media_seconds(disk, ffprobe), "audio": True, "video": video}
        files[rel] = disk

    for ep in tl["episodes"]:
        for sg in ep["segments"]:
            put(sg["file"], f"media/clips/{sg['clip']}.mp4", root / sg["file"], video=True)
        for sp in ep["speech"]:
            key = speech_key(sp)
            if key in media:
                continue
            src = root / sp["file"]
            if not src.is_file():
                raise ExportError.of("export.missing_file", file=sp["file"])
            disk = src if sp["speed"] == 1 else _fast_voice(src, sp["speed"], export_dir / "voice",
                                                            sp["line"], ffmpeg)
            put(key, f"media/voice/{sp['line']}.wav", disk, video=False)
        if ep.get("bgm"):
            put(ep["bgm"], f"media/bgm/{ep['episode']}{Path(ep['bgm']).suffix}", root / ep["bgm"], video=False)

    extras = extra_media(root)
    for rel, disk, _line in extras:
        files[rel] = disk
    xml = build_fcpxml(tl, media, event=title)
    text = readme(tl, title, [(rel, line) for rel, _disk, line in extras], lang)
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", title)[:80].strip(". _")
    if not safe.strip("."):
        safe = "storyboard-export"
    export_dir.mkdir(parents=True, exist_ok=True)
    zip_name = f"{safe}.{lang}.zip" if lang else f"{safe}.zip"
    out = export_dir / zip_name
    fd, name = tempfile.mkstemp(suffix=".part", prefix=f"{zip_name}.", dir=export_dir)
    os.close(fd)
    tmp = Path(name)
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
