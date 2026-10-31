"""出片合成（设计文档 3.3–3.5）：规划（纯函数）、ffmpeg 参数（纯函数）与执行。

规划：每集按镜头顺序排开，镜头时长取可播时长；本镜头的语音（TTS 用真实时长，原声或不出声的按字数估）
念不完时，先把语速提到最多 1.15 倍，还不够就按 1.15 倍念、把所在段的尾帧定格延长到念完，语音不截断。
段视频规整到计划长度：短了尾帧定格补齐，长了裁掉。段内各镜头的切换时刻由视频模型决定，台词按计划
镜头起点放置，属近似对齐（报告里写明）。
"""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from pipeline.quality import DEFAULT_SPEECH_CPS
from render import compose as shotcalc, voice

FPS = 30
SPEEDUP_MAX = 1.15
NATIVE_DB = -12          # tts_all：视频原声压成环境音
BGM_DB = -14
LUFS = -16
AUDIO_RATE = 48000
SHORT_SIDE = {"480p": 480, "720p": 720, "1080p": 1080}


class MixError(Exception):
    """合成失败：message 给用户看；stderr 是 ffmpeg 的错误输出（截尾）。"""

    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.stderr = stderr


def _even(x: float) -> int:
    return int(round(x / 2)) * 2


def frame_size(resolution: str, aspect: str) -> tuple:
    """(宽, 高)：短边按分辨率档（480p/720p/1080p），长边按画幅，取偶数。"""
    short = SHORT_SIDE.get(resolution, 720)
    try:
        a, b = (float(n) for n in (aspect or "9:16").split(":"))
    except ValueError:
        a, b = 9.0, 16.0
    if a <= 0 or b <= 0:
        a, b = 9.0, 16.0
    if a <= b:
        return short, _even(short * b / a)
    return _even(short * a / b), short


def native_audio_policy(audio_mode: str, mute: bool) -> Optional[float]:
    """视频原声的音量（dB）；None 为不要原声（无声模式，或 tts_all 下这一段设了原声静音）。"""
    if audio_mode == "silent" or (audio_mode == "tts_all" and mute):
        return None
    return float(NATIVE_DB) if audio_mode == "tts_all" else 0.0


def plan_episode(ep: dict, clips: list, voiced: dict, cps: float = DEFAULT_SPEECH_CPS) -> dict:
    """一集的合成计划。

    ep：分镜的一集；clips：本集的段（session.json 的 clips，按顺序）；voiced：语音条 id → 合成结果
    （含 duration、file）。不在 voiced 里的语音条按字数估时长，只进字幕。
    返回 {"episode", "total", "segments": [{"clip", "start", "duration", "base"}],
          "speech": [{"line", "file", "start", "speed"}], "subs": [{"start", "end", "text", "line"}],
          "notes": [{"shot", "kind": "speedup"|"freeze", "speed", "extend"?}]}
    """
    by_shot = {}
    for line in voice.speech_lines({"episodes": [ep]}):
        by_shot.setdefault(line["shot"], []).append(line)
    shots = {s["id"]: s for s in ep.get("shots") or []}
    t = 0.0
    segments, speech, subs, notes = [], [], [], []
    for c in clips:
        start, base = t, 0.0
        for sid in c["shots"]:
            shot = shots.get(sid)
            if shot is None:
                continue
            p = shotcalc.playable(shot, cps)
            base += p
            lines = by_shot.get(sid, [])
            durs = [voiced[x["id"]]["duration"] if x["id"] in voiced else len(x["text"]) / cps for x in lines]
            need = sum(durs)
            speed, eff = 1.0, p
            if need > p + 1e-9:
                if need <= p * SPEEDUP_MAX + 1e-9:
                    speed = need / p
                    notes.append({"shot": sid, "kind": "speedup", "speed": round(speed, 3)})
                else:
                    speed = SPEEDUP_MAX
                    eff = need / SPEEDUP_MAX
                    notes.append({"shot": sid, "kind": "freeze", "speed": SPEEDUP_MAX,
                                  "extend": round(eff - p, 2)})
            at = t
            for x, d in zip(lines, durs):
                dur = d / speed
                subs.append({"start": at, "end": at + dur, "text": x["text"], "line": x["id"]})
                if x["id"] in voiced:
                    speech.append({"line": x["id"], "file": str(voiced[x["id"]]["file"]), "start": at,
                                   "speed": speed})
                at += dur
            t += eff
        segments.append({"clip": c["id"], "start": round(start, 3), "duration": round(t - start, 3),
                         "base": round(base, 3)})
    return {"episode": ep["id"], "total": round(t, 3), "segments": segments, "speech": speech,
            "subs": subs, "notes": notes}


def _ts(sec: float) -> str:
    ms = int(round(max(0.0, sec) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt(subs: list) -> str:
    return "".join(f"{i}\n{_ts(x['start'])} --> {_ts(x['end'])}\n{x['text']}\n\n"
                   for i, x in enumerate(subs, 1))


# ---------- ffmpeg 参数（纯函数） ----------

def normalize_cmd(src: Optional[str], *, still: Optional[str], duration: float, size: tuple,
                  native_db: Optional[float], has_audio: bool, out: str, ffmpeg: str = "ffmpeg") -> list:
    """一段规整成统一尺寸、30 fps、48k 立体声，长度正好 duration：短了尾帧定格，长了裁掉。

    src 为段视频；没有视频时用 still（关键帧图）定格，再没有就黑场（草稿合成补位）。
    native_db 为原声音量，None 或源视频没有音轨时用静音轨（拼接要求每段都有音轨）。
    """
    w, h = size
    d = f"{duration:.3f}"
    fit = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
           f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS},"
           f"scale=out_range=tv,format=yuv420p")     # 关键帧图（全范围 JPEG/PNG）与视频统一色域
    if src:
        inputs = ["-i", src]
        vf = f"[0:v]{fit},tpad=stop_mode=clone:stop_duration={d}[v]"
    elif still:
        inputs = ["-loop", "1", "-framerate", str(FPS), "-i", still]
        vf = f"[0:v]{fit}[v]"
    else:
        inputs = ["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={FPS}"]
        vf = "[0:v]setsar=1[v]"
    inputs += ["-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_RATE}"]
    if src and has_audio and native_db is not None:
        af = (f"[0:a]aresample={AUDIO_RATE},aformat=channel_layouts=stereo,"
              f"volume={native_db:g}dB,apad[a]")
    else:
        af = "[1:a]anull[a]"
    return [ffmpeg, "-y", "-v", "error", *inputs, "-filter_complex", f"{vf};{af}",
            "-map", "[v]", "-map", "[a]", "-t", d, "-r", str(FPS),
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", str(AUDIO_RATE), "-ac", "2", out]


def concat_list(files: list) -> str:
    """concat 分离器的清单（绝对路径）。"""
    return "".join(f"file '{Path(f).resolve().as_posix()}'\n" for f in files)


def concat_cmd(list_file, out, ffmpeg: str = "ffmpeg") -> list:
    """各段参数一致（normalize_cmd 保证），直接流拷贝拼接。"""
    return [ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", str(out)]


def mix_cmd(video: str, plan: dict, *, bgm: Optional[str], out: str, ffmpeg: str = "ffmpeg") -> list:
    """配音按计划时刻放置（必要时提速），BGM 循环铺满并在有人声时压低（侧链压缩），
    与视频原声混合，响度标准化到 −16 LUFS。视频流原样拷贝。"""
    inputs = ["-i", video]
    parts = ["[0:a]anull[nat]"]
    labels = []
    for i, x in enumerate(plan["speech"], 1):
        inputs += ["-i", x["file"]]
        ms = int(round(x["start"] * 1000))
        parts.append(f"[{i}:a]aformat=sample_rates={AUDIO_RATE}:channel_layouts=stereo,"
                     f"atempo={x['speed']:.4f},adelay={ms}|{ms}[s{i}]")
        labels.append(f"[s{i}]")
    n = len(labels)
    if n:
        parts.append(f"{''.join(labels)}amix=inputs={n}:normalize=0:dropout_transition=0[speech]")
    mixed = ["[nat]"]
    if bgm:
        b = n + 1
        inputs += ["-stream_loop", "-1", "-i", bgm]
        parts.append(f"[{b}:a]aformat=sample_rates={AUDIO_RATE}:channel_layouts=stereo,"
                     f"volume={BGM_DB}dB,atrim=end={plan['total']:.3f}[bgm]")
        if n:
            parts.append("[speech]asplit=2[sp][k0]")
            parts.append("[k0]apad[key]")
            parts.append("[bgm][key]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[bgmd]")
            mixed += ["[sp]", "[bgmd]"]
        else:
            mixed.append("[bgm]")
    elif n:
        mixed.append("[speech]")
    loud = f"loudnorm=I={LUFS}:TP=-1.5:LRA=11"
    if len(mixed) > 1:
        parts.append(f"{''.join(mixed)}amix=inputs={len(mixed)}:normalize=0:dropout_transition=0,{loud}[out]")
    else:
        parts.append(f"[nat]{loud}[out]")
    return [ffmpeg, "-y", "-v", "error", *inputs, "-filter_complex", ";".join(parts),
            "-map", "0:v", "-map", "[out]", "-c:v", "copy", "-c:a", "aac", "-ar", str(AUDIO_RATE),
            "-t", f"{plan['total']:.3f}", out]


# ---------- 执行 ----------

def tools() -> Optional[tuple]:
    """(ffmpeg, ffprobe) 的路径；没装返回 None（合成被拒并提示 brew install ffmpeg）。"""
    f, p = shutil.which("ffmpeg"), shutil.which("ffprobe")
    return (f, p) if f and p else None


def run(cmd: list, what: str) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise MixError(f"{what}失败（ffmpeg 退出码 {r.returncode}）", (r.stderr or "")[-4000:])


def has_audio(path, ffprobe: str) -> bool:
    r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return r.returncode == 0 and bool(r.stdout.strip())


def media_seconds(path, ffprobe: str) -> float:
    r = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                        str(path)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


# ---------- 整章合成 ----------

def chosen_file(c: dict) -> Optional[str]:
    """段采用的那次的视频（会话目录下的相对路径）；没有成功的就 None。"""
    i = c.get("chosen")
    a = c["attempts"][i] if i is not None and 0 <= i < len(c.get("attempts") or []) else None
    return a["file"] if a and a.get("state") == "succeeded" and a.get("file") else None


def _video(root, c: dict) -> Optional[str]:
    """段可用的视频（绝对路径）：采用的那次成功且文件还在磁盘上；否则 None。"""
    rel = chosen_file(c)
    p = Path(root) / rel if rel else None
    return str(p) if p is not None and p.exists() else None


def _stat(path) -> Optional[list]:
    try:
        st = Path(path).stat()
    except OSError:
        return None
    return [str(path), st.st_size, st.st_mtime_ns]


def compose_fingerprint(root, doc: dict, s: dict, voices: dict, bgm: dict, draft: bool,
                        keyframes: dict = None, cps: float = DEFAULT_SPEECH_CPS) -> str:
    """成片的输入指纹：语音条、各镜头可播时长、画幅、声音模式、音色、各段可用的视频与静音、
    草稿补位（关键帧或黑场）、BGM、草稿合成。"""
    keyframes = keyframes or {}
    shots = [(sh["id"], round(shotcalc.playable(sh, cps), 3))
             for ep in doc.get("episodes") or [] for sh in ep.get("shots") or []]
    music = {}
    for k, v in sorted(bgm.items()):
        st = _stat(v)
        if st:
            music[k] = st
    size = frame_size(s["resolution"], ((doc.get("meta") or {}).get("video") or {}).get("aspect_ratio") or "9:16")
    holes = {}
    if draft:
        for c in s["clips"]:
            if not _video(root, c):
                kf = keyframes.get(c["shots"][0]) if c["shots"] else None
                holes[c["id"]] = (_stat(kf) if kf else None)
    return shotcalc.fingerprint(
        lines=[(x["id"], x["kind"], x["speaker"], x["text"]) for x in voice.speech_lines(doc)],
        shots=shots, mode=s["audio_mode"], resolution=s["resolution"], size=size, voices=voices,
        clips=[(c["id"], _video(root, c), bool(c.get("mute_native"))) for c in s["clips"]],
        holes=holes, bgm=music, draft=draft)


def preview(root, doc: dict, s: dict, *, tts, bgm: dict, draft: bool, keyframes: dict = None,
            cps: float = DEFAULT_SPEECH_CPS) -> dict:
    """合成前的预览：配音条数、未缓存字数与费用、缺音色的说话人、缺视频的段、成片指纹。不花钱。
    没有要配音的语音条时不碰 tts（可传 None）。"""
    lines = voice.tts_lines(voice.speech_lines(doc), s["audio_mode"])
    voices, missing = (voice.resolve_voices(doc, lines, s.get("voices") or {}, tts.caps) if lines
                       else ({}, []))
    est = (voice.estimate(lines, voices, tts, root) if lines and not missing
           else {"lines": len(lines), "chars": 0, "cny": 0.0})
    return {"lines": len(lines), "tts_chars": est["chars"], "tts_cny": est["cny"],
            "missing_voices": missing, "voices": voices,
            "no_video": [c["id"] for c in s["clips"] if not _video(root, c)],
            "fingerprint": compose_fingerprint(root, doc, s, voices, bgm, draft, keyframes, cps)}


def compose(root, doc: dict, s: dict, *, tts, keyframes: dict, bgm: dict, draft: bool, tools: tuple,
            on_cost=None, progress=None, cps: float = DEFAULT_SPEECH_CPS) -> dict:
    """合成整章：配音 → 每集规整、拼接、混音 → 字幕与报告。返回 {"files", "report"}（会话目录下的相对路径）。

    已合成的配音（audio/cache）与已规整的段（final/work，按输入指纹命名）都复用：失败后重跑不重做已完成的步骤。
    draft=True 时没出的段用首镜关键帧定格补位，没有关键帧用黑场；False 时缺段直接拒绝。
    """
    ffmpeg, ffprobe = tools
    root = Path(root)
    say = progress or (lambda step: None)
    if not draft:
        for c in s["clips"]:
            if not _video(root, c):
                raise MixError(f"{c['id']} 还没有可用的视频；打开「草稿合成」可用关键帧补位")
    lines = voice.tts_lines(voice.speech_lines(doc), s["audio_mode"])
    done, failed = [], []
    if lines:                       # 没有要配音的语音条就不碰 tts（tts 可为 None）
        voices, missing = voice.resolve_voices(doc, lines, s.get("voices") or {}, tts.caps)
        if missing:
            raise MixError("还有说话人没选音色：" + "、".join(k or "（未标说话人）" for k in missing))
        say(f"配音 {len(lines)} 条")
        try:
            done, failed = voice.synthesize(lines, voices, tts, root, on_cost=on_cost)
        except voice.VoiceError as e:
            raise MixError(str(e))
    if failed:
        raise MixError("有语音条合成失败，为免成片漏句已停止合成："
                       + "；".join(f"{x['id']}：{x['error']}" for x in failed[:5]))
    voiced = {x["id"]: x for x in done}
    size = frame_size(s["resolution"], ((doc.get("meta") or {}).get("video") or {}).get("aspect_ratio") or "9:16")
    work = root / "final" / "work"
    work.mkdir(parents=True, exist_ok=True)
    by_ep = {}
    for c in s["clips"]:
        by_ep.setdefault(c["episode"], []).append(c)
    report = {"audio_mode": s["audio_mode"], "size": f"{size[0]}x{size[1]}", "draft": draft, "episodes": [],
              "alignment": "段内镜头切换时刻由视频模型决定，台词按计划镜头起点放置，属近似对齐"}
    if s["audio_mode"] == "dialogue_native":
        report["warning"] = "台词由视频模型生成，不保证逐字"
    files = []
    for ep in doc.get("episodes") or []:
        clips = by_ep.get(ep["id"]) or []
        if not clips:
            continue
        plan = plan_episode(ep, clips, voiced, cps)
        segs, placeholders = [], []
        for seg, c in zip(plan["segments"], clips):
            src = _video(root, c)
            still = None
            if not src:
                if not draft:
                    raise MixError(f"{c['id']} 还没有可用的视频；打开「草稿合成」可用关键帧补位")
                kf = keyframes.get(c["shots"][0]) if c["shots"] else None
                still = str(kf) if kf else None
                placeholders.append(c["id"])
            ndb = native_audio_policy(s["audio_mode"], bool(c.get("mute_native")))
            audio = bool(src) and ndb is not None and has_audio(src, ffprobe)
            # 源文件按 (路径, 大小, 修改时间) 计：同一路径重新上传的关键帧或视频会重新规整
            key = hashlib.sha256(json.dumps([_stat(src) if src else None, _stat(still) if still else None,
                                             seg["duration"], size, ndb, audio]).encode()).hexdigest()[:16]
            out = work / f"{c['id']}.{key}.mp4"
            if not out.exists():
                say(f"规整 {c['id']}")
                tmp = out.with_suffix(".part.mp4")
                run(normalize_cmd(src, still=still, duration=seg["duration"], size=size, native_db=ndb,
                                  has_audio=audio, out=str(tmp), ffmpeg=ffmpeg), f"规整 {c['id']} ")
                tmp.replace(out)
            segs.append(out)
        lst = work / f"{ep['id']}.txt"
        lst.write_text(concat_list(segs), encoding="utf-8")
        joined = work / f"{ep['id']}.joined.mp4"
        say(f"拼接 {ep['id']}")
        run(concat_cmd(lst, joined, ffmpeg), f"拼接 {ep['id']} ")
        final = root / "final" / f"{ep['id']}.mp4"
        tmp = final.with_suffix(".part.mp4")
        say(f"混音 {ep['id']}")
        music = bgm.get(ep["id"])
        if music and not Path(music).exists():
            music = None
        run(mix_cmd(str(joined), plan, bgm=str(music) if music else None, out=str(tmp), ffmpeg=ffmpeg),
            f"混音 {ep['id']} ")
        tmp.replace(final)
        (root / "final" / f"{ep['id']}.srt").write_text(srt(plan["subs"]), encoding="utf-8")
        files += [f"final/{ep['id']}.mp4", f"final/{ep['id']}.srt"]
        report["episodes"].append({"episode": ep["id"], "seconds": plan["total"], "notes": plan["notes"],
                                   "placeholders": placeholders,
                                   "stale": [c["id"] for c in clips if c.get("state") == "stale"]})
    (root / "final" / "mix_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                                    encoding="utf-8")
    return {"files": files, "report": "final/mix_report.json"}
