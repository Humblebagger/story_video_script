#!/usr/bin/env python3
"""出片会话：建立与校验、沿用尝试与过期判定、排队确认与上限、提交前复查、采用与静音、接力、重启恢复。

用法: python3 tests/render/test_session.py
"""
import copy
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import os as _os, tempfile as _tempfile  # noqa: E402
_os.environ["STORYBOARD_DATA_DIR"] = _tempfile.mkdtemp()   # 数据目录用临时目录，不碰真实 backend/data（必须在导入 server.*、render.* 之前）
# 测试不读真实的 backend/.env：load_settings 里的 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"

from render import providers, session as sess  # noqa: E402
from render.providers import base  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402
from server import public  # noqa: E402
from server.messages import cause_of, msg, money, vendor, with_ref  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao" / "output_merged.json"
OWNER = {"user_id": "u", "nid": "n", "cid": "c", "vid": "v"}


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def clip(s, cid):
    return next(c for c in s["clips"] if c["id"] == cid)


class _LogGrab(logging.Handler):
    """挂在某个 logger 上收日志文字与记录（测试不读真实日志配置）。"""
    def __init__(self, name):
        super().__init__(logging.DEBUG)
        self.lines, self.records = [], []
        self._lg = logging.getLogger(name)

    def emit(self, rec):
        self.records.append(rec)
        self.lines.append(rec.getMessage())

    def __enter__(self):
        self._lg.addHandler(self)
        return self

    def __exit__(self, *a):
        self._lg.removeHandler(self)


def finish(root, fake, clip_id, style_ref=None):
    """不经出片线程把一段走完：提交 → 成功 → 下载。"""
    snap = sess.begin_submit(root, clip_id)
    s = sess.load(root)
    req = base.ClipRequest(prompt=snap["prompt"], model=s["model"], duration=snap["duration"],
                           resolution=s["resolution"])
    tid = fake.submit(req)
    sess.submitted(root, clip_id, tid, None, style_ref=style_ref)
    st = fake.poll(tid)
    sess.poll_update(root, clip_id, st)
    files = fake.download(st, sess.clip_dest(root, clip_id, tid))
    sess.downloaded(root, clip_id, files, fake.cost(st, req))


def main() -> int:
    doc = json.loads(YAO.read_text(encoding="utf-8"))
    fake = FakeVideo()
    providers.register("fake", lambda: fake)
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name) / "render" / "v"
    build = lambda d=doc, **patch: sess.build(root, d, owner=OWNER, patch=patch, keyframes={})  # noqa: E731

    # 1. 建会话：默认设置、全部 planned、每段有预估；非法设置拒绝
    s = build()
    assert (root / "session.json").exists()
    assert (s["provider"], s["model"], s["resolution"], s["audio_mode"]) == \
        ("fake", "fake-1", "720p", "tts_all")
    assert s["budget_cny"] == 200.0 and s["confirm_over_cny"] == 20.0 and s["spent_cny"] == 0.0
    assert s["clips"] and all(c["state"] == "planned" and c["attempts"] == [] for c in s["clips"])
    caps = fake.caps("fake-1")
    assert all(c["estimate_cny"] == base.estimate_cny(c["duration"], caps, "720p") for c in s["clips"])
    must_raise(sess.SessionError, build, resolution="4k")
    must_raise(sess.SessionError, build, audio_mode="karaoke")
    must_raise(sess.SessionError, build, provider="nope")
    must_raise(sess.SessionError, build, bogus=1)
    v = sess.view(s)
    assert "owner" not in v and v["counts"] == {"planned": len(s["clips"])}
    assert v["remaining_cny"] == round(sum(c["estimate_cny"] for c in s["clips"]), 2)
    assert "fake" in v["options"]["providers"] and v["options"]["resolutions"] == ["480p", "720p"]
    assert v["options"]["rate_note"] == {"code": "rate.video", "params": {}}
    seen_images = []
    real_est = base.estimate_cny
    base.estimate_cny = lambda d, c, r, images=0: (seen_images.append(images), real_est(d, c, r, images))[1]
    try:
        s2 = build()
    finally:
        base.estimate_cny = real_est
    from render import compose as _compose
    assert seen_images and seen_images[:len(s2["clips"])] == [_compose.image_count(c) for c in s2["clips"]]
    print("1. 建会话与校验 ✓")

    # 2. 单段排队：低于确认线直接排；在跑时不能改设置；读取时刷新不动在跑的段
    first, second = s["clips"][0]["id"], s["clips"][1]["id"]
    s = sess.queue_run(root, [first])
    assert clip(s, first)["state"] == "queued"
    must_raise(sess.Conflict, sess.queue_run, root, [first])
    must_raise(sess.Conflict, build, resolution="480p")
    s = sess.build(root, doc, owner=OWNER, patch={}, keyframes={}, allow_in_flight=True)
    assert clip(s, first)["state"] == "queued"
    must_raise(sess.NotFound, sess.queue_run, root, ["E99-C01"])
    print("2. 单段排队 ✓")

    # 3. 走完一段：已花 = 实际费用，采用最新一次
    finish(root, fake, first)
    s = sess.load(root)
    c = clip(s, first)
    t1 = c["attempts"][0]["task_id"]
    assert c["state"] == "done" and c["chosen"] == 0
    k1 = public.task_key(t1)
    assert c["attempts"][0]["file"] == f"clips/{first}.{k1}.mp4", "文件按任务号的短键命名（不带厂商任务号）"
    assert c["attempts"][0]["last_frame"] == f"clips/{first}.{k1}.last.jpg"
    assert sess.clip_dest(root, "E01-C01", "cgt-1").name == "E01-C01." + public.task_key("cgt-1") + ".mp4"
    assert s["spent_cny"] == c["attempts"][0]["cost_cny"] > 0
    print("3. 走完一段 ✓")

    # 4. 改设置或分镜 → 已出的段过期（旧视频仍在）；改回 → 恢复 done
    s = build(resolution="480p")
    assert clip(s, first)["state"] == "stale" and clip(s, first)["chosen"] == 0
    assert all(c["state"] == "planned" for c in s["clips"] if c["id"] != first)
    assert s["spent_cny"] > 0, "已花不随重建清零"
    s = build(resolution="720p")
    assert clip(s, first)["state"] == "done"
    edited = copy.deepcopy(doc)
    edited["episodes"][0]["shots"][0]["action"] += "（改）"
    s = build(edited)
    assert clip(s, first)["state"] == "stale"
    s = build()
    assert clip(s, first)["state"] == "done"
    print("4. 过期判定 ✓")

    # 5. 接力：上一段完成后给出尾帧路径；上一段在跑时等待
    c2 = clip(s, second)
    assert c2["first_frame"] == f"relay:{first}" and not sess.waiting_on_relay(s, c2)
    assert sess.relay_frame(root, s, c2) == root / f"clips/{first}.{k1}.last.jpg"
    s = sess.queue_run(root, [second])
    third = next(c for c in s["clips"] if c["first_frame"] == f"relay:{second}")
    assert sess.waiting_on_relay(s, third)
    print("5. 接力 ✓")

    # 6. 批量：必须带确认金额；不一致 409 附重算金额；超上限拒绝
    e = must_raise(sess.Conflict, sess.queue_run, root, None)
    total = e.expected_cny
    assert total == sess.view(sess.load(root))["remaining_cny"] > 0
    assert must_raise(sess.Conflict, sess.queue_run, root, None, total + 1).expected_cny == total
    assert total + sess.load(root)["spent_cny"] > 200
    must_raise(sess.BudgetExceeded, sess.queue_run, root, None, total)
    with sess.mutate(root) as s:
        s["budget_cny"] = 100000.0
    s = sess.queue_run(root, None, total)
    assert all(c["state"] == "queued" for c in s["clips"] if c["id"] != first)
    print("6. 批量确认与上限 ✓")

    # 7. 单段超过确认线也要带金额；提交前再查上限
    root2 = Path(tmp.name) / "render" / "v2"
    s2 = sess.build(root2, doc, owner=OWNER, patch={"confirm_over_cny": 1}, keyframes={})
    one = s2["clips"][0]["id"]
    e = must_raise(sess.Conflict, sess.queue_run, root2, [one])
    sess.queue_run(root2, [one], e.expected_cny)
    with sess.mutate(root2) as s2:
        s2["spent_cny"] = 199.99
    assert sess.begin_submit(root2, one) is None
    c = clip(sess.load(root2), one)
    assert c["state"] == "failed" and "超出单章上限" in c["error"] and c["attempts"] == []
    print("7. 单段确认线与提交前复查 ✓")

    # 8. 采用与静音
    s = sess.set_chosen(root, first, 0)
    assert clip(s, first)["state"] == "done"
    must_raise(sess.SessionError, sess.set_chosen, root, first, 5)
    must_raise(sess.Conflict, sess.set_chosen, root, second, 0)
    s = sess.set_mute(root, first, True)
    assert clip(s, first)["mute_native"] is True
    print("8. 采用与静音 ✓")

    # 9. 重启恢复：提交中断的尝试标失败、不重复提交；还有在跑的段返回 True
    snap = sess.begin_submit(root, second)
    assert snap["attempts"][-1]["state"] == "submitting"
    assert sess.recover(root) is True
    c = clip(sess.load(root), second)
    assert c["state"] == "failed" and "不确定生成服务是否已受理" in c["error"]
    assert c["attempts"][-1]["state"] == "failed" and c["uncertain"] is True
    print("9. 重启恢复 ✓")

    # 10. 不丢已付费的尝试：切段变了 → stale 保留；段消失 → orphaned；再重建不重复
    root3 = Path(tmp.name) / "render" / "v3"
    b3 = lambda d, **kw: sess.build(root3, d, owner=OWNER, patch=kw.pop("patch", {}), keyframes={})  # noqa: E731
    s3 = b3(doc, patch={"budget_cny": 100000.0})
    ep1 = [c["id"] for c in s3["clips"] if c["episode"] == s3["clips"][0]["episode"]]
    assert len(ep1) >= 2, ep1
    with sess.mutate(root3) as s3:
        for c in s3["clips"]:
            if c["id"] in ep1:
                c["state"] = "queued"
    for cid in ep1:
        finish(root3, fake, cid)
    kept = {cid: len(clip(sess.load(root3), cid)["attempts"]) for cid in ep1}
    cut2 = copy.deepcopy(doc)
    del cut2["episodes"][0]["shots"][1]
    s3 = b3(cut2)
    stale = [c for c in s3["clips"] if c["id"] in ep1 and c["state"] == "stale"]
    assert stale and all(len(c["attempts"]) == kept[c["id"]] and c["chosen"] == 0 for c in stale)
    s3 = b3(doc)
    assert all(c["state"] == "done" for c in s3["clips"] if c["id"] in ep1)
    cut = copy.deepcopy(doc)
    shots = cut["episodes"][0]["shots"]
    cut["episodes"][0]["shots"] = shots[:1]
    s3 = b3(cut)
    now = {c["id"] for c in s3["clips"]}
    gone = [cid for cid in ep1 if cid not in now]
    assert gone, "缩短后应有段消失"
    assert {o["id"] for o in s3["orphaned"]} == set(gone)
    assert all(len(o["attempts"]) == kept[o["id"]] for o in s3["orphaned"])
    for cid in ep1:
        if cid in now:
            assert len(clip(s3, cid)["attempts"]) == kept[cid]
            assert len(clip(s3, cid)["attempts"]) == kept[cid]
    s3 = b3(cut)
    assert [o["id"] for o in s3["orphaned"]] == gone, "再重建不重复"
    assert all(len(o["attempts"]) == kept[o["id"]] for o in s3["orphaned"])
    print("10. 保留尝试与 orphaned ✓")

    # 11. 文件损坏不当作没有会话
    root4 = Path(tmp.name) / "render" / "v4"
    sess.build(root4, doc, owner=OWNER, patch={}, keyframes={})
    (root4 / "session.json").write_text("{garbage", encoding="utf-8")
    must_raise(sess.Corrupt, sess.build, root4, doc, owner=OWNER, patch={}, keyframes={})
    must_raise(sess.Corrupt, sess.set_mute, root4, "E01-C01", True)
    assert list(root4.glob("session.json.corrupt-*")) and (root4 / "session.json").read_text() == "{garbage"
    assert sess.load(root4) is None
    print("11. 损坏保护 ✓")

    # 12. 在跑时带设置的刷新被拒；重复 id 不重复计金额
    must_raise(sess.Conflict, sess.build, root, doc, owner=OWNER, patch={"resolution": "480p"},
               keyframes={}, allow_in_flight=True)
    root5 = Path(tmp.name) / "render" / "v5"
    s5 = sess.build(root5, doc, owner=OWNER, patch={"confirm_over_cny": 0}, keyframes={})
    a = s5["clips"][0]
    e = must_raise(sess.Conflict, sess.queue_run, root5, [a["id"], a["id"]])
    assert e.expected_cny == round(a["estimate_cny"], 2)
    s5 = sess.queue_run(root5, [a["id"], a["id"]], e.expected_cny)
    assert clip(s5, a["id"])["state"] == "queued"
    print("12. 在跑拒改设置与去重 ✓")

    # ---------- 终审修复 ----------
    # 13. 段 id 重新出现：orphaned 的尝试接回来；再出一次不覆盖已付费的旧文件，两次都列出
    s3 = b3(doc)
    assert s3["orphaned"] == [], "接回后不再留在 orphaned"
    for cid in gone:
        c = clip(s3, cid)
        assert len(c["attempts"]) == kept[cid] and c["chosen"] == 0 and c["state"] == "done"
    g = gone[0]
    old_file = root3 / clip(s3, g)["attempts"][0]["file"]
    with sess.mutate(root3) as x:
        clip(x, g)["state"] = "queued"
    finish(root3, fake, g)
    c = clip(sess.load(root3), g)
    new_file = root3 / c["attempts"][-1]["file"]
    assert len(c["attempts"]) == kept[g] + 1 and c["chosen"] == kept[g]
    assert old_file.exists() and new_file.exists() and old_file != new_file
    assert c["attempts"][0]["file"] != c["attempts"][-1]["file"]
    print("13. 接回 orphaned、按尝试命名文件 ✓")

    # 14. 反复 orphan 不丢尝试：同 id 已有 orphaned 记录（旧数据）时合并而不是跳过；接回时 chosen 仍有效
    with sess.mutate(root3) as x:                   # 模拟旧版本留下的同 id 记录
        x["orphaned"].append({"id": g, "shots": clip(x, g)["shots"], "chosen": None,
                              "attempts": [{"task_id": "legacy-1", "state": "failed", "cost_cny": 0.0,
                                            "file": None, "last_frame": None, "error": "旧的",
                                            "fingerprint": "x"}]})
    total_g = kept[g] + 2
    s3 = b3(cut)
    o = [x for x in s3["orphaned"] if x["id"] == g]
    assert len(o) == 1 and len(o[0]["attempts"]) == total_g, o
    assert o[0]["attempts"][o[0]["chosen"]]["file"] == c["attempts"][-1]["file"]
    s3 = b3(cut)
    o = [x for x in s3["orphaned"] if x["id"] == g]
    assert len(o) == 1 and len(o[0]["attempts"]) == total_g, "第二次 orphan 不丢"
    s3 = b3(doc)
    c = clip(s3, g)
    assert len(c["attempts"]) == total_g and c["attempts"][c["chosen"]]["file"] == o[0]["attempts"][o[0]["chosen"]]["file"]
    assert c["state"] == "done" and not s3["orphaned"]
    print("14. 反复 orphan 不丢 ✓")

    # 15. 分镜被清空：不据此重建（否则段全挤进 orphaned），原样返回已存的会话；带设置改动则拒绝
    before = sess.load(root3)
    for empty in ({}, {"episodes": []}, {"episodes": [{"id": "E01", "shots": []}]}):
        got = b3(empty)
        assert [x["id"] for x in got["clips"]] == [x["id"] for x in before["clips"]]
    assert sess.load(root3)["clips"] == before["clips"]
    must_raise(sess.SessionError, b3, {"episodes": []}, patch={"resolution": "480p"})
    print("15. 分镜清空不清段 ✓")

    # 16. 待核对（uncertain）：批量的范围与金额都跳过它；单段点名重做清掉标记
    root6 = Path(tmp.name) / "render" / "v6"
    s6 = sess.build(root6, doc, owner=OWNER, patch={"budget_cny": 100000.0}, keyframes={})
    u = s6["clips"][0]["id"]
    sess.queue_run(root6, [u])
    sess.begin_submit(root6, u)
    sess.submit_failed(root6, u, "不确定", uncertain=True)
    v6 = sess.view(sess.load(root6))
    assert clip(v6, u)["uncertain"] is True and v6["uncertain_count"] == 1
    assert all(x["uncertain"] is False for x in v6["clips"] if x["id"] != u)
    rest = round(sum(x["estimate_cny"] for x in v6["clips"] if x["id"] != u), 2)
    assert v6["remaining_cny"] == rest
    assert must_raise(sess.Conflict, sess.queue_run, root6, None).expected_cny == rest
    s6 = sess.queue_run(root6, None, rest)
    assert clip(s6, u)["state"] == "failed" and clip(s6, u)["uncertain"] is True
    s6 = sess.build(root6, doc, owner=OWNER, patch={}, keyframes={}, allow_in_flight=True)
    assert clip(s6, u)["uncertain"] is True, "重建保留标记"
    s6 = sess.queue_run(root6, [u])
    assert clip(s6, u)["state"] == "queued" and clip(s6, u)["uncertain"] is False
    print("16. 待核对段批量跳过、单段重做清除 ✓")

    # 17. 上次提交没写回任务 id（仍是「提交中」）：不再提交，转失败并标待核对
    root7 = Path(tmp.name) / "render" / "v7"
    s7 = sess.build(root7, doc, owner=OWNER, patch={}, keyframes={})
    w = s7["clips"][0]["id"]
    sess.queue_run(root7, [w])
    assert sess.begin_submit(root7, w) is not None
    assert sess.begin_submit(root7, w) is None
    c = clip(sess.load(root7), w)
    assert len(c["attempts"]) == 1 and c["attempts"][0]["state"] == "failed"
    assert c["state"] == "failed" and c["uncertain"] is True and c["error"] == msg("film.submit.interrupted")["message"]
    assert c["error_msg"]["code"] == "film.submit.interrupted"
    print("17. 提交中未写回不重复提交 ✓")

    # 18. 风格图：段记 style / style_hash；用旧风格图出完的段换图后标可重出（仍 done、不进剩余）
    root8 = Path(tmp.name) / "render" / "v8"
    s1 = {"source": "data:image/png;base64,AAAA", "hash": "h1"}
    s2 = {"source": "data:image/png;base64,BBBB", "hash": "h2"}
    b8 = lambda st: sess.build(root8, doc, owner=OWNER, patch={}, keyframes={}, style=st)  # noqa: E731
    s8 = b8(s1)
    assert all(c["style"] in ("used", "full", "first_frame") for c in s8["clips"])
    assert all(c["style_hash"] == ("h1" if c["style"] == "used" else None) for c in s8["clips"])
    x = next(c["id"] for c in s8["clips"] if c["style"] == "used")
    sess.queue_run(root8, [x])
    finish(root8, fake, x, style_ref="h1")
    s8 = b8(s2)
    assert clip(s8, x)["state"] == "done" and clip(s8, x)["style_hash"] == "h2"
    v8 = sess.view(s8)
    assert next(c for c in v8["clips"] if c["id"] == x)["style_outdated"] is True
    assert v8["style_outdated_count"] == 1
    others = round(sum(c["estimate_cny"] for c in s8["clips"] if c["id"] != x), 2)
    assert v8["remaining_cny"] == others, "可重出的段不进剩余"
    v8 = sess.view(b8(s1))
    assert next(c for c in v8["clips"] if c["id"] == x)["style_outdated"] is False
    assert v8["style_outdated_count"] == 0
    v8 = sess.view(b8(None))
    assert all(c["style"] is None and c["style_outdated"] is False for c in v8["clips"])
    assert v8["style_outdated_count"] == 0
    # 旧会话的尝试没有 style_ref 键：现在有风格图就按可重出
    raw = sess.load(root8)
    for a in clip(raw, x)["attempts"]:
        a.pop("style_ref", None)
    sess._save(root8, raw)
    v8 = sess.view(b8(s1))
    assert next(c for c in v8["clips"] if c["id"] == x)["style_outdated"] is True
    print("18. 风格图记录与可重出 ✓")

    # 19. 提交时在尝试里记实际发出的图片张数；不传时不写
    root9 = Path(tmp.name) / "render" / "v9"
    s9 = sess.build(root9, doc, owner=OWNER, patch={}, keyframes={})
    cid = s9["clips"][0]["id"]
    sess.queue_run(root9, [cid])
    assert sess.begin_submit(root9, cid) is not None
    sess.submitted(root9, cid, "t-img", None, images=7)
    assert clip(sess.load(root9), cid)["attempts"][-1]["images"] == 7
    print("19. 尝试记录图片张数 ✓")

    # 20. 声音模式按厂商能力过滤；换厂商时继承的旧模式回落 tts_all；只读刷新不改写；明确指定不支持的模式报错
    mute = FakeVideo(native_audio=False)
    mute.name = "mute"
    providers.register("mute", lambda: mute)
    tmp2 = tempfile.TemporaryDirectory()
    r2 = Path(tmp2.name) / "render" / "v"
    b2 = lambda **patch: sess.build(r2, doc, owner=OWNER, patch=patch, keyframes={})  # noqa: E731
    s = b2(audio_mode="all_native")
    assert s["provider"] == "fake" and s["audio_mode"] == "all_native"
    assert sess.view(s)["options"]["audio_modes"] == ["tts_all", "dialogue_native", "all_native", "silent"]
    s = b2(provider="mute")
    assert s["provider"] == "mute" and s["audio_mode"] == "tts_all", "换厂商时不支持的旧模式回落"
    assert sess.view(s)["options"]["audio_modes"] == ["tts_all", "silent"]
    e = must_raise(sess.SessionError, b2, audio_mode="dialogue_native")
    assert "全部配音" in str(e)
    # 只读刷新：旧会话里存着不支持的模式（例如手改、或厂商能力变了），patch 为空时不改写
    with sess.mutate(r2) as cur:
        cur["audio_mode"] = "all_native"
    s = b2()
    assert s["audio_mode"] == "all_native"
    assert json.loads((r2 / "session.json").read_text(encoding="utf-8"))["audio_mode"] == "all_native"
    print("20. 声音模式过滤与回落 ✓")

    # 21. default_note：会话是 seedance 且缺省发生回落时给代码，其余为 None（文案在前端）
    sd_fake = FakeVideo()
    sd_fake.name = "seedance"
    providers.register("seedance", lambda: sd_fake)
    saved_env = os.environ.pop("STORYBOARD_VIDEO_PROVIDER")
    real_has = providers._has_key
    try:
        providers._has_key = lambda n: n == "seedance"
        r3 = Path(tmp2.name) / "render" / "v3"
        s = sess.build(r3, doc, owner=OWNER, patch={}, keyframes={})
        assert s["provider"] == "seedance"
        assert sess.view(s)["options"]["default_note"] == "minimax_key_missing"
        providers._has_key = lambda n: True
        assert sess.view(s)["options"]["default_note"] is None, "配了 MiniMax 就不提示"
        assert sess.build(r3, doc, owner=OWNER, patch={}, keyframes={})["provider"] == "seedance", \
            "已有会话不迁移"
    finally:
        providers._has_key = real_has
        os.environ["STORYBOARD_VIDEO_PROVIDER"] = saved_env
        from render.providers import _seedance
        providers.register("seedance", _seedance)
    assert sess.view(sess.load(root))["options"]["default_note"] is None, "显式设置（fake）时不提示"
    print("21. 缺省回落提示与已有会话不迁移 ✓")

    # 22. 切到 minimax：默认档位与分辨率（不联网：只建会话，不提交）
    import httpx
    from render.providers.minimax import BASE_URL, MiniMax
    mmx = MiniMax("k", client=httpx.Client(base_url=BASE_URL,
                                           transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    providers.register("minimax", lambda: mmx)
    s = b2(provider="minimax")
    assert (s["provider"], s["model"], s["resolution"], s["audio_mode"]) == ("minimax", "minimax-h3", "768P", "tts_all")
    from render.providers import _minimax
    providers.register("minimax", _minimax)
    print("22. 切到 MiniMax 的默认设置 ✓")

    # 23. 错误对象持久化：error（中文兜底）加 error_msg（{code, params}）
    d = {"error": "x", "error_msg": {"code": "a", "params": {}}}
    sess.set_error(d, None)
    assert d == {"error": None, "error_msg": None}
    m = msg("film.run.nothing")
    sess.set_error(d, m)
    assert d["error"] == "没有要出的段" and d["error_msg"] == {"code": "film.run.nothing", "params": {}}
    se = sess.SessionError.of("film.run.busy", id="E01-C01")
    sess.set_error(d, se)
    assert d["error"] == "E01-C01 已在排队或生成中"
    assert d["error_msg"] == {"code": "film.run.busy", "params": {"id": "E01-C01"}}
    sess.set_error(d, "旧字符串")
    assert d == {"error": "旧字符串", "error_msg": None}
    sess.set_error(d, msg("film.run.nothing"))
    assert "ref" not in d["error_msg"], "不带编号的消息不写 ref"
    sess.set_error(d, with_ref(msg("film.submit.crashed"), "K7Q2M9XD"))
    assert d["error_msg"] == {"code": "film.submit.crashed", "params": {}, "ref": "K7Q2M9XD"}, d
    assert d["error"].endswith("（参考编号 K7Q2M9XD）"), d["error"]
    d3 = {}
    sess.copy_error(d3, d)
    assert d3["error_msg"]["ref"] == "K7Q2M9XD" and d3["error"] == d["error"]
    d2 = {}
    sess.set_error(d, se)
    sess.copy_error(d2, d)
    assert d2["error"] == d["error"] and d2["error_msg"] == d["error_msg"]

    # 23.2 超上限的段带代码
    root9 = Path(tmp.name) / "render" / "ev9"
    s9 = sess.build(root9, doc, owner=OWNER, patch={}, keyframes={})
    k = s9["clips"][0]["id"]
    sess.queue_run(root9, [k])
    with sess.mutate(root9) as m9:
        m9["budget_cny"] = 0.001
    assert sess.begin_submit(root9, k) is None
    c = clip(sess.load(root9), k)
    assert c["error_msg"]["code"] == "film.submit.over_budget" and "超出单章上限" in c["error"]

    # 23.3 提交中断恢复：段与尝试都带代码
    root10 = Path(tmp.name) / "render" / "ev10"
    s10 = sess.build(root10, doc, owner=OWNER, patch={}, keyframes={})
    k = s10["clips"][0]["id"]
    sess.queue_run(root10, [k])
    assert sess.begin_submit(root10, k) is not None
    sess.recover(root10)
    c = clip(sess.load(root10), k)
    assert c["error_msg"]["code"] == "film.submit.interrupted"
    assert c["attempts"][-1]["error_msg"]["code"] == "film.submit.interrupted"

    # 23.4 重建保留失败段的 error_msg；23.5 重出成功后两个字段都清空
    root11 = Path(tmp.name) / "render" / "ev11"
    s11 = sess.build(root11, doc, owner=OWNER, patch={}, keyframes={})
    k = s11["clips"][0]["id"]
    sess.queue_run(root11, [k])
    sess.begin_submit(root11, k)
    sess.submit_failed(root11, k, msg("film.submit.build_failed", cause=vendor("boom")))
    c = clip(sess.load(root11), k)
    assert c["error_msg"]["code"] == "film.submit.build_failed" and "boom" in c["error"]
    s11 = sess.build(root11, doc, owner=OWNER, patch={}, keyframes={})
    c = clip(s11, k)
    assert c["state"] == "failed" and c["error_msg"]["code"] == "film.submit.build_failed", c
    sess.queue_run(root11, [k])
    c = clip(sess.load(root11), k)
    assert c["error"] is None and c["error_msg"] is None
    sess.begin_submit(root11, k)
    sess.submit_failed(root11, k, "旧写法字符串")
    c = clip(sess.load(root11), k)
    assert c["error"] == "旧写法字符串" and c["error_msg"] is None
    sess.queue_run(root11, [k])
    finish(root11, fake, k)
    c = clip(sess.load(root11), k)
    assert c["state"] == "done" and c["error"] is None and c["error_msg"] is None

    # 23.5b 采用成功的那次：段上遗留的 error / error_msg 清空，失败尝试自己的记录保留
    root13 = Path(tmp.name) / "render" / "ev13"
    s13 = sess.build(root13, doc, owner=OWNER, patch={}, keyframes={})
    k = s13["clips"][0]["id"]
    sess.queue_run(root13, [k])
    finish(root13, fake, k)
    sess.queue_run(root13, [k])
    sess.begin_submit(root13, k)
    sess.submit_failed(root13, k, msg("film.submit.build_failed", cause=vendor("boom")))
    c = clip(sess.load(root13), k)
    assert c["state"] == "failed" and c["error_msg"]
    c = clip(sess.set_chosen(root13, k, 0), k)
    assert c["state"] == "done" and c["error"] is None and c["error_msg"] is None
    assert c["attempts"][-1]["error_msg"]["code"] == "film.submit.build_failed"

    # 23.6 queue_run 超确认线
    root12 = Path(tmp.name) / "render" / "ev12"
    s12 = sess.build(root12, doc, owner=OWNER, patch={}, keyframes={})
    e = must_raise(sess.Conflict, sess.queue_run, root12, None)
    total = e.expected_cny
    assert e.code == "film.run.confirm" and e.params["amount"] == {"t": "money", "cny": total}, e.params
    assert "请确认金额后再出片" in str(e)

    # 23.7 未知分辨率
    e = must_raise(sess.SessionError, build, resolution="4k")
    assert e.code == "film.settings.bad_resolution" and isinstance(e.params["options"], list)
    e = must_raise(sess.SessionError, build, provider="nope")
    assert e.code == "film.settings.no_model", e.code
    with _LogGrab("render.session") as g:
        e = must_raise(sess.SessionError, build, model="nope-tier")
    assert e.code == "film.settings.no_model" and e.params == {} and "nope-tier" not in str(e), (e.code, e.params)
    assert any("nope-tier" in x and "fake" in x for x in g.lines), g.lines
    with _LogGrab("render.session") as g:
        must_raise(sess.SessionError, build, model="Bearer FAKE_TOKEN")
    assert g.lines and not any("FAKE_TOKEN" in x for x in g.lines), g.lines
    print("23. 错误对象持久化 ✓")
    # 24. 合成状态带代码
    root14 = Path(tmp.name) / "render" / "ev14"
    sess.build(root14, doc, owner=OWNER, patch={}, keyframes={})
    sess.begin_compose(root14, fingerprint="fp", tts_cny=0, draft=True)
    f = sess.load(root14)["final"]
    assert f["step"] == "开始" and f["step_msg"] == {"code": "compose.step.start", "params": {}}
    assert f["error"] is None and f["error_msg"] is None
    e = must_raise(sess.Conflict, sess.begin_compose, root14, fingerprint="fp", tts_cny=0, draft=True)
    assert e.code == "compose.busy" and str(e) == "正在合成，等它结束再合成"
    sess.compose_progress(root14, msg("compose.step.voice", n=3))
    f = sess.load(root14)["final"]
    assert f["step"] == "配音 3 条" and f["step_msg"] == {"code": "compose.step.voice", "params": {"n": 3}}
    sess.compose_progress(root14, "旧字符串")
    f = sess.load(root14)["final"]
    assert f["step"] == "旧字符串" and f["step_msg"] is None
    sess.compose_failed(root14, msg("compose.no_video", id="E01-C01"), "d")
    f = sess.load(root14)["final"]
    assert f["state"] == "failed" and f["error_msg"] == {"code": "compose.no_video", "params": {"id": "E01-C01"}}
    assert "E01-C01 还没有可用的视频" in f["error"]
    sess.compose_failed(root14, "纯字符串")
    f = sess.load(root14)["final"]
    assert f["error"] == "纯字符串" and f["error_msg"] is None
    sess.compose_failed(root14, sess.Conflict.of("compose.busy"))
    assert sess.load(root14)["final"]["error_msg"] == {"code": "compose.busy", "params": {}}
    sess.begin_compose(root14, fingerprint="fp", tts_cny=0, draft=True)
    sess.compose_done(root14, ["final/E01.mp4"], "final/mix_report.json")
    f = sess.load(root14)["final"]
    assert f["state"] == "done" and f["step"] == "完成" and f["step_msg"] == {"code": "compose.step.done", "params": {}}
    assert f["error"] is None and f["error_msg"] is None
    e = must_raise(sess.Conflict, sess.begin_compose, root14, fingerprint="fp", tts_cny=0, draft=True,
                   voices={"x": "y"})
    assert e.code == "compose.voices_changed" and e.expected_cny is None and "音色刚被改过" in str(e)
    e = must_raise(sess.BudgetExceeded, sess.begin_compose, root14, fingerprint="fp", tts_cny=9999, draft=True)
    assert e.code == "compose.over_budget" and e.params == {
        "budget": {"t": "money", "cny": 200.0}, "spent": {"t": "money", "cny": 0.0},
        "cost": {"t": "money", "cny": 9999.0}}, e.params
    assert str(e) == "超出上限 ¥200.00：已花 ¥0.00，本次配音约 ¥9999.00"
    with sess.mutate(root14) as s_:
        s_["clips"][0]["state"] = "running"
    e = must_raise(sess.Conflict, sess.begin_compose, root14, fingerprint="fp", tts_cny=0, draft=True)
    assert e.code == "compose.clips_busy"
    with sess.mutate(root14) as s_:
        s_["clips"][0]["state"] = "planned"
        s_["final"]["state"] = "running"
    sess.recover_compose(root14)
    f = sess.load(root14)["final"]
    assert f["state"] == "failed" and f["error_msg"] == {"code": "compose.interrupted", "params": {}}
    assert f["error"].startswith("合成时服务中断")
    assert not hasattr(sess, "COMPOSE_INTERRUPTED")
    print("24. 合成状态带代码 ✓")

    tmp2.cleanup()

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
