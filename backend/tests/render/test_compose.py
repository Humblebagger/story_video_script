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


def main() -> int:
    doc = json.loads(YAO.read_text(encoding="utf-8"))
    part_prompt(doc)
    # @@NEXT@@
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
