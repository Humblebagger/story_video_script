"""真实厂商冒烟（花真钱，上限 5 元）：用《药》第一段出一条最短的 Seedance 视频。

用法: cd backend && .venv/bin/python -m render.smoke [--model seedance-2.0-mini] [--resolution 480p]
                                                    [--out /tmp/seedance-smoke] [--yes]
打印方舟返回的 token 用量与按单价折算的金额——拿它与控制台账单核对，校准单价
（STORYBOARD_SEEDANCE_CNY_PER_M）。
"""
import argparse
import json
import sys
import time
from pathlib import Path

from render import compose
from render.providers import base
from render.providers.seedance import Seedance

LIMIT_CNY = 5.0
YAO = Path(__file__).resolve().parent.parent / "tests" / "real_text_yao" / "output_merged.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Seedance 真实冒烟（花钱）")
    ap.add_argument("--model", default="seedance-2.0-mini")
    ap.add_argument("--resolution", default="480p")
    ap.add_argument("--out", default="/tmp/seedance-smoke")
    ap.add_argument("--yes", action="store_true", help="不再询问，直接提交")
    a = ap.parse_args(argv)

    sd = Seedance.from_env()
    caps = sd.caps(a.model)
    doc = json.loads(YAO.read_text(encoding="utf-8"))
    session = {"provider": "seedance", "model": a.model, "resolution": a.resolution,
               "audio_mode": "tts_all"}
    clip = compose.build_clips(doc, caps, provider="seedance", model=a.model,
                               resolution=a.resolution, audio_mode="tts_all", keyframes={},
                               rewrite=sd.rewrite_prompt)[0]
    req, _ = compose.request_for(doc, session, clip, keyframes={}, relay_frame=None, caps=caps,
                                 rewrite=sd.rewrite_prompt)
    req.duration = caps.min_clip_sec               # 冒烟只出最短的一条
    est = base.estimate_cny(req.duration, caps, a.resolution)
    print(req.prompt, "\n")
    print(f"{a.model} · {a.resolution} · {base.request_seconds(req.duration, caps)} 秒 · "
          f"预估 ¥{est:.2f}（冒烟上限 ¥{LIMIT_CNY:g}）")
    if est > LIMIT_CNY:
        print("超出冒烟上限，不提交")
        return 1
    if not a.yes and input("提交？[y/N] ").strip().lower() != "y":
        return 1

    tid = sd.submit(req)
    print("任务：", tid)
    while True:
        time.sleep(10)
        st = sd.poll(tid)
        print("状态：", st.status, flush=True)
        if st.status in ("succeeded", "failed"):
            break
    if st.status == "failed":
        print("失败：", st.error)
        return 1
    files = sd.download(st, Path(a.out) / f"{clip['id']}.mp4")
    print("视频：", files["video"], "（可播放）" if base.is_playable_mp4(files["video"]) else "（不可播放！）")
    print("尾帧：", files["last_frame"])
    print("用量：", st.usage, f"→ 折算 ¥{sd.cost(st, req):.2f}，请与控制台账单核对")
    return 0


if __name__ == "__main__":
    sys.exit(main())
