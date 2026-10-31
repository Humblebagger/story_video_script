#!/usr/bin/env python3
"""出片：提示词组装（生产包快照不变、四种声音模式、占位符改写、可播时长），切段、参考图、首帧、指纹、请求组装。

用法: python3 tests/render/test_compose.py
"""
import copy
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
        rb = compose.build_clips(rich2, caps, keyframes={kf_shot: png}, **kw)
        target = next(b for b in rb if b["shots"][0] == kf_shot)
        if target["refs"]:
            assert target["frame_mode"] == "ref" and "[参考__first__]" in target["prompt"]
            assert len(target["refs"]) <= caps.max_refs - 1, "首帧占一个名额"

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


def main() -> int:
    doc = json.loads(YAO.read_text(encoding="utf-8"))
    part_prompt(doc)
    part_clips(doc)
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
