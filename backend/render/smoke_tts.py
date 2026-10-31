"""豆包语音真实冒烟（花真钱，约 0.01 元）：合成一句旁白，打印时长与按单价折算的金额——拿它与控制台
账单核对，必要时用 STORYBOARD_VOLC_TTS_CNY_PER_K 校准单价。

用法: cd backend && .venv/bin/python -m render.smoke_tts [--voice zh_male_m191_uranus_bigtts]
                                                        [--out /tmp/tts-smoke.wav] [--yes]
"""
import argparse
import sys
from pathlib import Path

from render.providers.tts_base import tts_cost
from render.providers.tts_volc import VOICES, VolcTts

TEXT = "秋天的后半夜，月亮下去了，太阳还没有出，只剩下一片乌蓝的天。"
LIMIT_CNY = 1.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="豆包语音真实冒烟（花钱）")
    ap.add_argument("--voice", default=VOICES[0].id, choices=[v.id for v in VOICES])
    ap.add_argument("--out", default="/tmp/tts-smoke.wav")
    ap.add_argument("--yes", action="store_true", help="不再询问，直接合成")
    a = ap.parse_args(argv)

    tts = VolcTts.from_env()
    est = tts_cost(len(TEXT), tts.caps)
    print(TEXT, "\n")
    print(f"{a.voice} · {len(TEXT)} 字 · 预估 ¥{est:.4f}（冒烟上限 ¥{LIMIT_CNY:g}）")
    if est > LIMIT_CNY:
        print("超出冒烟上限，不合成")
        return 1
    if not a.yes and input("合成？[y/N] ").strip().lower() != "y":
        return 1
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    r = tts.synthesize(TEXT, a.voice, None, 1.0, out)
    print("音频：", r.file, f"{r.duration:.2f} 秒")
    print(f"折算 ¥{r.cost_cny:.4f}，请与控制台账单核对")
    return 0


if __name__ == "__main__":
    sys.exit(main())
