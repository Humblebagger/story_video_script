"""视频厂商真实冒烟（花真钱，上限 5 元）：用《药》第一段出一条最短的视频。

用法: cd backend && .venv/bin/python -m render.smoke [--provider minimax|seedance] [--model …] [--resolution …]
                                                    [--out /tmp/video-smoke] [--yes] [--style 图]
缺省厂商与新建出片会话一致（MiniMax；没配 MiniMax 而配了方舟时为 Seedance）。
打印厂商返回的用量与按单价折算的金额、成片是否带音轨与实际宽高——拿它们与控制台账单、spec §5.1 的短边表核对。
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from render import compose
from render.providers import base, default_video_name, get_video

LIMIT_CNY = 5.0
YAO = Path(__file__).resolve().parent.parent / "tests" / "real_text_yao" / "output_merged.json"
DEFAULTS = {"seedance": ("seedance-2.0-mini", "480p"), "minimax": ("minimax-h3-lite", "480P")}


def _probe(video: Path) -> str:
    """ffprobe 看实际宽高与是否带音轨；没装 ffprobe 时说明一下。"""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return "（本机没有 ffprobe，无法判断音轨与宽高）"
    v = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout.strip()
    a = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                        "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout.strip()
    return f"实际宽高 {v.replace(',', '×') or '读不出'} · {'带音轨' if a else '不带音轨'}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="视频厂商真实冒烟（花钱）")
    ap.add_argument("--provider", choices=sorted(DEFAULTS), default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--resolution", default=None)
    ap.add_argument("--out", default="/tmp/video-smoke")
    ap.add_argument("--yes", action="store_true", help="不再询问，直接提交")
    ap.add_argument("--style", default=None, help="风格参考图路径（可选）")
    a = ap.parse_args(argv)
    name = a.provider or default_video_name()
    if name not in DEFAULTS:
        print(f"冒烟只支持 {'、'.join(sorted(DEFAULTS))}，当前缺省为 {name}；用 --provider 指定")
        return 1
    model = a.model or DEFAULTS[name][0]
    resolution = a.resolution or DEFAULTS[name][1]
    style = None
    if a.style:
        sp = Path(a.style)
        style = {"source": compose.data_uri(sp), "hash": hashlib.sha256(sp.read_bytes()).hexdigest()}

    vp = get_video(name)
    caps = vp.caps(model)
    doc = json.loads(YAO.read_text(encoding="utf-8"))
    session = {"provider": name, "model": model, "resolution": resolution, "audio_mode": "tts_all"}
    clip = compose.build_clips(doc, caps, provider=name, model=model, resolution=resolution,
                               audio_mode="tts_all", keyframes={}, rewrite=vp.rewrite_prompt, style=style)[0]
    req, _ = compose.request_for(doc, session, clip, keyframes={}, relay_frame=None, caps=caps,
                                 rewrite=vp.rewrite_prompt, style=style)
    req.duration = caps.min_clip_sec               # 冒烟只出最短的一条
    req.images = len(req.refs) + (1 if req.first_frame else 0)
    est = base.estimate_cny(req.duration, caps, resolution, req.images)
    print("厂商：", name)
    print(req.prompt, "\n")
    print("风格图：", clip.get("style"))
    print(f"{model} · {resolution} · {base.request_seconds(req.duration, caps)} 秒 · {req.images} 张图 · "
          f"预估 ¥{est:.2f}（冒烟上限 ¥{LIMIT_CNY:g}）")
    if est > LIMIT_CNY:
        print("超出冒烟上限，不提交")
        return 1
    if not a.yes and input("提交？[y/N] ").strip().lower() != "y":
        return 1

    Path(a.out).mkdir(parents=True, exist_ok=True)  # 下载不建上级目录，先建好再花钱
    tid = vp.submit(req)
    print("任务：", tid)
    while True:
        time.sleep(10)
        st = vp.poll(tid)
        print("状态：", st.status, flush=True)
        if st.status in ("succeeded", "failed"):
            break
    if st.status == "failed":
        print("失败：", st.error)
        return 1
    files = vp.download(st, Path(a.out) / f"{clip['id']}.mp4")
    print("视频：", files["video"], "（可播放）" if base.is_playable_mp4(files["video"]) else "（不可播放！）")
    print("成片：", _probe(files["video"]))
    print("尾帧：", files["last_frame"])
    print("用量：", st.usage, f"→ 折算 ¥{vp.cost(st, req):.2f}，请与控制台账单核对")
    return 0


if __name__ == "__main__":
    sys.exit(main())
