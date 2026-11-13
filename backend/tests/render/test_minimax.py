#!/usr/bin/env python3
"""MiniMax H3：能力表、改写与请求体、图片检查与规范化、错误映射、状态映射、下载重查与截尾帧、计费、密钥。

用 httpx.MockTransport 模拟接口，不联网、不花钱。用法: python3 tests/render/test_minimax.py
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from render.providers import base  # noqa: E402
from render.providers import minimax as mm  # noqa: E402
from render.providers.minimax import BASE_URL, MODELS, MiniMax, plan_normalize, rewrite_refs  # noqa: E402

# 测试不读真实的 backend/.env 与仓库根 .env：from_env 里的 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import render.providers.minimax as _prov_minimax  # noqa: E402
_prov_minimax._load_dotenv = lambda *_a, **_k: None

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 8
PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
HAS_FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def mmx(handler, key="k-secret"):
    return MiniMax(key, client=httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler)))


def png_uri(w, h, mime="image/png"):
    """用 ffmpeg 生成 w×h 的 PNG data URI。"""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "a.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=red:s={w}x{h}",
                        "-frames:v", "1", str(p)], check=True)
        return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def dims(uri):
    raw = base64.b64decode(uri.split(",", 1)[1])
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.img"
        p.write_bytes(raw)
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=width,height", "-of", "csv=p=0", str(p)],
                             capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


def main() -> int:
    os.environ.pop("STORYBOARD_MINIMAX_PRICE_SCALE", None)
    os.environ.pop("STORYBOARD_MINIMAX_NATIVE_AUDIO", None)
    seen = []

    def accept(request):
        seen.append(request)
        return httpx.Response(200, json={"task_id": "106916112212032", "base_resp": {"status_code": 0}})

    # 1. 能力表：三档的分辨率顺序（默认在前）、单价、图片费、短边；尾帧恒为 True；默认不出原声
    m = mmx(accept)
    h3, hs, lite = m.caps("minimax-h3"), m.caps("minimax-h3-highspeed"), m.caps("minimax-h3-lite")
    assert h3.resolutions == ["768P", "2K"] and hs.resolutions == ["768P", "480P"] == lite.resolutions
    assert h3.cny_per_sec == {"768P": 0.5, "2K": 0.8}
    assert hs.cny_per_sec == {"768P": 0.4, "480P": 0.26} and lite.cny_per_sec == {"768P": 0.26, "480P": 0.16}
    assert (h3.free_images, h3.cny_per_image, lite.cny_per_image) == (5, 0.2, 0.13)
    assert h3.short_side == {"768P": 768, "2K": 1440} and lite.short_side == {"768P": 768, "480P": 480}
    assert h3.returns_last_frame is True and h3.first_frame and not h3.frame_with_refs
    assert (h3.min_clip_sec, h3.max_clip_sec, h3.max_refs) == (4, 15, 9)
    assert h3.native_audio is False
    os.environ["STORYBOARD_MINIMAX_NATIVE_AUDIO"] = "1"
    assert m.caps("minimax-h3").native_audio is True
    os.environ.pop("STORYBOARD_MINIMAX_NATIVE_AUDIO")
    os.environ["STORYBOARD_MINIMAX_PRICE_SCALE"] = "0.5"
    assert m.caps("minimax-h3").cny_per_sec["768P"] == 0.25 and m.caps("minimax-h3").cny_per_image == 0.1
    os.environ["STORYBOARD_MINIMAX_PRICE_SCALE"] = "abc"
    assert m.caps("minimax-h3").cny_per_sec["768P"] == 0.5, "解析失败按 1.0"
    os.environ.pop("STORYBOARD_MINIMAX_PRICE_SCALE")
    must_raise(base.ProviderError, m.caps, "MiniMax-H3-Max")
    assert m.default_model == "minimax-h3" and set(m.models) == set(MODELS)
    assert m.console_name == "console.minimax" and m.rate_note["code"] == "rate.minimax"
    print("1. 能力表 ✓")

    # 2. 改写与请求体
    assert rewrite_refs("【首帧】{ref:__first__} 开场\n【参考】{ref:C01} 林冲\n【参考】{ref:C01} 再一次") == \
        "【首帧】参考图1 开场\n【参考】参考图2 林冲\n【参考】参考图3 再一次"
    assert m.rewrite_prompt("{ref:A}{ref:B}") == "参考图1参考图2"
    req = base.ClipRequest(prompt="p 参考图1 参考图2", model="minimax-h3", duration=7.3, resolution="768P",
                           aspect="9:16", refs=[base.RefImage("C01", "character", "https://img/c01.png"),
                                                base.RefImage("S01", "location", "https://img/s01.png")])
    assert m.submit(req) == "106916112212032"
    sent = seen[-1]
    body = json.loads(sent.content)
    assert sent.method == "POST" and sent.url.path == "/v2/video_generation"
    assert sent.headers["authorization"] == "Bearer k-secret"
    assert body["model"] == "MiniMax-H3" and (body["duration"], body["resolution"], body["ratio"]) == (8, "768P", "9:16")
    assert body["aigc_watermark"] is False and "response_format" not in body and "callback_url" not in body
    assert body["content"][0] == {"type": "text", "text": "p 参考图1 参考图2"}
    assert [c["image_url"]["url"] for c in body["content"][1:]] == ["https://img/c01.png", "https://img/s01.png"]
    assert all(c["role"] == "reference_image" and c["type"] == "image_url" for c in body["content"][1:])
    framed = base.ClipRequest(prompt="p", model="minimax-h3-lite", duration=4, resolution="480P", aspect="9:16",
                              first_frame="https://img/kf.png")
    m.submit(framed)
    body = json.loads(seen[-1].content)
    assert "ratio" not in body, "图生由图决定画幅，不传 ratio"
    assert body["content"][1] == {"type": "image_url", "image_url": {"url": "https://img/kf.png"}, "role": "first_frame"}
    text_only = base.ClipRequest(prompt="p", model="minimax-h3-lite", duration=4, resolution="480P", aspect="9:16")
    m.submit(text_only)
    assert json.loads(seen[-1].content)["ratio"] == "9:16", "Lite 文生也显式给比例"
    must_raise(base.ProviderError, m.submit,
               base.ClipRequest(prompt="x" * 7001, model="minimax-h3", duration=4, resolution="768P"))
    must_raise(base.ProviderError, m.submit,
               base.ClipRequest(prompt="p", model="minimax-h3", duration=4, resolution="768P", aspect="5:4"))
    must_raise(base.ProviderError, m.submit,
               base.ClipRequest(prompt="p", model="minimax-h3", duration=4, resolution="1080p"))
    n_before = len(seen)
    print("2. 改写与请求体 ✓")

    # 3. 图片：http(s) 原样；MIME 转小写；不支持的格式报错；过小、过宽的图规范化；临时目录用完即删
    up = "data:IMAGE/PNG;base64," + base64.b64encode(PNG_1x1).decode()
    if HAS_FF:
        made = []
        real_td = mm.tempfile.TemporaryDirectory

        class Spy(real_td):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                made.append(Path(self.name))
        mm.tempfile.TemporaryDirectory = Spy
        try:
            m.submit(base.ClipRequest(prompt="p 参考图1 参考图2", model="minimax-h3", duration=4, resolution="768P",
                                      refs=[base.RefImage("C01", "character", png_uri(100, 100)),
                                            base.RefImage("S01", "location", png_uri(3000, 800))]))
        finally:
            mm.tempfile.TemporaryDirectory = real_td
        imgs = [c["image_url"]["url"] for c in json.loads(seen[-1].content)["content"][1:]]
        for u in imgs:
            w, h = dims(u)
            assert 256 <= w <= 5760 and 256 <= h <= 5760 and 0.4 <= w / h <= 2.5, (w, h)
        assert made and not any(p.exists() for p in made), "规范化的临时目录提交后不存在"
        m.submit(base.ClipRequest(prompt="p 参考图1", model="minimax-h3", duration=4, resolution="768P",
                                  refs=[base.RefImage("C01", "character", up)]))
        assert json.loads(seen[-1].content)["content"][1]["image_url"]["url"].startswith("data:image/")
    else:
        print("   （本机没有 ffmpeg/ffprobe：跳过规范化用例）")
    orig_tool = mm._tool
    mm._tool = lambda name: None                       # 没装 ffmpeg：不规范化、原样发出（MIME 仍转小写）
    try:
        m.submit(base.ClipRequest(prompt="p 参考图1", model="minimax-h3", duration=4, resolution="768P",
                                  refs=[base.RefImage("C01", "character", up)]))
    finally:
        mm._tool = orig_tool
    assert json.loads(seen[-1].content)["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    e = must_raise(base.ProviderError, m.submit,
                   base.ClipRequest(prompt="p", model="minimax-h3", duration=4, resolution="768P",
                                    refs=[base.RefImage("C01", "character", "data:image/gif;base64,R0lG")]))
    assert "C01" in str(e) and "image/gif" in str(e)
    assert plan_normalize(1000, 1600) is None
    assert plan_normalize(100, 100) == (256, 256, 256, 256)
    assert plan_normalize(3000, 800) == (3000, 800, 3000, 1200)
    assert plan_normalize(400, 2000) == (400, 2000, 800, 2000)
    w, h, pw, ph = plan_normalize(8000, 3000)
    assert pw <= 5760 and ph <= 5760 and 0.4 <= pw / ph <= 2.5
    print("3. 图片检查与规范化 ✓")

    # 4. 错误映射（§8.1 判定表，每行至少一例）
    def answer(resp=None, exc=None):
        def h(request):
            if exc:
                raise exc
            return resp
        return mmx(h)
    q = base.ClipRequest(prompt="p", model="minimax-h3", duration=4, resolution="768P")
    for ex in (httpx.ConnectError("x"), httpx.ConnectTimeout("x"), httpx.PoolTimeout("x")):
        must_raise(base.TransientError, answer(exc=ex).submit, q)                       # 1
    must_raise(base.AmbiguousSubmit, answer(exc=httpx.ReadTimeout("x")).submit, q)        # 2
    must_raise(base.TransientError, answer(exc=httpx.ReadTimeout("x")).poll, "t")
    must_raise(base.TransientError, answer(httpx.Response(429, json={})).submit, q)       # 3
    must_raise(base.TransientError, answer(httpx.Response(529, json={})).submit, q)       # 3：529 先于 5xx
    must_raise(base.AmbiguousSubmit, answer(httpx.Response(500, json={})).submit, q)      # 4
    must_raise(base.TransientError, answer(httpx.Response(502, json={})).poll, "t")
    e = must_raise(base.ProviderError, answer(httpx.Response(402, json={})).submit, q)    # 5
    assert "余额不足" in str(e)
    e = must_raise(base.ProviderError, answer(httpx.Response(200, json={"base_resp": {"status_code": 1008,
                   "status_msg": "insufficient balance"}})).submit, q)                     # 9 + 5
    assert "余额不足" in str(e)
    e = must_raise(base.ProviderError, answer(httpx.Response(401, json={"error": {"type": "authorized_error",
                   "message": "invalid api key (1004)"}})).submit, q)                      # 6
    assert "密钥无效" in str(e) and "k-secret" not in str(e)
    e = must_raise(base.ProviderError, answer(httpx.Response(422, json={"error": {"code": 1026,
                   "message": "video description contains sensitive content"}})).submit, q)  # 7
    assert "审核" in str(e)
    e = must_raise(base.ProviderError, answer(httpx.Response(200, json={"error": {"message":
                   "video description contains sensitive content (1026)"}})).submit, q)    # 9：码在说明里
    assert "审核" in str(e)
    e = must_raise(base.ProviderError, answer(httpx.Response(400, json={"error": {"code": 2013,
                   "message": "prompt is required"}})).submit, q)                          # 8
    assert "2013" in str(e) and "prompt is required" in str(e)
    must_raise(base.AmbiguousSubmit, answer(httpx.Response(200, text="<html>")).submit, q)  # 10
    must_raise(base.AmbiguousSubmit, answer(httpx.Response(200, json={"base_resp": {"status_code": 0}})).submit, q)
    must_raise(base.TransientError, answer(httpx.Response(200, text="<html>")).poll, "t")
    print("4. 错误映射 ✓")

    # 5. 查询：状态映射、task 结构、usage 原样、失败原因
    def task(status, **extra):
        return mmx(lambda r: httpx.Response(200, json={"task": {"task_id": "t", "status": status, **extra},
                                                       "base_resp": {"status_code": 0}}))
    assert task("queued").poll("t").status == "pending"
    assert task("running").poll("t").status == "running"
    assert task("weird").poll("t").status == "running"
    st = task("succeeded", content={"url": "https://cdn/x.mp4"}, usage={"input_image_count": 7}).poll("t")
    assert (st.status, st.video_url, st.last_frame_url) == ("succeeded", "https://cdn/x.mp4", None)
    assert st.usage == {"input_image_count": 7}
    st = task("failed", error={"code": "1026", "message": "sensitive"}).poll("t")
    assert st.status == "failed" and "审核" in st.error
    st = task("failed", error={"code": "2056", "message": "boom"}).poll("t")
    assert st.error == "2056：boom"
    assert task("cancelled").poll("t").error == "任务已取消"
    poll_seen = []
    mmx(lambda r: (poll_seen.append(r), httpx.Response(200, json={"task": {"status": "running"}}))[1]).poll("abc")
    assert poll_seen[0].url.path == "/v2/query/video_generation/abc"
    print("5. 查询 ✓")

    # 6. 下载：正常；地址过期后重查再下；重查仍失败报错；尾帧截取与降级
    with tempfile.TemporaryDirectory() as d:
        clips = Path(d) / "clips"
        hits = []

        def cdn(request):
            hits.append(str(request.url))
            if request.url.path == "/v2/query/video_generation/t":
                return httpx.Response(200, json={"task": {"status": "succeeded", "content": {"url": "https://cdn/new.mp4"}}})
            if request.url.host == "cdn" and request.url.path == "/old.mp4":
                return httpx.Response(403)
            assert "authorization" not in request.headers, "下载直链不带密钥"
            return httpx.Response(200, content=MP4)
        orig_tool = mm._tool
        mm._tool = lambda name: None
        try:
            files = mmx(cdn).download(base.TaskState("t", "succeeded", video_url="https://cdn/ok.mp4"),
                                      clips / "E01-C01.v1.mp4")
            assert files["video"].read_bytes() == MP4 and files["last_frame"] is None, "没 ffmpeg 不截尾帧"
            files = mmx(cdn).download(base.TaskState("t", "succeeded", video_url="https://cdn/old.mp4"),
                                      clips / "E01-C02.v1.mp4")
            assert files["video"].exists() and any(h.endswith("/new.mp4") for h in hits)
            dead = mmx(lambda r: httpx.Response(403) if r.url.host == "cdn"
                       else httpx.Response(200, json={"task": {"status": "succeeded", "content": {"url": "https://cdn/x.mp4"}}}))
            e = must_raise(base.ProviderError, dead.download,
                           base.TaskState("t", "succeeded", video_url="https://cdn/x.mp4"), clips / "E01-C03.v1.mp4")
            assert "7 天" in str(e)
            must_raise(base.TransientError, mmx(lambda r: httpx.Response(503)).download,
                       base.TaskState("t", "succeeded", video_url="https://cdn/y.mp4"), clips / "E01-C04.v1.mp4")
        finally:
            mm._tool = orig_tool
        if HAS_FF:
            real = Path(d) / "real.mp4"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x568:d=1",
                            "-pix_fmt", "yuv420p", str(real)], check=True)
            payload = real.read_bytes()
            files = mmx(lambda r: httpx.Response(200, content=payload)).download(
                base.TaskState("t", "succeeded", video_url="https://cdn/r.mp4"), clips / "E01-C05.v1.mp4")
            assert files["last_frame"] and files["last_frame"].name == "E01-C05.v1.last.jpg"
            assert files["last_frame"].stat().st_size > 0
            files = mmx(lambda r: httpx.Response(200, content=MP4)).download(
                base.TaskState("t", "succeeded", video_url="https://cdn/bad.mp4"), clips / "E01-C06.v1.mp4")
            assert files["last_frame"] is None, "截不到尾帧不让本段失败"
            assert not (clips / "E01-C06.v1.last.jpg").exists()
    print("6. 下载与尾帧 ✓")

    # 7. 计费：失败为 0；≤ 5 张不加钱；7 张加 2 张；优先 usage.input_image_count，没有时用 req.images
    r = base.ClipRequest(prompt="", model="minimax-h3", duration=5, resolution="768P")
    ok = base.TaskState("t", "succeeded")
    assert m.cost(base.TaskState("t", "failed"), r) == 0.0
    assert m.cost(ok, r) == 2.5
    r.images = 5
    assert m.cost(ok, r) == 2.5
    r.images = 7
    assert m.cost(ok, r) == 2.9
    assert m.cost(base.TaskState("t", "succeeded", usage={"input_image_count": 9}), r) == 3.3
    lr = base.ClipRequest(prompt="", model="minimax-h3-lite", duration=4, resolution="480P", images=6)
    assert m.cost(ok, lr) == round(4 * 0.16 + 0.13, 2)
    assert base.estimate_cny(5, m.caps("minimax-h3"), "768P", images=7) == 2.9
    print("7. 计费 ✓")

    # 8. 密钥与地址：没配时报错说明去哪配；可换地址
    os.environ["MINIMAX_API_KEY"] = ""
    e = must_raise(base.ProviderError, MiniMax.from_env)
    assert "MINIMAX_API_KEY" in str(e)
    os.environ["MINIMAX_API_KEY"] = "k-env"
    os.environ["STORYBOARD_MINIMAX_BASE_URL"] = "https://api.example.io"
    try:
        inst = MiniMax.from_env()
        assert str(inst._http.base_url).rstrip("/") == "https://api.example.io"
    finally:
        os.environ["MINIMAX_API_KEY"] = ""
        os.environ.pop("STORYBOARD_MINIMAX_BASE_URL", None)
    assert len(seen) >= n_before
    print("8. 密钥与地址 ✓")

    # 9. 复审修正：adaptive 画幅；错误文本脱敏与截断；损坏的 data URI
    ad = base.ClipRequest(prompt="p", model="minimax-h3", duration=4, resolution="768P", aspect="adaptive",
                          refs=[base.RefImage("C01", "character", "https://img/c01.png")])
    m.submit(ad)
    assert json.loads(seen[-1].content)["ratio"] == "adaptive"
    m.submit(base.ClipRequest(prompt="p", model="minimax-h3-highspeed", duration=4, resolution="480P",
                              aspect="adaptive", refs=[base.RefImage("C01", "character", "https://img/c01.png")]))
    assert json.loads(seen[-1].content)["ratio"] == "adaptive"
    n_sent = len(seen)
    e = must_raise(base.ProviderError, m.submit, base.ClipRequest(
        prompt="p", model="minimax-h3-lite", duration=4, resolution="480P", aspect="adaptive",
        refs=[base.RefImage("C01", "character", "https://img/c01.png")]))
    assert "Lite" in str(e) and "adaptive" in str(e) and len(seen) == n_sent, "Lite 参考生不发 adaptive"
    leak = answer(httpx.Response(400, json={"error": {"code": 2013, "message":
                  "bad Authorization: Bearer k-secret and key k-secret " + "x" * 600}}))
    e = must_raise(base.ProviderError, leak.submit, q)
    assert "k-secret" not in str(e) and len(str(e)) < 400, str(e)
    e = must_raise(base.ProviderError, answer(httpx.Response(418, text="echo k-secret " + "y" * 900)).submit, q)
    assert "k-secret" not in str(e) and len(str(e)) < 400
    st = task("failed", error={"code": "2056", "message": "boom k-secret " + "z" * 600}).poll("t")
    assert "k-secret" not in st.error and len(st.error) < 400
    e = must_raise(base.ProviderError, m.submit, base.ClipRequest(
        prompt="p", model="minimax-h3", duration=4, resolution="768P",
        refs=[base.RefImage("C01", "character", "data:image/png;base64,@@@@!!!")]))
    assert "C01" in str(e) and "损坏" in str(e)
    print("9. 复审修正 ✓")

    # 10. 错误带代码
    def code_of(resp=None, exc=None, cls=base.ProviderError):
        return must_raise(cls, answer(resp, exc).submit, q)
    assert code_of(httpx.Response(402, json={})).code == "film.minimax.insufficient_balance"
    assert code_of(httpx.Response(401, json={})).code == "film.minimax.invalid_key"
    assert code_of(httpx.Response(422, json={"error": {"code": 1026, "message": "x"}})).code == "film.minimax.moderated"
    st = task("failed", error={"code": "1026", "message": "sensitive"}).poll("t")
    assert st.error_msg["code"] == "film.minimax.moderated" and "审核" in st.error
    assert task("cancelled").poll("t").error_msg["code"] == "film.provider.task_cancelled"
    e = code_of(httpx.Response(400, json={"error": {"code": 2013, "message": "echo k-secret here"}}))
    assert e.code == "film.provider.rejected" and e.params["detail"]["t"] == "vendor"
    assert "k-secret" not in json.dumps(e.params, ensure_ascii=False)
    st = task("failed", error={"code": "2056", "message": "boom k-secret"}).poll("t")
    assert st.error_msg["code"] == "film.provider.rejected" and "k-secret" not in json.dumps(st.error_msg)
    e = code_of(exc=httpx.ReadTimeout("x"), cls=base.AmbiguousSubmit)
    assert e.code == "film.provider.submit_cut"
    e = must_raise(base.ProviderError, mmx(lambda r: httpx.Response(200)).submit, base.ClipRequest(
        prompt="p", model="minimax-h3", duration=4, resolution="768P",
        refs=[base.RefImage("C01", "character", "data:image/png;base64,@@@@!!!")]))
    assert e.code == "film.minimax.corrupt_image"
    assert e.params["label"] == {"code": "film.minimax.label_ref", "params": {"id": "C01"}}
    with tempfile.TemporaryDirectory() as d:
        dead = mmx(lambda r: httpx.Response(403) if r.url.host == "cdn"
                   else httpx.Response(200, json={"task": {"status": "succeeded", "content": {"url": "https://cdn/x.mp4"}}}))
        e = must_raise(base.ProviderError, dead.download,
                       base.TaskState("t", "succeeded", video_url="https://cdn/x.mp4"), Path(d) / "c" / "a.mp4")
        assert e.code == "film.minimax.url_expired"
    assert MiniMax.rate_note == {"code": "rate.minimax", "params": {}} and MiniMax.console_name == "console.minimax"
    print("10. 错误带代码 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
