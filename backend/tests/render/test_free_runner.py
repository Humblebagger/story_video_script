#!/usr/bin/env python3
"""出片线程推进自由节点：只有自由节点在跑时不被丢下、与剧本段共用并发上限、请求按节点组装、
复查不过记失败不提交、重启续上。用法: python3 tests/render/test_free_runner.py
"""
import copy
import json
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

from render import compose, free, providers, session as sess  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402
from render.runner import Runner  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao" / "output_merged.json"
OWNER = {"user_id": "u", "nid": "n", "cid": "c", "vid": "v"}


def rich(doc):
    d = copy.deepcopy(doc)
    for kind in ("characters", "creatures", "props"):
        for card in d["assets"].get(kind) or []:
            card["reference_images"] = [{"view": "front", "uri": f"https://img/{card['id']}.png"}]
    for card in d["assets"]["locations"]:
        for a in card.get("angles") or []:
            a["uri"] = f"https://img/{card['id']}-{a['angle']}.png"
    return d


def drain(rn, limit=50):
    for _ in range(limit):
        if not rn.watching():
            return
        rn.tick()
    raise AssertionError("没跑完")


def main() -> int:
    plain = json.loads(YAO.read_text(encoding="utf-8"))
    doc = rich(plain)
    current = {"doc": doc}
    fake = FakeVideo()
    providers.register("fake", lambda: fake)
    tmp = tempfile.TemporaryDirectory()
    data = Path(tmp.name)
    root = data / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "v"
    s = sess.build(root, doc, owner=OWNER, patch={"budget_cny": 100000}, keyframes={})
    ctx = free.Ctx(doc, {}, False)
    char = doc["assets"]["characters"][0]["id"]

    def builder(r, s_now, c):
        caps = fake.caps(s_now["model"])
        if sess.is_free(c["id"]):
            return compose.request_for_free(current["doc"], s_now, c, keyframes={},
                                            tail_frame=free.tail_frame(r, s_now, c), caps=caps,
                                            rewrite=fake.rewrite_prompt)
        return compose.request_for(current["doc"], s_now, c, keyframes={},
                                   relay_frame=sess.relay_frame(r, s_now, c), caps=caps,
                                   rewrite=fake.rewrite_prompt)

    def node(fid="F01"):
        return next(n for n in sess.load(root)["free"] if n["id"] == fid)

    runner = Runner(builder, sleep=lambda _s: None, max_parallel=1)

    # 1. 只有一个自由节点在跑：每轮都还盯着，直到下载完；请求是节点的正文 + 参考行
    free.create(root, ctx)
    free.update(root, ctx, "F01", {"prompt": "空镜：河面起雾", "refs": [char]})
    free.queue(root, ctx, "F01")
    runner.watch(root)
    runner.tick()
    assert node()["state"] == "running" and runner.watching() == [root], "提交后还在盯"
    drain(runner)
    assert node()["state"] == "done"
    req = fake.submitted[-1]
    assert req.prompt.startswith(f"空镜：河面起雾\n【参考】[参考{char}]") and [r.asset_id for r in req.refs] == [char]
    print("1. 只有自由节点在跑 ✓")

    # 2. 与剧本段共用并发上限：上限 1 时一轮只提交一个
    first = s["clips"][0]["id"]
    sess.queue_run(root, [first])
    free.queue(root, ctx, "F01")
    runner.watch(root)
    n0 = len(fake.submitted)
    runner.tick()
    assert len(fake.submitted) == n0 + 1
    now = sess.load(root)
    running = [x["id"] for x in sess.items(now) if x["state"] == "running"]
    assert len(running) == 1, running
    drain(runner)
    print("2. 共用并发上限 ✓")

    # 3. 复查不过：参考图被删 → 记失败、写明原因、不提交
    free.queue(root, ctx, "F01")
    current["doc"] = plain
    n0 = len(fake.submitted)
    runner.watch(root)
    runner.tick()
    f = node()
    assert f["state"] == "failed" and "参考图" in f["error"] and len(fake.submitted) == n0
    assert not f["error"].startswith("组装请求失败"), f["error"]
    assert f["error_msg"]["code"].startswith("film.free_invalid."), f["error_msg"]
    assert f["attempts"][-1]["error_msg"] == f["error_msg"]
    current["doc"] = doc
    print("3. 复查不过不提交 ✓")

    # 4. 重启续跑：自由节点生成中 → 新线程 recover 认得，接着查、接着下
    free.queue(root, ctx, "F01")
    runner.watch(root)
    runner.tick()
    assert node()["state"] == "running"
    runner2 = Runner(builder, sleep=lambda _s: None, max_parallel=1)
    assert runner2.recover(data) == 1 and runner2.watching() == [root]
    drain(runner2)
    assert node()["state"] == "done"
    print("4. 重启续跑 ✓")

    # 5. 厂商判失败：自由节点终态 failed，错误记下
    fake.fail_with = "内容审核未通过"
    free.queue(root, ctx, "F01")
    runner.watch(root)
    drain(runner)
    f = node()
    assert f["state"] == "failed" and "内容审核未通过" in (f["error"] or ""), f
    assert f["error_msg"]["code"] == "film.fake.failed", f["error_msg"]
    assert f["attempts"][-1]["error_msg"] == f["error_msg"]
    fake.fail_with = None
    print("5. 厂商失败记错误 ✓")

    # 6. 预估超过剩余预算：不提交，记失败
    free.queue(root, ctx, "F01")
    with sess.mutate(root) as sm:          # 排队后上限被调低：线程提交前的最后一道检查要拦住
        sm["budget_cny"] = sm["spent_cny"] + 0.01
    n0 = len(fake.submitted)
    runner.watch(root)
    runner.tick()
    f = node()
    assert f["state"] == "failed" and "超出" in (f["error"] or "") and len(fake.submitted) == n0, f
    print("6. 超预算不提交 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
