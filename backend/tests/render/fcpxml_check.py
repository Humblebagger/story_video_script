"""FCPXML 1.10 结构校验（不放 DTD，见实施裁定 1），供两个测试共用。"""
import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote

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
    asset_dur = {}
    for a in res.findall("asset"):
        for k in ("id", "name", "start", "duration", "hasVideo", "hasAudio"):
            if a.get(k) is None:
                errs.append(f"asset 缺 {k}")
        asset_ids.add(a.get("id"))
        if a.get("duration") is not None and TIME_RE.match(a.get("duration")):
            asset_dur[a.get("id")] = frames(a.get("duration"))
        if a.get("hasVideo") == "1" and a.get("format") not in fmt_ids:
            errs.append("asset 的 format 引用不存在")
        mr = a.find("media-rep")
        if mr is None or mr.get("kind") != "original-media":
            errs.append("asset 缺 media-rep original-media")
        else:
            src = unquote(mr.get("src") or "")
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
        bgm_seen, bgm_end = False, 0
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
                elif frames(k.get("duration")) > asset_dur.get(k.get("ref"), 0):
                    errs.append(f"连接片段 {k.get('name')} 比素材还长")
            # BGM 轨（lane -2）：首尾相接、从 0 开始，总长等于本集总长（循环铺满）
            bg = [k for k in c.findall("asset-clip") if k.get("lane") == "-2"]
            if bg:
                p2 = 0
                for k in bg:
                    if frames(k.get("offset")) != p2:
                        errs.append(f"BGM offset 不连续: {k.get('offset')} != {p2}")
                    p2 = frames(k.get("offset")) + frames(k.get("duration"))
                if i != 0:
                    errs.append("BGM 应挂在第一段上")
                bgm_end = p2
                bgm_seen = True
        if bgm_seen and bgm_end != pos:
            errs.append(f"BGM 总长 {bgm_end} != 本集总帧数 {pos}")
        if frames(seq.get("duration")) != pos:
            errs.append(f"sequence duration {seq.get('duration')} != 总帧数 {pos}")
    return errs
