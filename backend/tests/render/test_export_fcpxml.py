#!/usr/bin/env python3
"""FCPXML 生成与说明的纯函数测试，内置结构校验（不放 DTD，见实施裁定 1）。

用法: python3 tests/render/test_export_fcpxml.py
"""
import random
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from render.export_fcpxml import build_fcpxml, readme  # noqa: E402

TIME_RE = re.compile(r"^(0s|\d+/30s)$")


def frames(t: str) -> int:
    return 0 if t == "0s" else int(t.split("/")[0])


def check_structure(xml: str, size=None) -> list[str]:
    errs: list[str] = []
    try:
        root = ET.fromstring(xml.split("<!DOCTYPE fcpxml>", 1)[-1])
    except ET.ParseError as e:
        return [f"XML 解析失败: {e}"]
    if root.tag != "fcpxml" or root.get("version") != "1.10":
        errs.append("根元素或版本不对")
    if [c.tag for c in root] != ["resources", "library"]:
        errs.append("子元素应依次是 resources、library")
        return errs
    res, lib = root[0], root[1]
    fmts = res.findall("format")
    if len(fmts) != 1:
        errs.append("format 应恰好一个")
        return errs
    fmt = fmts[0]
    if fmt.get("frameDuration") != "1/30s":
        errs.append("frameDuration 不是 1/30s")
    if size is not None and (fmt.get("width"), fmt.get("height")) != (str(size[0]), str(size[1])):
        errs.append("width/height 与 size 不一致")
    fmt_ids = {fmt.get("id")}
    asset_ids = set()
    for a in res.findall("asset"):
        for k in ("id", "name", "start", "duration", "hasVideo", "hasAudio"):
            if a.get(k) is None:
                errs.append(f"asset 缺 {k}")
        asset_ids.add(a.get("id"))
        if a.get("hasVideo") == "1" and a.get("format") not in fmt_ids:
            errs.append("asset 的 format 引用不存在")
        mr = a.find("media-rep")
        if mr is None or mr.get("kind") != "original-media":
            errs.append("asset 缺 media-rep original-media")
        else:
            src = mr.get("src") or ""
            if not src or src.startswith("/") or src.startswith("file:"):
                errs.append(f"src 不是相对路径: {src}")
    for el in root.iter():
        for k in ("offset", "start", "duration", "tcStart"):
            v = el.get(k)
            if v is not None and not TIME_RE.match(v):
                errs.append(f"时间格式不对 {el.tag}.{k}={v}")
    events = lib.findall("event")
    if len(events) != 1:
        errs.append("library 下应恰好一个 event")
        return errs
    for proj in events[0].findall("project"):
        if not proj.get("name") or len(proj.findall("sequence")) != 1:
            errs.append("project 缺名字或 sequence 不是恰好一个")
        seq = proj.find("sequence")
        if seq is None or seq.get("format") not in fmt_ids:
            errs.append("sequence 缺失或 format 引用不存在")
            continue
        spine = seq.find("spine")
        if spine is None:
            errs.append("缺 spine")
            continue
        pos = 0
        for i, c in enumerate(spine.findall("asset-clip")):
            if c.get("offset") is None or c.get("duration") is None:
                errs.append("主线片段缺 offset 或 duration")
                continue
            if c.get("ref") not in asset_ids:
                errs.append("主线 ref 不存在")
            if i == 0 and c.get("offset") != "0s":
                errs.append("第一段 offset 不是 0s")
            if frames(c.get("offset")) != pos:
                errs.append(f"offset 不连续: {c.get('offset')} != {pos}")
            pos = frames(c.get("offset")) + frames(c.get("duration"))
            for k in c.findall("asset-clip"):
                if k.get("lane") is None:
                    errs.append("连接片段缺 lane")
                if k.get("ref") not in asset_ids:
                    errs.append("连接片段 ref 不存在")
        if frames(seq.get("duration")) != pos:
            errs.append(f"sequence duration {seq.get('duration')} != 总帧数 {pos}")
    return errs


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
    "v2.wav": {"rel": "media/voice/v2.wav", "seconds": 2.1, "audio": True, "video": False},
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

    bad = xml.replace('offset="186/30s"', 'offset="187/30s"', 1)
    assert bad != xml and check_structure(bad)
    bad = xml.replace('src="media/a.mp4"', 'src="/abs/x.mp4"', 1)
    assert bad != xml and check_structure(bad)

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
              for p in [f"s{k}.mp4" for k in range(8)] + [f"v{j}.wav" for j in range(4)] + ["b.mp3"]}
        x = build_fcpxml(tl, md)
        assert check_structure(x, tl["size"]) == [], (n, check_structure(x, tl["size"]))
        r0 = ET.fromstring(x.split("<!DOCTYPE fcpxml>", 1)[1])
        for sq in r0.iter("sequence"):
            assert frames(sq.get("duration")) == sum(frames(c.get("duration")) for c in sq.findall("spine/asset-clip"))

    r = readme(TL, "测试")
    assert "Final Cut" in r and "DaVinci" in r and "srt" in r and "LUFS" in r
    assert re.search(r"[一-鿿]", r) and "relink" in r
    assert "E01/E01-C01" not in r
    tl2 = {**TL, "episodes": [{**TL["episodes"][0], "segments": [{**seg("K03", 0, 1, "a.mp4"), "placeholder": True}]}]}
    assert "E01/K03" in readme(tl2, "t")
    print("ALL PASS")


if __name__ == "__main__":
    main()
