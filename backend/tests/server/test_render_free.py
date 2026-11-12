#!/usr/bin/env python3
"""自由节点接口：新建与派生、修改与校验、生成（确认线、出片线程按节点组装请求、取文件）、挂靠段复制与采用、
删除与引用保护、有节点在跑时删版本被拒、编号不复用。

全程临时数据目录 + 假厂商，不联网、不花钱。用法: python3 tests/server/test_render_free.py
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
os.environ["STORYBOARD_RENDER_RUNNER"] = "0"     # 不起后台线程，测试里手动 tick

from fastapi.testclient import TestClient  # noqa: E402
from render import providers  # noqa: E402
from render.providers.fake import FAKE_MP4, FakeVideo  # noqa: E402
from server import app as app_mod  # noqa: E402
from server import auth, novels  # noqa: E402

FAKE = FakeVideo()
providers.register("fake", lambda: FAKE)


def rich(doc):
    d = copy.deepcopy(doc)
    for kind in ("characters", "creatures", "props"):
        for card in d["assets"].get(kind) or []:
            card["reference_images"] = [{"view": "front", "uri": f"https://img/{card['id']}.png"}]
    for card in d["assets"]["locations"]:
        for a in card.get("angles") or []:
            a["uri"] = f"https://img/{card['id']}-{a['angle']}.png"
    return d


DOC = rich(json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8")))


def drain(limit=3000):
    runner = app_mod._render_runner
    for _ in range(limit):
        if not runner.watching():
            return
        runner.tick()
    raise AssertionError("出片线程没跑完")


def pick(s, iid):
    return next(x for x in s["clips"] + s["free"] if x["id"] == iid)


def main() -> int:
    app_mod._render_runner.sleep = lambda _s: None
    c = TestClient(app_mod.app)
    uid = auth.register("bob", "secret1")["id"]
    H = {"Authorization": f"Bearer {auth.issue_token(uid)}"}
    nid = novels.create_novel(uid, "药")["id"]
    cid = novels.create_chapter(uid, nid, "第一章", text="原文")["id"]
    novels.create_version(uid, nid, cid, "v1", {}, "原文")
    novels.update_version_state(uid, nid, cid, "v1", "succeeded", result=copy.deepcopy(DOC))
    V = f"/novels/{nid}/chapters/{cid}/versions/v1"
    R = V + "/render"

    # 1. 没有会话 404；建会话后新建空白节点、派生；派生不存在的段 404
    assert c.post(R + "/free", headers=H, json={}).status_code == 404
    s = c.post(R + "/session", headers=H, json={}).json()
    assert s["free"] == [] and s["options"]["first_frame"] is True
    r = c.post(R + "/free", headers=H, json={})
    assert r.status_code == 200, r.text
    f1 = pick(r.json(), "F01")
    assert f1["target"] is None and f1["over_refs"] is False
    x = next(cl for cl in s["clips"] if cl["refs"])
    r = c.post(R + "/free", headers=H, json={"from_clip": x["id"]})
    f2 = pick(r.json(), "F02")
    assert f2["target"] == x["id"] and f2["refs"] == x["refs"]
    assert c.post(R + "/free", headers=H, json={"from_clip": "E99-C01"}).status_code == 404
    print("1. 新建与派生 ✓")

    # 2. 修改：只改传了的字段；显式传 null 清掉挂靠；校验不过 422；挂靠时改时长 422；不存在 404
    char = DOC["assets"]["characters"][0]["id"]
    r = c.patch(R + "/free/F01", headers=H, json={"prompt": "空镜：河面", "refs": [char]})
    assert r.status_code == 200, r.text
    assert pick(r.json(), "F01")["prompt"] == "空镜：河面" and pick(r.json(), "F01")["refs"] == [char]
    assert c.patch(R + "/free/F01", headers=H, json={"refs": ["ZZ"]}).status_code == 422
    assert c.patch(R + "/free/F02", headers=H, json={"duration": 3}).status_code == 422
    r = c.patch(R + "/free/F02", headers=H, json={"target": None})
    assert pick(r.json(), "F02")["target"] is None
    assert c.patch(R + "/free/F09", headers=H, json={"prompt": "x"}).status_code == 404
    print("2. 修改 ✓")

    # 3. 生成：没写提示词 422；超确认线 409 带金额；带上金额排队；出片线程按节点组装请求；取文件
    c.post(R + "/free", headers=H, json={})                         # F03 空白
    assert c.post(R + "/free/F03/run", headers=H, json={}).status_code == 422
    assert c.patch(R + "/session", headers=H, json={"confirm_over_cny": 1}).status_code == 200
    r = c.post(R + "/free/F01/run", headers=H, json={})
    assert r.status_code == 409, r.text
    cny = r.json()["detail"]["expected_cny"]
    r = c.post(R + "/free/F01/run", headers=H, json={"expected_cny": cny})
    assert r.status_code == 200 and pick(r.json(), "F01")["state"] == "queued", r.text
    drain()
    s = c.get(R + "/session", headers=H).json()
    f = pick(s, "F01")
    assert f["state"] == "done" and FAKE.submitted[-1].prompt.startswith("空镜：河面\n【参考】")
    assert c.get(R + "/files/" + f["attempts"][0]["file"], headers=H).content == FAKE_MP4
    print("3. 生成 ✓")

    # 4. 挂靠节点：成功后复制进目标段，用现有采用接口设为采用 → 该段 done；节点自身的采用
    r = c.patch(R + "/free/F02", headers=H, json={"target": x["id"]})
    r = c.post(R + "/free/F02/run", headers=H, json={"expected_cny": pick(r.json(), "F02")["estimate_cny"]})
    assert r.status_code == 200, r.text
    drain()
    cx = pick(c.get(R + "/session", headers=H).json(), x["id"])
    k = next(i for i, a in enumerate(cx["attempts"]) if a.get("free_id") == "F02")
    r = c.put(R + f"/clips/{x['id']}/chosen", headers=H, json={"attempt": k})
    assert r.status_code == 200 and pick(r.json(), x["id"])["state"] == "done", r.text
    assert c.put(R + "/free/F02/chosen", headers=H, json={"attempt": 5}).status_code == 422
    assert c.put(R + "/free/F02/chosen", headers=H, json={"attempt": 0}).status_code == 200
    print("4. 挂靠与采用 ✓")

    # 5. 删除：被当尾帧来源 409；有节点在跑时删版本 409；删除后编号不复用
    assert c.patch(R + "/free/F03", headers=H, json={"first_frame": "tail:F01"}).status_code == 200
    assert c.delete(R + "/free/F01", headers=H).status_code == 409
    c.patch(R + "/free/F03", headers=H, json={"first_frame": None, "prompt": "接着拍"})
    est = pick(c.get(R + "/session", headers=H).json(), "F03")["estimate_cny"]
    assert c.post(R + "/free/F03/run", headers=H, json={"expected_cny": est}).status_code == 200
    r = c.delete(V, headers=H)
    assert r.status_code == 409 and "还有片段在出" in r.json()["detail"], r.text
    drain()
    r = c.delete(R + "/free/F03", headers=H)
    assert r.status_code == 200 and all(n["id"] != "F03" for n in r.json()["free"])
    r = c.post(R + "/free", headers=H, json={})
    assert r.json()["free"][-1]["id"] == "F04"
    print("5. 删除 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
