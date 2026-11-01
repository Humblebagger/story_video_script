#!/usr/bin/env python3
"""整章合成端到端：用 ffmpeg 测试源生成假视频与 BGM、假 TTS 出配音，跑完整合成，检查成片时长、音轨、
字幕条数、补位与报告；重跑复用配音缓存与已规整的段；关掉草稿合成时缺段拒绝。预览与指纹不需要 ffmpeg。

没装 ffmpeg 时只跑预览部分并注明跳过。用法: python3 tests/render/test_mix_e2e.py
"""
import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from render import export_fcpxml, mix  # noqa: E402
from fcpxml_check import check_structure  # noqa: E402
from render.providers.fake import FakeTts  # noqa: E402

DOC = {
    "meta": {"narration": {"tts_voice": "male_mature"}, "video": {"aspect_ratio": "9:16"}},
    "assets": {"characters": [{"id": "C1", "name": "老栓", "voice": {"tts_voice": "female_young"}}]},
    "episodes": [{"id": "E01", "shots": [
        {"id": "S1", "duration_sec": 3, "narration": {"text": "秋天的后半夜月亮下去了"}},
        {"id": "S2", "duration_sec": 2, "dialogue": [{"type": "dialogue", "character_ref": "C1", "text": "小栓的爹"}]},
        {"id": "S3", "duration_sec": 2},
    ]}],
}


def session(with_video: bool) -> dict:
    a = [{"task_id": "t1", "state": "succeeded", "file": "clips/E01-C01.t1.mp4", "cost_cny": 1}]
    return {"audio_mode": "tts_all", "resolution": "480p", "voices": {}, "clips": [
        {"id": "E01-C01", "episode": "E01", "shots": ["S1", "S2"], "state": "done",
         "attempts": a if with_video else [], "chosen": 0 if with_video else None, "mute_native": False},
        {"id": "E01-C02", "episode": "E01", "shots": ["S3"], "state": "planned", "attempts": [], "chosen": None,
         "mute_native": False},
    ]}


class SlowTts(FakeTts):
    """配音比镜头略长（约 1.11 倍），合成时会被提速。"""

    def synthesize(self, text, voice, emotion, speed, dest):
        return super().synthesize(text, voice, emotion, speed * 0.9, dest)


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        tts = FakeTts()
        (root / "clips").mkdir()
        (root / "clips" / "E01-C01.t1.mp4").write_bytes(b"x")  # 占位文件；有 ffmpeg 时下面换成真视频
        p = mix.preview(root, DOC, session(True), tts=tts, bgm={}, draft=True)
        assert p["lines"] == 2 and p["tts_chars"] == len("秋天的后半夜月亮下去了") + len("小栓的爹")
        assert p["missing_voices"] == [] and p["no_video"] == ["E01-C02"] and p["voices"]["C1"] == "fake-female"
        fp = p["fingerprint"]
        assert mix.preview(root, DOC, session(True), tts=tts, bgm={}, draft=True)["fingerprint"] == fp
        assert mix.preview(root, DOC, session(False), tts=tts, bgm={}, draft=True)["fingerprint"] != fp, \
            "采用的视频变了，成片过期"
        s = dict(session(True), audio_mode="silent")
        assert mix.preview(root, DOC, s, tts=tts, bgm={}, draft=True)["tts_chars"] == 0
        d169 = copy.deepcopy(DOC)
        d169["meta"]["video"]["aspect_ratio"] = "16:9"
        assert mix.preview(root, d169, session(True), tts=tts, bgm={}, draft=True)["fingerprint"] != fp, "画幅变了"
        kf = root / "kf_S3.png"
        kf.write_bytes(b"png")
        assert mix.preview(root, DOC, session(True), tts=tts, bgm={}, draft=True,
                           keyframes={"S3": kf})["fingerprint"] != fp, "补位关键帧变了"
        gone = session(True)
        gone["clips"][0]["attempts"][0]["file"] = "clips/nope.mp4"
        assert mix.preview(root, DOC, gone, tts=tts, bgm={}, draft=True)["no_video"] == ["E01-C01", "E01-C02"]
        print("1. 预览：配音条数与未缓存字数、缺音色、缺视频的段、成片指纹 ✓")

        tools = mix.tools()
        if tools is None:
            print("\nALL PASS（跳过：没装 ffmpeg，端到端合成没跑；brew install ffmpeg 后再跑）")
            return 0
        ffmpeg, ffprobe = tools
        subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "4",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        str(root / "clips" / "E01-C01.t1.mp4")], check=True)
        (root / "audio" / "bgm").mkdir(parents=True)
        bgm = root / "audio" / "bgm" / "E01.wav"
        subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=44100",
                        "-t", "2", str(bgm)], check=True)
        steps, spent = [], []
        out = mix.compose(root, DOC, session(True), tts=tts, keyframes={}, bgm={"E01": bgm}, draft=True,
                          tools=tools, on_cost=spent.append, progress=steps.append)
        assert out == {"files": ["final/E01.mp4", "final/E01.srt"], "report": "final/mix_report.json"}
        video = root / "final" / "E01.mp4"
        report = json.loads((root / "final" / "mix_report.json").read_text(encoding="utf-8"))
        assert abs(mix.media_seconds(video, ffprobe) - report["episodes"][0]["seconds"]) < 0.5
        assert mix.has_audio(video, ffprobe)
        assert (root / "final" / "E01.srt").read_text(encoding="utf-8").count(" --> ") == 2
        assert report["episodes"][0]["placeholders"] == ["E01-C02"] and report["audio_mode"] == "tts_all"
        assert len(tts.calls) == 2 and sum(spent) > 0 and any("混音" in s for s in steps)
        print(f"2. 整章合成：成片 {mix.media_seconds(video, ffprobe):.2f} 秒、有音轨、字幕 2 条、缺段补位写进报告 ✓")

        tl_path = root / "final" / "timeline.json"
        tl = json.loads(tl_path.read_text(encoding="utf-8"))
        ep_tl = tl["episodes"][0]
        want = mix.plan_episode(DOC["episodes"][0], session(True)["clips"],
                                {x["line"]: {"duration": x["duration"] * x["speed"], "file": x["file"]}
                                 for x in ep_tl["speech"]})
        assert [(x["clip"], x["start"], x["duration"]) for x in ep_tl["segments"]] == \
            [(x["clip"], x["start"], x["duration"]) for x in want["segments"]]
        assert tl["version"] == 1 and tl["fps"] == mix.FPS and tl["draft"] is True
        assert all((root / x["file"]).is_file() for x in ep_tl["segments"])
        assert [x["placeholder"] for x in ep_tl["segments"]] == [False, True]
        assert len(ep_tl["speech"]) == 2 and all((root / x["file"]).is_file() for x in ep_tl["speech"])
        assert ep_tl["bgm"] == "audio/bgm/E01.wav" and (root / ep_tl["bgm"]).is_file()
        print("2b. 时间轴 timeline.json：段、配音、BGM 与计划一致，文件都在 ✓")

        title = "药-第一章-v1"
        z1 = export_fcpxml.export(root, title=title, tools=tools)
        assert z1 == root / "final" / "export" / "药-第一章-v1.zip"
        with zipfile.ZipFile(z1) as z:
            names = set(z.namelist())
            xml = z.read(f"{title}/project.fcpxml").decode("utf-8")
        assert {f"{title}/project.fcpxml", f"{title}/README.txt", f"{title}/subtitles/E01.srt"} <= names
        assert check_structure(xml, tl["size"]) == [], check_structure(xml, tl["size"])
        srcs = re.findall(r'<media-rep [^>]*src="([^"]+)"', xml)
        assert srcs and all(f"{title}/{unquote(x)}" in names for x in srcs)
        assert f"{title}/media/bgm/E01.wav" in names and f"{title}/media/clips/E01-C01.mp4" in names
        print(f"2c. 导出：zip 含 fcpxml、说明、字幕与 {len(srcs)} 个素材，结构校验通过 ✓")

        slow_root = root / "slow"
        (slow_root / "clips").mkdir(parents=True)
        shutil.copy(root / "clips" / "E01-C01.t1.mp4", slow_root / "clips" / "E01-C01.t1.mp4")
        doc2 = {"meta": DOC["meta"], "assets": DOC["assets"], "episodes": [{"id": "E01", "shots": [
            {"id": "S1", "duration_sec": 3, "narration": {"text": "秋天的后半夜月亮下去了啊啊"}}]}]}
        s2 = session(True)
        s2["clips"] = s2["clips"][:1]
        s2["clips"][0]["shots"] = ["S1"]
        mix.compose(slow_root, doc2, s2, tts=SlowTts(), keyframes={}, bgm={}, draft=True, tools=tools)
        ep2 = json.loads((slow_root / "final" / "timeline.json").read_text(encoding="utf-8"))["episodes"][0]
        sp = ep2["speech"][0]
        assert sp["speed"] > 1.0, sp
        zs = export_fcpxml.export(slow_root, title="slow", tools=tools)
        with zipfile.ZipFile(zs) as z:
            z.extract(f"slow/media/voice/{sp['line']}.wav", slow_root / "unz")
        got = mix.media_seconds(slow_root / "unz" / "slow" / "media" / "voice" / f"{sp['line']}.wav", ffprobe)
        orig = mix.media_seconds(slow_root / sp["file"], ffprobe)
        assert abs(got - orig / sp["speed"]) <= 0.05, (got, orig, sp["speed"])
        cache = sorted((slow_root / "final" / "export" / "voice").glob("*.wav"))
        assert len(cache) == 1
        stamp = cache[0].stat().st_mtime_ns
        zs_stamp = zs.stat().st_mtime_ns
        zs2 = export_fcpxml.export(slow_root, title="slow", tools=tools)
        assert zs2 == zs and cache[0].stat().st_mtime_ns == stamp, "提速缓存不重做"
        assert zs.stat().st_mtime_ns != zs_stamp and zipfile.is_zipfile(zs), "zip 被覆盖"
        # 两句共用一个源 wav、倍速不同：各自一个文件、各自正确的时长
        tlp = slow_root / "final" / "timeline.json"
        tl_orig = tlp.read_text(encoding="utf-8")
        tl2 = json.loads(tl_orig)
        sp2 = dict(tl2["episodes"][0]["speech"][0], line="S1-L9", speed=1.0, duration=round(orig, 3))
        tl2["episodes"][0]["speech"].append(sp2)
        tlp.write_text(json.dumps(tl2, ensure_ascii=False), encoding="utf-8")
        zd = export_fcpxml.export(slow_root, title="dup", tools=tools)
        with zipfile.ZipFile(zd) as z:
            z.extractall(slow_root / "unz2")
        d2 = slow_root / "unz2" / "dup" / "media" / "voice"
        assert abs(mix.media_seconds(d2 / f"{sp['line']}.wav", ffprobe) - orig / sp["speed"]) <= 0.05
        assert abs(mix.media_seconds(d2 / "S1-L9.wav", ffprobe) - orig) <= 0.05
        tlp.write_text(tl_orig, encoding="utf-8")
        # 标题清洗：不出现绝对路径或 .. 目录
        for bad in ["..", ".", "", "a/../b"]:
            zb = export_fcpxml.export(slow_root, title=bad, tools=tools)
            with zipfile.ZipFile(zb) as z:
                for n in z.namelist():
                    assert not n.startswith("/") and ".." not in n.split("/") and n.split("/")[0], (bad, n)
            assert zb.parent == slow_root / "final" / "export" and not zb.name.startswith("."), zb
        assert (slow_root / "final" / "export" / "storyboard-export.zip").is_file()
        assert not list((slow_root / "final" / "export").glob("*.part"))
        (slow_root / "final" / "timeline.json").unlink()
        try:
            export_fcpxml.export(slow_root, title="slow", tools=tools)
            raise AssertionError("没有时间轴应拒绝")
        except export_fcpxml.ExportError as e:
            assert "重新合成" in str(e)
        print(f"2d. 提速配音预渲染 {sp['speed']:.3f} 倍：{orig:.2f}s -> {got:.2f}s；缓存复用、zip 覆盖、无时间轴提示重新合成 ✓")

        work = sorted((root / "final" / "work").glob("*.mp4"))
        stamps = {w.name: w.stat().st_mtime_ns for w in work if ".joined" not in w.name}
        mix.compose(root, DOC, session(True), tts=tts, keyframes={}, bgm={"E01": bgm}, draft=True, tools=tools)
        assert len(tts.calls) == 2, "配音缓存复用"
        assert {w.name: w.stat().st_mtime_ns for w in sorted((root / "final" / "work").glob("*.mp4"))
                if ".joined" not in w.name} == stamps, "已规整的段复用"
        print("3. 重跑复用配音缓存与已规整的段 ✓")

        tl_before = tl_path.read_bytes()
        try:
            mix.compose(root, DOC, session(True), tts=tts, keyframes={}, bgm={}, draft=False, tools=tools)
            raise AssertionError("关掉草稿合成时缺段应拒绝")
        except mix.MixError as e:
            assert "E01-C02" in str(e)
        assert tl_path.read_bytes() == tl_before and not (root / "final" / ".next").exists(), "失败不动旧时间轴"
        print("4. 关掉草稿合成时缺段拒绝 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
