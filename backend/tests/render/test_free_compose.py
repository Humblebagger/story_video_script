#!/usr/bin/env python3
"""自由节点的厂商请求：按 refs 顺序拼参考行与参考图（编号一致，改顺序后照样一致）、首帧两种来源、
首帧占参考位、风格图、复查不过抛 FreeInvalid。用法: python3 tests/render/test_free_compose.py
"""
import copy
import dataclasses
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import _noenv  # noqa: E402,F401  测试不读真实 .env

from render import compose  # noqa: E402
from render.plan import assets_index  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402
from render.providers.seedance import rewrite_refs  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao" / "output_merged.json"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
SESSION = {"provider": "fake", "model": "fake-1", "resolution": "720p", "audio_mode": "tts_all"}


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def rich(doc):
    d = copy.deepcopy(doc)
    for kind in ("characters", "creatures", "props"):
        for card in d["assets"].get(kind) or []:
            card["reference_images"] = [{"view": "front", "uri": f"https://img/{card['id']}.png"}]
    for card in d["assets"]["locations"]:
        for a in card.get("angles") or []:
            a["uri"] = f"https://img/{card['id']}-{a['angle']}.png"
    return d


def main() -> int:
    plain = json.loads(YAO.read_text(encoding="utf-8"))
    doc = rich(plain)
    idx = assets_index(doc)
    caps = FakeVideo().caps("fake-1")          # max_refs 3，首帧与参考图不能同用
    chars = [c["id"] for c in doc["assets"]["characters"]]
    loc = next(c for c in doc["assets"]["locations"] if c.get("angles"))
    shot = doc["episodes"][0]["shots"][0]["id"]
    tmp = Path(tempfile.mkdtemp())
    kf = tmp / "kf.png"
    kf.write_bytes(PNG)
    tail = tmp / "x.last.jpg"
    tail.write_bytes(b"\xff\xd8\xff\xe0jpg")

    def name(aid):
        return compose.asset_slot(idx, aid)["name"]

    def node(**over):
        return {"id": "F01", "prompt": "雨夜街头", "refs": [], "first_frame": None, "duration": 4.0, **over}

    def req_for(n, d=doc, keyframes=None, tail_frame=None, use_caps=caps, style=None):
        return compose.request_for_free(d, SESSION, n, keyframes=keyframes or {}, tail_frame=tail_frame,
                                        caps=use_caps, rewrite=rewrite_refs, style=style)

    # 1. 按 id 取参考位：类别由 id 所在的那一类决定，不分着装 / 机位；参考位计数
    sl = compose.asset_slot(idx, chars[0])
    assert sl["role"] == "character" and sl["variant"] is None
    assert sl["name"] == doc["assets"]["characters"][0]["name"]
    assert compose.asset_slot(idx, loc["id"])["role"] == "location"
    assert compose.asset_slot(idx, "ZZ") is None
    assert compose.free_slots_needed(["a", "b"], "keyframe:x", caps) == 3
    assert compose.free_slots_needed([], "keyframe:x", caps) == 0
    assert compose.free_slots_needed(["a"], None, caps) == 1
    print("1. 资产参考位 ✓")

    # 2. 参考行按 refs 顺序编号，参考图同序；换顺序后编号跟着走
    for refs in ([chars[0], loc["id"]], [loc["id"], chars[0]]):
        req, used = req_for(node(refs=refs))
        lines = req.prompt.splitlines()
        assert lines[0] == "雨夜街头" and used is None and req.first_frame is None
        assert lines[1:] == [f"【参考】@图片{i + 1} {name(a)}" for i, a in enumerate(refs)], lines
        assert [r.asset_id for r in req.refs] == refs and req.refs[0].source.startswith("https://img/")
        assert (req.duration, req.model, req.resolution, req.style_ref) == (4.0, "fake-1", "720p", None)
    print("2. 参考编号与顺序 ✓")

    # 3. 关键帧作首帧：有参考且厂商不能同用 → 首帧占第一个参考位，【首帧】行排在最前；超位抛错
    req, used = req_for(node(refs=chars[:2], first_frame=f"keyframe:{shot}"), keyframes={shot: kf})
    assert used == f"keyframe:{shot}" and req.first_frame is None
    assert [r.role for r in req.refs] == ["first_frame", "character", "character"]
    lines = req.prompt.splitlines()
    assert lines[1].startswith("【首帧】@图片1") and lines[2].startswith("【参考】@图片2")
    must_raise(compose.FreeInvalid, req_for, node(refs=chars[:3], first_frame=f"keyframe:{shot}"),
               keyframes={shot: kf})
    print("3. 首帧占参考位 ✓")

    # 4. 尾帧作首帧、不带参考：直接作首帧
    req, used = req_for(node(first_frame="tail:E01-C01"), tail_frame=tail)
    assert used == "tail:E01-C01" and req.first_frame.startswith("data:image/jpeg;base64,") and req.refs == []
    print("4. 尾帧作首帧 ✓")

    # 5. 风格图：按 refs 里的位置放，带上哈希
    style = {"source": "data:image/png;base64,AAAA", "hash": "h1"}
    req, _ = req_for(node(refs=[chars[0], compose.STYLE_ID]), style=style)
    assert [r.role for r in req.refs] == ["character", "style"] and req.style_ref == "h1"
    assert req.prompt.splitlines()[2] == f"【参考】@图片2 {compose.STYLE_TEXT}"
    print("5. 风格图 ✓")

    # 6. 复查不过：抛 FreeInvalid（不提交、不花钱）
    for n, kw in (
        (node(prompt="  "), {}),
        (node(refs=[chars[0]]), {"d": plain}),                    # 资产图被删
        (node(refs=["ZZ"]), {}),
        (node(refs=[compose.STYLE_ID]), {}),                       # 风格图已删
        (node(first_frame=f"keyframe:{shot}"), {}),                # 关键帧没了
        (node(first_frame="tail:E01-C01"), {"tail_frame": tmp / "nope.jpg"}),
        (node(first_frame="tail:E01-C01"), {}),
        (node(first_frame=f"keyframe:{shot}"), {"keyframes": {shot: kf},
                                                "use_caps": dataclasses.replace(caps, first_frame=False)}),
    ):
        must_raise(compose.FreeInvalid, req_for, n, **kw)
    e = must_raise(compose.FreeInvalid, req_for, node(refs=[compose.STYLE_ID]))
    assert e.code == "film.free_invalid.style_gone" and "风格图已删除" in str(e)
    assert must_raise(compose.FreeInvalid, req_for, node(prompt="  ")).code == "film.free_invalid.empty_prompt"
    print("6. 复查不过 ✓")

    # 7. 正文与资产名里的占位符被清掉，@图片n 只剩生成的那些，按 1..n 顺序
    import re
    req, _ = req_for(node(prompt="让 {ref:C01} 转身，看 @图片3", refs=[chars[0], loc["id"]]))
    nums = re.findall(r"@图片(\d+)", req.prompt)
    assert nums == ["1", "2"] and len(req.refs) == 2, req.prompt
    assert req.prompt.splitlines()[0] == "让  转身，看"
    req, _ = req_for(node(prompt="{ref:C01}开场 @图片9", refs=chars[:2], first_frame=f"keyframe:{shot}"),
                     keyframes={shot: kf})
    assert re.findall(r"@图片(\d+)", req.prompt) == ["1", "2", "3"] and len(req.refs) == 3
    d2 = copy.deepcopy(doc)
    d2["assets"]["characters"][0]["name"] = "甲{ref:x}"
    req, _ = req_for(node(refs=[chars[0]]), d=d2)
    assert re.findall(r"@图片(\d+)", req.prompt) == ["1"] and "{ref" not in req.prompt, req.prompt
    print("7. 占位符清理 ✓")

    # 8. 清理要反复做到不再变化：拼回来的占位符也得清；清完为空照样报错
    for body in ("让 {ref@图片9:C01} 转身", "看 @图{ref:x}片9"):
        req, _ = req_for(node(prompt=body, refs=[chars[0]]))
        assert re.findall(r"@图片(\d+)", req.prompt) == ["1"] and len(req.refs) == 1, req.prompt
        assert "{ref" not in req.prompt, req.prompt
    d3 = copy.deepcopy(doc)
    d3["assets"]["characters"][0]["name"] = "甲{ref@图片9:x}"
    req, _ = req_for(node(refs=[chars[0]]), d=d3)
    assert re.findall(r"@图片(\d+)", req.prompt) == ["1"] and "{ref" not in req.prompt, req.prompt
    must_raise(compose.FreeInvalid, req_for, node(prompt="{ref:C01} @图片1"))
    print("8. 反复清理与清空 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
