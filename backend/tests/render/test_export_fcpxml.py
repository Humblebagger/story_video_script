#!/usr/bin/env python3
"""FCPXML 生成与说明的纯函数测试，内置结构校验（不放 DTD，见实施裁定 1）。

用法: python3 tests/render/test_export_fcpxml.py
"""
import json
import random
import re
import xml.etree.ElementTree as ET
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from render.export_fcpxml import ExportError, build_fcpxml, export, extra_media, readme  # noqa: E402
from fcpxml_check import check_structure, frames  # noqa: E402


def seg(clip, start, dur, file):
    return {"clip": clip, "start": start, "duration": dur, "base": file, "file": file, "placeholder": False}


TL = {
    "version": 1, "fps": 30, "size": [720, 1280], "draft": False, "bgm_db": -14,
    "episodes": [
        {"episode": "E01", "total": 14.5,
         "segments": [seg("E01-C01", 0.0, 6.2, "a.mp4"), seg("E01-C02", 6.2, 3.8, "b.mp4"),
                      seg("E01-C03", 10.0, 4.5, "c.mp4")],
         "speech": [{"line": "S1-L1", "file": "v1.wav", "start": 0.4, "speed": 1.0, "duration": 3.0},
                    {"line": "S2-L1", "file": "v2.wav", "start": 6.5, "speed": 1.1, "duration": 2.1}],
         "bgm": "bgm/E01.mp3"},
        {"episode": "E02", "total": 5.0, "segments": [seg("E02-C01", 0.0, 5.0, "d.mp4")], "speech": [], "bgm": None},
    ],
}
MEDIA = {
    "a.mp4": {"rel": "media/a.mp4", "seconds": 6.2, "audio": True, "video": True},
    "b.mp4": {"rel": "media/b.mp4", "seconds": 3.8, "audio": True, "video": True},
    "c.mp4": {"rel": "media/c.mp4", "seconds": 4.5, "audio": False, "video": True},
    "d.mp4": {"rel": "media/d.mp4", "seconds": 5.0, "audio": True, "video": True},
    "v1.wav": {"rel": "media/voice/v1.wav", "seconds": 3.0, "audio": True, "video": False},
    "v2.wav@1.1": {"rel": "media/voice/v2.wav", "seconds": 2.1, "audio": True, "video": False},
    "bgm/E01.mp3": {"rel": "media/bgm/E01.mp3", "seconds": 30.0, "audio": True, "video": False},
}


def main() -> None:
    xml = build_fcpxml(TL, MEDIA)
    assert check_structure(xml, TL["size"]) == [], check_structure(xml, TL["size"])
    assert check_structure(xml, [1, 2])
    root = ET.fromstring(xml.split("<!DOCTYPE fcpxml>", 1)[1])
    f = root.find("resources/format")
    projs = root.findall("library/event/project")
    assert [p.get("name") for p in projs] == ["E01", "E02"]
    seg2 = projs[0].findall("sequence/spine/asset-clip")[1]
    voice = [k for k in seg2.findall("asset-clip")]
    assert len(voice) == 1
    assert (voice[0].get("offset"), voice[0].get("lane"), voice[0].get("duration")) == ("9/30s", "-1", "63/30s")
    seg1 = projs[0].findall("sequence/spine/asset-clip")[0]
    bgm = [k for k in seg1.findall("asset-clip") if k.get("lane") == "-2"]
    assert len(bgm) == 1 and bgm[0].get("offset") == "0s" and bgm[0].get("duration") == "435/30s"
    assert bgm[0].find("adjust-volume").get("amount") == "-14dB"
    assert projs[1].findall(".//asset-clip/asset-clip") == []
    # BGM 比本集长：只有一段；素材时长是实测值
    a_bgm = next(a for a in root.findall("resources/asset") if a.find("media-rep").get("src") == "media/bgm/E01.mp3")
    assert a_bgm.get("duration") == "900/30s"

    # BGM 比本集短：首尾相接地循环，总长等于本集总长，最后一段裁短，素材时长仍是实测值
    md2 = {**MEDIA, "bgm/E01.mp3": {**MEDIA["bgm/E01.mp3"], "seconds": 4.0}}
    x2 = build_fcpxml(TL, md2)
    assert check_structure(x2, TL["size"]) == [], check_structure(x2, TL["size"])
    r2 = ET.fromstring(x2.split("<!DOCTYPE fcpxml>", 1)[1])
    bg2 = [k for k in r2.findall("library/event/project")[0].find("sequence/spine/asset-clip")
           if k.tag == "asset-clip" and k.get("lane") == "-2"]
    assert [(k.get("offset"), k.get("duration")) for k in bg2] == [
        ("0s", "120/30s"), ("120/30s", "120/30s"), ("240/30s", "120/30s"), ("360/30s", "75/30s")], bg2
    assert all(k.find("adjust-volume").get("amount") == "-14dB" for k in bg2)
    a2 = next(a for a in r2.findall("resources/asset") if a.find("media-rep").get("src") == "media/bgm/E01.mp3")
    assert a2.get("duration") == "120/30s"
    assert len({k.get("ref") for k in bg2}) == 1

    bad = xml.replace('offset="186/30s"', 'offset="187/30s"', 1)
    assert bad != xml and check_structure(bad)
    bad = xml.replace('src="media/a.mp4"', 'src="/abs/x.mp4"', 1)
    assert bad != xml and check_structure(bad)

    # 素材时长不得短于时间轴用到的帧数（实测短一帧的文件不能让片段超出素材）
    short = {k: dict(v) for k, v in MEDIA.items()}
    short["a.mp4"]["seconds"] = 6.2 - 1 / 30
    ra = ET.fromstring(build_fcpxml(TL, short).split("<!DOCTYPE fcpxml>", 1)[1])
    assert ra.find("resources/asset[@name='a']").get("duration") == "186/30s"
    # media-rep src 是 URL：带空格的名字要百分号编码，校验时解码
    sp = {k: dict(v) for k, v in MEDIA.items()}
    sp["a.mp4"]["rel"] = "media/clips/E01 a.mp4"
    xs = build_fcpxml(TL, sp)
    assert 'src="media/clips/E01%20a.mp4"' in xs and check_structure(xs, TL["size"]) == []

    # 随机时间轴：起点与时长都不对齐到帧，主线仍须首尾相接、总长等于各段之和
    rnd = random.Random(7)
    for n in range(200):
        eps = []
        for e in range(rnd.randint(1, 3)):
            t, segs, files = 0.0, [], {}
            for k in range(rnd.randint(1, 7)):
                d = round(rnd.uniform(0.7, 8), 3)
                segs.append(seg(f"C{k}", round(t, 3), d, f"s{k}.mp4"))
                t += d
            speech = [{"line": f"L{j}", "file": f"v{j}.wav", "start": round(rnd.uniform(0, t), 3), "speed": 1.0,
                       "duration": round(rnd.uniform(0.01, 4), 3)} for j in range(rnd.randint(0, 4))]
            eps.append({"episode": f"E{e}", "total": round(t, 3), "segments": segs, "speech": speech,
                        "bgm": "b.mp3" if rnd.random() < 0.5 else None})
        tl = {**TL, "episodes": eps}
        md = {p: {"rel": f"media/{p}", "seconds": 9.0, "audio": True, "video": p.endswith(".mp4")}
              for p in [f"s{k}.mp4" for k in range(8)] + [f"v{j}.wav" for j in range(4)]}
        md["b.mp3"] = {"rel": "media/b.mp3", "seconds": round(rnd.uniform(0.5, 20), 3), "audio": True, "video": False}
        x = build_fcpxml(tl, md)
        assert check_structure(x, tl["size"]) == [], (n, check_structure(x, tl["size"]))
        r0 = ET.fromstring(x.split("<!DOCTYPE fcpxml>", 1)[1])
        for sq in r0.iter("sequence"):
            assert frames(sq.get("duration")) == sum(frames(c.get("duration")) for c in sq.findall("spine/asset-clip"))
            bg = [k for k in sq.iter("asset-clip") if k.get("lane") == "-2"]
            if bg:
                assert sum(frames(k.get("duration")) for k in bg) == frames(sq.get("duration")), n

    r = readme(TL, "测试")
    assert "Final Cut" in r and "DaVinci" in r and "srt" in r and "LUFS" in r
    assert re.search(r"[一-鿿]", r) and "relink" in r
    assert "E01/E01-C01" not in r
    tl2 = {**TL, "episodes": [{**TL["episodes"][0], "segments": [{**seg("K03", 0, 1, "a.mp4"), "placeholder": True}]}]}
    assert "E01/K03" in readme(tl2, "t")
    # 补拍素材：只附带没挂靠、有采用结果且文件还在的自由节点；说明里列出来，不写进时间线
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "clips").mkdir()
        (root / "clips" / "F01.t1.mp4").write_bytes(b"x")
        (root / "clips" / "F02.t2.mp4").write_bytes(b"x")
        s = {"free": [
            {"id": "F01", "target": None, "chosen": 0, "prompt": "空镜：河面\n第二行",
             "attempts": [{"state": "succeeded", "file": "clips/F01.t1.mp4"}]},
            {"id": "F02", "target": "E01-C01", "chosen": 0, "prompt": "挂靠的",
             "attempts": [{"state": "succeeded", "file": "clips/F02.t2.mp4"}]},
            {"id": "F03", "target": None, "chosen": None, "prompt": "没出", "attempts": []},
            {"id": "F04", "target": None, "chosen": 0, "prompt": "文件没了",
             "attempts": [{"state": "succeeded", "file": "clips/gone.mp4"}]},
        ]}
        (root / "session.json").write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
        ex = extra_media(root)
        assert [(rel, disk.name, line) for rel, disk, line in ex] == [("media/extra/F01.mp4", "F01.t1.mp4", "空镜：河面")]
        assert extra_media(root / "nope") == []
    r = readme(TL, "t", [("media/extra/F01.mp4", "空镜：河面")])
    assert "media/extra/F01.mp4" in r and "补拍素材" in r and "Extra footage" in r
    assert "补拍素材" not in readme(TL, "t")
    # 会话文件被改坏：chosen 非整数/布尔、缺 id、尝试不是字典、file 不是字符串，都跳过而不是抛错
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "clips").mkdir()
        (root / "clips" / "G01.mp4").write_bytes(b"x")
        good = {"id": "G01", "target": None, "chosen": 0, "prompt": "好的",
                "attempts": [{"state": "succeeded", "file": "clips/G01.mp4"}]}
        bad = [
            {**good, "id": "B1", "chosen": "0"},
            {**good, "id": "B2", "chosen": True},
            {**good, "id": "B3", "chosen": 0.5},
            {k: v for k, v in good.items() if k != "id"},
            {**good, "id": "B5", "attempts": ["oops"]},
            {**good, "id": "B6", "attempts": [{"state": "succeeded", "file": 123}]},
            {**good, "id": "B7", "attempts": None},
            "not-a-dict",
        ]
        (root / "session.json").write_text(json.dumps({"free": bad + [good]}, ensure_ascii=False), encoding="utf-8")
        assert [(rel, disk.name) for rel, disk, _ in extra_media(root)] == [("media/extra/G01.mp4", "G01.mp4")]

    # README 按语言：不带 lang 与并排一致；zh/en 各只有一段，附加行单语也在
    both = readme(TL, "测试")
    zh_only, en_only = readme(TL, "测试", lang="zh"), readme(TL, "测试", lang="en")
    assert "----" not in zh_only and "----" not in en_only
    assert "剪辑工程说明" in zh_only and "relink" not in zh_only
    assert "relink" in en_only and not re.search(r"[一-鿿]", en_only.replace("测试", ""))
    assert both == zh_only.rstrip("\n") + "\n\n----\n\n" + en_only
    assert readme(TL, "测试", lang="fr") == both
    tlp = {**TL, "episodes": [{**TL["episodes"][0], "segments": [{**seg("K03", 0, 1, "a.mp4"), "placeholder": True}]}]}
    assert "E01/K03" in readme(tlp, "t", lang="zh") and "E01/K03" in readme(tlp, "t", lang="en")
    ex1 = [("media/extra/F01.mp4", "x")]
    assert "补拍素材" in readme(TL, "t", ex1, lang="zh") and "Extra footage" not in readme(TL, "t", ex1, lang="zh")
    assert "Extra footage" in readme(TL, "t", ex1, lang="en") and "补拍素材" not in readme(TL, "t", ex1, lang="en")
    # 导出：文件名带语言，互不覆盖；报错带代码
    import zipfile
    from render import mix as _mix
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "final").mkdir()
        e = None
        try:
            export(root, title="T", tools=("ffmpeg", "ffprobe"))
        except ExportError as ex_:
            e = ex_
        assert e is not None and e.as_msg()["code"] == "export.no_timeline", e
        (root / "clips").mkdir()
        (root / "clips" / "a.mp4").write_bytes(b"x")
        tl = {**TL, "episodes": [{**TL["episodes"][0], "segments": [seg("K01", 0, 1, "clips/a.mp4")], "speech": [], "bgm": None}]}
        (root / "final" / "timeline.json").write_text(json.dumps(tl), encoding="utf-8")
        old = _mix.media_seconds
        _mix.media_seconds = lambda disk, probe: 1.0
        try:
            outs = {l: export(root, title="T", tools=("ffmpeg", "ffprobe"), lang=l) for l in ("en", "zh", None, "fr")}
            assert [o.name for o in outs.values()] == ["T.en.zip", "T.zh.zip", "T.zip", "T.zip"]
            assert all(o.exists() for o in outs.values())
            rd = lambda o: zipfile.ZipFile(o).read("T/README.txt").decode()
            assert "relink" in rd(outs["en"]) and "----" not in rd(outs["en"]) and "relink" not in rd(outs["zh"])
            assert "----" in rd(outs[None])
            # 产物缺失
            (root / "clips" / "a.mp4").unlink()
            try:
                export(root, title="T", tools=("ffmpeg", "ffprobe"))
                raise AssertionError("应抛 ExportError")
            except ExportError as ex_:
                m = ex_.as_msg()
                assert m["code"] == "export.missing_file" and m["params"] == {"file": "media/clips/K01.mp4"}, m
            (root / "clips" / "a.mp4").write_bytes(b"x")
            # 预渲染配音失败：stderr 不变
            (root / "v.wav").write_bytes(b"x")
            sp = {"line": "L1", "file": "v.wav", "speed": 1.2, "start": 0, "duration": 1}
            tl["episodes"][0]["speech"] = [sp]
            (root / "final" / "timeline.json").write_text(json.dumps(tl), encoding="utf-8")
            try:
                export(root, title="T", tools=("/nonexistent-ffmpeg", "ffprobe"))
                raise AssertionError("应抛 ExportError")
            except ExportError as ex_:
                m = ex_.as_msg()
                assert m["code"] == "export.voice_prerender" and m["params"] == {"line": "L1"}, m
                assert ex_.stderr and "预渲染配音 L1 失败" == str(ex_)
        finally:
            _mix.media_seconds = old
    print("ALL PASS")


if __name__ == "__main__":
    main()
