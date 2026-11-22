#!/usr/bin/env python3
"""配音与合成接口：音色（默认、选择、清除、校验）、合成预览、合成的拦截（没装 ffmpeg、缺音色、配音金额
确认 409、草稿合成关掉时缺段、上限、合成中再合成、预览后改音色）、后台线程推进到完成/失败（报错隐去服务器路径）、
成片过期（按成片出自的那次合成）、重启中断（含关掉后台出片）、BGM 上传删除、无声模式不需要配音密钥。

假视频厂商 + 假 TTS；合成本身用替身函数（真 ffmpeg 合成由 tests/render/test_mix_e2e.py 覆盖）。
用法: python3 tests/server/test_compose.py
"""
import copy
import io
import json
import logging
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* 之前

# 测试不读真实的 backend/.env：load_settings 里的 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"
os.environ["STORYBOARD_TTS_PROVIDER"] = "fake"
os.environ["STORYBOARD_RENDER_RUNNER"] = "0"

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from render import export_fcpxml, mix, providers, voice, session as render_session  # noqa: E402
from render.providers.fake import FakeTts, FakeVideo  # noqa: E402
from render.providers.tts_base import tts_cost  # noqa: E402
from server import app as app_mod  # noqa: E402
from server import auth, error_refs, novels  # noqa: E402

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
    r = c.get(R + "/voices", headers=H)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "film.session.none", r.text
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
    r = c.put(R + "/voices", headers=H, json={"voices": {"narration": "nope", "C1": "nah"}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "tts.unknown_voice_list", r.text
    assert r.json()["detail"]["params"] == {"voices": ["nope", "nah"]} \
        and r.json()["detail"]["message"] == "没有这个音色：nope、nah", r.text
    assert next(x for x in v["speakers"] if x["key"] == "narration")["name"] == \
        {"code": "voice.narrator", "params": {}}
    assert v["rate_note"] == {"code": "rate.tts", "params": {}}
    assert all(isinstance(x["name"], str) for x in v["speakers"] if x["key"] != "narration" and x["key"])
    from render.providers.base import ProviderError as _PE

    def _no_key():
        raise _PE.of("tts.vendor.no_key")
    real_lines = voice.speech_lines
    voice.speech_lines = lambda d: real_lines(d) + [{"id": "X-L1", "episode": "E01", "shot": "X", "kind": "dialogue",
                                                      "speaker": "", "text": "无名氏", "emotion": None}]
    try:
        v2 = c.get(R + "/voices", headers=H).json()
    finally:
        voice.speech_lines = real_lines
    unl = next(x for x in v2["speakers"] if x["key"] == "")
    assert unl["name"] == {"code": "voice.unlabeled", "params": {}}, unl
    providers.register_tts("fake", _no_key)
    r = c.get(R + "/voices", headers=H)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "tts.vendor.no_key", r.text
    assert r.json()["detail"]["message"] == "配音服务还没有配置，请联系管理员"
    os.environ["STORYBOARD_TTS_PROVIDER"] = "nope"
    r = c.get(R + "/voices", headers=H)
    os.environ["STORYBOARD_TTS_PROVIDER"] = "fake"
    assert r.status_code == 422 and r.json()["detail"]["code"] == "tts.vendor.misconfigured", r.text
    providers.register_tts("fake", lambda: TTS)
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
    assert p["exportable"] is False and p["export_reason"] == "none"
    r = c.get(R + "/export.zip", headers=H)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "export.none", r.text
    print("3. 合成预览 ✓")

    # 4. 拦截：没装 ffmpeg → 422；缺音色 → 422；补齐音色后金额要确认（409 带金额）
    real_tools, real_compose = mix.tools, mix.compose
    mix.tools = lambda: None
    r = c.post(R + "/compose", headers=H, json={})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "compose.no_ffmpeg", r.text
    assert "brew" not in json.dumps(r.json()["detail"], ensure_ascii=False), "面向用户，不写安装命令"
    mix.tools = lambda: ("ffmpeg", "ffprobe")
    if v["missing"]:
        r = c.post(R + "/compose", headers=H, json={})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "compose.missing_voices", r.text
        c.put(R + "/voices", headers=H, json={"voices": {k: "fake-male" for k in v["missing"]}})
    p = c.get(R + "/compose", headers=H).json()
    chars = sum(len(x["text"]) for x in lines)
    assert p["missing_voices"] == [] and p["tts_chars"] == chars and p["tts_cny"] == tts_cost(chars, TTS.caps)
    r = c.post(R + "/compose", headers=H, json={})
    assert r.status_code == 409 and r.json()["detail"] == {
        "code": "compose.confirm_cny", "params": {"cost": {"t": "money", "cny": round(p["tts_cny"], 2)}},
        "message": f"本次配音约 ¥{p['tts_cny']:.2f}，请确认金额后再合成", "expected_cny": p["tts_cny"]}, r.text
    assert c.post(R + "/compose", headers=H, json={"expected_cny": p["tts_cny"] + 1}).status_code == 409
    assert c.post(R + "/compose", headers=H, json={"expected_cny": p["tts_cny"] + 0.004}).status_code == 409, \
        "差 0.004 元也要重新确认"
    r = c.post(R + "/compose", headers=H, json={"expected_cny": p["tts_cny"], "draft": False})
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "compose.no_video_count" and d["params"] == {"n": len(p["no_video"])}, r.text
    assert "草稿合成" in d["message"]
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

    # 5b. 导出：旧成片没有时间轴 → 409 重新合成；有时间轴 → zip；过期 409；别人 404；没 ffmpeg 503
    p5 = c.get(R + "/compose", headers=H).json()
    assert p5["exportable"] is False and p5["export_reason"] == "no_timeline"
    r = c.get(R + "/export.zip", headers=H)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "export.no_timeline", r.text
    (Path(root) / "final" / "timeline.json").write_text("{}", encoding="utf-8")
    p5 = c.get(R + "/compose", headers=H).json()
    assert p5["exportable"] is True and p5["export_reason"] is None
    real_export = export_fcpxml.export

    zname = ["药-第一章.zip"]

    langs = []

    def fake_export(root_, *, title, tools, lang=None):
        assert tools == ("ffmpeg", "ffprobe") and "药" in title and "第一章" in title
        langs.append(lang)
        d = Path(root_) / "final" / "export"
        d.mkdir(parents=True, exist_ok=True)
        z = d / (zname[0].replace(".zip", f".{lang}.zip") if lang else zname[0])
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("药/project.fcpxml", "<fcpxml/>")
        return z
    export_fcpxml.export = fake_export
    try:
        r = c.get(R + "/export.zip", headers=H)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/zip"
        cd = r.headers["content-disposition"]
        assert "filename*=utf-8''" in cd.lower() and 'filename="' in cd, cd
        assert "%E8%8D%AF-%E7%AC%AC%E4%B8%80%E7%AB%A0.zip" in cd, cd
        # 纯 ASCII 名字也要同时带 filename= 与 filename*=
        zname[0] = "My_Novel-Chapter_1-ab12cd34.zip"
        r = c.get(R + "/export.zip", headers=H)
        assert r.status_code == 200, r.text
        assert r.headers["content-disposition"] == (
            'attachment; filename="My_Novel-Chapter_1-ab12cd34.zip"; '
            "filename*=UTF-8''My_Novel-Chapter_1-ab12cd34.zip"), r.headers["content-disposition"]
        assert any(n.endswith("project.fcpxml") for n in zipfile.ZipFile(io.BytesIO(r.content)).namelist())
        # 语言：?lang=en 文件名带 .en.zip；?lang=fr 视同不带
        langs.clear()
        r = c.get(R + "/export.zip?lang=en", headers=H)
        assert r.status_code == 200 and langs == ["en"], (r.text, langs)
        assert "My_Novel-Chapter_1-ab12cd34.en.zip" in r.headers["content-disposition"], r.headers["content-disposition"]
        r = c.get(R + "/export.zip?lang=fr", headers=H)
        assert r.status_code == 200 and langs == ["en", None], langs
        assert r.headers["content-disposition"].startswith('attachment; filename="My_Novel-Chapter_1-ab12cd34.zip"')
        # 导出报错转 409 消息对象且不带服务器目录
        def boom(root_, *, title, tools, lang=None):
            raise export_fcpxml.ExportError.of("export.missing_file", file=f"{root_}/final/x.mp4")
        export_fcpxml.export = boom
        r = c.get(R + "/export.zip", headers=H)
        dumped = json.dumps(r.json()["detail"], ensure_ascii=False)
        assert r.status_code == 409 and str(root) not in dumped and str(Path(root).resolve()) not in dumped, r.text
        d = r.json()["detail"]
        assert d["code"] == "export.missing_file" and d["params"]["file"].startswith("…/final/x.mp4"), d
        assert "合成产物缺失" in d["message"]
        export_fcpxml.export = fake_export
        # 没装 ffmpeg
        mix.tools = lambda: None
        r = c.get(R + "/export.zip", headers=H)
        assert r.status_code == 503 and r.json()["detail"]["code"] == "export.no_ffmpeg", r.text
        assert "brew" not in json.dumps(r.json()["detail"], ensure_ascii=False)
        mix.tools = lambda: ("ffmpeg", "ffprobe")
        # 别的用户看不到
        uid2 = auth.register("bob", "secret2")["id"]
        H2 = {"Authorization": f"Bearer {auth.issue_token(uid2)}"}
        assert c.get(R + "/export.zip", headers=H2).status_code == 404
        # 分镜一改成片过期
        novels.update_version_result(uid, nid, cid, "v1", edited, verification={}, status="succeeded")
        p5 = c.get(R + "/compose", headers=H).json()
        assert p5["exportable"] is False and p5["export_reason"] == "stale"
        r = c.get(R + "/export.zip", headers=H)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "export.stale", r.text
        novels.update_version_result(uid, nid, cid, "v1", copy.deepcopy(DOC), verification={}, status="succeeded")
    finally:
        export_fcpxml.export = real_export
        (Path(root) / "final" / "timeline.json").unlink()
    print("5b. 导出：无时间轴 409、zip 下载、报错隐去目录、无 ffmpeg 503、他人 404、过期 409 ✓")

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
    f = c.get(R + "/compose", headers=H).json()["final"]
    assert f["error_msg"]["code"] == "compose.crashed" and f["error_msg"]["params"] == {} and len(f["error_msg"]["ref"]) == 8, f
    assert "RuntimeError" not in f["error"] and "意外" not in f["error"].replace("意外错误", ""), "不显示异常类名与原文"
    assert f["error"].startswith("合成时出现意外错误，请重试；仍失败请联系管理员") and "参考编号" in f["error"], f
    assert "RuntimeError" in error_refs.find(f["error_msg"]["ref"])["detail"], "记录里有异常类名"
    print("6. 合成失败与意外异常都落到失败 ✓")

    # 7. 合成中不能再合成；超上限拒绝；重启时中断的合成标失败
    render_session.begin_compose(root, fingerprint="x", tts_cny=0, draft=True)
    r = c.post(R + "/compose", headers=H, json={"expected_cny": exp})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "compose.busy", r.text
    try:
        app_mod._compose_quote({"id": uid}, nid, cid, "v1", True)
        raise AssertionError("合成中应 409")
    except HTTPException as e:
        assert e.status_code == 409 and e.detail["code"] == "compose.busy", e.detail
    r = c.get(R + "/export.zip", headers=H)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "export.busy", r.text
    render_session.recover(root)
    f = render_session.load(root)["final"]
    assert f["state"] == "failed" and f["error_msg"] == {"code": "compose.interrupted", "params": {}} and "服务中断" in f["error"]
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
        assert e.code == "compose.voices_changed" and e.expected_cny is None, (e.code, e.expected_cny)
    try:
        app_mod._render_call(render_session.begin_compose, root, fingerprint="x", tts_cny=0, draft=True,
                             voices=seen_voices)
        raise AssertionError("音色变了应 409")
    except HTTPException as e:
        assert e.status_code == 409 and e.detail["code"] == "compose.voices_changed", e.detail
        assert "expected_cny" in e.detail and e.detail["expected_cny"] is None, e.detail
    c.put(R + "/voices", headers=H, json={"voices": {"narration": seen_voices.get("narration", "")}})
    assert render_session.load(root)["final"]["state"] == "done", "被拒时不动成片"
    # 7e. 关掉后台出片（STORYBOARD_RENDER_RUNNER=0）时启动也收尾中断的合成
    render_session.begin_compose(root, fingerprint="x", tts_cny=0, draft=True)
    app_mod._start_render_runner()
    f = render_session.load(root)["final"]
    assert f["state"] == "failed" and f["error_msg"] == {"code": "compose.interrupted", "params": {}} and "服务中断" in f["error"]
    mix.compose = fake_compose
    TTS.caps.cny_per_k_chars = 100000.0
    big = c.get(R + "/compose", headers=H).json()["tts_cny"]
    r = c.post(R + "/compose", headers=H, json={"expected_cny": big})
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "compose.over_budget", r.text
    assert set(d["params"]) == {"budget", "spent", "cost"} and d["params"]["cost"]["t"] == "money", d
    TTS.caps.cny_per_k_chars = 0.3
    print("7. 合成中再合成 409、超上限 422、重启中断标失败（关掉后台出片也收尾）、预览后改音色 409 ✓")

    # 8. BGM：上传、预览里列出、类型与集号校验、删除
    assert c.put(R + "/bgm/E01", headers={**H, "Content-Type": "audio/mpeg"}, content=b"ID3bgm").status_code == 200
    assert c.get(R + "/compose", headers=H).json()["bgm"] == ["E01"]
    r = c.put(R + "/bgm/E01", headers={**H, "Content-Type": "text/plain"}, content=b"x")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "compose.bgm.bad_type", r.text
    r = c.put(R + "/bgm/E99", headers={**H, "Content-Type": "audio/mpeg"}, content=b"x")
    assert r.status_code == 404 and r.json()["detail"] == {
        "code": "compose.bgm.no_episode", "params": {"episode": "E99"}, "message": "没有这一集：E99"}, r.text
    r = c.put(R + "/bgm/E01", headers={**H, "Content-Type": "audio/mpeg"}, content=b"")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "compose.bgm.too_big", r.text
    assert c.put(R + "/bgm/E01", headers={**H, "Content-Type": "audio/wav"}, content=b"RIFFwav").status_code == 200
    assert sorted(p.name for p in (root / "audio" / "bgm").iterdir()) == ["E01.wav"], "换格式时删掉旧文件"
    old_max = app_mod.BGM_MAX_BYTES
    app_mod.BGM_MAX_BYTES = 4
    r = c.put(R + "/bgm/E01", headers={**H, "Content-Type": "audio/mpeg"}, content=b"too-large")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "compose.bgm.too_big", r.text
    app_mod.BGM_MAX_BYTES = old_max
    assert sorted(p.name for p in (root / "audio" / "bgm").iterdir()) == ["E01.wav"], "超限不动旧文件"
    r = c.delete(R + "/bgm/E99", headers=H)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "compose.bgm.no_episode", r.text
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

    # 11. 合成线程：带代码的 MixError 原样落到 error_msg；意外异常给固定说法，类名与堆栈只进日志（先脱敏）
    class _Cap(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []

        def emit(self, rec):
            self.records.append(rec)
    cap = _Cap()
    lg = logging.getLogger("render.app")
    lg.addHandler(cap)
    old_level, lg.level = lg.level, logging.DEBUG
    try:
        def coded(*a, **kw):
            raise mix.MixError.of("compose.ffmpeg_failed", what=f"混音 E01 {root}/x.mp4", rc=1)
        mix.compose = coded
        exp = c.get(R + "/compose", headers=H).json()["tts_cny"]
        assert c.post(R + "/compose", headers=H, json={"expected_cny": exp}).status_code == 200
        wait(root)
        f = render_session.load(root)["final"]
        assert f["error_msg"]["code"] == "compose.ffmpeg_failed" and f["error_msg"]["params"]["rc"] == 1, f
        assert str(root) not in json.dumps(f, ensure_ascii=False) and "…/x.mp4" in f["error"], f
        assert "…/x.mp4" in json.dumps(f["error_msg"], ensure_ascii=False), "params 里的目录也隐去"

        os.environ["ARK_API_KEY"] = "zq"                      # 短密钥也要抹掉
        os.environ["VOLC_TTS_API_KEY"] = "tts-secret-1"

        def crash(*a, **kw):
            raise ValueError("炸了 Bearer abc.def zq tts-secret-1 " + str(root))
        mix.compose = crash
        assert c.post(R + "/compose", headers=H, json={"expected_cny": exp}).status_code == 200
        wait(root)
        f = render_session.load(root)["final"]
        assert f["error_msg"]["code"] == "compose.crashed" and f["error_msg"]["params"] == {} and len(f["error_msg"]["ref"]) == 8, f
        assert "ValueError" in error_refs.find(f["error_msg"]["ref"])["detail"], "记录里有异常类名"
        assert "ValueError" not in f["error"] and "炸了" not in f["error"], f
        errs = [r for r in cap.records if r.levelno >= logging.ERROR]
        assert errs, "意外异常要写 ERROR 日志"
        text = "\n".join(r.getMessage() for r in errs)
        assert "ValueError" in text and "炸了" in text and "Traceback" in text, text
        assert "abc.def" not in text and "tts-secret-1" not in text and " zq " not in text, text
        assert all(r.exc_info is None for r in errs), "不把原始 exc_info 交给日志"
        from render.providers import base as _b
        assert _b.scrub_secrets("x zq y tts-secret-1 z inst", ["inst"]) == "x *** y *** z ***", "app 与 runner 共用同一个脱敏帮手"
        # 会话目录里带环境密钥：整行日志（位置字段 + 堆栈）都不含密钥
        os.environ["ARK_API_KEY"] = str(root)
        cap.records.clear()

        def crash2(*a, **kw):
            raise ValueError("boom")
        mix.compose = crash2
        assert c.post(R + "/compose", headers=H, json={"expected_cny": exp}).status_code == 200
        wait(root)
        errs = [r.getMessage() for r in cap.records if r.levelno >= logging.ERROR]
        assert errs and "合成异常" in errs[0] and "ValueError" in errs[0], errs
        assert not any(str(root) in x for x in errs), errs
        # 状态写回也失败：二次日志同样把数据目录换成 <data>（root 与堆栈里的绝对路径都不留）
        os.environ.pop("ARK_API_KEY", None)
        cap.records.clear()
        real_cf = render_session.compose_failed

        def cf_boom(*a, **kw):
            raise OSError(f"disk full {root}/session.json")
        render_session.compose_failed = cf_boom
        try:
            assert c.post(R + "/compose", headers=H, json={"expected_cny": exp}).status_code == 200
            wait_until = __import__("time").time() + 5
            while __import__("time").time() < wait_until and not any("写回失败" in r.getMessage() for r in cap.records):
                __import__("time").sleep(0.05)
        finally:
            render_session.compose_failed = real_cf
        second = [r.getMessage() for r in cap.records if "写回失败" in r.getMessage()]
        real_dir = os.environ["STORYBOARD_DATA_DIR"]
        assert second and "<data>" in second[0] and real_dir not in second[0] and str(root) not in second[0], second
    finally:
        lg.removeHandler(cap)
        lg.level = old_level
        os.environ.pop("ARK_API_KEY", None)
        os.environ.pop("VOLC_TTS_API_KEY", None)
    print("11. 合成线程：带代码的错误落 error_msg，意外异常只给固定说法、日志脱敏 ✓")

    mix.tools, mix.compose = real_tools, real_compose
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
