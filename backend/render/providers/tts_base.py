"""出片：TTS 厂商统一接口（设计文档 3.2）。

主流程只用 caps / synthesize。厂商一律产出 WAV（16 位单声道 PCM），时长按帧数算，不需要 ffprobe。
新增厂商 = 新文件 + 在 providers/__init__.py 用 register_tts 注册一行。错误沿用视频厂商的两类：
ProviderError（明确失败，原样展示）、TransientError（断连、限流，调用方重试）；另加 BilledError：
厂商已收下请求（可能已计费）后才失败，调用方按 billed_cny 记账且不重试。
"""
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from render.providers.base import ProviderError, TransientError  # noqa: F401  （供 TTS 厂商与调用方导入）


class BilledError(ProviderError):
    """厂商已收下请求后才失败（如流式响应中途断开）：这次可能已计费，按 billed_cny 记账，不重试。"""

    def __init__(self, message: str, billed_cny: float):
        super().__init__(message)
        self.billed_cny = billed_cny      # 构造写 BilledError.of(code, billed_cny, **params)


@dataclass
class Voice:
    id: str
    name: str
    gender: str          # male / female
    lang: str = "zh"


@dataclass
class TtsCaps:
    voices: list         # list[Voice]
    emotions: bool       # 是否接受情绪参数
    max_chars: int       # 单次请求最多字数（超出由 voice.py 按标点切开）
    cny_per_k_chars: float


@dataclass
class TtsResult:
    file: Path
    duration: float      # 秒（按 WAV 帧数）
    cost_cny: float
    chars: int


class TtsProvider(Protocol):
    name: str
    caps: TtsCaps
    rate_note: dict     # 费率依据（消息对象 {code, params}）：如实写出处、是否经账单核对

    def synthesize(self, text: str, voice: str, emotion: Optional[str], speed: float,
                   dest: Path) -> TtsResult: ...


def tts_cost(chars: int, caps: TtsCaps) -> float:
    return round(chars * caps.cny_per_k_chars / 1000, 4)


def default_voice(caps: TtsCaps, hint: Optional[str]) -> Optional[str]:
    """分镜里的抽象音色提示（male_elder、female_young…）→ 该厂商第一个同性别音色；看不出性别返回 None。"""
    h = (hint or "").strip().lower()
    gender = "female" if h.startswith("female") else "male" if h.startswith("male") else None
    if gender is None:
        return None
    return next((v.id for v in caps.voices if v.gender == gender), None)


def write_wav(dest: Path, pcm: bytes, rate: int) -> float:
    """16 位单声道 PCM 写成 WAV（先写临时文件再改名），返回时长（秒）。目录须已存在。"""
    dest = Path(dest)
    tmp = dest.with_name(dest.name + ".part")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    tmp.replace(dest)
    return len(pcm) / 2 / rate


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def concat_wavs(parts: list, dest: Path) -> float:
    """同参数的几段 WAV 首尾相接（长句切开合成后拼回），返回总时长。"""
    frames, rate = b"", None
    for p in parts:
        with wave.open(str(p), "rb") as w:
            if rate is None:
                rate = w.getframerate()
            if w.getframerate() != rate or w.getnchannels() != 1 or w.getsampwidth() != 2:
                raise ProviderError.of("tts.concat_mismatch")
            frames += w.readframes(w.getnframes())
    return write_wav(dest, frames, rate or 24000)
