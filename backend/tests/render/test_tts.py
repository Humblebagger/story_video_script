#!/usr/bin/env python3
"""TTS 统一接口与假 TTS：默认音色按性别、费用、WAV 时长与拼接、注册表。

不联网、不花钱。用法: python3 tests/render/test_tts.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from render import providers  # noqa: E402
from render.providers import tts_base  # noqa: E402
from render.providers.fake import FakeTts  # noqa: E402


def main() -> int:
    tts = FakeTts()
    assert tts_base.default_voice(tts.caps, "male_elder") == "fake-male"
    assert tts_base.default_voice(tts.caps, "female_young") == "fake-female"
    assert tts_base.default_voice(tts.caps, "child") is None
    assert tts_base.default_voice(tts.caps, None) is None
    assert tts_base.tts_cost(10000, tts.caps) == 3.0
    print("1. 默认音色按性别、费用 ✓")

    with tempfile.TemporaryDirectory() as d:
        r = tts.synthesize("九个字的一句台词呀", "fake-male", None, 1.0, Path(d) / "a.wav")
        assert abs(r.duration - 2.0) < 0.01 and r.chars == 9, r
        assert r.cost_cny == tts_base.tts_cost(9, tts.caps)
        assert abs(tts_base.wav_seconds(r.file) - r.duration) < 1e-6
        r2 = tts.synthesize("再来四个", "fake-female", None, 1.0, Path(d) / "b.wav")
        total = tts_base.concat_wavs([r.file, r2.file], Path(d) / "ab.wav")
        assert abs(total - (r.duration + r2.duration)) < 0.01
        try:
            tts.synthesize("x", "nope", None, 1.0, Path(d) / "c.wav")
            raise AssertionError("未知音色应抛 ProviderError")
        except tts_base.ProviderError as e:
            assert e.code == "tts.unknown_voice" and e.params == {"voice": "nope"}, (e.code, e.params)
            assert str(e) == "未知的音色：nope"
        assert not (Path(d) / "c.wav").exists()
        for kw, code in (({"fail_with": "x"}, "tts.fake.failed"),):
            try:
                FakeTts(**kw).synthesize("x", "fake-male", None, 1.0, Path(d) / "c.wav")
                raise AssertionError("应失败")
            except tts_base.ProviderError as e:
                assert e.code == code and e.params == {"detail": {"t": "vendor", "text": "x"}}, e.params
                assert str(e) == "x"
        try:
            FakeTts(fail_times=1).synthesize("x", "fake-male", None, 1.0, Path(d) / "c.wav")
            raise AssertionError("应限流")
        except tts_base.TransientError as e:
            assert e.code == "tts.fake.throttled" and "限流" in str(e)
        try:
            FakeTts(fail_billed="断").synthesize("x", "fake-male", None, 1.0, Path(d) / "c.wav")
        except tts_base.BilledError as e:
            assert e.billed_cny > 0 and str(e) == "断"
        import wave
        with wave.open(str(Path(d) / "odd.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 10)
        try:
            tts_base.concat_wavs([r.file, Path(d) / "odd.wav"], Path(d) / "x.wav")
            raise AssertionError("参数不一致应抛")
        except tts_base.ProviderError as e:
            assert e.code == "tts.concat_mismatch" and str(e) == "拼接的语音片段参数不一致"
        assert FakeTts.rate_note == {"code": "rate.fake_tts", "params": {}}
    print("2. 假 TTS 出 WAV、时长按字数、拼接 ✓")

    os.environ["STORYBOARD_TTS_PROVIDER"] = "fake"
    assert providers.default_tts_name() == "fake" and "fake" in providers.tts_names()
    assert providers.get_tts() is providers.get_tts("fake")
    try:
        providers.get_tts("nope")
        raise AssertionError("未注册的厂商应抛 KeyError")
    except KeyError as e:
        assert e.code == "tts.vendor.misconfigured" and e.params == {}, (e.code, e.params)
        assert "nope" not in e.as_msg()["message"]
    os.environ.pop("STORYBOARD_TTS_PROVIDER")
    assert "fake" not in providers.tts_names(), "假 TTS 不是默认时不出现在可选里"
    print("3. 注册表 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
