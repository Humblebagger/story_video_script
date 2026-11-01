#!/usr/bin/env python3
"""小说风格参考图：上传 / 取回 / 替换 / 删除与用户隔离。用法: python3 tests/server/test_style_image.py

全程使用临时数据目录，不碰真实 data/。
"""
import hashlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* 之前
os.environ["STORYBOARD_RENDER_RUNNER"] = "0"

from fastapi.testclient import TestClient  # noqa: E402
from server import app as app_mod  # noqa: E402
from server import auth, novels  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100
JPG = b"\xff\xd8\xff\xe0" + b"1" * 100


def main() -> int:
    c = TestClient(app_mod.app)
    alice, bob = auth.register("alice", "secret1"), auth.register("bob", "secret2")
    H = {"Authorization": f"Bearer {auth.issue_token(alice['id'])}"}
    HB = {"Authorization": f"Bearer {auth.issue_token(bob['id'])}"}
    nid = novels.create_novel(alice["id"], "药")["id"]
    U = f"/novels/{nid}/style-image"
    sdir = novels._style_dir(alice["id"], nid)

    # 1. 新小说没有图
    assert c.get(U, headers=H).status_code == 404
    assert c.get(f"/novels/{nid}", headers=H).json()["style_image"] is None
    print("新小说: 无图 / style_image 为 None ✓")

    # 2. 上传
    r = c.put(U, headers={**H, "Content-Type": "image/png"}, content=PNG)
    assert r.status_code == 200, r.text
    meta = r.json()
    assert meta["hash"] == hashlib.sha256(PNG).hexdigest()
    assert meta["mime"] == "image/png" and meta["bytes"] == len(PNG) and meta["updated_at"]
    print("上传: 元数据 ✓")

    # 3. 取回
    g = c.get(U, headers=H)
    assert g.status_code == 200 and g.content == PNG
    assert g.headers["content-type"] == "image/png"
    assert c.get(f"/novels/{nid}", headers=H).json()["style_image"]["hash"] == meta["hash"]
    print("取回: 字节一致 / 详情带元数据 ✓")

    # 4. 换格式：删旧文件
    r = c.put(U, headers={**H, "Content-Type": "image/jpeg"}, content=JPG)
    assert r.status_code == 200 and r.json()["mime"] == "image/jpeg"
    assert [p.name for p in sdir.iterdir()] == ["style.jpg"]
    assert c.get(U, headers=H).content == JPG
    print("替换: 只剩 style.jpg ✓")

    # 5. 非法输入
    assert c.put(U, headers={**H, "Content-Type": "image/gif"}, content=PNG).status_code == 422
    assert c.put(U, headers={**H, "Content-Type": "image/png"}, content=b"").status_code == 422
    big = b"0" * (novels.KEYFRAME_MAX_BYTES + 1)
    assert c.put(U, headers={**H, "Content-Type": "image/png"}, content=big).status_code == 422
    assert c.get(U, headers=H).content == JPG, "失败的上传不动原图"
    print("非法类型 / 空体 / 超限: 422 ✓")

    # 6. 他人
    assert c.get(U, headers=HB).status_code == 404
    assert c.put(U, headers={**HB, "Content-Type": "image/png"}, content=PNG).status_code == 404
    assert c.delete(U, headers=HB).status_code == 404
    assert c.get(U, headers=H).content == JPG
    print("用户隔离 ✓")

    # 7. 删除（幂等）
    assert c.delete(U, headers=H).status_code == 200
    assert c.get(U, headers=H).status_code == 404
    assert c.get(f"/novels/{nid}", headers=H).json()["style_image"] is None
    assert c.delete(U, headers=H).status_code == 200
    print("删除: 幂等 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        _TMP.cleanup()
    sys.exit(code)
