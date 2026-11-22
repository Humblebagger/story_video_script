"""火山引擎豆包语音合成（大模型 2.0，HTTP 单向流式接口）。

接口与价格核实于 2026-10-31 的官方文档：
- POST https://openspeech.bytedance.com/api/v3/tts/unidirectional。请求头 X-Api-Key（新版控制台），或
  X-Api-App-Id + X-Api-Access-Key（旧版控制台）；X-Api-Resource-Id: seed-tts-2.0 决定模型与计费。
- 请求体 user.uid、req_params.text、req_params.speaker、req_params.audio_params（format、sample_rate、
  speech_rate [-50,100]，100 为 2 倍速）。响应是逐行 JSON：音频块 {"code":0,"data":"<base64>"}，
  结束块 code=20000000；其他非 0 码为失败。
- 2.0 音色名以 _uranus_bigtts 结尾；后付费 3 元/万字符。
我们要 pcm（24kHz 16 位单声道）自己封成 WAV，时长按帧数算。密钥只放进请求头，不进日志与报错。
收到 200 之后的任何失败（中途断开、坏行、坏音频、流内错误码、没有结束块）按已计费报 BilledError、不重试。
"""
import base64
import binascii
import json
import logging
import os
import re
import uuid
from pathlib import Path

import httpx

from pipeline.config import ROOT as BACKEND_ROOT
from pipeline.config import _load_dotenv
from render.providers import base
from server.messages import msg as _msg, with_ref
from render.providers.base import ProviderError, TransientError, scrub
from render.providers.tts_base import BilledError, TtsCaps, TtsResult, Voice, tts_cost, write_wav

log = logging.getLogger("render.providers.tts_volc")

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


def _clean(text, secrets: list) -> str:
    """厂商文字进报错参数前：抹掉密钥与 Bearer 凭据。"""
    t = str(text)
    for s in secrets:
        t = scrub(t, s)
    return scrub(t)


def _safe_code(code, secrets: list):
    """错误码进参数：只放行整数或纯数字字符串（最长 12 位）；其余返回 None（调用方改走中性拒绝，原值进错误记录）。"""
    if isinstance(code, bool):
        return None
    if isinstance(code, int) and 0 <= code < 10 ** 12:
        return code
    if isinstance(code, str) and re.fullmatch(r"[0-9]{1,12}", code):
        return code
    return None


def _reject(r: httpx.Response, secrets: list) -> ProviderError:
    """4xx：厂商给了 message 就按「厂商拒绝」处理（原话脱敏后进日志与错误记录，不给用户），否则只报 HTTP 状态。"""
    try:
        d = r.json()
        if not isinstance(d, dict):
            d = {}
        head = d.get("header") or {}
        msg = d.get("message") or head.get("message") or ""
        code = d.get("code") or head.get("code") or r.status_code
    except ValueError:
        msg, code = _clean(r.text, secrets)[:200], r.status_code    # 先抹掉再截断，免得密钥被截半漏出
    msg = _clean(msg, secrets)
    if msg:
        return ProviderError.from_msg(base.vendor_reject(
            "tts.vendor.rejected", f"{_safe_code(code, secrets)}: {msg}", who="volc", secrets=secrets))
    return ProviderError.of("tts.vendor.rejected_http", status=r.status_code)


class VolcTts:
    name = "volc"

    def __init__(self, *, api_key: str = "", app_id: str = "", access_key: str = "",
                 client=None, url: str = URL, timeout: float = 60.0):
        if not api_key and not (app_id and access_key):
            log.warning("未配置豆包语音密钥：在 backend/.env 写 VOLC_TTS_API_KEY（新版控制台），"
                        "或 VOLC_TTS_APP_ID 与 VOLC_TTS_ACCESS_KEY（旧版控制台）")  # i18n: internal
            raise ProviderError.of("tts.vendor.no_key")
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

    def _billed(self, code: str, text: str, /, **params) -> BilledError:
        return BilledError.of(code, tts_cost(len(text), self.caps), **params)

    def _scrub(self, text) -> str:
        for s in self._auth.values():
            text = scrub(text, s)
        return scrub(text)

    def synthesize(self, text, voice, emotion, speed, dest):
        params = {"format": "pcm", "sample_rate": SAMPLE_RATE,
                  "speech_rate": max(-50, min(100, round((speed - 1) * 100)))}
        if emotion and self.caps.emotions:
            params["emotion"] = emotion
        body = {"user": {"uid": "storyboard"},
                "req_params": {"text": text, "speaker": voice, "audio_params": params}}
        headers = {**self._auth, "X-Api-Resource-Id": RESOURCE_ID,
                   "X-Api-Request-Id": str(uuid.uuid4()), "Content-Type": "application/json"}
        pcm, done, seen = bytearray(), False, False
        try:
            with self._http.stream("POST", self._url, headers=headers, json=body) as r:
                if r.status_code == 429 or r.status_code >= 500:
                    raise TransientError.of("tts.vendor.unavailable", status=r.status_code)
                if r.status_code >= 400:
                    r.read()
                    raise _reject(r, list(self._auth.values()))
                seen = True         # 已收下请求：此后的失败可能已计费，按已计费报、不重试
                for raw in r.iter_lines():
                    line = raw.strip()
                    if line.startswith("data:"):
                        line = line[len("data:"):].strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        raise self._billed("tts.vendor.not_json", text) from None
                    if not isinstance(msg, dict):
                        raise self._billed("tts.vendor.not_json", text)
                    code = msg.get("code", 0)
                    if code == DONE:
                        done = True
                        break
                    if code != 0:
                        detail = msg.get("message") or ""
                        secrets = list(self._auth.values())
                        safe_code = _safe_code(code, secrets)
                        cost = tts_cost(len(text), self.caps)
                        if safe_code is None:        # 形状不明的错误码：不进参数，走中性拒绝（原值进错误记录，带编号）
                            raise BilledError.from_msg(base.vendor_reject(
                                "tts.vendor.rejected", f"{_clean(code, secrets)}: {detail}", who="volc", secrets=secrets), cost)
                        if detail:                   # 原话进日志与错误记录，编号挂在 tts.vendor.failed 上
                            rec = base.vendor_reject("tts.vendor.rejected", f"{safe_code}: {detail}", who="volc", secrets=secrets)
                            m = _msg("tts.vendor.failed", code=safe_code)
                            if rec.get("ref"):
                                m = with_ref(m, rec["ref"])
                            raise BilledError.from_msg(m, cost)
                        raise self._billed("tts.vendor.failed", text, code=safe_code)
                    if msg.get("data"):
                        try:
                            pcm += base64.b64decode(msg["data"], validate=True)
                        except (binascii.Error, ValueError, TypeError):
                            raise self._billed("tts.vendor.bad_audio", text) from None
        except httpx.TransportError as e:
            log.warning("豆包语音连接异常：%s seen=%s", type(e).__name__, seen)  # i18n: internal
            if seen:
                raise self._billed("tts.vendor.cut", text) from None
            raise TransientError.of("tts.vendor.connect_failed") from None
        if not done or not pcm:
            raise self._billed("tts.vendor.incomplete", text)
        duration = write_wav(Path(dest), bytes(pcm), SAMPLE_RATE)
        return TtsResult(Path(dest), duration, tts_cost(len(text), self.caps), len(text))
