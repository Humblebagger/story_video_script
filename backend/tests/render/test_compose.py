#!/usr/bin/env python3
"""出片：提示词组装（生产包快照不变、四种声音模式、占位符改写、可播时长），切段、参考图、首帧、指纹、请求组装。

用法: python3 tests/render/test_compose.py
"""
import copy
import re
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from adapters import seedance as seedance_pack  # noqa: E402
from pipeline.quality import speech_seconds  # noqa: E402
from render import compose  # noqa: E402
from render.plan import assets_index, build_plan  # noqa: E402
from render.providers.seedance import rewrite_refs  # noqa: E402
from render.providers import base  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao" / "output_merged.json"
GOLDEN = Path(__file__).resolve().parent / "golden_plan_yao.json"


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def part_prompt(doc):
    idx = assets_index(doc)
    shots = [s for ep in doc["episodes"] for s in ep["shots"]]

    # 1. 生产包改走 compose 之后逐字不变
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert build_plan(doc) == golden["plan"], "渲染任务清单与改造前不一致"
    packs = [seedance_pack.render_episode(doc, ep, 15.0) for ep in doc["episodes"]]
    assert packs == golden["packs"], "Markdown 生产包与改造前不一致"
    print("1. 生产包快照不变 ✓")

    # 2. 占位符：厂商无关层写 {ref:ID}，Seedance 按出现顺序改写为 @图片n
    clip = [s for s in shots if s.get("characters") and s.get("location_ref")][:2]
    text, ids = compose.neutral_prompt(clip, doc, idx)
    assert "{ref:" in text and "@图片" not in text
    assert ids == [sl["asset_id"] for sl in compose.ref_slots(clip, idx)]
    out = rewrite_refs(text)
    assert "{ref:" not in out and "@图片1" in out and f"@图片{len(ids)}" in out
    assert rewrite_refs("{ref:C01}{ref:S03}{ref:S03}") == "@图片1@图片2@图片3", "同一资产两次各占一张图"
    print("2. 占位符与改写 ✓")

    # 3. 四种声音模式
    talky = next(s for s in shots if s.get("dialogue"))
    line = talky["dialogue"][0]["text"]
    t, _ = compose.neutral_prompt([talky], doc, idx, mode="tts_all", slots=[])
    assert line not in t and "人物交谈但不发声" in t and "无人声" in t, "tts_all：台词不进提示词"
    t, _ = compose.neutral_prompt([talky], doc, idx, mode="dialogue_native", slots=[])
    assert line in t and "台词逐字念出" in t
    told = next(s for s in shots if (s.get("narration") or {}).get("text"))
    narr = told["narration"]["text"]
    t, _ = compose.neutral_prompt([told], doc, idx, mode="dialogue_native", slots=[])
    assert narr not in t, "dialogue_native：旁白不进提示词"
    t, _ = compose.neutral_prompt([told], doc, idx, mode="all_native", slots=[])
    assert narr in t and "旁白与台词逐字念出" in t
    t, _ = compose.neutral_prompt([talky], doc, idx, mode="silent", slots=[])
    assert "【声音】无声" in t and line not in t
    print("3. 四种声音模式 ✓")

    # 4. 出片按可播时长写时间轴；没有图的资产写文字描述；首帧占第一个参考位
    long = next(s for s in shots if speech_seconds(s) > s.get("duration_sec", 3) + 0.5)
    t, _ = compose.neutral_prompt([long], doc, idx, mode="tts_all", slots=[], timing="playable")
    assert f"，{round(compose.playable(long), 1)}秒，" in t.splitlines()[0]
    t, ids = compose.neutral_prompt([long], doc, idx, mode="tts_all", slots=[],
                                    described=["人物：某人（白发）"], first_frame=True)
    assert "【描述】人物：某人（白发）" in t and ids == [compose.FIRST]
    assert "【首帧】{ref:" + compose.FIRST + "}" in t
    print("4. 可播时长、文字描述、首帧位 ✓")

    # 4b. 带 beats 的镜头：声音模式与可播时长同样生效（shot_line 逐拍展开，不读 action/dialogue）
    bshot = dict(talky, beats=[{"action": "第一拍", "duration_sec": 1},
                               {"action": "第二拍", "duration_sec": 1}])
    t, _ = compose.neutral_prompt([bshot], doc, idx, mode="tts_all", slots=[])
    assert "人物交谈但不发声" in t and line not in t, "beats + tts_all：应有不发声且台词不进提示词"
    t, _ = compose.neutral_prompt([bshot], doc, idx, mode="dialogue_native", slots=[])
    assert line in t and "人物交谈但不发声" not in t, "beats + dialogue_native：台词应进提示词"
    t, _ = compose.neutral_prompt([bshot], doc, idx, mode="tts_all", slots=[], timing="playable")
    end = float(round(compose.playable(bshot), 1))  # shot_line 输出 4.0 而非 4
    assert f"-{end}秒" in t, "beats + playable：末拍应止于可播时长"
    t, _ = compose.neutral_prompt([dict(talky, action="")], doc, idx, mode="tts_all", slots=[])
    assert "，，" not in t, "空 action 不应产生前导逗号"
    print("4b. 带 beats 的镜头 ✓")


def part_clips(doc):
    fake = FakeVideo()
    caps = fake.caps("fake-1")
    idx = assets_index(doc)

    # 5. 切段：按可播时长装箱，顺序不变；单镜超上限独立成段并标截断
    clips = compose.cut_clips(doc, caps)
    for ep in doc["episodes"]:
        mine = [c for c in clips if c["episode"] == ep["id"]]
        assert [s["id"] for c in mine for s in c["shots"]] == [s["id"] for s in ep["shots"]]
        assert [c["id"] for c in mine] == [f"{ep['id']}-C{i:02d}" for i in range(1, len(mine) + 1)]
    for c in clips:
        if c["truncated"]:
            assert len(c["shots"]) == 1 and compose.playable(c["shots"][0]) > caps.max_clip_sec
        else:
            assert c["duration"] <= caps.max_clip_sec + 1e-6
    assert any(c["truncated"] for c in clips), "《药》里有超过 10 秒的镜头"
    print("5. 切段 ✓")

    # 6. 参考图：主要角色 > 场景 > 次要角色与生物 > 道具；没有图只写文字
    rich = copy.deepcopy(doc)
    for kind in ("characters", "props"):
        for card in rich["assets"][kind]:
            card["reference_images"] = [{"view": "front", "uri": f"https://img/{card['id']}.png"}]
    for card in rich["assets"]["locations"]:
        for a in card.get("angles") or []:
            a["uri"] = f"https://img/{card['id']}-{a['angle']}.png"
    ridx = assets_index(rich)
    c1, c2 = rich["assets"]["characters"][0]["id"], rich["assets"]["characters"][1]["id"]
    loc = next(card for card in rich["assets"]["locations"] if card.get("angles"))
    prop = rich["assets"]["props"][0]["id"]
    clip = [
        {"id": "T1", "duration_sec": 3, "action": "甲", "characters": [{"ref": c1}],
         "location_ref": loc["id"], "location_angle": loc["angles"][0]["angle"],
         "prop_refs": [{"ref": prop}]},
        {"id": "T2", "duration_sec": 3, "action": "乙",
         "characters": [{"ref": c1}, {"ref": c2}]},
    ]
    got = compose.pick_refs(clip, ridx, 2)
    assert [s["asset_id"] for s in got["kept"]] == [c1, loc["id"]], "主要角色与场景优先"
    assert {s["asset_id"] for s in got["dropped"]} == {c2, prop} and got["missing"] == []
    assert got["kept"][1]["source"] == f"https://img/{loc['id']}-{loc['angles'][0]['angle']}.png"
    assert len(compose.pick_refs(clip, ridx, 10)["kept"]) == 4
    for card in rich["assets"]["props"]:
        card["reference_images"] = [{"view": "front", "uri": "local/none.png"}]   # 非 http/data 不算有图
    got = compose.pick_refs(clip, assets_index(rich), 10)
    assert [s["asset_id"] for s in got["missing"]] == [prop]
    assert compose.describe(got["missing"][0], assets_index(rich)).startswith("道具：")
    print("6. 参考图优先级与文字描述 ✓")

    # 7. 首帧：关键帧优先；没有参考图时用上一段尾帧接力；有参考图时关键帧占参考位
    with tempfile.TemporaryDirectory() as d:
        kf_shot = clips[1]["shots"][0]["id"]
        png = Path(d) / f"{kf_shot}.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)
        kw = dict(provider="fake", model="fake-1", resolution="720p", audio_mode="tts_all",
                  rewrite=fake.rewrite_prompt)
        built = compose.build_clips(doc, caps, keyframes={kf_shot: png}, **kw)
        assert built[1]["first_frame"] == f"keyframe:{kf_shot}" and built[1]["frame_mode"] == "frame"
        relay = [b for b in built if (b["first_frame"] or "").startswith("relay:")]
        assert relay and all(b["frame_mode"] == "frame" for b in relay)
        assert all(not b["first_frame"] for b in built
                   if b["id"].endswith("-C01") and b["shots"][0] != kf_shot), "每集第一段不接力"
        assert "{ref:" not in built[0]["prompt"], "已按厂商语法改写"

        # 有参考图：关键帧作为第一个参考位
        rich2 = copy.deepcopy(rich)
        for card in rich2["assets"]["characters"]:
            card["reference_images"] = [{"view": "front", "uri": f"https://img/{card['id']}.png"}]
        rc = next(c for c in compose.cut_clips(rich2, caps) if c["shots"][0].get("characters"))
        rk = rc["shots"][0]["id"]
        rpng = Path(d) / f"rich-{rk}.png"
        rpng.write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 16)
        rkw = {rk: rpng}
        rb = compose.build_clips(rich2, caps, keyframes=rkw, **kw)
        target = next(b for b in rb if b["id"] == rc["id"])
        assert target["refs"], "合成用例必须有参考图"
        assert target["frame_mode"] == "ref" and "[参考__first__]" in target["prompt"]
        assert len(target["refs"]) <= caps.max_refs - 1, "首帧占一个名额"
        sess = {"provider": "fake", "model": "fake-1", "resolution": "720p", "audio_mode": "tts_all"}
        row = {k: v for k, v in target.items() if not k.startswith("_")}
        rq, _ = compose.request_for(rich2, sess, row, keyframes=rkw, relay_frame=None,
                                    caps=caps, rewrite=fake.rewrite_prompt)
        assert rq.refs[0].asset_id == compose.FIRST and rq.refs[0].role == "first_frame"
        assert rq.refs[0].source.startswith("data:image/png;base64,") and rq.first_frame is None

        caps2 = FakeVideo(frame_with_refs=True).caps("fake-1")
        rb2 = compose.build_clips(rich2, caps2, keyframes=rkw, **kw)
        t2 = next(b for b in rb2 if b["shots"][0] == rk)
        assert t2["frame_mode"] == "frame"
        row2f = {k: v for k, v in t2.items() if not k.startswith("_")}
        rq2, _ = compose.request_for(rich2, sess, row2f, keyframes=rkw, relay_frame=None,
                                     caps=caps2, rewrite=fake.rewrite_prompt)
        assert rq2.first_frame and all(r.asset_id != compose.FIRST for r in rq2.refs)

        # 关键帧文件内容变了：指纹跟着变，其他段不变
        png2 = Path(d) / "other.png"
        png2.write_bytes(b"\x89PNG\r\n\x1a\n" + b"9" * 16)
        chg = compose.build_clips(doc, caps, keyframes={kf_shot: png2}, **kw)
        assert chg[1]["fingerprint"] != built[1]["fingerprint"]
        assert all(a["fingerprint"] == b["fingerprint"]
                   for i, (a, b) in enumerate(zip(chg, built)) if i != 1)

        # 关键帧文件丢了：不崩，该段不用关键帧
        gone = compose.build_clips(doc, caps, keyframes={kf_shot: Path(d) / "gone.png"}, **kw)
        assert not (gone[1]["first_frame"] or "").startswith("keyframe:")

        # 8. 指纹：设置或分镜变了才变
        again = compose.build_clips(doc, caps, keyframes={kf_shot: png}, **kw)
        assert [b["fingerprint"] for b in again] == [b["fingerprint"] for b in built]
        lo = compose.build_clips(doc, caps, keyframes={kf_shot: png},
                                 **{**kw, "resolution": "480p"})
        assert all(a["fingerprint"] != b["fingerprint"] for a, b in zip(lo, built))
        edited = copy.deepcopy(doc)
        edited["episodes"][0]["shots"][0]["action"] += "（改）"
        eb = compose.build_clips(edited, caps, keyframes={kf_shot: png}, **kw)
        assert eb[0]["fingerprint"] != built[0]["fingerprint"]
        assert eb[1]["fingerprint"] == built[1]["fingerprint"], "只影响所在的段"
        must_raise(ValueError, compose.build_clips, doc, caps, keyframes={},
                   **{**kw, "audio_mode": "karaoke"})
        print("7. 首帧来源 ✓\n8. 指纹 ✓")

        # 9. 请求组装：按已保存分镜重建，指纹对不上抛 Stale
        session = {"provider": "fake", "model": "fake-1", "resolution": "720p",
                   "audio_mode": "tts_all"}
        clip_row = {k: v for k, v in built[1].items() if not k.startswith("_")}
        req, used = compose.request_for(doc, session, clip_row, keyframes={kf_shot: png},
                                        relay_frame=None, caps=caps, rewrite=fake.rewrite_prompt)
        assert isinstance(req, base.ClipRequest) and used == f"keyframe:{kf_shot}"
        assert req.first_frame.startswith("data:image/png;base64,") and req.refs == []
        assert req.prompt == built[1]["prompt"] and req.duration == built[1]["duration"]
        assert req.aspect == doc["meta"]["video"]["aspect_ratio"] and req.audio is True
        r2 = next(b for b in built if (b["first_frame"] or "").startswith("relay:"))
        row2 = {k: v for k, v in r2.items() if not k.startswith("_")}
        req2, used2 = compose.request_for(doc, session, row2, keyframes={kf_shot: png},
                                          relay_frame=None, caps=caps, rewrite=fake.rewrite_prompt)
        assert req2.first_frame is None and used2 is None, "上一段还没尾帧：不带首帧"
        jpg = Path(d) / "prev.last.jpg"
        jpg.write_bytes(b"\xff\xd8x")
        req3, used3 = compose.request_for(doc, session, row2, keyframes={kf_shot: png},
                                          relay_frame=jpg, caps=caps, rewrite=fake.rewrite_prompt)
        assert req3.first_frame.startswith("data:image/jpeg;base64,") and used3 == r2["first_frame"]
        must_raise(compose.Stale, compose.request_for, edited, session,
                   {k: v for k, v in built[0].items() if not k.startswith("_")},
                   keyframes={kf_shot: png}, relay_frame=None, caps=caps,
                   rewrite=fake.rewrite_prompt)
        silent = compose.request_for(doc, {**session, "audio_mode": "silent"},
                                     {**clip_row, "fingerprint": compose.build_clips(
                                         doc, caps, keyframes={kf_shot: png},
                                         **{**kw, "audio_mode": "silent"})[1]["fingerprint"]},
                                     keyframes={kf_shot: png}, relay_frame=None, caps=caps,
                                     rewrite=fake.rewrite_prompt)[0]
        assert silent.audio is False
        print("9. 请求组装 ✓")


def part_style(doc):
    fake = FakeVideo()
    style = {"source": "data:image/png;base64,AAAA", "hash": "h1"}
    style2 = {"source": "data:image/png;base64,BBBB", "hash": "h2"}
    rich = copy.deepcopy(doc)
    for kind in ("characters", "props"):
        for card in rich["assets"][kind]:
            card["reference_images"] = [{"view": "front", "uri": f"https://img/{card['id']}.png"}]
    for card in rich["assets"]["locations"]:
        for a in card.get("angles") or []:
            a["uri"] = f"https://img/{card['id']}-{a['angle']}.png"
    kw = dict(provider="fake", model="fake-1", resolution="720p", audio_mode="tts_all",
              rewrite=fake.rewrite_prompt)
    sess = {"provider": "fake", "model": "fake-1", "resolution": "720p", "audio_mode": "tts_all"}

    def fp(caps, d, st, kf=None):
        return compose.build_clips(d, caps, keyframes=kf or {}, style=st, **kw)

    def strip(cl):
        return [{k: v for k, v in c.items() if k not in ("style", "style_hash")} for c in cl]

    caps = fake.caps("fake-1")
    caps_w = FakeVideo(frame_with_refs=True).caps("fake-1")
    with tempfile.TemporaryDirectory() as d:
        # 1. 不变性
        for dd in (doc, rich):
            base_ = compose.build_clips(dd, caps, keyframes={}, **kw)
            none_ = fp(caps, dd, None)
            assert strip(base_) == strip(none_) and base_ == none_
            a, b, c = fp(caps, dd, None), fp(caps, dd, style), fp(caps, dd, style2)
            assert [x["fingerprint"] for x in a] == [x["fingerprint"] for x in b] \
                == [x["fingerprint"] for x in c]
            # 9. 没有风格图
            assert all(x["style"] is None and x["style_hash"] is None for x in a)
        # 2. 有空位
        big = FakeVideo(max_refs=8).caps("fake-1")
        got = fp(big, rich, style)
        used = [c for c in got if c["style"] == "used"]
        assert used
        some = next(c for c in used if any(r not in (compose.STYLE_ID,) for r in c["refs"]))
        assert some["style_hash"] == "h1" and compose.STYLE_ID in some["refs"]
        assert "画风参考" in some["prompt"]
        # 带场景的段：风格图在主要角色之后、场景之前
        idx = assets_index(rich)
        locs = set(idx["locations"])
        withloc = [c for c in used if any(r in locs for r in c["refs"])]
        assert withloc
        for c in withloc:
            pos = c["refs"].index(compose.STYLE_ID)
            li = min(i for i, r in enumerate(c["refs"]) if r in locs)
            assert pos < li
            assert all(r not in locs and r in idx["characters"] for r in c["refs"][:pos])
        # 3. 满了，但有非主要角色：场景被挪走
        c1, c2 = rich["assets"]["characters"][0]["id"], rich["assets"]["characters"][1]["id"]
        loc = next(card for card in rich["assets"]["locations"] if card.get("angles"))
        shot = {"id": "S1", "duration_sec": 3, "action": "甲", "characters": [{"ref": c1}],
                "location_ref": loc["id"], "location_angle": loc["angles"][0]["angle"]}
        mini = copy.deepcopy(rich)
        mini["episodes"] = [{"id": mini["episodes"][0]["id"], "shots": [shot]}]
        two = FakeVideo(max_refs=2).caps("fake-1")
        got = fp(two, mini, style)[0]
        assert got["style"] == "used" and got["refs"] == [c1, compose.STYLE_ID]
        assert got["dropped_refs"] == [loc["id"]]
        assert "【描述】场景：" in got["prompt"], "被挪走的场景改用文字描述"
        base0 = fp(two, mini, None)[0]
        assert base0["refs"] == [c1, loc["id"]] and got["fingerprint"] == base0["fingerprint"]
        # 4. 满了，全是主要角色
        one = FakeVideo(max_refs=1).caps("fake-1")
        got = fp(one, mini, style)[0]
        assert got["style"] == "full" and got["refs"] == [c1]
        assert compose.STYLE_ID not in got["refs"] and "画风参考" not in got["prompt"]
        assert got["prompt"] == fp(one, mini, None)[0]["prompt"]
        # 5/6. 首帧单用 / 同用
        png = Path(d) / "S1.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)
        no_refs = copy.deepcopy(mini)
        for card in no_refs["assets"]["characters"] + no_refs["assets"]["props"]:
            card["reference_images"] = []
        for card in no_refs["assets"]["locations"]:
            for a in card.get("angles") or []:
                a["uri"] = ""
        g = fp(caps, no_refs, style, {"S1": png})[0]
        assert g["frame_mode"] == "frame" and g["style"] == "first_frame"
        assert compose.STYLE_ID not in g["refs"]
        g = fp(caps_w, mini, style, {"S1": png})[0]
        assert g["frame_mode"] == "frame" and g["style"] == "used"
        # 尾帧接力不受影响：同一份分镜，有无风格图，relay 判定一致
        for dd, cc in ((doc, caps), (rich, caps_w)):
            a, b = fp(cc, dd, None), fp(cc, dd, style)
            assert [x["first_frame"] for x in a] == [x["first_frame"] for x in b]
            assert any((x["first_frame"] or "").startswith("relay:") for x in b)
            assert [x["frame_mode"] for x in a] == [x["frame_mode"] for x in b]
        # 7. 关键帧占参考位：cap 少一，风格图照常参与排序（无条件断言）
        four = FakeVideo(max_refs=4).caps("fake-1")
        s2 = copy.deepcopy(mini)
        sh1 = dict(shot, characters=[{"ref": c1}, {"ref": c2}])
        sh2 = {"id": "S2", "duration_sec": 3, "action": "乙", "characters": [{"ref": c1}]}
        s2["episodes"][0]["shots"] = [sh1, sh2]
        g = fp(four, s2, style, {"S1": png})[0]
        g0 = fp(four, s2, None, {"S1": png})[0]
        assert g["frame_mode"] == "ref" and g["style"] == "used"
        assert g["refs"] == [c1, compose.STYLE_ID, loc["id"]] and g["dropped_refs"] == [c2]
        assert len(g["refs"]) <= four.max_refs - 1
        assert g["fingerprint"] == g0["fingerprint"]
        row7 = {k: v for k, v in g.items() if not k.startswith("_")}
        rq7, _ = compose.request_for(s2, sess, row7, keyframes={"S1": png}, relay_frame=None,
                                     caps=four, rewrite=fake.rewrite_prompt, style=style)
        assert rq7.refs[0].role == "first_frame" and rq7.refs[0].source.startswith("data:image/png")
        assert [r.asset_id for r in rq7.refs] == [compose.FIRST, c1, compose.STYLE_ID, loc["id"]]
        assert any(r.role == "style" and r.source == style["source"] for r in rq7.refs)
        order = re.findall(r"\[参考([^\]]+)\]", rq7.prompt)
        assert order == [r.asset_id for r in rq7.refs], "请求图片顺序与提示词占位符编号一致"
        # 8. 组装请求
        row = {k: v for k, v in fp(two, mini, style)[0].items() if not k.startswith("_")}
        rq, _ = compose.request_for(mini, sess, row, keyframes={}, relay_frame=None, caps=two,
                                    rewrite=fake.rewrite_prompt, style=style)
        st = [r for r in rq.refs if r.role == "style"]
        assert len(st) == 1 and st[0].source == style["source"] and rq.style_ref == "h1"
        assert re.findall(r"\[参考([^\]]+)\]", rq.prompt) == [r.asset_id for r in rq.refs]
        rq2, _ = compose.request_for(mini, sess, row, keyframes={}, relay_frame=None, caps=two,
                                     rewrite=fake.rewrite_prompt, style=style2)
        assert rq2.style_ref == "h2"
        rowf = {k: v for k, v in fp(one, mini, style)[0].items() if not k.startswith("_")}
        rq3, _ = compose.request_for(mini, sess, rowf, keyframes={}, relay_frame=None, caps=one,
                                     rewrite=fake.rewrite_prompt, style=style)
        assert rq3.style_ref is None and all(r.role != "style" for r in rq3.refs)
        rq4, _ = compose.request_for(mini, sess, row, keyframes={}, relay_frame=None, caps=two,
                                     rewrite=fake.rewrite_prompt)
        assert rq4.style_ref is None
    print("10. 风格参考位 ✓")


def main() -> int:
    doc = json.loads(YAO.read_text(encoding="utf-8"))
    part_prompt(doc)
    part_clips(doc)
    part_style(doc)
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
