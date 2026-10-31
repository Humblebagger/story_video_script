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
from render import compose, voice

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
            p = compose.playable(shot, cps)
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
           f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS}")
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
                     f"volume={BGM_DB}dB,atrim=0:{plan['total']:.3f}[bgm]")
        if n:
            parts.append("[speech]asplit=2[sp][key]")
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
