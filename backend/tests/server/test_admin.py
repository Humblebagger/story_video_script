#!/usr/bin/env python3
"""管理后台：账号字段、管理逻辑与约束、审计、命令行、/admin 接口。

全程使用临时数据目录。用法: python3 tests/server/test_admin.py
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* 之前

from server import admin, audit, auth, novels, pricing, usage  # noqa: E402


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def part_auth():
    root = auth.register("root", "secret1")
    bob = auth.register("bob", "secret1")
    assert root["role"] == "user" and root["disabled"] is False, "新用户默认普通、未停用"

    # 角色、上限、停用
    auth.update_user(root["id"], role="admin")
    assert auth.get_user(root["id"])["role"] == "admin"
    auth.update_user(bob["id"], monthly_cap_usd=5.0)
    assert auth.get_user_raw(bob["id"])["monthly_cap_usd"] == 5.0
    must_raise(ValueError, auth.update_user, bob["id"], salt="x")
    tok = auth.issue_token(bob["id"])
    assert auth.verify_token(tok)["id"] == bob["id"]
    auth.update_user(bob["id"], disabled=True)
    assert auth.verify_token(tok) is None, "停用后现有 token 立即失效"
    e = must_raise(auth.AuthError, auth.authenticate, "bob", "secret1")
    assert str(e) == "账号已停用"
    must_raise(auth.AuthError, auth.authenticate, "bob", "wrong")
    auth.update_user(bob["id"], disabled=False)
    assert auth.verify_token(tok)["id"] == bob["id"]

    # 重置密码
    must_raise(auth.AuthError, auth.set_password, bob["id"], "123")
    auth.set_password(bob["id"], "newpass1")
    assert auth.authenticate("bob", "newpass1")["id"] == bob["id"]

    # 安全列表不含密码字段
    safe = auth.list_users_safe()
    assert all("password_hash" not in u and "salt" not in u for u in safe)
    assert {u["username"] for u in safe} == {"root", "bob"}
    assert all(u["has_password"] for u in safe)

    # 最近活跃：首次写入，10 分钟内不重复写
    auth.touch_seen(bob["id"])
    first = auth.get_user_raw(bob["id"])["last_seen_at"]
    assert first
    time.sleep(1.1)
    auth.touch_seen(bob["id"])
    assert auth.get_user_raw(bob["id"])["last_seen_at"] == first, "节流期内不写"

    # 写盘失败不能让请求 500：touch_seen 吞掉 OSError，且下次还会重试
    real_save = auth._save_users
    calls = []

    def boom(users):
        calls.append(1)
        raise OSError("disk full")

    auth._seen_at.pop(bob["id"], None)
    auth._save_users = boom
    try:
        auth.touch_seen(bob["id"])
        auth.touch_seen(bob["id"])
    finally:
        auth._save_users = real_save
    assert len(calls) == 2, "失败不记节流时间，下次继续重试"
    auth.touch_seen(bob["id"])
    assert auth.get_user_raw(bob["id"])["last_seen_at"] != first, "恢复后写入成功"
    print("1. 角色 / 上限 / 停用立即生效 / 重置密码 / 安全列表 / 最近活跃节流与写盘失败 ✓")
    return root, bob


def part_admin(root, bob):
    me = auth.get_user_raw(root["id"])
    table = pricing.load()

    # 计数与标题：只读元数据
    nid = novels.create_novel(bob["id"], "药")["id"]
    cid = novels.create_chapter(bob["id"], nid, "第一章", text="原文很长")["id"]
    novels.create_version(bob["id"], nid, cid, "v1", {}, "原文很长")
    novels.update_version_state(bob["id"], nid, cid, "v1", "failed", error="E" * 500,
                                manifest={"attempts": [{"usage": {"calls": 2, "input": 10,
                                                                 "output": 20}}, {}],
                                          "contracts": {"model": "claude-sonnet-5"},
                                          "input": {"normalized_chars": 1234}})
    assert novels.counts(bob["id"]) == {"novels": 1, "chapters": 1, "versions": 1}
    assert novels.titles(bob["id"], nid, cid) == ("药", "第一章")
    assert novels.titles(bob["id"], "n_gone", None) == (None, None)

    usage.record(user_id=bob["id"], purpose="convert", model="claude-sonnet-5",
                 usage={"calls": 1, "input": 1_000_000}, ok=True, chars=2000,
                 novel_id=nid, chapter_id=cid, version_id="v0")

    # 用户行与详情：不含原文
    rows = {r["username"]: r for r in admin.user_rows(table)}
    b = rows["bob"]
    assert (b["novels"], b["chapters"], b["versions"]) == (1, 1, 1)
    assert abs(b["month_cost_usd"] - 2.0) < 1e-9
    d = admin.user_detail(bob["id"], table)
    assert d["recent"][0]["novel_title"] == "药" and d["recent"][0]["chapter_title"] == "第一章"
    assert abs(d["recent"][0]["cost_usd"] - 2.0) < 1e-9 and len(d["daily"]) == 30
    blob = json.dumps(d, ensure_ascii=False) + json.dumps(rows, ensure_ascii=False)
    assert "原文很长" not in blob, "后台不得返回原文"
    must_raise(admin.NotFound, admin.user_detail, "f" * 12, table)

    # 操作与约束
    must_raise(admin.AdminError, admin.patch_user, me, bob["id"], {"disabled": True, "role": "user"})
    must_raise(admin.AdminError, admin.patch_user, me, root["id"], {"disabled": True})
    must_raise(admin.AdminError, admin.patch_user, me, root["id"], {"role": "user"})
    must_raise(admin.AdminError, admin.patch_user, me, bob["id"], {"role": "boss"})
    must_raise(admin.AdminError, admin.patch_user, me, bob["id"], {"monthly_cap_usd": -1})
    must_raise(admin.AdminError, admin.patch_user, me, bob["id"], {"username": "x"})
    assert admin.patch_user(me, bob["id"], {"monthly_cap_usd": 3})["monthly_cap_usd"] == 3.0
    assert admin.patch_user(me, bob["id"], {"monthly_cap_usd": None})["monthly_cap_usd"] is None
    assert admin.patch_user(me, bob["id"], {"disabled": True})["disabled"] is True
    assert admin.patch_user(me, bob["id"], {"disabled": False})["disabled"] is False
    assert admin.patch_user(me, bob["id"], {"role": "admin"})["role"] == "admin"
    # bob 是管理员后由 bob 停用 root：root 不是最后一个管理员，可以
    bob_me = auth.get_user_raw(bob["id"])
    admin.patch_user(bob_me, root["id"], {"disabled": True})
    # 现在 bob 是唯一未停用的管理员；root（已停用）不能去掉 bob 的管理员——但 root 已停用、
    # 接口层根本进不来；这里直接验证「最后一个管理员」约束
    e = must_raise(admin.AdminError, admin._guard_last_admin, bob["id"])
    assert "至少保留一个管理员" in str(e)
    admin.patch_user(bob_me, root["id"], {"disabled": False})
    admin.reset_password(me, bob["id"], "another1")
    assert auth.authenticate("bob", "another1")["id"] == bob["id"]
    must_raise(admin.AdminError, admin.reset_password, me, bob["id"], "1")

    # 审计：每个成功操作都有一条，最新在前；重置密码不记密码
    log = audit.read(limit=100)
    actions = [a["action"] for a in log]
    assert actions[0] == "reset_password" and "another1" not in json.dumps(log)
    for want in ("set_cap", "disable", "enable", "grant_admin"):
        assert want in actions, want
    print("2. 计数与标题 / 用户行与详情不含原文 / 操作约束 / 审计 ✓")
    return nid, cid


def part_jobs_overview(root, bob, nid, cid):
    table = pricing.load()
    jobs = admin.jobs_view([{"id": "j1", "user_id": bob["id"], "status": "running",
                             "work_title": "药", "chapter": "第一章", "chars": 99,
                             "created_at": "2026-10-30T00:00:00+00:00"},
                            {"id": "j2", "user_id": bob["id"], "status": "succeeded",
                             "created_at": "2026-10-30T00:00:00+00:00"}])
    assert [j["id"] for j in jobs["running"]] == ["j1"] and jobs["running"][0]["username"] == "bob"
    f = jobs["failed"][0]
    assert f["id"] == "v1" and f["novel_title"] == "药" and f["attempts"] == 2
    assert f["chars"] == 1234 and len(f["error"]) == 300
    ov = admin.overview(table, running=1)
    assert ov["users"] == 2 and ov["running"] == 1 and ov["failed_7d"] == 1
    assert len(ov["daily"]) == 30 and ov["cost_30d"] > 0
    csv_text = admin.usage_csv(30, table)
    assert csv_text.splitlines()[0].startswith("at,user_id,username,purpose,model")
    assert ",bob," in csv_text
    rep = admin.usage_report("user", 30, table)
    assert rep["rows"][0]["label"] == "bob" and rep["per_k_chars"]["n"] == 1

    # 历史补导：从版本 manifest 生成记录，重复执行不重复
    r1 = admin.backfill_usage()
    assert r1["added"] == 1, r1
    r2 = admin.backfill_usage()
    assert r2["added"] == 0 and r2["existing"] == 1
    back = [r for r in usage.read() if r.get("version_id") == "v1"]
    assert back[0]["calls"] == 2 and back[0]["ok"] is False and back[0]["chars"] == 1234
    print("3. 任务（运行中 / 近期失败）/ 概览 / CSV / 用量报表 / 历史补导去重 ✓")


def part_cli():
    auth.register("carol", "secret1")
    assert admin.main(["promote", "carol"]) == 0
    assert auth.get_user_raw(next(u["id"] for u in auth.list_users_safe()
                                  if u["username"] == "carol"))["role"] == "admin"
    assert admin.main(["demote", "carol"]) == 0
    assert admin.main(["promote", "nobody"]) == 1
    assert admin.main(["list"]) == 0
    print("4. 命令行 promote / demote / list ✓")


def part_api():
    from fastapi.testclient import TestClient
    from server import app as app_mod

    c = TestClient(app_mod.app)
    users = {u["username"]: u for u in auth.list_users_safe()}
    root_tok = auth.issue_token(users["root"]["id"])
    carol_tok = auth.issue_token(users["carol"]["id"])
    H = {"Authorization": f"Bearer {root_tok}"}

    # 权限：普通用户 403，未登录 401
    assert c.get("/admin/overview", headers={"Authorization": f"Bearer {carol_tok}"}).status_code == 403
    assert c.get("/admin/overview").status_code == 401
    assert c.get("/auth/me", headers=H).json()["role"] == "admin"

    # 只读接口
    assert c.get("/admin/overview", headers=H).json()["users"] == 3
    rows = c.get("/admin/users", headers=H).json()["users"]
    assert {r["username"] for r in rows} == {"root", "bob", "carol"}
    assert "原文很长" not in json.dumps(rows, ensure_ascii=False)
    bob_id = users["bob"]["id"]
    assert c.get(f"/admin/users/{bob_id}", headers=H).json()["user"]["username"] == "bob"
    assert c.get("/admin/users/ffffffffffff", headers=H).status_code == 404
    assert c.get("/admin/usage?group=day&days=7", headers=H).json()["group"] == "day"
    assert c.get("/admin/usage?group=bogus&days=7", headers=H).status_code == 400
    assert c.get("/admin/usage?group=user&days=5", headers=H).status_code == 422
    r = c.get("/admin/usage.csv?days=30", headers=H)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "failed" in c.get("/admin/jobs", headers=H).json()
    assert c.get("/admin/audit", headers=H).json()["audit"][0]["action"]

    # 操作：停用后对方 token 立即 401、不能登录；启用恢复
    carol_id = users["carol"]["id"]
    assert c.patch(f"/admin/users/{carol_id}", json={"disabled": True}, headers=H).status_code == 200
    assert c.get("/auth/me", headers={"Authorization": f"Bearer {carol_tok}"}).status_code == 401
    r = c.post("/auth/login", json={"username": "carol", "password": "secret1"})
    assert r.status_code == 401 and r.json()["detail"] == "账号已停用"
    c.patch(f"/admin/users/{carol_id}", json={"disabled": False}, headers=H)
    assert c.patch(f"/admin/users/{users['root']['id']}", json={"disabled": True},
                   headers=H).status_code == 400
    assert c.post(f"/admin/users/{carol_id}/password", json={"password": "freshpw1"},
                  headers=H).json() == {"ok": True}
    assert c.post("/auth/login", json={"username": "carol", "password": "freshpw1"}).status_code == 200

    # 价格表
    t = c.get("/admin/pricing", headers=H).json()
    t["models"]["mystery"] = {"input": 1, "output": 1, "cache_read": 0, "cache_write": 0}
    assert c.put("/admin/pricing", json=t, headers=H).status_code == 200
    assert "mystery" in c.get("/admin/pricing", headers=H).json()["models"]
    bad = {"models": {"m": {"input": -1}}}
    assert c.put("/admin/pricing", json=bad, headers=H).status_code == 400
    assert c.get("/admin/audit", headers=H).json()["audit"][0]["action"] == "update_pricing"

    # 非有限数 / disabled 非布尔：400，且列表接口不被毒化
    jh = {**H, "Content-Type": "application/json"}
    r = c.patch(f"/admin/users/{carol_id}", headers=jh,
                content=json.dumps({"monthly_cap_usd": float("nan")}, allow_nan=True))
    assert r.status_code == 400, r.text
    r = c.patch(f"/admin/users/{carol_id}", headers=jh, content='{"monthly_cap_usd": 1e400}')
    assert r.status_code == 400, r.text
    assert c.patch(f"/admin/users/{carol_id}", json={"disabled": None}, headers=H).status_code == 400
    t2 = c.get("/admin/pricing", headers=H).json()
    t2["models"]["mystery"]["input"] = float("inf")
    r = c.put("/admin/pricing", headers=jh, content=json.dumps(t2, allow_nan=True))
    assert r.status_code == 400, r.text
    assert c.get("/admin/users", headers=H).status_code == 200
    assert c.get("/admin/pricing", headers=H).status_code == 200

    # 月上限：上限 0 时提交转换被拒 429（不会真的启动转换）
    carol = auth.get_user_raw(carol_id)
    nid = novels.create_novel(carol_id, "孔乙己")["id"]
    cid = novels.create_chapter(carol_id, nid, "一", text="正文")["id"]
    c.patch(f"/admin/users/{carol_id}", json={"monthly_cap_usd": 0}, headers=H)
    carol_tok = auth.issue_token(carol_id)
    r = c.post(f"/novels/{nid}/chapters/{cid}/versions", json={},
               headers={"Authorization": f"Bearer {carol_tok}"})
    assert r.status_code == 429 and "本月用量已达上限" in r.json()["detail"], r.text
    assert carol["username"] == "carol"

    # 落账：章后整理调用后写一条 digest 记录
    from pipeline.chat import UsageCallback

    class FakeDigestChat:
        usage = UsageCallback()

        def usage_totals(self):
            return {"calls": 1, "input": 5, "output": 7, "cache_read": 0, "cache_write": 0}

    app_mod._record_chat_usage(carol_id, nid, cid, FakeDigestChat(), ok=True)
    last = usage.read(user_id=carol_id)[-1]
    assert last["purpose"] == "digest" and last["output"] == 7 and last["chapter_id"] == cid

    # 落账：转换结束（成功与失败都记；没有调用不记）
    job = {"id": "vx", "user_id": carol_id, "novel_id": nid, "chapter_id": cid,
           "version_id": "vx", "chars": 2}
    manifest = {"attempts": [{"usage": {"calls": 1, "input": 3, "output": 4}}],
                "contracts": {"model": "claude-sonnet-5"}, "input": {"normalized_chars": 2}}
    before = len(usage.read())
    app_mod._record_usage(job, manifest, ok=False)
    app_mod._record_usage(job, {"attempts": []}, ok=True)
    after = usage.read()
    assert len(after) == before + 1 and after[-1]["ok"] is False and after[-1]["input"] == 3
    print("5. 接口权限 / 只读接口 / 停用即时生效 / 重置密码 / 价格表 / 月上限 429 / 落账 ✓")


def main() -> int:
    root, bob = part_auth()
    nid, cid = part_admin(root, bob)
    part_jobs_overview(root, bob, nid, cid)
    part_cli()
    part_api()
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
