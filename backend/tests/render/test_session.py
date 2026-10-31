#!/usr/bin/env python3
"""出片会话：建立与校验、沿用尝试与过期判定、排队确认与上限、提交前复查、采用与静音、接力、重启恢复。

用法: python3 tests/render/test_session.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"

from render import providers, session as sess  # noqa: E402
from render.providers import base  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402

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


def finish(root, fake, clip_id):
    """不经出片线程把一段走完：提交 → 成功 → 下载。"""
    snap = sess.begin_submit(root, clip_id)
    s = sess.load(root)
    req = base.ClipRequest(prompt=snap["prompt"], model=s["model"], duration=snap["duration"],
                           resolution=s["resolution"])
    tid = fake.submit(req)
    sess.submitted(root, clip_id, tid, None)
    st = fake.poll(tid)
    sess.poll_update(root, clip_id, st)
    files = fake.download(st, Path(root) / "clips" / f"{clip_id}.v{len(snap['attempts'])}.mp4")
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
    assert c["state"] == "done" and c["chosen"] == 0
    assert c["attempts"][0]["file"] == f"clips/{first}.v1.mp4"
    assert c["attempts"][0]["last_frame"] == f"clips/{first}.v1.last.jpg"
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
    assert sess.relay_frame(root, s, c2) == root / f"clips/{first}.v1.last.jpg"
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
    assert c["state"] == "failed" and "不确定厂商是否已受理" in c["error"]
    assert c["attempts"][-1]["state"] == "failed"
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
    s3 = b3(doc)
    assert [o["id"] for o in s3["orphaned"]] == gone
    s3 = b3(doc)
    assert [o["id"] for o in s3["orphaned"]] == gone
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

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
