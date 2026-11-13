#!/usr/bin/env python3
"""静帧预演：关键帧出图提示词 + 关键帧图的上传/取回/删除。用法: python3 tests/server/test_keyframes.py

全程使用临时数据目录，不碰真实 data/。
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* 之前
# 测试不读真实的 backend/.env：load_settings 里的 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None

from render.keyframes import keyframe_plan, shot_keyframe  # noqa: E402
from render.plan import assets_index  # noqa: E402
from server import novels  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao"
U = "a" * 12
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def main() -> int:
    doc = json.loads((YAO / "output_merged.json").read_text(encoding="utf-8"))
    shots = [s for ep in doc["episodes"] for s in ep["shots"]]

    # 1. 提示词：每镜一条；人物外貌服装、场景、道具状态取自资产卡；不含台词与运镜
    plan = keyframe_plan(doc)
    assert [k["shot_id"] for k in plan] == [s["id"] for s in shots], "每镜一条，顺序一致"
    k = plan[1]
    shot = shots[1]
    assert doc["meta"]["style"]["style_prefix"] in k["prompt"] and "电影静帧" in k["prompt"]
    assert shot["action"] in k["prompt"]
    c01 = doc["assets"]["characters"][0]
    assert c01["name"] in k["prompt"] and c01["appearance"]["face"] in k["prompt"], "人物外貌取自资产卡"
    assert c01["outfits"][0]["description"] in k["prompt"], "按镜头的 outfit 取服装"
    assert "纯白背景" not in k["prompt"], "资产设定图的「纯白背景」不能混进镜头画面"
    assert k["reference_assets"] == [c["ref"] for c in shot["characters"]] + [shot["location_ref"]]
    assert k["negative_prompt"].startswith(doc["meta"]["style"]["negative_prompt"])
    talky = next(s for s in shots if s.get("dialogue"))
    kt = shot_keyframe(talky, doc, assets_index(doc))
    assert talky["dialogue"][0]["text"] not in kt["prompt"], "静帧不写台词"
    prop_shot = next(s for s in shots if s.get("prop_refs") and s["prop_refs"][0].get("state"))
    pk = shot_keyframe(prop_shot, doc)
    card = next(p for p in doc["assets"]["props"] if p["id"] == prop_shot["prop_refs"][0]["ref"])
    state = next(st for st in card["states"] if st["id"] == prop_shot["prop_refs"][0]["state"])
    assert state["description"] in pk["prompt"], "道具按镜头里的状态描述"
    beat_shot = {**shots[0], "beats": [{"action": "第一拍动作", "duration_sec": 1}]}
    assert "画面：第一拍动作" in shot_keyframe(beat_shot, doc)["prompt"], "分拍的镜头取第一拍"
    constrained = {**shots[0], "constraints": ["不要出现人脸"]}
    assert shot_keyframe(constrained, doc)["negative_prompt"].endswith("不要出现人脸")
    print(f"提示词: {len(plan)} 镜 / 外貌服装场景道具取自资产卡 / 不写台词 / 分拍取首拍 / 负面约束 ✓")

    # 2. 关键帧图：挂在版本上；只收图片、限大小、镜头必须在这个版本里
    nid = novels.create_novel(U, "药")["id"]
    cid = novels.create_chapter(U, nid, "第一章")["id"]
    novels.create_version(U, nid, cid, "v1", {}, "")
    novels.update_version_state(U, nid, cid, "v1", "succeeded", result=doc)
    sid = shots[0]["id"]
    assert novels.list_keyframes(U, nid, cid, "v1") == []
    novels.save_keyframe(U, nid, cid, "v1", sid, "image/png", PNG)
    path, kind = novels.keyframe_file(U, nid, cid, "v1", sid)
    assert kind == "image/png" and path.read_bytes() == PNG
    novels.save_keyframe(U, nid, cid, "v1", sid, "image/jpeg; q=1", b"\xff\xd8jpeg")
    path, kind = novels.keyframe_file(U, nid, cid, "v1", sid)
    assert kind == "image/jpeg" and len(list(path.parent.iterdir())) == 1, "换图不留旧文件"
    assert novels.list_keyframes(U, nid, cid, "v1") == [sid]
    must_raise(novels.NovelError, novels.save_keyframe, U, nid, cid, "v1", sid, "text/html", b"<x>")
    must_raise(novels.NovelError, novels.save_keyframe, U, nid, cid, "v1", sid, "image/png",
               b"0" * (novels.KEYFRAME_MAX_BYTES + 1))
    must_raise(novels.NotFound, novels.save_keyframe, U, nid, cid, "v1", "E99-SH001", "image/png", PNG)
    must_raise(novels.NovelError, novels.save_keyframe, U, nid, cid, "v1", "../x", "image/png", PNG)
    novels.delete_keyframe(U, nid, cid, "v1", sid)
    must_raise(novels.NotFound, novels.keyframe_file, U, nid, cid, "v1", sid)
    print("关键帧图: 上传 / 换图 / 只收图片 / 限大小 / 镜头须在本版本 / 拦路径穿越 / 删除 ✓")

    # 3. 删版本连带删它的关键帧
    novels.create_version(U, nid, cid, "v2", {}, "")
    novels.update_version_state(U, nid, cid, "v2", "succeeded", result=doc)
    novels.adopt_version(U, nid, cid, "v2")
    novels.save_keyframe(U, nid, cid, "v1", sid, "image/png", PNG)
    novels.delete_version(U, nid, cid, "v1")
    assert not (novels._chapter_dir(U, nid, cid) / "keyframes" / "v1").exists()
    print("删版本: 关键帧一并清掉 ✓")

    # 4. 接口
    from fastapi import HTTPException
    from server import app as app_mod
    A = {"id": U}
    assert len(app_mod.render_keyframes(app_mod.KeyframesRequest(result=doc), A)["keyframes"]) \
        == len(shots)
    e = must_raise(HTTPException, app_mod.render_keyframes,
                   app_mod.KeyframesRequest(result={"episodes": [{"shots": [None]}]}), A)
    assert e.status_code == 422
    novels.save_keyframe(U, nid, cid, "v2", sid, "image/webp", b"RIFFwebp")
    assert app_mod.keyframes_list(nid, cid, "v2", A) == {"shots": [sid]}
    resp = app_mod.keyframes_get(nid, cid, "v2", sid, A)
    assert resp.media_type == "image/webp"
    e = must_raise(HTTPException, app_mod.keyframes_get, nid, cid, "v2", "E01-SH002", A)
    assert e.status_code == 404
    app_mod.keyframes_delete(nid, cid, "v2", sid, A)
    e = must_raise(HTTPException, app_mod.keyframes_list, nid, cid, "nope", A)
    assert e.status_code == 404
    print("接口: 提示词 / 列表 / 取图 / 删除 / 不存在 404 ✓")

    # 5. 上传报错是消息对象
    import asyncio

    class Req:
        def __init__(self, ctype, body):
            self.headers, self._b = {"content-type": ctype}, body

        async def body(self):
            return self._b

    put = lambda shot, ctype, body: must_raise(  # noqa: E731
        HTTPException, lambda: asyncio.run(app_mod.keyframes_put(nid, cid, "v2", shot, Req(ctype, body), A)))
    e = put(sid, "text/html", b"<x>")
    assert e.status_code == 422 and e.detail["code"] == "chapter.keyframe.bad_type"
    e = put(sid, "image/png", b"0" * (novels.KEYFRAME_MAX_BYTES + 1))
    assert e.status_code == 422 and e.detail["code"] == "common.image_too_big" and e.detail["params"] == {"mb": 8}
    e = put("E99-SH001", "image/png", PNG)
    assert e.status_code == 404 and e.detail["code"] == "chapter.keyframe.no_shot" and e.detail["params"]["shot"] == "E99-SH001"
    e = must_raise(HTTPException, app_mod.keyframes_get, nid, cid, "v2", sid, A)
    assert e.status_code == 404 and e.detail["code"] == "chapter.keyframe.not_found"
    print("上传报错: 类型 / 过大 / 没有镜头 / 没有关键帧 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        _TMP.cleanup()
    sys.exit(code)
