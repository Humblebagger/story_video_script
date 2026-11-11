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

from render import providers, session as sess  # noqa: E402
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


def main() -> int:
    part_session()
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
