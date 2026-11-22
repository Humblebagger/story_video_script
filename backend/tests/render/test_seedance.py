#!/usr/bin/env python3
"""Seedance（火山方舟）：请求体、错误分级、状态映射、下载、计费、密钥。

用 httpx.MockTransport 模拟方舟，不联网、不花钱。用法: python3 tests/render/test_seedance.py
"""
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from render.providers import base  # noqa: E402
from render.providers.seedance import BASE_URL, MODELS, Seedance, rewrite_refs  # noqa: E402

# 测试不读真实的 backend/.env 与仓库根 .env：from_env 里的 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import render.providers.seedance as _prov_seedance  # noqa: E402
_prov_seedance._load_dotenv = lambda *_a, **_k: None

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 8



class _LogGrab(logging.Handler):
    """挂在某个 logger 上收日志文字（测试不读真实日志配置）。"""
    def __init__(self, name, level=logging.DEBUG):
        super().__init__(level)
        self.lines, self.records = [], []
        self._lg = logging.getLogger(name)

    def emit(self, rec):
        self.records.append(rec)
        self.lines.append(rec.getMessage())

    def __enter__(self):
        self._lg.addHandler(self)
        return self

    def __exit__(self, *a):
        self._lg.removeHandler(self)


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
    assert e.code == "film.vendor.rejected" and "InvalidParameter" not in str(e) and "duration" not in str(e)

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
    assert st.status == "failed" and st.error_msg["code"] == "film.vendor.output_moderated"
    assert "审核未通过" not in st.error      # 厂商原文不进界面，只进日志
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
    with _LogGrab("render.providers.seedance") as g:
        e = must_raise(base.ProviderError, Seedance.from_env)
    assert e.code == "film.vendor.no_key" and "ARK_API_KEY" not in str(e) and ".env" not in str(e)
    assert any("ARK_API_KEY" in x for x in g.lines), g.lines
    print("6. 密钥 ✓")

    # 7. 错误带代码
    assert must_raise(base.ProviderError, Seedance.from_env).code == "film.vendor.no_key"
    e = must_raise(base.TransientError, status(429).submit, req)
    assert e.code == "film.vendor.throttled"
    st = task({"id": "x", "status": "expired"}).poll("x")
    assert st.error_msg["code"] == "film.vendor.task_expired" and st.error == "任务超时"
    assert Seedance.rate_note == {"code": "rate.ark", "params": {}} and Seedance.console_name == "console.ark"
    # 7b. 面向最终用户的文案：档位、异常类名不进界面，只进日志
    with _LogGrab("render.providers.seedance") as g:
        e = must_raise(base.ProviderError, sd.caps, "nope-tier")
    assert e.code == "film.settings.no_model" and e.params == {} and "nope-tier" not in str(e)
    assert any("nope-tier" in x for x in g.lines), g.lines
    with _LogGrab("render.providers.seedance") as g:
        e = must_raise(base.TransientError, ark(refused).submit, req)
    assert e.code == "film.vendor.connect_failed" and e.params == {} and "ConnectError" not in str(e)
    assert any("ConnectError" in x for x in g.lines), g.lines
    with _LogGrab("render.providers.seedance") as g:
        e = must_raise(base.AmbiguousSubmit, raising(httpx.ReadTimeout).submit, req)
    assert e.code == "film.provider.submit_cut" and e.params == {} and str(e) == "网络中断"
    assert any("ReadTimeout" in x for x in g.lines), g.lines
    with _LogGrab("render.providers.seedance") as g:
        ds = Seedance("k", client=httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(refused)))
        e2 = must_raise(base.TransientError, ds._fetch, "https://tos.example/v.mp4", Path(tempfile.mkdtemp()) / "x.mp4")
    assert e2.code == "film.provider.download_connect" and e2.params == {}
    assert any("ConnectError" in x for x in g.lines), g.lines
    print("7. 错误带代码 ✓")

    # 8. 厂商原文脱敏（三条路径）：消息不带原话；原话脱敏后进日志，长度有上限
    def flat(o):
        return json.dumps(o, ensure_ascii=False)
    leak = "echo k-secret and Bearer OTHER_TOKEN " + "x" * 400
    with _LogGrab("render.providers.base") as g:
        e = must_raise(base.ProviderError, status(400, {"error": {"code": "Bad", "message": leak}}).submit, req)
    assert e.code == "film.vendor.rejected" and e.params == {} and "Bad" not in str(e) and "xxx" not in str(e)
    assert any("Bad: " in x and "seedance" in x for x in g.lines), g.lines
    assert "k-secret" not in flat(g.lines) and "OTHER_TOKEN" not in flat(g.lines)
    with _LogGrab("render.providers.base") as g:
        e = must_raise(base.ProviderError, ark(lambda r: httpx.Response(400, text=leak)).submit, req)
    assert e.code == "film.vendor.rejected" and "k-secret" not in flat([str(e), e.params, g.lines])
    assert "OTHER_TOKEN" not in flat([str(e), e.params, g.lines])
    with _LogGrab("render.providers.base") as g:
        st = task({"id": "x", "status": "failed", "error": {"code": "Bad", "message": leak}}).poll("x")
    assert st.error_msg["code"] == "film.vendor.rejected" and st.error_msg["params"] == {} and "Bad" not in st.error
    assert "k-secret" not in flat([st.error, st.error_msg, g.lines]) and "OTHER_TOKEN" not in flat([st.error, st.error_msg, g.lines])
    assert any("Bad: " in x for x in g.lines), g.lines
    print("8. 原文脱敏 ✓")

    # 9. 方舟错误码友好映射：界面只给友好文案，厂商原文只进日志
    KEY = "k-secret"
    ZH = {
        "film.vendor.auth": "视频生成服务鉴权失败，请联系管理员",
        "film.vendor.balance": "视频生成服务账户余额不足，暂时无法出片，请联系管理员",
        "film.vendor.access_denied": "视频生成服务拒绝访问，请联系管理员",
        "film.vendor.tier_unavailable": "所选的视频档位暂时不可用，请换一个档位或联系管理员",
        "film.vendor.limit_paused": "视频生成服务已达到用量上限并暂停，请联系管理员",
        "film.vendor.quota": "额度不足或排队已满，持续失败请联系管理员",
        "film.vendor.input_moderated": "这一段的画面描述或参考图没通过内容审核：改写描述或换参考图后重试",
        "film.vendor.copyright": "这一段的描述可能涉及版权限制：改写后重试",
        "film.vendor.output_moderated": "生成的视频没通过内容审核：调整这一段的描述后重试",
        "film.vendor.output_copyright": "生成的视频可能涉及版权限制：调整这一段的描述后重试",
    }

    def body_of(code):
        return {"error": {"code": code, "message": f"vendor text with {KEY} Bearer OTHER_TOKEN"}}

    cases = [
        (401, "AuthenticationError", "film.vendor.auth"),
        (401, "InvalidSubscription", "film.vendor.auth"),
        (403, "AccountOverdueError", "film.vendor.balance"),
        (403, "AccessDenied", "film.vendor.access_denied"),
        (403, "InvalidAccountStatus", "film.vendor.access_denied"),
        (404, "InvalidEndpointOrModel.NotFound", "film.vendor.tier_unavailable"),
        (404, "InvalidEndpointOrModel.ModelIDAccessDisabled", "film.vendor.tier_unavailable"),
        (404, "ModelNotOpen", "film.vendor.tier_unavailable"),
        (403, "OperationDenied.ServiceNotOpen", "film.vendor.tier_unavailable"),
        (403, "OperationDenied.ServiceOverdue", "film.vendor.balance"),
        (403, "OperationDenied.PermissionDenied", "film.vendor.access_denied"),
        (404, "InvalidEndpoint.ClosedEndpoint", "film.vendor.tier_unavailable"),
        (400, "InputImageRiskDetection", "film.vendor.input_moderated"),
        (400, "InputVideoSensitiveContentDetected", "film.vendor.input_moderated"),
        (400, "InputTextRiskDetection.Foo", "film.vendor.input_moderated"),
        (400, "InputImageSensitiveContentDetected.PolicyViolation", "film.vendor.copyright"),
        (400, "SensitiveContentDetected.Violence", "film.vendor.input_moderated"),
        (400, "InputTextSensitiveContentDetected", "film.vendor.input_moderated"),
        (400, "InputImageSensitiveContentDetected", "film.vendor.input_moderated"),
        (400, "InputTextRiskDetection", "film.vendor.input_moderated"),
        (400, "SensitiveContentDetected.PolicyViolation", "film.vendor.copyright"),
        (400, "InputTextSensitiveContentDetected.PolicyViolation", "film.vendor.copyright"),
    ]
    for http, vcode, ours in cases:
        e = must_raise(base.ProviderError, status(http, body_of(vcode)).submit, req)
        assert type(e) is base.ProviderError and e.code == ours, (vcode, e.code)
        assert str(e) == ZH[ours] and KEY not in flat([str(e), e.args, e.params]) and "vendor text" not in str(e)

    # SetLimitExceeded 的 429：不重试（不是瞬时错误，也不是 AmbiguousSubmit），提交与查询都一样
    for call in (lambda s: s.submit(req), lambda s: s.poll("x")):
        e = must_raise(base.ProviderError, call, status(429, body_of("SetLimitExceeded")))
        assert type(e) is base.ProviderError and e.code == "film.vendor.limit_paused" and str(e) == ZH[e.code]
        assert not isinstance(e, (base.TransientError, base.AmbiguousSubmit))

    # QuotaExceeded 是 429：免费额度用尽或排队已满，可重试，用自己的代码
    e = must_raise(base.TransientError, status(429, body_of("QuotaExceeded")).submit, req)
    assert e.code == "film.vendor.quota" and str(e) == ZH[e.code] and KEY not in flat([str(e), e.params])
    e = must_raise(base.TransientError, status(429, body_of("QuotaExceeded")).poll, "x")
    assert e.code == "film.vendor.quota"
    e = must_raise(base.TransientError, status(403, body_of("QuotaExceeded")).submit, req)     # 非 429 同样可重试
    assert e.code == "film.vendor.quota"

    # 429 里别的映射码不该出现：一律当限流重试，不给用户鉴权 / 审核之类的误导文案
    for vcode in ("AuthenticationError", "OperationDenied.ServiceNotOpen", "SensitiveContentDetected.Violence"):
        e = must_raise(base.TransientError, status(429, body_of(vcode)).submit, req)
        assert e.code == "film.vendor.throttled", (vcode, e.code)
        e = must_raise(base.TransientError, status(429, body_of(vcode)).poll, "x")
        assert e.code == "film.vendor.throttled"

    # QuotaExceeded 只在 429 与明确拒绝的 4xx 可重试；5xx 照旧（提交含糊、查询不可用），不自动重提
    e = must_raise(base.AmbiguousSubmit, status(500, body_of("QuotaExceeded")).submit, req)
    assert e.code == "film.vendor.http_ambiguous"
    e = must_raise(base.TransientError, status(503, body_of("QuotaExceeded")).poll, "x")
    assert e.code == "film.vendor.unavailable"
    # 查询返回 failed + QuotaExceeded：终态失败（不重试、不重提），文案是额度
    st = task({"id": "x", "status": "failed", "error": body_of("QuotaExceeded")["error"]}).poll("x")
    assert st.status == "failed" and st.error_msg["code"] == "film.vendor.quota" and st.error == ZH["film.vendor.quota"]

    # 真正的限流仍可重试
    for vcode in ("RateLimitExceeded.EndpointRPMExceeded", "ServerOverloaded", "RequestBurstTooFast"):
        e = must_raise(base.TransientError, status(429, body_of(vcode)).submit, req)
        assert e.code == "film.vendor.throttled"
    e = must_raise(base.TransientError, ark(lambda r: httpx.Response(429, text="slow down")).submit, req)
    assert e.code == "film.vendor.throttled"

    # 轮询里的失败
    for vcode, ours in (("OutputVideoSensitiveContentDetected", "film.vendor.output_moderated"),
                        ("OutputAudioSensitiveContentDetected", "film.vendor.output_moderated"),
                        ("OutputImageSensitiveContentDetected", "film.vendor.output_moderated"),
                        ("OutputImageRiskDetection", "film.vendor.output_moderated"),
                        ("OutputVideoSensitiveContentDetected.PolicyViolation", "film.vendor.output_copyright")):
        st = task({"id": "x", "status": "failed", "error": body_of(vcode)["error"]}).poll("x")
        assert st.error_msg["code"] == ours and st.error == ZH[ours]
        assert KEY not in flat([st.error, st.error_msg])

    # 未映射：统一给 film.vendor.rejected，原文进日志
    with _LogGrab("render.providers.base") as g:
        e = must_raise(base.ProviderError, status(400, {"error": {"code": "InvalidParameter",
                                                                  "message": "duration 不合法"}}).submit, req)
    assert e.code == "film.vendor.rejected" and e.params == {} and "duration" not in str(e)
    assert any("duration 不合法" in x for x in g.lines), g.lines
    for payload in ({"error": {}}, {}, {"error": None}, []):
        with _LogGrab("render.providers.base") as g:
            e = must_raise(base.ProviderError, ark(lambda r, p=payload: httpx.Response(400, json=p)).submit, req)
        assert e.code == "film.vendor.rejected" and e.params == {} and "HTTP" not in str(e), (payload, e.code, str(e))
        assert any("HTTP 400" in x for x in g.lines), g.lines
    e = must_raise(base.ProviderError, ark(lambda r: httpx.Response(401, text="nope")).submit, req)
    assert e.code == "film.vendor.auth"
    e = must_raise(base.ProviderError, ark(lambda r: httpx.Response(403, text="nope")).submit, req)
    assert e.code == "film.vendor.access_denied"
    e = must_raise(base.ProviderError, ark(lambda r: httpx.Response(418, text="teapot")).submit, req)
    assert e.code == "film.vendor.rejected"
    e = must_raise(base.ProviderError, status(403, body_of("OperationDenied.InvalidState")).submit, req)
    assert e.code == "film.vendor.rejected"
    # 有 code 但没命中时不做 HTTP 回落
    e = must_raise(base.ProviderError, status(403, body_of("SomethingNew")).submit, req)
    assert e.code == "film.vendor.rejected"

    # 日志：命中映射时原文进 WARNING，密钥不进
    class _Grab(logging.Handler):
        def __init__(self):
            super().__init__()
            self.lines = []

        def emit(self, rec):
            self.lines.append(rec.getMessage())

    grab = _Grab()
    lg = logging.getLogger("render.providers.seedance")
    lg.addHandler(grab)
    try:
        must_raise(base.ProviderError, ark(lambda r: httpx.Response(
            401, json=body_of("AuthenticationError"), headers={"x-request-id": "rid-123"})).submit, req)
        must_raise(base.ProviderError, status(429, body_of("SetLimitExceeded")).submit, req)
        task({"id": "x", "status": "failed", "error": body_of("OutputVideoSensitiveContentDetected")["error"]}).poll("task-77")
    finally:
        lg.removeHandler(grab)
    assert any("AuthenticationError" in x and "401" in x for x in grab.lines), grab.lines
    assert any("SetLimitExceeded" in x and "429" in x for x in grab.lines), grab.lines
    assert any("OutputVideoSensitiveContentDetected" in x for x in grab.lines), grab.lines
    assert any("AuthenticationError" in x and "rid-123" in x and MODELS[req.model]["id"] in x for x in grab.lines), grab.lines
    assert any("OutputVideoSensitiveContentDetected" in x and "task-77" in x for x in grab.lines), grab.lines
    assert not any(KEY in x or "OTHER_TOKEN" in x for x in grab.lines), grab.lines
    print("9. 方舟错误码映射 ✓")

    # 9b. 日志整体脱敏：响应头回显实例密钥、正文含其他厂商环境密钥、任务编号与档位里带密钥、Bearer 凭据
    OTHER = "FAKE-MINIMAX-ENV-VALUE-xyz"
    old_env = os.environ.get("MINIMAX_API_KEY")
    os.environ["MINIMAX_API_KEY"] = OTHER
    try:
        skey = "k-instance-secret"
        with _LogGrab("render.providers.seedance") as g:
            sdk = ark(lambda r: httpx.Response(401, json={"error": {"code": "AuthenticationError", "message": f"bad {OTHER}"}},
                                               headers={"X-Request-Id": skey}), key=skey)
            must_raise(base.ProviderError, sdk.submit, req)
            sdt = ark(lambda r: httpx.Response(401, json={"error": {"code": "AuthenticationError", "message": "x"}}), key=skey)
            must_raise(base.ProviderError, sdt.poll, f"cgt-{skey}")
            def refused2(request):
                raise httpx.ConnectError("refused", request=request)
            must_raise(base.TransientError, ark(refused2, key=skey).poll, f"cgt-{skey}")
            must_raise(base.ProviderError, ark(accept, key=skey).caps, f"Bearer {skey}-FAKE_TOKEN")
        assert g.lines and any("AuthenticationError" in x for x in g.lines), g.lines
        for x in g.lines:
            assert skey not in x and OTHER not in x and "FAKE_TOKEN" not in x, x
    finally:
        if old_env is None:
            os.environ.pop("MINIMAX_API_KEY", None)
        else:
            os.environ["MINIMAX_API_KEY"] = old_env
    print("9b. 日志整体脱敏 ✓")

    # 10. 取消：先查状态，只有排队中才发 DELETE；方舟的 DELETE 回空对象，所以再查一次确认变成 cancelled
    calls = []

    def cancel_api(*statuses):
        left = list(statuses)

        def handler(r):
            calls.append((r.method, r.url.path))
            if r.method == "GET":
                return httpx.Response(200, json={"id": "cgt-1", "status": left.pop(0)})
            return httpx.Response(200, json={})
        return handler

    path = "/api/v3/contents/generations/tasks/cgt-1"
    assert ark(cancel_api("queued", "cancelled")).cancel("cgt-1") is True
    assert calls == [("GET", path), ("DELETE", path), ("GET", path)], calls
    for status in ("running", "succeeded", "failed", "expired", "cancelled"):
        calls.clear()
        assert ark(cancel_api(status)).cancel("cgt-1") is False
        assert calls == [("GET", path)], (status, calls)
    assert ark(cancel_api("queued", "running")).cancel("cgt-1") is False, "DELETE 之后没变成 cancelled：不算取消成功"

    def cancel_refused(r):
        if r.method == "GET":
            return httpx.Response(200, json={"id": "cgt-1", "status": "queued"})
        return httpx.Response(400, json={"error": {"code": "InvalidParameter", "message": "task is running"}})

    must_raise(base.ProviderError, ark(cancel_refused).cancel, "cgt-1")
    assert base.try_cancel(ark(cancel_refused), "cgt-1") is False, "取消接口报错由 try_cancel 接住"
    assert Seedance.typical_sec == (120, 480)
    print("10. 取消 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
