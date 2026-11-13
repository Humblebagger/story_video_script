#!/usr/bin/env python3
"""合成的纯计算：画幅、原声策略、声画对齐（提速 / 定格）、字幕、ffmpeg 参数；整章合成的复用（ffmpeg 用替身）。
不需要 ffmpeg。

用法: python3 tests/render/test_mix.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from render import mix, voice  # noqa: E402
from server.messages import compact, msg, render_zh  # noqa: E402

EP = {"id": "E01", "shots": [
    {"id": "S1", "duration_sec": 4, "narration": {"text": "一" * 9}},
    {"id": "S2", "duration_sec": 2, "dialogue": [{"type": "dialogue", "character_ref": "C1", "text": "二" * 9}]},
    {"id": "S3", "duration_sec": 2, "narration": {"text": "三" * 9}},
    {"id": "S4", "duration_sec": 3},
]}
CLIPS = [{"id": "E01-C01", "shots": ["S1", "S2"]}, {"id": "E01-C02", "shots": ["S3", "S4"]}]
VOICED = {"S1-L1": {"duration": 2.0, "file": "a.wav"}, "S2-L1": {"duration": 2.2, "file": "b.wav"},
          "S3-L1": {"duration": 3.0, "file": "c.wav"}}


def near(a, b, eps=1e-3):
    return abs(a - b) < eps


def main() -> int:
    assert mix.frame_size("720p", "9:16") == (720, 1280)
    assert mix.frame_size("480p", "9:16") == (480, 854)
    assert mix.frame_size("1080p", "16:9") == (1920, 1080)
    assert mix.frame_size("720p", "1:1") == (720, 720)
    assert mix.frame_size("720p", "bad") == (720, 1280)
    assert mix.frame_size("768P", "9:16", {"768P": 768}) == (768, 1366)
    assert mix.frame_size("2K", "9:16", {"2K": 1440}) == (1440, 2560)
    assert mix.frame_size("480P", "16:9", {"480P": 480}) == (854, 480)
    assert mix.frame_size("720p", "9:16", {}) == (720, 1280), "不传短边表时旧行为不变"
    assert mix.frame_size("768P", "9:16") == (720, 1280), "未知分辨率仍回落 720"
    assert mix.native_audio_policy("tts_all", False) == -12 and mix.native_audio_policy("tts_all", True) is None
    assert mix.native_audio_policy("dialogue_native", True) == 0.0 and mix.native_audio_policy("silent", False) is None
    print("1. 画幅与原声策略 ✓")

    plan = mix.plan_episode(EP, CLIPS, VOICED)
    s1, s2 = plan["segments"]
    assert s1["clip"] == "E01-C01" and s1["start"] == 0 and near(s1["duration"], 6.0) and near(s1["base"], 6.0)
    assert near(s2["start"], 6.0) and near(s2["duration"], 3.0 / 1.15 + 3) and near(s2["base"], 5.0)
    assert near(plan["total"], 6.0 + 3.0 / 1.15 + 3)
    sp = {x["line"]: x for x in plan["speech"]}
    assert near(sp["S1-L1"]["start"], 0) and sp["S1-L1"]["speed"] == 1.0
    assert near(sp["S2-L1"]["start"], 4.0) and near(sp["S2-L1"]["speed"], 1.1)
    assert near(sp["S3-L1"]["start"], 6.0) and near(sp["S3-L1"]["speed"], 1.15)
    kinds = {n["shot"]: n["kind"] for n in plan["notes"]}
    assert kinds == {"S2": "speedup", "S3": "freeze"}
    assert near(next(n for n in plan["notes"] if n["shot"] == "S3")["extend"], 3.0 / 1.15 - 2, 0.01)
    sub2 = next(x for x in plan["subs"] if x["line"] == "S2-L1")
    assert near(sub2["start"], 4.0) and near(sub2["end"], 6.0)
    assert all(abs(x["duration"] - VOICED[x["line"]]["duration"] / x["speed"]) < 5e-4 + 1e-9 for x in plan["speech"]), \
        "speech.duration 为提速后时长"
    tdoc = mix.timeline_doc([{"plan": plan, "files": ["final/work/a.mp4", "final/work/b.mp4"],
                              "placeholders": ["E01-C02"], "bgm": None}], size=(480, 854), draft=True)
    assert tdoc["version"] == 1 and tdoc["fps"] == mix.FPS and tdoc["size"] == [480, 854] and tdoc["draft"] is True
    assert tdoc["bgm_db"] == mix.BGM_DB and tdoc["episodes"][0]["bgm"] is None
    tsegs = tdoc["episodes"][0]["segments"]
    assert [x["file"] for x in tsegs] == ["final/work/a.mp4", "final/work/b.mp4"]
    assert [x["placeholder"] for x in tsegs] == [False, True] and tsegs[1]["start"] == s2["start"]
    print("2. 对齐：念得完不动、超出 15% 内提速、更多就按 1.15 倍念并定格延长 ✓")

    native = mix.plan_episode(EP, CLIPS, {k: v for k, v in VOICED.items() if k != "S1-L1"})
    assert "S1-L1" not in {x["line"] for x in native["speech"]}
    sub1 = next(x for x in native["subs"] if x["line"] == "S1-L1")
    assert near(sub1["end"] - sub1["start"], 2.0), "没合成的语音条按字数估时长，只进字幕"
    print("3. 原声语音条只进字幕 ✓")

    assert mix._ts(3661.5) == "01:01:01,500" and mix._ts(-1) == "00:00:00,000"
    text = mix.srt([{"start": 0, "end": 2, "text": "第一句"}, {"start": 4, "end": 6.25, "text": "第二句"}])
    assert text == "1\n00:00:00,000 --> 00:00:02,000\n第一句\n\n2\n00:00:04,000 --> 00:00:06,250\n第二句\n\n"
    print("4. 字幕 ✓")

    cmd = mix.normalize_cmd("in.mp4", still=None, duration=5.6087, size=(720, 1280), native_db=-12,
                            has_audio=True, out="o.mp4")
    joined = " ".join(cmd)
    assert "tpad=stop_mode=clone:stop_duration=5.609" in joined and "volume=-12dB" in joined
    assert cmd[cmd.index("-t") + 1] == "5.609" and "scale=720:1280:force_original_aspect_ratio=decrease" in joined
    assert "pad=720:1280:(ow-iw)/2:(oh-ih)/2" in joined and cmd[-1] == "o.mp4"
    quiet = " ".join(mix.normalize_cmd("in.mp4", still=None, duration=3, size=(720, 1280), native_db=None,
                                       has_audio=True, out="o.mp4"))
    assert "[1:a]anull[a]" in quiet and "volume" not in quiet, "不要原声时用静音轨"
    still = mix.normalize_cmd(None, still="kf.png", duration=3, size=(720, 1280), native_db=-12,
                              has_audio=False, out="o.mp4")
    assert still[still.index("-i") - 1] == str(mix.FPS) and "-loop" in still and "kf.png" in still
    black = " ".join(mix.normalize_cmd(None, still=None, duration=3, size=(480, 854), native_db=None,
                                       has_audio=False, out="o.mp4"))
    assert "color=c=black:s=480x854" in black
    assert "scale=out_range=tv,format=yuv420p" in " ".join(still), "关键帧图与视频统一色域"
    print("5. 规整参数：缩放补边、尾帧定格、原声音量、关键帧或黑场补位 ✓")

    lst = mix.concat_list(["/a/1.mp4", "/a/2.mp4"])
    assert lst == "file '/a/1.mp4'\nfile '/a/2.mp4'\n"
    assert mix.concat_cmd("l.txt", "o.mp4")[-4:] == ["l.txt", "-c", "copy", "o.mp4"]
    m = mix.mix_cmd("v.mp4", plan, bgm="bgm.mp3", out="out.mp4")
    fc = m[m.index("-filter_complex") + 1]
    assert m.count("-i") == 1 + 3 + 1 and m[m.index("bgm.mp3") - 3:m.index("bgm.mp3")] == ["-stream_loop", "-1", "-i"]
    assert "atempo=1.1000" in fc and "adelay=4000|4000" in fc and "amix=inputs=3" in fc
    assert "sidechaincompress" in fc and f"loudnorm=I={mix.LUFS}" in fc
    assert "[k0]apad[key]" in fc and f"atrim=end={plan['total']:.3f}" in fc
    assert m[m.index("-t") + 1] == f"{plan['total']:.3f}" and m[-1] == "out.mp4"
    bare = mix.mix_cmd("v.mp4", {"speech": [], "total": 3.0}, bgm=None, out="out.mp4")
    assert "[nat]loudnorm" in bare[bare.index("-filter_complex") + 1] and bare.count("-i") == 1
    print("6. 拼接与混音参数：配音按时刻放置并提速、BGM 循环并在有人声时压低、响度标准化 ✓")

    # 7. 整章合成（ffmpeg 换成替身）：无声模式不碰 tts；同一路径重新上传的关键帧会重新规整
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        kf = root / "kf.png"
        kf.write_bytes(b"png-1")
        ran = []

        def fake_run(cmd, what):
            ran.append(render_zh(what["code"], what["params"]).strip())
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(cmd[-1]).write_bytes(b"x")
        real_run, mix.run = mix.run, fake_run
        try:
            doc = {"episodes": [EP]}
            s = {"audio_mode": "silent", "resolution": "720p", "voices": {},
                 "clips": [dict(c, episode="E01", attempts=[], chosen=None) for c in CLIPS]}
            kfs = {"S1": kf}
            assert mix.preview(root, doc, s, tts=None, bgm={}, draft=True, keyframes=kfs)["lines"] == 0
            args = dict(tts=None, keyframes=kfs, bgm={}, draft=True, tools=("ffmpeg", "ffprobe"))
            mix.compose(root, doc, s, **args)
            first = [x for x in ran if x.startswith("规整")]
            assert len(first) == 2, ran
            ran.clear()
            mix.compose(root, doc, s, **args)
            assert not [x for x in ran if x.startswith("规整")], "输入没变，已规整的段复用"
            kf.write_bytes(b"png-2-reuploaded")
            ran.clear()
            mix.compose(root, doc, s, **args)
            assert [x for x in ran if x.startswith("规整")] == ["规整 E01-C01"], ran
        finally:
            mix.run = real_run
    print("7. 无声模式不需要 tts；换关键帧后补位段重新规整 ✓")

    # 8. 合成过程带代码：ffmpeg 失败、缺视频、缺音色、语音条失败、配音异常、进度与报告
    class _R:
        returncode, stderr = 3, "boom" * 2000

    real_sub, mix.subprocess.run = mix.subprocess.run, lambda *a, **k: _R()
    try:
        what = compact(msg("compose.step.normalize", id="E01-C01"))
        try:
            mix.run(["ffmpeg"], what)
            raise AssertionError("应抛 MixError")
        except mix.MixError as e:
            assert e.code == "compose.ffmpeg_failed" and e.params == {"what": what, "rc": 3}, e.params
            assert str(e) == "规整 E01-C01 失败（ffmpeg 退出码 3）" and len(e.stderr) == 4000
    finally:
        mix.subprocess.run = real_sub

    def raises(fn):
        try:
            fn()
        except mix.MixError as e:
            return e
        raise AssertionError("应抛 MixError")

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        doc = {"episodes": [EP]}
        base = {"audio_mode": "silent", "resolution": "720p", "voices": {},
                "clips": [dict(c, episode="E01", attempts=[], chosen=None) for c in CLIPS]}
        e = raises(lambda: mix.compose(root, doc, base, tts=None, keyframes={}, bgm={}, draft=False,
                                       tools=("f", "p")))
        assert e.code == "compose.no_video" and e.params == {"id": "E01-C01"}
        assert "E01-C01 还没有可用的视频" in str(e)

        class _Caps:
            voices = []
        class _Tts:
            caps = _Caps()
        real_resolve = voice.resolve_voices
        voice.resolve_voices = lambda *a, **k: ({}, ["", "C1"])
        try:
            e = raises(lambda: mix.compose(root, doc, dict(base, audio_mode="tts_all"), tts=_Tts(), keyframes={},
                                           bgm={}, draft=True, tools=("f", "p")))
        finally:
            voice.resolve_voices = real_resolve
        assert e.code == "compose.missing_voices"
        assert e.params == {"speakers": [compact(msg("voice.unlabeled")), "C1"]}, e.params
        assert str(e) == "还有说话人没选音色：（未标说话人）、C1"

        real_syn = voice.synthesize
        voice.resolve_voices = lambda *a, **k: ({}, [])
        cause = compact(msg("film.session.dir_gone"))
        fails = [{"id": f"S{i}-L1", "error": "x", "error_msg": cause} for i in range(7)]
        voice.synthesize = lambda *a, **k: ([], fails)
        try:
            args = dict(tts=_Tts(), keyframes={}, bgm={}, draft=True, tools=("f", "p"))
            e = raises(lambda: mix.compose(root, doc, dict(base, audio_mode="tts_all"), **args))
            assert e.code == "compose.lines_failed" and len(e.params["items"]) == 5
            assert e.params["items"][0] == {"code": "compose.line_failed",
                                            "params": {"id": "S0-L1", "cause": cause}}, e.params["items"][0]
            assert str(e).startswith("有语音条合成失败，为免成片漏句已停止合成：S0-L1：出片会话目录已不存在")
            assert "、S1-L1：" in str(e)

            def boom(*a, **k):
                raise voice.VoiceError.of("film.session.dir_gone")
            voice.synthesize = boom
            e = raises(lambda: mix.compose(root, doc, dict(base, audio_mode="tts_all"), **args))
            assert e.code == "compose.voice_failed" and e.params == {"cause": cause}, e.params
            assert str(e) == "出片会话目录已不存在（版本可能已删除）"
        finally:
            voice.synthesize = real_syn
            voice.resolve_voices = real_resolve

        # 进度回调收到消息对象；报告的对齐说明与原声提示是 {code, params}
        steps = []
        voice.resolve_voices, voice.synthesize = (lambda *a, **k: ({}, [])), (lambda *a, **k: ([], []))
        real_run, mix.run = mix.run, lambda cmd, what: (Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True),
                                                        Path(cmd[-1]).write_bytes(b"x"))
        try:
            mix.compose(root, doc, dict(base, audio_mode="dialogue_native"), tts=_Tts(), keyframes={}, bgm={},
                        draft=True, tools=("f", "p"), progress=steps.append)
        finally:
            mix.run = real_run
            voice.resolve_voices, voice.synthesize = real_resolve, real_syn
        assert [(x["code"], x["params"]) for x in steps] == [
            ("compose.step.voice", {"n": 2}),
            ("compose.step.normalize", {"id": "E01-C01"}), ("compose.step.normalize", {"id": "E01-C02"}),
            ("compose.step.concat", {"id": "E01"}), ("compose.step.mix", {"id": "E01"})], steps
        assert steps[1]["message"] == "规整 E01-C01"
        rep = json.loads((root / "final" / "mix_report.json").read_text(encoding="utf-8"))
        assert rep["alignment"] == {"code": "compose.alignment", "params": {}}
        assert rep["warning"] == {"code": "compose.warning_native", "params": {}}
    print("8. 合成过程带代码：ffmpeg 失败、缺视频、缺音色、语音条失败、配音异常、进度与报告 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
