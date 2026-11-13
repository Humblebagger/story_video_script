#!/usr/bin/env python3
"""配音：语音条顺序（与 timeline.ts speechOf 一致）、各声音模式走 TTS 的语音条、说话人与音色分配、
缓存命中不重复计费、长句切开、瞬时错误重试与失败汇总（含收下后失败按已计费）、预估。

假 TTS，不联网、不花钱。用法: python3 tests/render/test_voice.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from render import voice  # noqa: E402
from render.providers.fake import FakeTts  # noqa: E402
from render.providers.tts_base import tts_cost  # noqa: E402

DOC = json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8"))
SMALL = {
    "meta": {"narration": {"tts_voice": "male_mature"}},
    "assets": {"characters": [{"id": "C1", "name": "老栓", "voice": {"tts_voice": "male_elder"}},
                              {"id": "C2", "name": "大妈", "voice": {"tts_voice": "female_mid"}},
                              {"id": "C3", "name": "路人"}]},
    "episodes": [{"id": "E01", "shots": [
        {"id": "S1", "narration": {"text": "旁白在前"},
         "dialogue": [{"type": "dialogue", "character_ref": "C1", "text": "台词一"},
                      {"type": "inner_monologue", "character_ref": "C2", "text": "心里话"}]},
        {"id": "S2", "narration": {"text": "旁白在后", "order": "after_dialogue"},
         "dialogue": [{"type": "voiceover", "character_ref": "C3", "text": "画外音"},
                      {"type": "dialogue", "character_ref": "C1", "text": ""}]},
        {"id": "S3"},
    ]}],
}


def main() -> int:
    lines = voice.speech_lines(SMALL)
    assert [(x["id"], x["kind"], x["speaker"]) for x in lines] == [
        ("S1-L1", "narration", "narration"), ("S1-L2", "dialogue", "C1"), ("S1-L3", "inner_monologue", "C2"),
        ("S2-L1", "voiceover", "C3"), ("S2-L2", "narration", "narration")], lines
    real = voice.speech_lines(DOC)
    expect = sum(bool((s.get("narration") or {}).get("text")) + sum(bool(d.get("text")) for d in s.get("dialogue") or [])
                 for ep in DOC["episodes"] for s in ep["shots"])
    assert len(real) == expect and len({x["id"] for x in real}) == len(real)
    print(f"1. 语音条顺序与 speechOf 一致（《药》{len(real)} 条） ✓")

    assert len(voice.tts_lines(lines, "tts_all")) == 5
    assert [x["kind"] for x in voice.tts_lines(lines, "dialogue_native")] == [
        "narration", "inner_monologue", "voiceover", "narration"]
    assert voice.tts_lines(lines, "all_native") == [] and voice.tts_lines(lines, "silent") == []
    print("2. 各声音模式走 TTS 的语音条 ✓")

    tts = FakeTts()
    voices, missing = voice.resolve_voices(SMALL, lines, {}, tts.caps)
    assert voices == {"narration": "fake-male", "C1": "fake-male", "C2": "fake-female"} and missing == ["C3"]
    voices, missing = voice.resolve_voices(SMALL, lines, {"C3": "fake-female", "C1": "nope"}, tts.caps)
    assert voices["C3"] == "fake-female" and voices["C1"] == "fake-male" and missing == [], "无效的选择退回默认"
    assert voice.speakers(SMALL)["C1"] == {"name": "老栓", "hint": "male_elder"}
    assert voice.speakers(SMALL)[voice.NARRATION]["name"] == {"code": "voice.narrator", "params": {}}
    print("3. 说话人与音色：用户选的优先、按提示性别默认、缺音色列出 ✓")

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        est = voice.estimate(lines, voices, tts, root)
        chars = sum(len(x["text"]) for x in lines)
        assert est == {"lines": 5, "chars": chars, "cny": tts_cost(chars, tts.caps)}, est
        spent = []
        done, failed = voice.synthesize(lines, voices, tts, root, on_cost=spent.append, sleep=lambda s: None)
        assert not failed and len(done) == 5 and len(tts.calls) == 5
        assert abs(sum(spent) - sum(x["cost_cny"] for x in done)) < 1e-9 and not any(x["cached"] for x in done)
        assert all(Path(x["file"]).exists() and x["duration"] > 0 for x in done)
        again, _ = voice.synthesize(lines, voices, tts, root, on_cost=spent.append, sleep=lambda s: None)
        assert len(tts.calls) == 5 and all(x["cached"] and x["cost_cny"] == 0 for x in again), "缓存命中不重合成"
        assert voice.estimate(lines, voices, tts, root)["chars"] == 0
        other = dict(voices, narration="fake-female")
        voice.synthesize(lines, other, tts, root, sleep=lambda s: None)
        assert len(tts.calls) == 7, "换了音色的两条旁白重合成"
    print("4. 合成、缓存命中不重复计费、换音色才重合成 ✓")

    with tempfile.TemporaryDirectory() as d:
        short = FakeTts(max_chars=10)
        text = "秋天的后半夜，月亮下去了，太阳还没有出，只剩下一片乌蓝的天。"
        assert all(len(p) <= 10 for p in voice.split_text(text, 10)) and "".join(voice.split_text(text, 10)) == text
        line = [{"id": "X-L1", "episode": "E01", "shot": "X", "kind": "narration", "speaker": "narration",
                 "text": text, "emotion": None}]
        done, failed = voice.synthesize(line, {"narration": "fake-male"}, short, Path(d), sleep=lambda s: None)
        assert not failed and len(short.calls) == len(voice.split_text(text, 10)) > 1
        assert abs(done[0]["duration"] - len(text) / 4.5) < 0.05
        assert not list((Path(d) / voice.CACHE_DIR).glob("*.part*")), "切开的片段拼完删掉"
    print("5. 长句按标点切开合成再拼 ✓")

    with tempfile.TemporaryDirectory() as d:
        flaky = FakeTts(fail_times=5)
        sleeps = []
        two = lines[:2]
        done, failed = voice.synthesize(two, voices, flaky, Path(d), retries=3, sleep=sleeps.append)
        assert [x["id"] for x in failed] == ["S1-L1"] and "限流" in failed[0]["error"]
        assert failed[0]["error_msg"] == {"code": "tts.fake.throttled", "params": {}}, failed[0]
        assert [x["id"] for x in done] == ["S1-L2"] and len(sleeps) == 4
    # 连接一直失败直到重试耗尽：最终失败原因不能再承诺「自动重试」
    import httpx
    from render.providers.tts_volc import VOICES, VolcTts

    def refused(request):
        raise httpx.ConnectError("refused", request=request)
    with tempfile.TemporaryDirectory() as d:
        volc = VolcTts(api_key="k-secret", client=httpx.Client(transport=httpx.MockTransport(refused)))
        vv = {"narration": VOICES[0].id}
        _, failed = voice.synthesize(lines[:1], vv, volc, Path(d), retries=2, sleep=lambda s: None)
        assert len(failed) == 1 and failed[0]["error_msg"]["code"] == "tts.volc.connect_failed", failed
        assert "自动重试" not in failed[0]["error"] and "retrying" not in failed[0]["error"], failed[0]["error"]
        from server.messages import render_zh
        assert "自动重试" not in render_zh(failed[0]["error_msg"]["code"], failed[0]["error_msg"]["params"]), failed[0]
    with tempfile.TemporaryDirectory() as d:
        bad = FakeTts(fail_with="音色无权限")
        done, failed = voice.synthesize(two, voices, bad, Path(d), sleep=lambda s: None)
        assert not done and [x["error"] for x in failed] == ["音色无权限", "音色无权限"] and len(bad.calls) == 2
        assert failed[0]["error_msg"] == {"code": "tts.fake.failed",
                                          "params": {"detail": {"t": "vendor", "text": "音色无权限"}}}, failed[0]
    with tempfile.TemporaryDirectory() as d:
        billed = FakeTts(fail_billed="中途断开")
        spent = []
        one = lines[:1]
        done, failed = voice.synthesize(one, voices, billed, Path(d), on_cost=spent.append, sleep=sleeps.append)
        assert not done and [x["error"] for x in failed] == ["中途断开"] and len(billed.calls) == 1, "不重试"
        assert failed[0]["error_msg"] == {"t": "vendor", "text": "中途断开"}, "无代码的 BilledError：error_msg 是厂商原文"
        assert spent == [tts_cost(len(one[0]["text"]), billed.caps)], "收下后才失败照记花费"
        assert not list((Path(d) / voice.CACHE_DIR).glob("*.wav")), "失败不留缓存"
    print("6. 瞬时错误重试 3 次、明确失败不重试，收下后失败按已计费记账，失败汇总不中断其余各条 ✓")

    try:
        voice.synthesize(lines, voices, tts, Path("/nonexistent/render/v1"), sleep=lambda s: None)
        raise AssertionError("会话目录不存在应抛 VoiceError")
    except voice.VoiceError as e:
        assert e.code == "film.session.dir_gone" and str(e) == "出片会话目录已不存在（版本可能已删除）"
    print("7. 会话目录已删不重建 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
