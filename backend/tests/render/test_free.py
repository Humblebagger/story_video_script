#!/usr/bin/env python3
"""自由节点（会话侧）：旧会话兼容、统一遍历与查找、build 保留与挂靠同步、迁移函数、重启恢复、合成互锁与上限。
后续任务在这里追加：新建、派生、修改、删除、排队与采用；挂靠节点下载后复制进目标段。

全程临时目录 + 假厂商，不联网、不花钱。用法: python3 tests/render/test_free.py
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

from render import compose, free, providers, session as sess  # noqa: E402
from render.providers import base  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao" / "output_merged.json"
OWNER = {"user_id": "u", "nid": "n", "cid": "c", "vid": "v"}
DOC = json.loads(YAO.read_text(encoding="utf-8"))
FAKE = FakeVideo()
providers.register("fake", lambda: FAKE)
_TMP = tempfile.TemporaryDirectory()


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def rich(doc):
    """给资产卡补上可用的参考图（http 地址），参考位才有图可用。"""
    d = copy.deepcopy(doc)
    for kind in ("characters", "creatures", "props"):
        for card in d["assets"].get(kind) or []:
            card["reference_images"] = [{"view": "front", "uri": f"https://img/{card['id']}.png"}]
    for card in d["assets"]["locations"]:
        for a in card.get("angles") or []:
            a["uri"] = f"https://img/{card['id']}-{a['angle']}.png"
    return d


def new_root(name):
    return Path(_TMP.name) / name / "render" / "v"


def build(root, doc=DOC, allow_in_flight=False, **patch):
    return sess.build(root, doc, owner=OWNER, patch=patch, keyframes={}, allow_in_flight=allow_in_flight)


def node(fid="F01", **over):
    n = {"id": fid, "target": None, "target_shots": None, "target_lost": False, "prompt": "雨夜街头，一盏路灯",
         "refs": [], "first_frame": None, "duration": 4.0, "estimate_cny": 4.0, "state": "planned",
         "error": None, "uncertain": False, "attempts": [], "chosen": None,
         "created_at": "2026-11-11T00:00:00+00:00"}
    n.update(over)
    return n


def put_free(root, *nodes, seq=None):
    """直接写会话里的自由节点（不经接口），测试会话侧的行为。"""
    with sess.mutate(root) as s:
        s["free"] = list(nodes)
        s["free_seq"] = len(nodes) if seq is None else seq


def item(s, iid):
    return next(x for x in sess.items(s) if x["id"] == iid)


def finish(root, iid):
    """不经出片线程把一条（已排队的段或自由节点）走完：提交 → 成功 → 下载。返回任务 id。"""
    snap = sess.begin_submit(root, iid)
    assert snap is not None, iid
    s = sess.load(root)
    req = base.ClipRequest(prompt=snap["prompt"], model=s["model"], duration=snap["duration"],
                           resolution=s["resolution"])
    tid = FAKE.submit(req)
    sess.submitted(root, iid, tid, None)
    st = FAKE.poll(tid)
    sess.poll_update(root, iid, st)
    files = FAKE.download(st, sess.clip_dest(root, iid, tid))
    sess.downloaded(root, iid, files, FAKE.cost(st, req))
    return tid


def part_session():
    root = new_root("session")
    caps = FAKE.caps("fake-1")

    # 1. 旧会话没有 free：读出来补空列表；视图带 free、free_seq 与厂商能力
    s = build(root)
    assert s["free"] == [] and s["free_seq"] == 0
    with sess.mutate(root) as raw:
        raw.pop("free")
        raw.pop("free_seq")
    s = build(root)
    assert s["free"] == [] and s["free_seq"] == 0
    v = sess.view(s)
    assert v["free"] == [] and v["free_seq"] == 0
    assert v["options"]["first_frame"] is True and v["options"]["frame_with_refs"] is False
    print("1. 旧会话兼容 ✓")

    # 2. 统一遍历与按 id 查找
    first, second = s["clips"][0], s["clips"][1]
    put_free(root, node("F01"), node("F02", state="queued"))
    s = sess.load(root)
    assert [x["id"] for x in sess.items(s)][-2:] == ["F01", "F02"]
    assert sess.any_in_flight(s) and sess.is_free("F01") and not sess.is_free(first["id"])
    assert sess._item(s, "F02")["state"] == "queued" and sess._item(s, first["id"])["id"] == first["id"]
    must_raise(sess.NotFound, sess._item, s, "F09")
    print("2. 统一遍历 ✓")

    # 3. build 保留 free 与序号；挂靠节点时长跟随目标段；在跑的节点原样不动；有节点在跑时不能改设置
    put_free(root, node("F01", target=first["id"], target_shots=list(first["shots"]), duration=1.0),
             node("F02", state="queued", target="E99-C01", target_shots=["X"]), seq=7)
    s = build(root, allow_in_flight=True)
    f1, f2 = item(s, "F01"), item(s, "F02")
    assert s["free_seq"] == 7
    assert f1["duration"] == first["duration"]
    assert f1["estimate_cny"] == base.estimate_cny(first["duration"], caps, "720p")
    assert f2["target"] == "E99-C01" and not f2["target_lost"], "在跑的节点不动"
    must_raise(sess.Conflict, build, root, resolution="480p")
    print("3. build 保留与同步 ✓")

    # 4. 目标段消失或同 id 换了镜头 → 转独立素材；改分辨率重算预估
    put_free(root, node("F01", target="E99-C01", target_shots=["X"]),
             node("F02", target=first["id"], target_shots=["E01-SH999"]),
             node("F03", target=second["id"], target_shots=list(second["shots"])))
    s = build(root)
    assert item(s, "F01")["target"] is None and item(s, "F01")["target_lost"]
    assert item(s, "F02")["target"] is None and item(s, "F02")["target_lost"], "同 id 换了镜头也算没了"
    assert item(s, "F03")["target"] == second["id"] and not item(s, "F03")["target_lost"]
    s = build(root, resolution="480p")
    assert item(s, "F01")["estimate_cny"] == base.estimate_cny(4.0, caps, "480p")
    build(root, resolution="720p")
    print("4. 目标段消失 ✓")

    # 5. 视图：在跑预留含自由节点；参考位超限标记；计数只看剧本段
    put_free(root, node("F01", state="queued", estimate_cny=3.0),
             node("F02", refs=["a", "b", "c"], first_frame="keyframe:x"))
    v = sess.view(sess.load(root))
    assert v["reserved_cny"] == 3.0
    assert [x["over_refs"] for x in v["free"]] == [False, True]
    assert "queued" not in v["counts"], "计数只看剧本段"
    assert not [c["id"] for c in sess._remaining(sess.load(root)) if c["id"].startswith("F")]
    print("5. 视图 ✓")

    # 6. 迁移函数按 id 也认自由节点：提交、轮询、下载；文件按节点 id 命名；花费计入已花
    put_free(root, node("F01", state="queued"))
    spent0 = sess.load(root)["spent_cny"]
    tid = finish(root, "F01")
    s = sess.load(root)
    f = item(s, "F01")
    assert f["state"] == "done" and f["chosen"] == 0 and f["attempts"][0]["fingerprint"] is None
    assert f["attempts"][0]["file"] == f"clips/F01.{tid}.mp4" and (root / f["attempts"][0]["file"]).is_file()
    assert s["spent_cny"] == round(spent0 + f["attempts"][0]["cost_cny"], 2) > spent0
    print("6. 迁移函数 ✓")

    # 7. 重启恢复：自由节点提交中断标失败、待核对；有自由节点在排队时报告还要续
    put_free(root, node("F01", state="queued"), node("F02", state="queued"))
    assert sess.begin_submit(root, "F01") is not None      # 提交中断：没拿到任务 id
    assert sess.recover(root) is True, "F02 还在排队"
    f1 = item(sess.load(root), "F01")
    assert f1["state"] == "failed" and f1["uncertain"] and f1["attempts"][-1]["state"] == "failed"
    put_free(root, node("F01"))
    assert sess.recover(root) is False
    print("7. 重启恢复 ✓")

    # 8. 互锁：有自由节点在跑时不能合成；排队剧本段的上限算上在跑的自由节点
    put_free(root, node("F01", state="queued", estimate_cny=150.0))
    must_raise(sess.Conflict, sess.begin_compose, root, fingerprint="fp", tts_cny=0.0, draft=True)
    put_free(root, seq=1)
    est = item(sess.load(root), first["id"])["estimate_cny"]
    build(root, budget_cny=150 + est - 0.01)
    put_free(root, node("F01", state="queued", estimate_cny=150.0))
    must_raise(sess.BudgetExceeded, sess.queue_run, root, [first["id"]])
    put_free(root, node("F01", estimate_cny=150.0))
    assert item(sess.queue_run(root, [first["id"]]), first["id"])["state"] == "queued"
    print("8. 合成互锁与上限 ✓")


def part_crud():
    root = new_root("crud")
    doc = rich(DOC)
    s = build(root, doc)
    ctx = free.Ctx(doc, {}, False)
    caps = FAKE.caps("fake-1")
    clips = s["clips"]
    with_refs = next(c for c in clips if c["refs"])
    ids = [c["id"] for c in doc["assets"]["characters"]]

    # 9. 新建空白节点：编号递增，默认 5 秒、带预估
    s = free.create(root, ctx)
    f1 = item(s, "F01")
    assert (f1["target"], f1["prompt"], f1["refs"], f1["duration"], f1["state"]) == (None, "", [], 5.0, "planned")
    assert f1["estimate_cny"] == base.estimate_cny(5.0, caps, "720p") and s["free_seq"] == 1
    print("9. 新建 ✓")

    # 10. 派生：预填正文（去掉参考行与占位）、参考、时长、挂靠
    assert free.derive_prompt("雨夜\n【参考】@图片1 角色\n【首帧】{ref:__first__} 开场\n他看向@图片2 的方向") \
        == "雨夜\n他看向 的方向"
    s = free.create(root, ctx, with_refs["id"])
    f2 = item(s, "F02")
    assert f2["target"] == with_refs["id"] and f2["target_shots"] == with_refs["shots"]
    assert f2["refs"] == with_refs["refs"] and f2["duration"] == with_refs["duration"]
    assert f2["prompt"] and "【参考】" not in f2["prompt"] and "[参考" not in f2["prompt"]
    must_raise(sess.NotFound, free.create, root, ctx, "E99-C01")
    print("10. 派生 ✓")

    # 11. 派生时接力换成尾帧：上一段还没出 → 不带；出完 → tail:<上一段>
    root2 = new_root("relay")
    s2 = build(root2)
    relay = next(c for c in s2["clips"] if (c.get("first_frame") or "").startswith("relay:"))
    prev = relay["first_frame"][len("relay:"):]
    ctx2 = free.Ctx(DOC, {}, False)
    assert item(free.create(root2, ctx2, relay["id"]), "F01")["first_frame"] is None
    sess.queue_run(root2, [prev])
    finish(root2, prev)
    assert item(free.create(root2, ctx2, relay["id"]), "F02")["first_frame"] == f"tail:{prev}"
    print("11. 接力换尾帧 ✓")

    # 12. 修改与校验：不合法整条不写
    s = free.update(root, ctx, "F01", {"prompt": "雨夜街头", "refs": with_refs["refs"][:1]})
    assert item(s, "F01")["prompt"] == "雨夜街头" and item(s, "F01")["refs"] == with_refs["refs"][:1]
    for bad in ({"refs": ["ZZ"]}, {"refs": [ids[0], ids[0]]}, {"refs": ids[:4]}, {"refs": [compose.STYLE_ID]},
                {"first_frame": f"keyframe:{clips[0]['shots'][0]}"}, {"first_frame": "tail:F01"},
                {"first_frame": f"tail:{clips[0]['id']}"}, {"first_frame": "foo"},
                {"duration": 0.5}, {"duration": 11}, {"prompt": "长" * 2001}, {"bogus": 1}):
        must_raise(sess.SessionError, free.update, root, ctx, "F01", bad)
    must_raise(sess.SessionError, free.update, root, free.Ctx(DOC, {}, False), "F01", {"refs": [ids[0]]})
    assert item(sess.load(root), "F01")["prompt"] == "雨夜街头", "校验不过不写"
    s = free.update(root, free.Ctx(doc, {}, True), "F01", {"refs": [compose.STYLE_ID]})
    assert item(s, "F01")["refs"] == [compose.STYLE_ID]
    kshot = clips[0]["shots"][0]
    s = free.update(root, free.Ctx(doc, {kshot: "/kf.png"}, False), "F01", {"first_frame": f"keyframe:{kshot}"})
    assert item(s, "F01")["first_frame"] == f"keyframe:{kshot}"
    s = free.update(root, ctx, "F01", {"duration": 3})
    assert item(s, "F01")["duration"] == 3.0 and item(s, "F01")["estimate_cny"] == base.estimate_cny(3.0, caps, "720p")
    must_raise(sess.SessionError, free.update, root, ctx, "F02", {"duration": 3})   # 挂靠的跟随目标段
    s = free.update(root, ctx, "F01", {"target": with_refs["id"]})
    assert item(s, "F01")["duration"] == with_refs["duration"] and item(s, "F01")["target_shots"] == with_refs["shots"]
    s = free.update(root, ctx, "F01", {"target": None})
    assert item(s, "F01")["target"] is None
    must_raise(sess.NotFound, free.update, root, ctx, "F01", {"target": "E99-C01"})
    must_raise(sess.NotFound, free.update, root, ctx, "F09", {"prompt": "x"})
    print("12. 修改与校验 ✓")

    # 13. 排队：没写提示词不能生成；超确认线要带金额，金额不符重新确认；上限；在跑时不能再排、不能改、不能删；合成中不能生成
    free.create(root, ctx)                                              # F03 空白
    must_raise(sess.SessionError, free.queue, root, ctx, "F03")
    free.update(root, ctx, "F03", {"prompt": "空镜：河面", "duration": 10})
    with sess.mutate(root) as raw:
        raw["confirm_over_cny"] = 5.0
    e = must_raise(sess.Conflict, free.queue, root, ctx, "F03")
    total = item(sess.load(root), "F03")["estimate_cny"]
    assert e.expected_cny == total
    must_raise(sess.Conflict, free.queue, root, ctx, "F03", total + 1)
    with sess.mutate(root) as raw:
        raw["budget_cny"] = raw["spent_cny"] + total - 0.01
    must_raise(sess.BudgetExceeded, free.queue, root, ctx, "F03", total)
    with sess.mutate(root) as raw:
        raw["budget_cny"] = 100000.0
    s = free.queue(root, ctx, "F03", total)
    assert item(s, "F03")["state"] == "queued"
    must_raise(sess.Conflict, free.queue, root, ctx, "F03", total)
    must_raise(sess.Conflict, free.update, root, ctx, "F03", {"prompt": "改"})
    must_raise(sess.Conflict, free.delete, root, "F03")
    with sess.mutate(root) as raw:
        raw["final"] = {"state": "running"}
    must_raise(sess.Conflict, free.queue, root, ctx, "F01")
    with sess.mutate(root) as raw:
        raw["final"] = None
    print("13. 排队 ✓")

    # 14. 采用：只能采用成功的那次
    finish(root, "F03")
    assert item(free.set_chosen(root, "F03", 0), "F03")["chosen"] == 0
    must_raise(sess.SessionError, free.set_chosen, root, "F03", 3)
    print("14. 采用 ✓")

    # 15. 删除：被别的节点当尾帧来源时不能删；只删属于它自己的文件；编号不复用
    free.update(root, ctx, "F01", {"first_frame": "tail:F03"})
    must_raise(sess.Conflict, free.delete, root, "F03")
    free.update(root, ctx, "F01", {"first_frame": None})
    f3 = item(sess.load(root), "F03")
    own = root / f3["attempts"][0]["file"]
    with sess.mutate(root) as raw:          # 模拟已复制进剧本段的一次：共用同一文件
        raw["clips"][0]["attempts"].append(dict(f3["attempts"][0], free_id="F03", cost_cny=0.0))
    s = free.delete(root, "F03")
    assert "F03" not in [x["id"] for x in s["free"]] and own.is_file(), "共用的文件保留"
    s = free.create(root, ctx)
    assert s["free"][-1]["id"] == "F04" and s["free_seq"] == 4, "编号不复用"
    with sess.mutate(root) as raw:
        item(raw, "F04").update(prompt="x", state="queued")
    finish(root, "F04")
    a4 = item(sess.load(root), "F04")["attempts"][0]
    paths = [root / a4["file"], root / a4["last_frame"]]
    free.delete(root, "F04")
    assert not any(p.exists() for p in paths), "只属于它的文件一并删掉"
    print("15. 删除 ✓")

    # 16. 采用：重试失败后采用先前成功的那次 → 回到 done 并清错误
    free.create(root, ctx)
    fid = sess.load(root)["free"][-1]["id"]
    with sess.mutate(root) as raw:
        item(raw, fid).update(prompt="y", state="queued")
    finish(root, fid)
    with sess.mutate(root) as raw:
        n = item(raw, fid)
        n["attempts"].append({"state": "failed"})
        n.update(state="failed", error="boom")
    assert item(sess.load(root), fid)["state"] == "failed"
    n = item(free.set_chosen(root, fid, 0), fid)
    assert n["state"] == "done" and n["error"] is None and n["chosen"] == 0
    print("16. 采用后回到 done ✓")

    # 17. 删除：副本只共用尾帧时，尾帧也要保留
    with sess.mutate(root) as raw:
        raw["clips"][0]["attempts"].append(dict(item(raw, fid)["attempts"][0], file="elsewhere.mp4",
                                                free_id=fid, cost_cny=0.0))
    a = item(sess.load(root), fid)["attempts"][0]
    video, tail = root / a["file"], root / a["last_frame"]
    free.delete(root, fid)
    assert tail.is_file() and not video.exists(), "副本还在用的尾帧保留，其余删掉"
    print("17. 共用尾帧 ✓")


def part_deliver():
    root = new_root("deliver")
    doc = rich(DOC)
    s = build(root, doc)
    ctx = free.Ctx(doc, {}, False)
    x, y = s["clips"][0], s["clips"][1]

    # 16. 目标段空闲：复制追加到末尾，花费记 0、带 free_id、指纹为目标段当前指纹；不自动采用
    free.create(root, ctx, x["id"])
    free.update(root, ctx, "F01", {"prompt": "重拍"})
    free.queue(root, ctx, "F01")
    tid = finish(root, "F01")
    s = sess.load(root)
    cx = item(s, x["id"])
    cp = cx["attempts"][-1]
    assert cp["free_id"] == "F01" and cp["task_id"] == tid and cp["cost_cny"] == 0.0
    assert cp["fingerprint"] == cx["fingerprint"] and cx["chosen"] is None and cx["state"] == "planned"
    assert item(s, "F01")["attempts"][0]["cost_cny"] > 0
    s = sess.set_chosen(root, x["id"], len(cx["attempts"]) - 1)
    assert item(s, x["id"])["state"] == "done"
    print("16. 复制到空闲的目标段 ✓")

    # 17. 目标段在提交窗口（排队、最后一次是 submitting）或生成中：复制插在在跑那次之前，随后的写回落到真正那次
    sess.queue_run(root, [y["id"]])
    assert sess.begin_submit(root, y["id"]) is not None
    free.create(root, ctx, y["id"])                                     # F02
    free.update(root, ctx, "F02", {"prompt": "重拍二"})
    free.queue(root, ctx, "F02")
    finish(root, "F02")
    cy = item(sess.load(root), y["id"])
    assert [a.get("free_id") for a in cy["attempts"]] == ["F02", None]
    assert cy["attempts"][-1]["state"] == "submitting"
    s_now = sess.load(root)
    req = base.ClipRequest(prompt=cy["prompt"], model=s_now["model"], duration=cy["duration"],
                           resolution=s_now["resolution"])
    real = FAKE.submit(req)
    sess.submitted(root, y["id"], real, None)
    free.queue(root, ctx, "F02")
    finish(root, "F02")
    cy = item(sess.load(root), y["id"])
    assert [a.get("free_id") for a in cy["attempts"]] == ["F02", "F02", None]
    assert cy["attempts"][-1]["task_id"] == real
    st = FAKE.poll(real)
    sess.poll_update(root, y["id"], st)
    sess.downloaded(root, y["id"], FAKE.download(st, sess.clip_dest(root, y["id"], real)), FAKE.cost(st, req))
    cy = item(sess.load(root), y["id"])
    assert cy["chosen"] == 2 and cy["attempts"][2]["task_id"] == real and cy["attempts"][0]["free_id"] == "F02"
    assert cy["attempts"][0]["file"] != cy["attempts"][2]["file"]
    print("17. 提交窗口与生成中 ✓")

    # 18. 交付前目标段换了镜头：不复制，节点转独立素材
    free.create(root, ctx, x["id"])                                     # F03
    free.update(root, ctx, "F03", {"prompt": "三"})
    with sess.mutate(root) as raw:
        item(raw, "F03")["target_shots"] = ["E01-SH999"]
    n_before = len(item(sess.load(root), x["id"])["attempts"])
    free.queue(root, ctx, "F03")
    finish(root, "F03")
    s = sess.load(root)
    assert len(item(s, x["id"])["attempts"]) == n_before
    f3 = item(s, "F03")
    assert f3["target"] is None and f3["target_lost"] and f3["state"] == "done"
    print("18. 目标段变了不复制 ✓")

    # 19. 采用复制件的段不因风格图误报「可按新图重出」
    with sess.mutate(root) as raw:
        cx = item(raw, x["id"])
        cx["style"], cx["style_hash"] = "used", "h-new"
    v = sess.view(sess.load(root))
    assert not item(v, x["id"])["style_outdated"]
    print("19. 风格图不误报 ✓")

    # 20. 目标段下载中（clip 状态 downloading，最后一次尝试仍是 running）：复制照样插在它前面，
    #     随后的下载写回落到原来那次，复制件原样不动
    root = new_root("deliver-dl")
    doc = rich(DOC)
    s = build(root, doc)
    ctx = free.Ctx(doc, {}, False)
    z = s["clips"][0]
    sess.queue_run(root, [z["id"]])
    snap = sess.begin_submit(root, z["id"])
    s_now = sess.load(root)
    req = base.ClipRequest(prompt=snap["prompt"], model=s_now["model"], duration=snap["duration"],
                           resolution=s_now["resolution"])
    real = FAKE.submit(req)
    sess.submitted(root, z["id"], real, None)
    st = FAKE.poll(real)
    sess.poll_update(root, z["id"], st)
    cz = item(sess.load(root), z["id"])
    assert cz["state"] == "downloading" and cz["attempts"][-1]["state"] == "running"
    free.create(root, ctx, z["id"])                                     # F01
    free.update(root, ctx, "F01", {"prompt": "下载中重拍"})
    free.queue(root, ctx, "F01")
    finish(root, "F01")
    cz = item(sess.load(root), z["id"])
    assert [a.get("free_id") for a in cz["attempts"]] == ["F01", None]
    assert cz["attempts"][-1]["task_id"] == real and cz["attempts"][-1]["state"] == "running"
    copy_before = dict(cz["attempts"][0])
    sess.downloaded(root, z["id"], FAKE.download(st, sess.clip_dest(root, z["id"], real)), FAKE.cost(st, req))
    cz = item(sess.load(root), z["id"])
    assert cz["attempts"][-1]["state"] == "succeeded" and cz["attempts"][-1]["file"]
    assert cz["attempts"][-1]["task_id"] == real and cz["chosen"] == 1
    assert cz["attempts"][0] == copy_before and cz["attempts"][0]["free_id"] == "F01"
    print("20. 目标段下载中 ✓")


def part_image_counts():
    """估价调用点都把图片张数传给了 estimate_cny（FakeVideo 图片单价为 0，漏传不会改变金额，故用桩记录）。"""
    root = new_root("imgcount")
    doc = rich(DOC)
    s = build(root, doc)
    ctx = free.Ctx(doc, {}, False)
    with_refs = next(c for c in s["clips"] if c["refs"])
    seen = []
    real = base.estimate_cny
    base.estimate_cny = lambda d, c, r, images=0: (seen.append(images), real(d, c, r, images))[1]
    try:
        seen.clear()
        s = free.create(root, ctx, with_refs["id"])        # 派生：带参考
        assert seen[-1] == compose.image_count(item(s, "F01")) and seen[-1] >= 1
        seen.clear()
        s = free.update(root, ctx, "F01", {"refs": []})    # 修改：张数随参考变
        assert seen[-1] == 0
        s = free.update(root, ctx, "F01", {"refs": list(with_refs["refs"][:1])})
        assert seen[-1] == 1
        seen.clear()
        seen.clear()
        build(root, doc)                                    # 重建时 _sync_free 重算挂靠节点
        n = item(sess.load(root), "F01")
        assert compose.image_count(n) == 1 and seen[-1] == 1, "_sync_free 是 build 里最后一次估价"
    finally:
        base.estimate_cny = real
    print("21. 估价传图片张数 ✓")


def main() -> int:
    part_session()
    part_crud()
    part_deliver()
    part_image_counts()
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
