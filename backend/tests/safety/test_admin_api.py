#!/usr/bin/env python3
"""后台的内容拦截接口：权限、列表（用户名、作品与章节名、筛选、按编号查）、查看记审计、未放行计数、放行（审计、
幂等、模型拒答 409、不存在 404）、删除章节与作品时清空摘录。用法: python3 tests/safety/test_admin_api.py"""
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
os.environ["STORYBOARD_RENDER_RUNNER"] = "0"

from fastapi.testclient import TestClient  # noqa: E402
from safety import store  # noqa: E402
from safety.text import text_hash  # noqa: E402
from server import app as app_mod  # noqa: E402
from server import audit, auth, novels  # noqa: E402


def main() -> int:
    with TestClient(app_mod.app) as c:      # with：触发启动钩子（清理）
        root = auth.register("root", "secret1")
        auth.update_user(root["id"], role="admin")
        bob = auth.register("bob", "secret1")
        H = {"Authorization": f"Bearer {auth.issue_token(root['id'])}"}
        B = {"Authorization": f"Bearer {auth.issue_token(bob['id'])}"}
        nid = novels.create_novel(bob["id"], "药")["id"]
        cid = novels.create_chapter(bob["id"], nid, "第一章", text="原文")["id"]
        cid2 = novels.create_chapter(bob["id"], nid, "第二章", text="原文")["id"]
        ctx = {"stage": "convert", "user_id": bob["id"], "novel_id": nid, "chapter_id": cid, "version_id": "v1"}
        b1 = store.record_block("违规甲", category="sexual", reason="露骨", ctx=ctx)
        b2 = store.record_block("违规乙", category="drugs", reason="方法",
                                ctx=dict(ctx, stage="video", chapter_id=cid2, clip_id="E01-C01"))
        b3 = store.record_block("被拒丙", category="unspecified", reason_code=store.REFUSED, ctx=ctx, cache=False)

        # 1. 权限：普通用户 403，未登录 401
        for method, path in (("get", "/admin/safety/blocks"), ("get", "/admin/safety/count"),
                             ("post", f"/admin/safety/blocks/{b1}/release")):
            assert getattr(c, method)(path, headers=B).status_code == 403, path
            assert getattr(c, method)(path).status_code == 401, path
        print("1. 权限 ✓")

        # 2. 列表：最近的在前，带用户名、作品名、章节名；查看记审计；计数接口不记审计
        n_audit = len(audit.read(1000))
        rows = c.get("/admin/safety/blocks", headers=H).json()["blocks"]
        assert {r["id"] for r in rows} == {b1, b2, b3} and len(rows) == 3
        assert [r["last_at"] for r in rows] == sorted((r["last_at"] for r in rows), reverse=True), "最近的在前"
        r1 = next(r for r in rows if r["id"] == b1)
        assert (r1["username"], r1["novel_title"], r1["chapter_title"]) == ("bob", "药", "第一章")
        assert r1["excerpt"] == "违规甲" and r1["reason"] == "露骨" and r1["releasable"] is True and "hash" not in r1
        assert next(r for r in rows if r["id"] == b3)["releasable"] is False
        assert next(r for r in rows if r["id"] == b2)["clip_id"] == "E01-C01"
        last = audit.read(1)[0]
        assert len(audit.read(1000)) == n_audit + 1 and last["action"] == "view_safety_blocks"
        assert c.get("/admin/safety/count", headers=H).json() == {"blocked": 3}
        assert len(audit.read(1000)) == n_audit + 1, "计数接口不带摘录，不记审计"
        print("2. 列表与审计 ✓")

        # 3. 筛选：状态、天数、编号（小写也认）；非法状态 422
        assert [r["id"] for r in c.get(f"/admin/safety/blocks?ref={b2.lower()}", headers=H).json()["blocks"]] == [b2]
        assert c.get("/admin/safety/blocks?ref=ZZZZZZZZ", headers=H).json()["blocks"] == []
        assert c.get("/admin/safety/blocks?status=released", headers=H).json()["blocks"] == []
        assert len(c.get("/admin/safety/blocks?days=7", headers=H).json()["blocks"]) == 3
        assert c.get("/admin/safety/blocks?status=bogus", headers=H).status_code == 422
        print("3. 筛选 ✓")

        # 4. 放行：状态改变、结论缓存改为通过、写审计；再放行幂等；模型拒答 409；不存在 404
        r = c.post(f"/admin/safety/blocks/{b1}/release", headers=H)
        assert r.status_code == 200 and r.json()["status"] == "released" and r.json()["released_by"] == "root"
        assert store.get_verdict(text_hash("违规甲")) == {**store.get_verdict(text_hash("违规甲")),
                                                         "verdict": "pass", "released": True}
        last = audit.read(1)[0]
        assert last["action"] == "release_safety_block" and last["target"] == "bob" and last["after"]["id"] == b1
        assert c.post(f"/admin/safety/blocks/{b1}/release", headers=H).status_code == 200
        r = c.post(f"/admin/safety/blocks/{b3}/release", headers=H)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "admin.safety.not_releasable"
        r = c.post("/admin/safety/blocks/ZZZZZZZZ/release", headers=H)
        assert r.status_code == 404 and r.json()["detail"]["code"] == "admin.safety.not_found"
        assert c.get("/admin/safety/count", headers=H).json() == {"blocked": 2}
        assert [r["id"] for r in c.get("/admin/safety/blocks?status=released", headers=H).json()["blocks"]] == [b1]
        print("4. 放行 ✓")

        # 5. 用户删章节、删作品：对应记录的摘录与理由清空，记录还在
        assert c.delete(f"/novels/{nid}/chapters/{cid2}", headers=B).status_code == 200
        assert store.find_block(b2)["excerpt"] == "" and store.find_block(b1)["excerpt"] == "违规甲"
        assert c.delete(f"/novels/{nid}", headers=B).status_code == 200
        assert store.find_block(b1)["excerpt"] == "" and store.find_block(b1)["reason"] == ""
        rows = c.get("/admin/safety/blocks", headers=H).json()["blocks"]
        assert len(rows) == 3 and all(r["novel_title"] is None for r in rows), "作品已删：名字为空，记录保留"
        print("5. 删除时清空 ✓")

        # 6. 存储失败：放行写盘失败 -> 503 带代码，不是 500；内存丢弃，磁盘恢复后重试成功
        real_write = store._write
        def boom(*_a, **_k):
            raise OSError("disk full /secret/path")
        store._write = boom
        try:
            r = c.post(f"/admin/safety/blocks/{b2}/release", headers=H)
        finally:
            store._write = real_write
        assert r.status_code == 503 and r.json()["detail"]["code"] == "admin.safety.storage_failed", r.text
        assert "secret" not in r.text
        assert c.post(f"/admin/safety/blocks/{b2}/release", headers=H).status_code == 200
        print("6. 存储失败 ✓")

        # 7. 删除时先清摘录再删（第四轮 3）：清理失败 → 503 带代码，章节与作品都还在，可重试；之后迟到的记录不留摘录
        nid7 = novels.create_novel(bob["id"], "七")["id"]
        cid7 = novels.create_chapter(bob["id"], nid7, "七一", text="原文")["id"]
        ctx7 = dict(ctx, novel_id=nid7, chapter_id=cid7)
        b7 = store.record_block("第七节违规", category="drugs", reason="方法", ctx=ctx7)
        store._write = boom
        try:
            r = c.delete(f"/novels/{nid7}/chapters/{cid7}", headers=B)
            assert r.status_code == 503 and r.json()["detail"]["code"] == "safety.purge_failed", r.text
            assert "secret" not in r.text
            r = c.delete(f"/novels/{nid7}", headers=B)
            assert r.status_code == 503 and r.json()["detail"]["code"] == "safety.purge_failed", r.text
        finally:
            store._write = real_write
        assert novels.get_chapter(bob["id"], nid7, cid7)["id"] == cid7, "清理失败：章节保持不删"
        assert store.find_block(b7)["excerpt"] == "第七节违规"
        assert c.delete(f"/novels/{nid7}/chapters/{cid7}", headers=B).status_code == 200, "重试成功"
        assert store.find_block(b7)["excerpt"] == ""
        late = store.record_block("删除后才到的结论", category="drugs", reason="迟到", ctx=ctx7)
        assert store.find_block(late)["excerpt"] == "" and store.find_block(late)["reason"] == ""
        assert c.delete(f"/novels/{nid7}/chapters/nope", headers=B).status_code == 404
        print("7. 删除时先清后删 ✓")

        # 8. 放行审计（第四轮 4）：先写 requested 审计；审计写失败 → 503 带代码、不放行；放行写盘失败 → 503，审计保持 requested
        b8 = store.record_block("第八节违规", category="drugs", reason="方法", ctx=ctx)
        real_audit = app_mod.audit.write

        def audit_boom(*_a, **_k):
            raise OSError("audit disk full /secret/path")
        app_mod.audit.write = audit_boom
        try:
            r = c.post(f"/admin/safety/blocks/{b8}/release", headers=H)
        finally:
            app_mod.audit.write = real_audit
        assert r.status_code == 503 and r.json()["detail"]["code"] == "admin.safety.audit_failed", r.text
        assert "secret" not in r.text
        assert store.find_block(b8)["status"] == "blocked" and store.get_verdict(text_hash("第八节违规"))["verdict"] == "block"
        n_audit = len(audit.read(10000))
        store._write = boom
        try:
            r = c.post(f"/admin/safety/blocks/{b8}/release", headers=H)
        finally:
            store._write = real_write
        assert r.status_code == 503 and r.json()["detail"]["code"] == "admin.safety.storage_failed", r.text
        rows8 = audit.read(10000)
        assert len(rows8) == n_audit + 1 and rows8[0]["action"] == "release_safety_block"
        assert rows8[0]["after"]["status"] == "requested" and rows8[0]["after"]["id"] == b8, rows8[0]
        r = c.post(f"/admin/safety/blocks/{b8}/release", headers=H)
        assert r.status_code == 200
        rows8 = audit.read(10000)
        assert [x["after"]["status"] for x in rows8[:2]] == ["released", "requested"], rows8[:2]
        # 查看列表的审计写失败也是带代码的错误
        app_mod.audit.write = audit_boom
        try:
            r = c.get("/admin/safety/blocks", headers=H)
        finally:
            app_mod.audit.write = real_audit
        assert r.status_code == 503 and r.json()["detail"]["code"] == "admin.safety.audit_failed", r.text
        print("8. 放行审计 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        _TMP.cleanup()
    sys.exit(code)
