#!/usr/bin/env python3
"""Seedance（火山方舟）：请求体、错误分级、状态映射、下载、计费、密钥。

用 httpx.MockTransport 模拟方舟，不联网、不花钱。用法: python3 tests/render/test_seedance.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from render.providers import base  # noqa: E402
from render.providers.seedance import BASE_URL, MODELS, Seedance, rewrite_refs  # noqa: E402

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 8


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def ark(handler, key="k-secret"):
    return Seedance(key, client=httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler)))


def main() -> int:
    seen = []

    def accept(request):
        seen.append(request)
        return httpx.Response(200, json={"id": "cgt-1"})

    # 1. 提交：参考图模式、首帧模式、整数秒、密钥只在请求头
    sd = ark(accept)
    req = base.ClipRequest(prompt="p @图片1", model="seedance-2.0-fast", duration=7.3,
                           resolution="720p", aspect="9:16", audio=True,
                           refs=[base.RefImage("C01", "character", "https://img/c01.png")])
    assert sd.submit(req) == "cgt-1"
    sent = seen[-1]
    body = json.loads(sent.content)
    assert sent.method == "POST" and sent.url.path == "/api/v3/contents/generations/tasks"
    assert sent.headers["authorization"] == "Bearer k-secret"
    assert body["model"] == MODELS["seedance-2.0-fast"]["id"]
    assert (body["duration"], body["resolution"], body["ratio"]) == (8, "720p", "9:16")
    assert body["return_last_frame"] is True and body["watermark"] is False
    assert body["generate_audio"] is True
    assert body["content"][0] == {"type": "text", "text": "p @图片1"}
    assert body["content"][1] == {"type": "image_url", "image_url": {"url": "https://img/c01.png"},
                                  "role": "reference_image"}
    framed = base.ClipRequest(prompt="p", model="seedance-2.0-mini", duration=3, resolution="480p",
                              audio=False, first_frame="data:image/png;base64,AAAA")
    sd.submit(framed)
    body = json.loads(seen[-1].content)
    assert body["duration"] == 4, "不足 4 秒按 4 秒"
    assert body["generate_audio"] is False
    assert body["content"][1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"},
                                  "role": "first_frame"}
    must_raise(base.ProviderError, sd.submit, base.ClipRequest(prompt="p", model="nope",
                                                               duration=5, resolution="720p"))
    print("1. 提交请求体 ✓")

    # 2. 错误分级：429/5xx/断连 → 瞬时；4xx → 厂商原因原样；密钥不进报错
    def status(code, payload=None):
        return ark(lambda r: httpx.Response(code, json=payload or {}))

    must_raise(base.TransientError, status(429).submit, req)
    e = must_raise(base.ProviderError, status(400, {"error": {"code": "InvalidParameter",
                                                              "message": "duration 不合法"}}).submit, req)
    assert "InvalidParameter" in str(e) and "duration 不合法" in str(e) and "k-secret" not in str(e)

    def refused(request):
        raise httpx.ConnectError("connection refused", request=request)

    e = must_raise(base.TransientError, ark(refused).submit, req)
    assert "k-secret" not in str(e)
    print("2. 错误分级 ✓")

    # 2b. 提交只在请求没发出去（连不上、连接/连接池超时）或 429 时可重试；请求发出后断连、超时、
    #     5xx、2xx 却没有任务 id 都可能已建了付费任务 → AmbiguousSubmit（不重试）。查询照旧
    def raising(exc_type):
        def handler(request):
            raise exc_type("boom", request=request)
        return ark(handler)

    for exc_type in (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
        e = must_raise(base.TransientError, raising(exc_type).submit, req)
        assert not isinstance(e, base.AmbiguousSubmit)
    for exc_type in (httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.WriteTimeout, httpx.ReadError):
        e = must_raise(base.AmbiguousSubmit, raising(exc_type).submit, req)
        assert "k-secret" not in str(e)
    for code in (500, 502, 503):
        must_raise(base.AmbiguousSubmit, status(code).submit, req)
    must_raise(base.AmbiguousSubmit, ark(lambda r: httpx.Response(200, content=b"<html>")).submit, req)
    must_raise(base.AmbiguousSubmit, status(200, {"status": "queued"}).submit, req)
    must_raise(base.TransientError, raising(httpx.ReadTimeout).poll, "cgt-1")
    must_raise(base.TransientError, status(502).poll, "cgt-1")
    must_raise(base.TransientError, status(429).poll, "cgt-1")
    print("2b. 提交结果不明不重试 ✓")

    # 3. 查询：状态映射、产物地址、用量
    def task(payload):
        return ark(lambda r: httpx.Response(200, json=payload))

    ok = {"id": "cgt-1", "status": "succeeded",
          "content": {"video_url": "https://tos.example/v.mp4", "last_frame_url": "https://tos.example/l.jpg"},
          "usage": {"completion_tokens": 108900, "total_tokens": 108900}}
    st = task(ok).poll("cgt-1")
    assert st.status == "succeeded" and st.video_url == "https://tos.example/v.mp4"
    assert st.last_frame_url == "https://tos.example/l.jpg" and st.usage == {"completion_tokens": 108900}
    assert task({"id": "x", "status": "queued"}).poll("x").status == "pending"
    assert task({"id": "x", "status": "running"}).poll("x").status == "running"
    st = task({"id": "x", "status": "failed",
               "error": {"code": "OutputVideoSensitiveContentDetected", "message": "审核未通过"}}).poll("x")
    assert st.status == "failed" and "审核未通过" in st.error
    st = task({"id": "x", "status": "expired"}).poll("x")
    assert st.status == "failed" and st.error
    print("3. 查询映射 ✓")

    # 4. 下载：视频与尾帧；结果地址不带方舟密钥；过期地址报厂商错误
    def files(request):
        assert "authorization" not in request.headers, "下载结果地址不带方舟密钥"
        return httpx.Response(200, content=MP4 if request.url.path.endswith(".mp4") else b"\xff\xd8jpg")

    succeeded = base.TaskState("cgt-1", "succeeded", video_url="https://tos.example/v.mp4",
                               last_frame_url="https://tos.example/l.jpg",
                               usage={"completion_tokens": 108900})
    with tempfile.TemporaryDirectory() as d:
        got = ark(files).download(succeeded, Path(d) / "clips" / "E01-C01.v1.mp4")
        assert base.is_playable_mp4(got["video"]) and got["last_frame"].read_bytes() == b"\xff\xd8jpg"
        must_raise(base.ProviderError, ark(lambda r: httpx.Response(403)).download,
                   succeeded, Path(d) / "x.mp4")
    print("4. 下载 ✓")

    # 5. 计费：有 usage 按 token × 单价；没有按秒估；失败 0；能力表
    fast = MODELS["seedance-2.0-fast"]["cny_per_m"]
    r720 = base.ClipRequest(prompt="", model="seedance-2.0-fast", duration=5, resolution="720p")
    assert sd.cost(succeeded, r720) == round(108900 * fast / 1e6, 2)
    caps = sd.caps("seedance-2.0-fast")
    assert sd.cost(base.TaskState("x", "succeeded"), r720) == base.estimate_cny(5, caps, "720p")
    assert sd.cost(base.TaskState("x", "failed"), r720) == 0.0
    assert caps.resolutions == ["480p", "720p"] and caps.max_refs == 9
    assert caps.min_clip_sec == 4 and caps.max_clip_sec == 15 and not caps.frame_with_refs
    assert abs(caps.cny_per_sec["720p"] - 21600 * fast / 1e6) < 1e-4
    assert "1080p" in sd.caps("seedance-2.0").resolutions
    must_raise(base.ProviderError, sd.caps, "nope")
    assert sd.rewrite_prompt("{ref:C01} {ref:S03}") == "@图片1 @图片2" == rewrite_refs("{ref:C01} {ref:S03}")
    print("5. 计费与能力表 ✓")

    # 6. 密钥：没配时报错说明去哪配（设为空串，.env 不会覆盖已有变量）
    os.environ["ARK_API_KEY"] = ""
    e = must_raise(base.ProviderError, Seedance.from_env)
    assert "ARK_API_KEY" in str(e)
    print("6. 密钥 ✓")

    # 7. 错误带代码
    assert must_raise(base.ProviderError, Seedance.from_env).code == "film.ark.no_key"
    e = must_raise(base.TransientError, status(429).submit, req)
    assert e.code == "film.ark.throttled"
    st = task({"id": "x", "status": "expired"}).poll("x")
    assert st.error_msg["code"] == "film.ark.task_expired" and st.error == "任务超时"
    assert Seedance.rate_note == {"code": "rate.ark", "params": {}} and Seedance.console_name == "console.ark"
    print("7. 错误带代码 ✓")

    # 8. 厂商原文脱敏（三条路径）且兜底不截断、结构化参数限长
    def flat(o):
        return json.dumps(o, ensure_ascii=False)
    leak = "echo k-secret and Bearer OTHER_TOKEN " + "x" * 400
    e = must_raise(base.ProviderError, status(400, {"error": {"code": "Bad", "message": leak}}).submit, req)
    assert "k-secret" not in flat([str(e), e.args, e.params]) and "OTHER_TOKEN" not in flat([str(e), e.params])
    assert len(str(e)) > 400 and len(e.params["detail"]["text"]) == 300
    e = must_raise(base.ProviderError, ark(lambda r: httpx.Response(400, text=leak)).submit, req)
    assert "k-secret" not in flat([str(e), e.params]) and "OTHER_TOKEN" not in flat([str(e), e.params])
    st = task({"id": "x", "status": "failed", "error": {"code": "Bad", "message": leak}}).poll("x")
    assert "k-secret" not in flat([st.error, st.error_msg]) and "OTHER_TOKEN" not in flat([st.error, st.error_msg])
    assert len(st.error) > 400 and len(st.error_msg["params"]["detail"]["text"]) == 300
    print("8. 原文脱敏 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
