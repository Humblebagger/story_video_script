#!/usr/bin/env python3
"""合成配音前的内容检查：编辑过的版本检查配音全文，拦截时合成失败且不调配音与合成；未编辑的版本跳过；
通过时照常合成。直接调 _compose_worker，合成本身用替身。用法: python3 tests/safety/test_compose_gate.py"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import _noenv  # noqa: E402,F401  测试不读真实 .env

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* 之前
import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"
os.environ["STORYBOARD_TTS_PROVIDER"] = "fake"
os.environ["STORYBOARD_RENDER_RUNNER"] = "0"
os.environ["STORYBOARD_SAFETY"] = "1"

from render import mix, providers, session as render_session, voice  # noqa: E402
from render.providers.fake import FakeTts, FakeVideo  # noqa: E402
from safety import gate  # noqa: E402
from server import app as app_mod  # noqa: E402
from server import auth, novels  # noqa: E402

DOC = json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8"))
providers.register("fake", lambda: FakeVideo())
providers.register_tts("fake", lambda: FakeTts())


def main() -> int:
    uid = auth.register("alice", "secret1")["id"]
    nid = novels.create_novel(uid, "药")["id"]
    cid = novels.create_chapter(uid, nid, "一", text="原文")["id"]
    novels.create_version(uid, nid, cid, "v1", {}, "原文")
    novels.update_version_state(uid, nid, cid, "v1", "succeeded", result=DOC)
    root = novels.render_dir(uid, nid, cid, "v1")
    owner = {"user_id": uid, "nid": nid, "cid": cid, "vid": "v1"}
    s = render_session.build(root, DOC, owner=owner, patch={"audio_mode": "tts_all"}, keyframes={})
    want = "\n".join(x["text"] for x in voice.tts_lines(voice.speech_lines(DOC), "tts_all"))
    assert want.strip(), "夹具要有配音文字"

    checked, composed = [], []
    verdict = {"error": None}

    def fake_check(text, ctx):
        checked.append((text, ctx["stage"], ctx["version_id"], ctx["user_id"]))
        if verdict["error"] is not None:
            raise verdict["error"]

    def fake_compose(*a, **kw):
        composed.append(1)
        return {"files": [], "report": ""}

    real_check, real_compose = gate.check_sync, mix.compose
    gate.check_sync, mix.compose = fake_check, fake_compose
    try:
        def run():
            render_session.begin_compose(root, fingerprint="fp", tts_cny=0.0, draft=True, voices={})
            app_mod._compose_worker(root, DOC, render_session.load(root), {}, True, ("ffmpeg", "ffprobe"))
            return render_session.load(root)["final"]

        # 1. 未编辑的版本：不检查，照常合成
        final = run()
        assert checked == [] and composed == [1] and final["state"] == "done", final
        print("1. 未编辑版本跳过 ✓")

        # 2. 编辑过的版本：检查配音全文（阶段 tts），通过则合成
        novels.update_version_result(uid, nid, cid, "v1", DOC, verification={}, status="succeeded")
        assert novels.get_version(uid, nid, cid, "v1")["edited_at"]
        final = run()
        assert checked == [(want, "tts", "v1", uid)] and composed == [1, 1] and final["state"] == "done"
        print("2. 编辑过的版本检查后合成 ✓")

        # 3. 拦截：合成失败，消息是 safety.blocked 带编号，没有调用合成（配音在合成里，同样没调）
        verdict["error"] = gate.blocked_error("sexual", "AB12CD34")
        final = run()
        assert composed == [1, 1] and final["state"] == "failed", final
        assert final["error_msg"]["code"] == "safety.blocked" and final["error_msg"]["ref"] == "AB12CD34"
        print("3. 拦截 ✓")

        # 4. 不可用：合成失败，消息是 safety.unavailable
        verdict["error"] = gate.unavailable_error()
        final = run()
        assert composed == [1, 1] and final["error_msg"]["code"] == "safety.unavailable"
        print("4. 不可用 ✓")

        # 5. 无声模式没有要配音的文字：不检查
        render_session.build(root, DOC, owner=owner, patch={"audio_mode": "silent"}, keyframes={},
                             allow_in_flight=True)
        verdict["error"], n = None, len(checked)
        final = run()
        assert len(checked) == n and final["state"] == "done"
        print("5. 无声模式不检查 ✓")
    finally:
        gate.check_sync, mix.compose = real_check, real_compose

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        _TMP.cleanup()
    sys.exit(code)
