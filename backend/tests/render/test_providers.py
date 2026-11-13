#!/usr/bin/env python3
"""出片：厂商统一接口的公共函数、假厂商、注册表。用法: python3 tests/render/test_providers.py"""
import logging
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from render import providers  # noqa: E402
from render.providers import base  # noqa: E402
from render.providers.fake import FAKE_MP4, FakeVideo  # noqa: E402

# 测试不读真实的 .env：各处 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import pipeline.config as _pc  # noqa: E402
import render.providers.minimax as _mm  # noqa: E402
import render.providers.seedance as _sd  # noqa: E402
_pc._load_dotenv = _mm._load_dotenv = _sd._load_dotenv = lambda *_a, **_k: None


class _LogGrab(logging.Handler):
    """挂在某个 logger 上收日志文字与记录（测试不读真实日志配置）。"""
    def __init__(self, name):
        super().__init__(logging.DEBUG)
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


def main() -> int:
    fake = FakeVideo()
    caps = fake.caps("fake-1")

    # 1. 整数秒：向上取整，夹在上下限之间；预估 = 秒数 × 单价
    assert base.request_seconds(4.2, caps) == 5
    assert base.request_seconds(1.0, caps) == 2 and base.request_seconds(30, caps) == 10
    assert base.request_seconds(6.0, caps) == 6, "整数不多算一秒"
    assert base.estimate_cny(4.2, caps, "720p") == 5.0
    assert base.estimate_cny(4.2, caps, "480p") == 2.5
    print("1. 整数秒与预估 ✓")

    # 1b. 图片费：缺省字段为 0 时与旧版相同；超出免费张数的部分按张计
    assert base.estimate_cny(4.2, caps, "720p", images=9) == 5.0, "缺省不收图片费"
    priced = base.Caps(max_clip_sec=15, min_clip_sec=4, max_refs=9, first_frame=True, last_frame=False,
                       returns_last_frame=True, native_audio=False, frame_with_refs=False,
                       resolutions=["768P"], cny_per_sec={"768P": 0.5},
                       short_side={"768P": 768}, free_images=5, cny_per_image=0.2)
    assert base.estimate_cny(4, priced, "768P") == 2.0
    assert base.estimate_cny(4, priced, "768P", images=5) == 2.0, "前 5 张免费"
    assert base.estimate_cny(4, priced, "768P", images=7) == 2.4, "超出 2 张"
    assert base.ClipRequest(prompt="", model="m", duration=1, resolution="r").images is None
    print("1b. 图片费 ✓")

    # 2. 可播放校验：MP4 容器头，不依赖 ffmpeg
    with tempfile.TemporaryDirectory() as d:
        good, bad = Path(d) / "a.mp4", Path(d) / "b.mp4"
        good.write_bytes(FAKE_MP4)
        bad.write_bytes(b"<html>expired</html>")
        assert base.is_playable_mp4(good) and not base.is_playable_mp4(bad)
        assert not base.is_playable_mp4(Path(d) / "missing.mp4")
    print("2. 可播放校验 ✓")

    # 3. 假厂商：提交 → 轮询 → 成功 → 下载 → 计费；失败、瞬时错误
    slow = FakeVideo(polls_to_finish=2)
    req = base.ClipRequest(prompt="p", model="fake-1", duration=4.2, resolution="720p")
    tid = slow.submit(req)
    assert slow.poll(tid).status == "running"
    st = slow.poll(tid)
    assert st.status == "succeeded" and st.usage == {"seconds": 5}
    with tempfile.TemporaryDirectory() as d:
        files = slow.download(st, Path(d) / "clips" / "E01-C01.v1.mp4")
        assert base.is_playable_mp4(files["video"])
        assert files["last_frame"].name == "E01-C01.v1.last.jpg" and files["last_frame"].exists()
    assert slow.cost(st, req) == 5.0
    assert slow.cost(base.TaskState("x", "failed"), req) == 0.0, "失败不计费"
    must_raise(base.ProviderError, slow.poll, "nope")
    bad = FakeVideo(fail_with="审核未通过")
    st = bad.poll(bad.submit(req))
    assert st.status == "failed" and st.error == "审核未通过"
    flaky = FakeVideo(transient_submits=1)
    must_raise(base.TransientError, flaky.submit, req)
    assert flaky.submit(req) == "fake-1", "瞬时错误不占任务号"
    assert fake.rewrite_prompt("看 {ref:C01} 和 {ref:S03}") == "看 [参考C01] 和 [参考S03]"
    must_raise(base.ProviderError, fake.caps, "nope")
    print("3. 假厂商全流程 ✓")

    # 4. 注册表：同名只建一次；未注册抛 KeyError
    mine = FakeVideo()
    providers.register("fake", lambda: mine)
    assert providers.get_video("fake") is mine and providers.get_video("fake") is mine
    must_raise(KeyError, providers.get_video, "nope")
    os.environ["MINIMAX_API_KEY"] = ""          # 先置空串：.env 不会覆盖已有变量
    with _LogGrab("render.providers.minimax") as g:
        e = must_raise(base.ProviderError, providers.get_video, "minimax")
    assert e.code == "film.minimax.no_key" and "MINIMAX_API_KEY" not in str(e)
    assert any("MINIMAX_API_KEY" in x for x in g.lines), g.lines
    with _LogGrab("render.providers.fake") as g:
        e = must_raise(base.ProviderError, FakeVideo().caps, "nope-tier")
    assert e.code == "film.fake.unknown_model" and e.params == {} and "nope-tier" not in str(e)
    assert any("nope-tier" in x for x in g.lines), g.lines
    print("4. 注册表 ✓")

    # 5. 缺省厂商：显式设置照用；只有 MiniMax 密钥 → minimax；只有方舟 → 回落 seedance；都没有 → minimax
    saved_env = os.environ.pop("STORYBOARD_VIDEO_PROVIDER", None)
    real_has = providers._has_key
    try:
        for keys, want, fell in (({"minimax"}, "minimax", False), ({"minimax", "seedance"}, "minimax", False),
                                 ({"seedance"}, "seedance", True), (set(), "minimax", False)):
            providers._has_key = lambda n, ks=keys: n in ks
            assert providers.default_video_name() == want, (keys, want)
            assert providers.default_fell_back() is fell, (keys, fell)
        os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"
        providers._has_key = lambda n: (_ for _ in ()).throw(AssertionError("显式设置时不该查密钥"))
        assert providers.default_video_name() == "fake" and providers.default_fell_back() is False
        assert "fake" in providers.names()
        os.environ.pop("STORYBOARD_VIDEO_PROVIDER")
        providers._has_key = lambda n: False
        assert "fake" not in providers.names() and {"minimax", "seedance"} <= set(providers.names())
    finally:
        providers._has_key = real_has
        if saved_env is None:
            os.environ.pop("STORYBOARD_VIDEO_PROVIDER", None)
        else:
            os.environ["STORYBOARD_VIDEO_PROVIDER"] = saved_env
    print("5. 缺省厂商与回落 ✓")

    # 6. 错误带代码
    e = must_raise(KeyError, providers.get_video, "nope")
    assert e.code == "film.provider.unknown" and e.args[0] == "未知的视频厂商：nope"
    assert FakeVideo().rate_note["code"] == "rate.fake"
    print("6. 错误带代码 ✓")

    # 脱敏：模型密钥、签名密钥、x-api-key 头
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-fake-0123456789"
    os.environ["STORYBOARD_SECRET"] = "fake-signing-secret-0123"
    try:
        out = base.scrub_secrets("k=sk-ant-fake-0123456789 s=fake-signing-secret-0123")
        assert "sk-ant-fake-0123456789" not in out and "fake-signing-secret-0123" not in out, out
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("STORYBOARD_SECRET", None)
    for raw in ("x-api-key: abc", '{"x-api-key": "abc"}', "X-Api-Key=abc"):
        assert "abc" not in base.scrub(raw), (raw, base.scrub(raw))
    print("脱敏：模型密钥 / 签名密钥 / x-api-key ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
