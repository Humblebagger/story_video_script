#!/usr/bin/env python3
"""豆包语音合成：请求头与请求体、逐行 JSON 解析与 WAV、语速映射、错误分级、密钥不外泄、读密钥。

用 httpx.MockTransport 模拟，不联网、不花钱。用法: python3 tests/render/test_tts_volc.py
"""
import base64
import json
import os
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from render import providers  # noqa: E402
from render.providers import tts_volc  # noqa: E402
from render.providers.tts_base import BilledError, ProviderError, TransientError, tts_cost, wav_seconds  # noqa: E402
from render.providers.tts_volc import RESOURCE_ID, VOICES, VolcTts  # noqa: E402

VOICE = "zh_male_m191_uranus_bigtts"


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def volc(handler, **kw):
    kw.setdefault("api_key", "k-secret")
    return VolcTts(client=httpx.Client(transport=httpx.MockTransport(handler)), **kw)


def stream(*pcm, end=True, prefix=""):
    rows = [json.dumps({"code": 0, "message": "", "data": base64.b64encode(p).decode()}) for p in pcm]
    if end:
        rows.append(json.dumps({"code": 20000000, "message": "ok", "data": None}))
    return "".join(f"{prefix}{r}\n" for r in rows).encode()


def main() -> int:
    seen = []

    def ok(request):
        seen.append(request)
        return httpx.Response(200, content=stream(b"\x01\x00" * 24000, b"\x02\x00" * 12000))

    with tempfile.TemporaryDirectory() as d:
        tts = volc(ok)
        r = tts.synthesize("你好世界", VOICE, "开心", 1.0, Path(d) / "a.wav")
        assert abs(r.duration - 1.5) < 1e-6 and r.chars == 4 and r.cost_cny == tts_cost(4, tts.caps), r
        assert abs(wav_seconds(r.file) - 1.5) < 1e-6
        h = seen[0].headers
        assert h["x-api-key"] == "k-secret" and h["x-api-resource-id"] == RESOURCE_ID and h["x-api-request-id"]
        assert "x-api-app-id" not in h
        body = json.loads(seen[0].content)
        assert body["req_params"]["text"] == "你好世界" and body["req_params"]["speaker"] == VOICE
        assert body["req_params"]["audio_params"] == {"format": "pcm", "sample_rate": 24000, "speech_rate": 0}, \
            "2.0 音色不传情绪参数"
        assert tts.caps.cny_per_k_chars == 0.3 and {v.id for v in tts.caps.voices} == {v.id for v in VOICES}
        print("1. 请求头、请求体、逐行 JSON 拼成 WAV、按字计费 ✓")

        old = volc(ok, api_key="", app_id="app-1", access_key="ak-1")
        old.synthesize("一", VOICE, None, 1.5, Path(d) / "b.wav")
        h = seen[-1].headers
        assert h["x-api-app-id"] == "app-1" and h["x-api-access-key"] == "ak-1" and "x-api-key" not in h
        assert json.loads(seen[-1].content)["req_params"]["audio_params"]["speech_rate"] == 50
        volc(ok).synthesize("一", VOICE, None, 3.0, Path(d) / "c.wav")
        assert json.loads(seen[-1].content)["req_params"]["audio_params"]["speech_rate"] == 100
        sse = volc(lambda r: httpx.Response(200, content=stream(b"\x00\x00" * 2400, prefix="data: ")))
        assert abs(sse.synthesize("一", VOICE, None, 1.0, Path(d) / "d.wav").duration - 0.1) < 1e-6
        print("2. 旧版控制台鉴权、语速映射与夹取、data: 前缀 ✓")

        def status(code, payload=None):
            return volc(lambda r: httpx.Response(code, json=payload or {}))
        must_raise(TransientError, status(429).synthesize, "一", VOICE, None, 1.0, Path(d) / "e.wav")
        must_raise(TransientError, status(503).synthesize, "一", VOICE, None, 1.0, Path(d) / "e.wav")
        e = must_raise(ProviderError, status(401, {"message": "invalid key"}).synthesize,
                       "一", VOICE, None, 1.0, Path(d) / "e.wav")
        assert "invalid key" in str(e) and "k-secret" not in str(e)
        bad = volc(lambda r: httpx.Response(200, content=(json.dumps(
            {"code": 45000000, "message": "speaker permission denied"}) + "\n").encode()))
        e = must_raise(BilledError, bad.synthesize, "一", VOICE, None, 1.0, Path(d) / "e.wav")
        assert "45000000" in str(e) and "permission" in str(e) and e.billed_cny == tts_cost(1, bad.caps)
        cut = volc(lambda r: httpx.Response(200, content=stream(b"\x00\x00" * 10, end=False)))
        must_raise(BilledError, cut.synthesize, "一", VOICE, None, 1.0, Path(d) / "e.wav")

        def refused(request):
            raise httpx.ConnectError("refused", request=request)
        e = must_raise(TransientError, volc(refused).synthesize, "一", VOICE, None, 1.0, Path(d) / "e.wav")
        assert "k-secret" not in str(e)
        assert not (Path(d) / "e.wav").exists(), "失败时不留文件"
        print("3. 错误分级：限流/5xx/连不上为瞬时，4xx 为明确失败，密钥不进报错 ✓")

        class Broken(httpx.SyncByteStream):
            """先给一行正常音频，再中途断开。"""
            def __iter__(self):
                yield stream(b"\x00\x00" * 10, end=False)
                raise httpx.ReadError("reset")

        text = "收到之后才失败"
        cases = {
            "中途断开": lambda r: httpx.Response(200, stream=Broken()),
            "不是 JSON 对象": lambda r: httpx.Response(200, content=b"[1, 2]\n"),
            "不是 JSON": lambda r: httpx.Response(200, content=b"oops\n"),
            "音频无法解码": lambda r: httpx.Response(200, content=(json.dumps(
                {"code": 0, "data": "@@不是base64@@"}) + "\n").encode()),
        }
        for what, handler in cases.items():
            t = volc(handler)
            e = must_raise(BilledError, t.synthesize, text, VOICE, None, 1.0, Path(d) / "f.wav")
            assert isinstance(e, ProviderError), "BilledError 属明确失败，调用方不重试"
            assert e.billed_cny == tts_cost(len(text), t.caps) > 0, (what, e.billed_cny)
            assert "k-secret" not in str(e) and e.__cause__ is None, what
            assert not (Path(d) / "f.wav").exists(), what
        assert "无法解码" in str(must_raise(BilledError, volc(cases["音频无法解码"]).synthesize,
                                           text, VOICE, None, 1.0, Path(d) / "f.wav"))
        print("4. 收到 200 后的失败（中途断开、坏行、坏音频、流内错误码、没有结束块）按已计费报 ✓")

    real_load = tts_volc._load_dotenv
    saved = {k: os.environ.pop(k, None) for k in ("VOLC_TTS_API_KEY", "VOLC_TTS_APP_ID", "VOLC_TTS_ACCESS_KEY")}
    tts_volc._load_dotenv = lambda path: None
    try:
        e = must_raise(ProviderError, VolcTts.from_env)
        assert "VOLC_TTS_API_KEY" in str(e)
        os.environ["VOLC_TTS_API_KEY"] = "env-key"
        assert VolcTts.from_env()._auth == {"X-Api-Key": "env-key"}
        providers._TTS_INSTANCES.pop("volc", None)
        assert isinstance(providers.get_tts("volc"), VolcTts)
    finally:
        tts_volc._load_dotenv = real_load
        providers._TTS_INSTANCES.pop("volc", None)
        os.environ.pop("VOLC_TTS_API_KEY", None)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    print("5. 读密钥（没配给出处）、注册为 volc ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
