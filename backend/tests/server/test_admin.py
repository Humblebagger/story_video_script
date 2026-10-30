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

from server import auth  # noqa: E402


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
    print("1. 角色 / 上限 / 停用立即生效 / 重置密码 / 安全列表 / 最近活跃节流 ✓")
    return root, bob


def main() -> int:
    part_auth()
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
