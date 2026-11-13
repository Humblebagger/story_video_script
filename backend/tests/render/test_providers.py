#!/usr/bin/env python3
"""出片：厂商统一接口的公共函数、假厂商、注册表。用法: python3 tests/render/test_providers.py"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from render import providers  # noqa: E402
from render.providers import base  # noqa: E402
from render.providers.fake import FAKE_MP4, FakeVideo  # noqa: E402


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
    print("4. 注册表 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
