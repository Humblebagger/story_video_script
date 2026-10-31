"""火山引擎豆包语音合成（大模型 2.0，HTTP 单向流式接口）。

接口与价格核实于 2026-10-31 的官方文档：
- POST https://openspeech.bytedance.com/api/v3/tts/unidirectional。请求头 X-Api-Key（新版控制台），或
  X-Api-App-Id + X-Api-Access-Key（旧版控制台）；X-Api-Resource-Id: seed-tts-2.0 决定模型与计费。
- 请求体 user.uid、req_params.text、req_params.speaker、req_params.audio_params（format、sample_rate、
  speech_rate [-50,100]，100 为 2 倍速）。响应是逐行 JSON：音频块 {"code":0,"data":"<base64>"}，
  结束块 code=20000000；其他非 0 码为失败。
- 2.0 音色名以 _uranus_bigtts 结尾；后付费 3 元/万字符。
我们要 pcm（24kHz 16 位单声道）自己封成 WAV，时长按帧数算。密钥只放进请求头，不进日志与报错。
"""
import base64
import json
import os
import uuid
from pathlib import Path

import httpx

from pipeline.config import ROOT as BACKEND_ROOT
from pipeline.config import _load_dotenv
from render.providers.base import ProviderError, TransientError
from render.providers.tts_base import TtsCaps, TtsResult, Voice, tts_cost, write_wav

URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
RESOURCE_ID = "seed-tts-2.0"
SAMPLE_RATE = 24000
DONE = 20000000
# 2026-10 后付费刊例价 3 元/万字符；用真实账单校准后可用 STORYBOARD_VOLC_TTS_CNY_PER_K 覆盖（元/千字符）
DEFAULT_CNY_PER_K = 0.3
VOICES = [
    Voice("zh_male_m191_uranus_bigtts", "云舟 2.0", "male"),
    Voice("zh_male_taocheng_uranus_bigtts", "小天 2.0", "male"),
    Voice("zh_male_liufei_uranus_bigtts", "刘飞 2.0", "male"),
    Voice("zh_female_vv_uranus_bigtts", "Vivi 2.0", "female"),
    Voice("zh_female_xiaohe_uranus_bigtts", "小何 2.0", "female"),
    Voice("zh_female_sophie_uranus_bigtts", "魅力苏菲 2.0", "female"),
    Voice("zh_female_qingxinnvsheng_uranus_bigtts", "清新女声 2.0", "female"),
    Voice("zh_female_cancan_uranus_bigtts", "知性灿灿 2.0", "female"),
]


def _per_k() -> float:
    try:
        v = float(os.environ.get("STORYBOARD_VOLC_TTS_CNY_PER_K", ""))
    except ValueError:
        return DEFAULT_CNY_PER_K
    return v if v > 0 else DEFAULT_CNY_PER_K


def _error_text(r: httpx.Response) -> str:
    try:
        d = r.json()
        head = d.get("header") or {}
        msg = d.get("message") or head.get("message") or ""
        code = d.get("code") or head.get("code") or r.status_code
    except ValueError:
        msg, code = r.text[:200], r.status_code
    return f"豆包语音拒绝了请求（{code}）：{msg}" if msg else f"豆包语音拒绝了请求（HTTP {r.status_code}）"


class VolcTts:
    name = "volc"
    rate_note = "2026-10 火山引擎豆包语音合成 2.0 后付费刊例价（3 元/万字符），未经账单核对"

    def __init__(self, *, api_key: str = "", app_id: str = "", access_key: str = "",
                 client=None, url: str = URL, timeout: float = 60.0):
        if not api_key and not (app_id and access_key):
            raise ProviderError("没有配置豆包语音密钥：在 backend/.env 写 VOLC_TTS_API_KEY=…（新版控制台），"
                                "或 VOLC_TTS_APP_ID 与 VOLC_TTS_ACCESS_KEY（旧版控制台）")
        self._auth = ({"X-Api-Key": api_key} if api_key
                      else {"X-Api-App-Id": app_id, "X-Api-Access-Key": access_key})
        self._http = client or httpx.Client(timeout=timeout)
        self._url = url
        self.caps = TtsCaps(voices=list(VOICES), emotions=False, max_chars=300, cny_per_k_chars=_per_k())

    @classmethod
    def from_env(cls) -> "VolcTts":
        _load_dotenv(BACKEND_ROOT / ".env")
        _load_dotenv(BACKEND_ROOT.parent / ".env")
        return cls(api_key=os.environ.get("VOLC_TTS_API_KEY", "").strip(),
                   app_id=os.environ.get("VOLC_TTS_APP_ID", "").strip(),
                   access_key=os.environ.get("VOLC_TTS_ACCESS_KEY", "").strip())

    def synthesize(self, text, voice, emotion, speed, dest):
        params = {"format": "pcm", "sample_rate": SAMPLE_RATE,
                  "speech_rate": max(-50, min(100, round((speed - 1) * 100)))}
        if emotion and self.caps.emotions:
            params["emotion"] = emotion
        body = {"user": {"uid": "storyboard"},
                "req_params": {"text": text, "speaker": voice, "audio_params": params}}
        headers = {**self._auth, "X-Api-Resource-Id": RESOURCE_ID,
                   "X-Api-Request-Id": str(uuid.uuid4()), "Content-Type": "application/json"}
        pcm, done = bytearray(), False
        try:
            with self._http.stream("POST", self._url, headers=headers, json=body) as r:
                if r.status_code == 429 or r.status_code >= 500:
                    raise TransientError(f"豆包语音暂时不可用（HTTP {r.status_code}）")
                if r.status_code >= 400:
                    r.read()
                    raise ProviderError(_error_text(r))
                for raw in r.iter_lines():
                    line = raw.strip()
                    if line.startswith("data:"):
                        line = line[len("data:"):].strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        raise TransientError("豆包语音返回的不是 JSON")
                    code = msg.get("code", 0)
                    if code == DONE:
                        done = True
                        break
                    if code != 0:
                        detail = msg.get("message") or ""
                        raise ProviderError(f"豆包语音合成失败（{code}）" + (f"：{detail}" if detail else ""))
                    if msg.get("data"):
                        pcm += base64.b64decode(msg["data"])
        except httpx.TransportError as e:
            raise TransientError(f"连接豆包语音失败：{type(e).__name__}")
        if not done or not pcm:
            raise TransientError("豆包语音没有返回完整的音频")
        duration = write_wav(Path(dest), bytes(pcm), SAMPLE_RATE)
        return TtsResult(Path(dest), duration, tts_cost(len(text), self.caps), len(text))
