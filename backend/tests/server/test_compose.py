#!/usr/bin/env python3
"""配音与合成接口：音色（默认、选择、清除、校验）、合成预览、合成的拦截（没装 ffmpeg、缺音色、配音金额
确认 409、草稿合成关掉时缺段、上限、合成中再合成、预览后改音色）、后台线程推进到完成/失败（报错隐去服务器路径）、
成片过期（按成片出自的那次合成）、重启中断（含关掉后台出片）、BGM 上传删除、无声模式不需要配音密钥。

假视频厂商 + 假 TTS；合成本身用替身函数（真 ffmpeg 合成由 tests/render/test_mix_e2e.py 覆盖）。
用法: python3 tests/server/test_compose.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* 之前
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"
os.environ["STORYBOARD_TTS_PROVIDER"] = "fake"
os.environ["STORYBOARD_RENDER_RUNNER"] = "0"

from fastapi.testclient import TestClient  # noqa: E402
from render import mix, providers, voice, session as render_session  # noqa: E402
from render.providers.fake import FakeTts, FakeVideo  # noqa: E402
from render.providers.tts_base import tts_cost  # noqa: E402
from server import app as app_mod  # noqa: E402
from server import auth, novels  # noqa: E402

FAKE = FakeVideo()
TTS = FakeTts()
providers.register("fake", lambda: FAKE)
providers.register_tts("fake", lambda: TTS)
DOC = json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8"))


def wait(root):
    t = app_mod._compose_threads.get(str(root))
    if t:
        t.join(10)
        assert not t.is_alive(), "合成线程没跑完"


def main() -> int:
    c = TestClient(app_mod.app)
    uid = auth.register("alice", "secret1")["id"]
    H = {"Authorization": f"Bearer {auth.issue_token(uid)}"}
    nid = novels.create_novel(uid, "药")["id"]
    cid = novels.create_chapter(uid, nid, "第一章", text="原文")["id"]
    novels.create_version(uid, nid, cid, "v1", {}, "原文")
    novels.update_version_state(uid, nid, cid, "v1", "succeeded", result=copy.deepcopy(DOC))
    R = f"/novels/{nid}/chapters/{cid}/versions/v1/render"
    root = novels.render_dir(uid, nid, cid, "v1")

    # 1. 没会话：音色与合成都 404
    assert c.get(R + "/voices", headers=H).status_code == 404
    assert c.get(R + "/compose", headers=H).status_code == 404
    assert c.post(R + "/session", headers=H, json={}).status_code == 200
    print("1. 没会话时 404 ✓")

    # 2. 音色：按提示默认、缺音色列出、选择与清除、无效音色 422
    v = c.get(R + "/voices", headers=H).json()
    assert v["provider"] == "fake" and {x["id"] for x in v["voices"]} == {"fake-male", "fake-female"}
    keys = [x["key"] for x in v["speakers"]]
    assert keys[0] == "narration" or "narration" in keys
    narr = next(x for x in v["speakers"] if x["key"] == "narration")
    assert narr["voice"] == "fake-male" and narr["chosen"] is None, "旁白提示 male_mature → 男声"
    assert set(v["missing"]) == {x["key"] for x in v["speakers"] if x["voice"] is None}
    assert c.put(R + "/voices", headers=H, json={"voices": {"narration": "nope"}}).status_code == 422
    v = c.put(R + "/voices", headers=H, json={"voices": {"narration": "fake-female"}}).json()
    narr = next(x for x in v["speakers"] if x["key"] == "narration")
    assert narr["voice"] == "fake-female" and narr["chosen"] == "fake-female"
    v = c.put(R + "/voices", headers=H, json={"voices": {"narration": ""}}).json()
    assert next(x for x in v["speakers"] if x["key"] == "narration")["voice"] == "fake-male", "清除后回到默认"
    print(f"2. 音色：默认、选择、清除、校验（缺音色 {len(v['missing'])} 个） ✓")

    # 3. 合成预览：配音字数与费用、缺视频的段、没装 ffmpeg 时也能看
    p = c.get(R + "/compose", headers=H).json()
    lines = voice.tts_lines(voice.speech_lines(DOC), "tts_all")
    assert p["lines"] == len(lines) and p["no_video"] and p["final"] is None and "tools" in p
    assert p["missing_voices"] == v["missing"]
    print("3. 合成预览 ✓")

    # 4. 拦截：没装 ffmpeg → 422；缺音色 → 422；补齐音色后金额要确认（409 带金额）
    real_tools, real_compose = mix.tools, mix.compose
    mix.tools = lambda: None
    r = c.post(R + "/compose", headers=H, json={})
    assert r.status_code == 422 and "brew install ffmpeg" in r.json()["detail"] \
        and "apt install ffmpeg" in r.json()["detail"], "没装 ffmpeg 的提示写 macOS 与 Linux 两种装法"
    mix.tools = lambda: ("ffmpeg", "ffprobe")
    if v["missing"]:
        r = c.post(R + "/compose", headers=H, json={})
        assert r.status_code == 422 and "音色" in r.json()["detail"]
        c.put(R + "/voices", headers=H, json={"voices": {k: "fake-male" for k in v["missing"]}})
    p = c.get(R + "/compose", headers=H).json()
    chars = sum(len(x["text"]) for x in lines)
    assert p["missing_voices"] == [] and p["tts_chars"] == chars and p["tts_cny"] == tts_cost(chars, TTS.caps)
    r = c.post(R + "/compose", headers=H, json={})
    assert r.status_code == 409 and r.json()["detail"]["expected_cny"] == p["tts_cny"]
    assert c.post(R + "/compose", headers=H, json={"expected_cny": p["tts_cny"] + 1}).status_code == 409
    r = c.post(R + "/compose", headers=H, json={"expected_cny": p["tts_cny"], "draft": False})
    assert r.status_code == 422 and "草稿合成" in r.json()["detail"]
    print("4. 拦截：没装 ffmpeg、缺音色、配音金额确认、关掉草稿合成时缺段 ✓")

    # 5. 合成：后台线程推进到完成；配音费计入已花；成片可取；分镜一改成片过期
    def fake_compose(root_, doc, s, *, tts, keyframes, bgm, draft, tools, on_cost=None, progress=None):
        assert draft and tts is TTS and s["final"]["state"] == "running"
        progress("配音 3 条")
        on_cost(0.5)
        (Path(root_) / "final").mkdir(exist_ok=True)
        (Path(root_) / "final" / "E01.mp4").write_bytes(b"mp4")
        return {"files": ["final/E01.mp4"], "report": "final/mix_report.json"}
    mix.compose = fake_compose
    before = render_session.load(root)["spent_cny"]
    r = c.post(R + "/compose", headers=H, json={"expected_cny": p["tts_cny"]})
    assert r.status_code == 200, r.text
    assert r.json()["final"]["state"] == "running"
    wait(root)
    p2 = c.get(R + "/compose", headers=H).json()
    f = p2["final"]
    assert f["state"] == "done" and f["files"] == ["final/E01.mp4"] and f["stale"] is False, f
    assert abs(render_session.load(root)["spent_cny"] - before - 0.5) < 1e-9
    assert c.get(R + "/files/final/E01.mp4", headers=H).content == b"mp4"
    edited = copy.deepcopy(DOC)
    edited["episodes"][0]["shots"][0]["narration"]["text"] += "（改）"
    novels.update_version_result(uid, nid, cid, "v1", edited, verification={}, status="succeeded")
    assert c.get(R + "/compose", headers=H).json()["final"]["stale"] is True
    novels.update_version_result(uid, nid, cid, "v1", copy.deepcopy(DOC), verification={}, status="succeeded")
    print("5. 后台合成到完成、配音费计入已花、成片可取、分镜一改就过期 ✓")

    # 6. 合成失败：错误与 ffmpeg 输出记下；意外异常也落到失败
    def broken(*a, **kw):
        raise mix.MixError(f"混音 E01 失败（ffmpeg 退出码 1）：{root}/final/work/E01.joined.mp4",
                           f"Invalid argument: {Path(root).resolve()}/final/E01.part.mp4")
    mix.compose = broken
    exp = c.get(R + "/compose", headers=H).json()["tts_cny"]
    assert c.post(R + "/compose", headers=H, json={"expected_cny": exp}).status_code == 200
    wait(root)
    f = c.get(R + "/compose", headers=H).json()["final"]
    assert f["state"] == "failed" and "混音" in f["error"] and f["detail"].startswith("Invalid argument")
    assert str(root) not in f["error"] + f["detail"] and str(Path(root).resolve()) not in f["detail"], f
    assert "…/final/work/E01.joined.mp4" in f["error"], "报错里隐去服务器路径"
    assert f["files"] == ["final/E01.mp4"] and f["stale"] is False, "失败不改现有成片的出处，没改动就不过期"
    assert f["files_fingerprint"] == p2["fingerprint"] and f["files_draft"] is True

    def boom(*a, **kw):
        raise RuntimeError("意外")
    mix.compose = boom
    assert c.post(R + "/compose", headers=H, json={"expected_cny": exp}).status_code == 200
    wait(root)
    assert "RuntimeError" in c.get(R + "/compose", headers=H).json()["final"]["error"]
    print("6. 合成失败与意外异常都落到失败 ✓")

    # 7. 合成中不能再合成；超上限拒绝；重启时中断的合成标失败
    render_session.begin_compose(root, fingerprint="x", tts_cny=0, draft=True)
    assert c.post(R + "/compose", headers=H, json={"expected_cny": exp}).status_code == 409
    render_session.recover(root)
    f = render_session.load(root)["final"]
    assert f["state"] == "failed" and f["error"] == render_session.COMPOSE_INTERRUPTED
    # 7b. 合成中不能出片
    render_session.begin_compose(root, fingerprint="x", tts_cny=0, draft=True)
    clip0 = render_session.load(root)["clips"][0]["id"]
    assert c.post(R + f"/clips/{clip0}/run", headers=H, json={}).status_code == 409
    render_session.recover(root)
    # 7c. 成片按当时的草稿设置判过期
    fp_full = c.get(R + "/compose?draft=false", headers=H).json()["fingerprint"]
    with render_session.mutate(root) as s_:       # 旧记录（没有 files_fingerprint）回退到 fingerprint
        s_["final"] = {"state": "done", "fingerprint": fp_full, "draft": False, "files": ["final/E01.mp4"],
                       "report": None}
    assert c.get(R + "/compose", headers=H).json()["final"]["stale"] is False
    with render_session.mutate(root) as s_:
        s_["final"]["draft"] = True
    assert c.get(R + "/compose", headers=H).json()["final"]["stale"] is True
    # 7d. 预览后音色被改：开始合成时 409 要重新确认
    seen_voices = dict(render_session.load(root).get("voices") or {})
    c.put(R + "/voices", headers=H, json={"voices": {"narration": "fake-female"}})
    try:
        render_session.begin_compose(root, fingerprint="x", tts_cny=0, draft=True, voices=seen_voices)
        raise AssertionError("音色变了应 409")
    except render_session.Conflict as e:
        assert "音色" in str(e)
    c.put(R + "/voices", headers=H, json={"voices": {"narration": seen_voices.get("narration", "")}})
    assert render_session.load(root)["final"]["state"] == "done", "被拒时不动成片"
    # 7e. 关掉后台出片（STORYBOARD_RENDER_RUNNER=0）时启动也收尾中断的合成
    render_session.begin_compose(root, fingerprint="x", tts_cny=0, draft=True)
    app_mod._start_render_runner()
    f = render_session.load(root)["final"]
    assert f["state"] == "failed" and f["error"] == render_session.COMPOSE_INTERRUPTED
    mix.compose = fake_compose
    TTS.caps.cny_per_k_chars = 100000.0
    big = c.get(R + "/compose", headers=H).json()["tts_cny"]
    r = c.post(R + "/compose", headers=H, json={"expected_cny": big})
    assert r.status_code == 422 and "上限" in r.json()["detail"]
    TTS.caps.cny_per_k_chars = 0.3
    print("7. 合成中再合成 409、超上限 422、重启中断标失败（关掉后台出片也收尾）、预览后改音色 409 ✓")

    # 8. BGM：上传、预览里列出、类型与集号校验、删除
    assert c.put(R + "/bgm/E01", headers={**H, "Content-Type": "audio/mpeg"}, content=b"ID3bgm").status_code == 200
    assert c.get(R + "/compose", headers=H).json()["bgm"] == ["E01"]
    assert c.put(R + "/bgm/E01", headers={**H, "Content-Type": "text/plain"}, content=b"x").status_code == 422
    assert c.put(R + "/bgm/E99", headers={**H, "Content-Type": "audio/mpeg"}, content=b"x").status_code == 404
    assert c.put(R + "/bgm/E01", headers={**H, "Content-Type": "audio/wav"}, content=b"RIFFwav").status_code == 200
    assert sorted(p.name for p in (root / "audio" / "bgm").iterdir()) == ["E01.wav"], "换格式时删掉旧文件"
    old_max = app_mod.BGM_MAX_BYTES
    app_mod.BGM_MAX_BYTES = 4
    assert c.put(R + "/bgm/E01", headers={**H, "Content-Type": "audio/mpeg"}, content=b"too-large").status_code == 422
    app_mod.BGM_MAX_BYTES = old_max
    assert sorted(p.name for p in (root / "audio" / "bgm").iterdir()) == ["E01.wav"], "超限不动旧文件"
    assert c.delete(R + "/bgm/E99", headers=H).status_code == 404
    assert c.delete(R + "/bgm/*", headers=H).status_code == 404
    assert c.delete(R + "/bgm/E01", headers=H).status_code == 200
    assert c.get(R + "/compose", headers=H).json()["bgm"] == []
    print("8. BGM 上传、校验、删除 ✓")

    # 9. 没有要配音的语音条（无声模式）：不需要配音密钥
    def no_key():
        raise providers.base.ProviderError("没有配置配音密钥")
    providers.register_tts("fake", no_key)
    with render_session.mutate(root) as s_:
        mode, s_["audio_mode"] = s_["audio_mode"], "silent"
    try:
        r = c.get(R + "/compose", headers=H)
        assert r.status_code == 200 and r.json()["lines"] == 0 and r.json()["tts_cny"] == 0, r.text
        assert r.json()["voices"] == {} and r.json()["missing_voices"] == []

        def silent_compose(root_, doc, s, *, tts, **kw):
            assert tts is None, "无声模式不取配音厂商"
            return {"files": ["final/E01.mp4"], "report": "final/mix_report.json"}
        mix.compose = silent_compose
        assert c.post(R + "/compose", headers=H, json={}).status_code == 200
        wait(root)
        assert render_session.load(root)["final"]["state"] == "done"
        v = c.get(R + "/voices", headers=H)
        assert v.status_code == 200 and v.json()["speakers"] == [] and v.json()["voices"] == [], \
            "没有要配音的语音条：音色表为空，不要配音密钥"
    finally:
        with render_session.mutate(root) as s_:
            s_["audio_mode"] = mode
        providers.register_tts("fake", lambda: TTS)
    print("9. 无声模式不需要配音密钥（预览、合成、音色表） ✓")

    # 10. 合成报告随预览返回；读不到或坏了为 None
    assert c.get(R + "/compose", headers=H).json()["report"] is None, "第 9 步的成片没写报告文件"
    (root / "final").mkdir(exist_ok=True)
    (root / "final" / "mix_report.json").write_text(json.dumps({"episodes": [], "size": "720x1280"}),
                                                    encoding="utf-8")
    with render_session.mutate(root) as s_:
        s_["final"].update(state="done", files=["final/E01.mp4"], report="final/mix_report.json")
    assert c.get(R + "/compose", headers=H).json()["report"]["size"] == "720x1280"
    (root / "final" / "mix_report.json").write_text("{坏", encoding="utf-8")
    assert c.get(R + "/compose", headers=H).json()["report"] is None
    print("10. 合成报告随预览返回 ✓")

    mix.tools, mix.compose = real_tools, real_compose
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
