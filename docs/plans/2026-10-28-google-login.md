# Google 账号登录 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有「用户名 + 密码」登录之外加上 Google 账号登录，并支持已有账号绑定、解绑 Google。

**Architecture:** 前端用 Google Identity Services 官方按钮拿 ID token，后端用 `google-auth` 校验（签名、`aud`、`exp`、`iss`），按 Google `sub` 在新的 `identities.json` 里找或建用户，再用现有 `auth.issue_token` 签发同一种 HMAC token。下游所有接口、数据隔离不变。

**Tech Stack:** FastAPI、`google-auth` + `requests`（后端）；React 19 + Vite + TS、happy-dom 测试（前端）。

**Spec:** `docs/specs/2026-10-28-google-login-design.md`

**全局约束**

- 分支 `langchain`，Python 用 `backend/.venv`（3.12）。
- 提交只 `git add` 具体文件，禁止 `git add -A` / `git commit -a`。
- 提交信息**不得**带任何 Claude 署名（无 `Co-Authored-By`、无 `Claude-Session`）。
- 不读、不打印 `backend/.env`。
- 后端测试是脚本式：`cd backend && .venv/bin/python tests/server/test_xxx.py`，结尾打印 `ALL PASS`。
- 前端测试：`cd frontend && npm test`（先 `tsc -b --force`，再逐个 `vite build --ssr` + `node`），每个套件结尾打印 `ALL PASS`。

**与 spec 的一处偏差（Task 3 同步改 spec）：** spec 写「凭证无效 → 401」。前端 `api.ts` 的 `send()` 把任何 401 当作「登录过期」并清空会话，已登录用户绑定时传了坏凭证会被直接踢出。所以凭证无效改为 **400**，文案不变。

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/requirements.txt` | 改 | 加 `google-auth`、`requests` |
| `backend/server/google_id.py` | 新建 | 校验 Google ID token；公钥带 1 小时缓存，遇到未知 `kid` 强制刷新一次；`client_id()` 读环境变量 |
| `backend/server/auth.py` | 改 | 密码变可选；`identities.json` 读写；用户名生成；`login_with_identity` / `link_identity` / `unlink_identity`；`_public` 增加 `has_password`、`identities` |
| `backend/server/app.py` | 改 | `/auth/config`、`/auth/google`、`/auth/google/link`、`DELETE /auth/identities/google`；抽出 `_backfill_library` |
| `backend/tests/server/test_google_id.py` | 新建 | 用本地生成的 RSA 密钥走真实的 `google.auth.jwt.decode` 路径 |
| `backend/tests/server/test_google_login.py` | 新建 | `TestClient` 打接口，注入假校验函数 |
| `backend/.env.example` | 改 | `STORYBOARD_GOOGLE_CLIENT_ID`、`HTTPS_PROXY` 说明 |
| `frontend/src/auth.ts` | 改 | `User` 增加 `has_password`、`identities`；`updateCachedUser` |
| `frontend/src/api.ts` | 改 | `authConfig`、`googleLogin`、`googleLink`、`googleUnlink` |
| `frontend/src/google.ts` | 新建 | 加载 GIS 脚本（只加载一次）+ 最小类型声明 |
| `frontend/src/components/GoogleButton.tsx` | 新建 | 渲染官方按钮；加载失败显示「Google 登录暂不可用」 |
| `frontend/src/components/LoginView.tsx` | 改 | 顶部 Google 按钮 + 分隔线 |
| `frontend/src/components/AccountPanel.tsx` | 新建 | 账号面板：显示绑定、绑定、解绑 |
| `frontend/src/App.tsx` | 改 | 用户名旁「账号」按钮，打开面板 |
| `frontend/src/index.css` | 改 | `.login__or`、`.gbtn`、`.acct`、`.who__acct` |
| `frontend/tests/login.test.tsx` | 新建 | 登录页与账号面板的界面回归 |
| `frontend/tests/flow.test.tsx` | 改 | 桩后端补 `/auth/config` |
| `frontend/package.json` | 改 | `test` 脚本加入 `login.test.tsx` |
| `README.md`、`frontend/README.md` | 改 | 登录说明与 Google Cloud 配置步骤 |

---

### Task 1: Google ID token 校验模块

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/server/google_id.py`
- Test: `backend/tests/server/test_google_id.py`

- [ ] **Step 1: 加依赖并安装**

在 `backend/requirements.txt` 末尾追加两行：

```
google-auth>=2.40,<3
requests>=2.31,<3
```

Run: `cd backend && .venv/bin/pip install -r requirements.txt`
Expected: 安装成功；`.venv/bin/python -c "import google.auth, requests; print('ok')"` 打印 `ok`

- [ ] **Step 2: 写失败测试**

Create `backend/tests/server/test_google_id.py`:

```python
#!/usr/bin/env python3
"""Google ID token 校验：用本地生成的 RSA 密钥签 token，走真实的 google.auth.jwt.decode。

不连网：公钥获取函数被替换成返回本地公钥的假函数。
用法: python3 tests/server/test_google_id.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from google.auth import crypt, jwt  # noqa: E402

from server import google_id  # noqa: E402

AUD = "cid-test.apps.googleusercontent.com"


def keypair() -> tuple:
    """返回 (私钥 PEM, 公钥 PEM)。优先用 cryptography（google-auth 也优先用它验签）。"""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa as crsa
        k = crsa.generate_private_key(public_exponent=65537, key_size=2048)
        priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption())
        pub = k.public_key().public_bytes(serialization.Encoding.PEM,
                                          serialization.PublicFormat.SubjectPublicKeyInfo)
    except ImportError:
        import rsa
        pubk, privk = rsa.newkeys(2048)
        priv, pub = privk.save_pkcs1(), pubk.save_pkcs1()
    return priv, pub


PRIV, PUB = keypair()
fetches = []


def fake_fetch(certs: dict):
    def fetch():
        fetches.append(time.time())
        return certs
    return fetch


def token(kid="k1", **over) -> str:
    now = int(time.time())
    claims = {"iss": "https://accounts.google.com", "aud": AUD, "sub": "1098",
              "email": "alice@gmail.com", "email_verified": True, "name": "Alice",
              "picture": "https://p/a.png", "iat": now, "exp": now + 3600}
    claims.update(over)
    signer = crypt.RSASigner.from_string(PRIV, key_id=kid)
    return jwt.encode(signer, claims).decode()


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def main() -> int:
    google_id.fetch_certs = fake_fetch({"k1": PUB.decode()})
    google_id.reset_cache()

    # 1. 合法 token → 资料；公钥只取一次（缓存）
    c = google_id.verify(token(), AUD)
    assert c == {"sub": "1098", "email": "alice@gmail.com", "email_verified": True,
                 "name": "Alice", "picture": "https://p/a.png"}, c
    google_id.verify(token(), AUD)
    assert len(fetches) == 1, "公钥应缓存"
    print("1. 合法 token / 公钥缓存 ✓")

    # 2. aud 不符、过期、iss 不对、缺 sub、乱码 → InvalidToken
    must_raise(google_id.InvalidToken, google_id.verify, token(aud="other"), AUD)
    must_raise(google_id.InvalidToken, google_id.verify,
               token(iat=int(time.time()) - 7200, exp=int(time.time()) - 3600), AUD)
    must_raise(google_id.InvalidToken, google_id.verify, token(iss="https://evil.example"), AUD)
    must_raise(google_id.InvalidToken, google_id.verify, token(sub=""), AUD)
    must_raise(google_id.InvalidToken, google_id.verify, "not-a-jwt", AUD)
    print("2. aud / 过期 / iss / 缺 sub / 乱码 都拒绝 ✓")

    # 3. 未知 kid：强制刷新一次公钥，仍没有就拒绝
    before = len(fetches)
    must_raise(google_id.InvalidToken, google_id.verify, token(kid="k9"), AUD)
    assert len(fetches) == before + 1, "未知 kid 应刷新一次公钥"
    print("3. 未知 kid 刷新一次后拒绝 ✓")

    # 4. 公钥取不到 → Unavailable
    def down():
        raise google_id.Unavailable("boom")
    google_id.fetch_certs = down
    google_id.reset_cache()
    must_raise(google_id.Unavailable, google_id.verify, token(), AUD)
    print("4. 取不到公钥 → Unavailable ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && .venv/bin/python tests/server/test_google_id.py`
Expected: FAIL，`ImportError: cannot import name 'google_id' from 'server'`

- [ ] **Step 4: 实现**

Create `backend/server/google_id.py`:

```python
"""Google 登录：校验前端 Google Identity Services 拿到的 ID token。

只做一件事——确认这个 token 是 Google 签发给我们这个 client ID 的、没过期，
然后交出 sub / email / name / picture。用户的查找与创建在 auth.py。

公钥（Google 的签名证书）缓存 1 小时；遇到缓存里没有的 kid（Google 轮换了密钥）
强制刷新一次。后端访问 Google 遵循标准的 HTTPS_PROXY 环境变量（requests 自动读取）。
"""
import base64
import json
import os
import threading
import time
from typing import Callable, Optional

import requests
from google.auth import exceptions as gexc
from google.auth import jwt as gjwt

CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
CERTS_TTL = 3600
CLOCK_SKEW = 10


class InvalidToken(Exception):
    """token 不是 Google 签给我们的、或已过期——用户重新登录即可。"""


class Unavailable(Exception):
    """取不到 Google 公钥（网络问题）——不是用户的错，稍后重试。"""


def client_id() -> Optional[str]:
    """没配就是没启用 Google 登录。每次现读，改 .env 重启即生效，测试也能临时改。"""
    return (os.environ.get("STORYBOARD_GOOGLE_CLIENT_ID") or "").strip() or None


def _fetch_certs() -> dict:
    try:
        r = requests.get(CERTS_URL, timeout=10)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        raise Unavailable(str(e)) from e


# 测试替换成本地公钥
fetch_certs: Callable[[], dict] = _fetch_certs

_lock = threading.Lock()
_cache: dict = {"certs": None, "at": 0.0}


def reset_cache() -> None:
    with _lock:
        _cache["certs"], _cache["at"] = None, 0.0


def _certs(force: bool = False) -> dict:
    with _lock:
        stale = time.time() - _cache["at"] > CERTS_TTL
        if force or _cache["certs"] is None or stale:
            _cache["certs"] = fetch_certs()
            _cache["at"] = time.time()
        return _cache["certs"]


def _kid(token: str) -> Optional[str]:
    try:
        head = token.split(".")[0]
        return json.loads(base64.urlsafe_b64decode(head + "=" * (-len(head) % 4))).get("kid")
    except (ValueError, IndexError, AttributeError):
        return None


def verify(credential: str, audience: str) -> dict:
    """校验通过返回 {sub, email, email_verified, name, picture}；否则抛 InvalidToken / Unavailable。"""
    certs = _certs()
    kid = _kid(credential)
    if kid and kid not in certs:
        certs = _certs(force=True)
    try:
        claims = gjwt.decode(credential, certs=certs, audience=audience,
                             clock_skew_in_seconds=CLOCK_SKEW)
    except (ValueError, gexc.GoogleAuthError) as e:
        raise InvalidToken(str(e)) from e
    if claims.get("iss") not in ISSUERS:
        raise InvalidToken(f"iss 不是 Google：{claims.get('iss')!r}")
    if not claims.get("sub"):
        raise InvalidToken("缺少 sub")
    return {
        "sub": str(claims["sub"]),
        "email": claims.get("email") or "",
        "email_verified": bool(claims.get("email_verified")),
        "name": claims.get("name") or "",
        "picture": claims.get("picture") or "",
    }
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && .venv/bin/python tests/server/test_google_id.py`
Expected: 四段 ✓，最后 `ALL PASS`

- [ ] **Step 6: 提交**

```bash
git add backend/requirements.txt backend/server/google_id.py backend/tests/server/test_google_id.py
git commit -m "Google ID token 校验：google-auth 验签与 aud/exp/iss，公钥缓存 1 小时、未知 kid 刷新一次，取不到公钥单独报不可用"
```

---

### Task 2: 用户与第三方身份绑定（auth.py）

**Files:**
- Modify: `backend/server/auth.py`
- Test: `backend/tests/server/test_identities.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/server/test_identities.py`:

```python
#!/usr/bin/env python3
"""第三方身份绑定：按 (provider, subject) 找或建用户、绑定、解绑、无密码账号的密码登录。

全程使用临时数据目录。用法: python3 tests/server/test_identities.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory()
_LEGACY = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name          # 必须在导入 server.* 之前
os.environ["STORYBOARD_LEGACY_RUNS"] = _LEGACY.name
(Path(_LEGACY.name) / "old.json").write_text("{}", encoding="utf-8")

from server import auth  # noqa: E402


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def prof(email, name="", picture=""):
    return {"email": email, "name": name, "picture": picture}


def main() -> int:
    # 1. 首个用户经 Google 新建：无密码、用户名取邮箱前缀、接管旧数据
    u, created = auth.login_with_identity("google", "g-alice", prof("alice@gmail.com", "Alice"))
    assert created and u["username"] == "alice", u
    assert u["has_password"] is False
    assert u["identities"] == [{"provider": "google", "email": "alice@gmail.com"}]
    assert (auth.user_dir(u["id"]) / "runs" / "old.json").exists(), "首个用户应接管旧数据"
    print("1. Google 新建首个用户 / 用户名取邮箱前缀 / 接管旧数据 ✓")

    # 2. 同一 sub 再登录：同一用户，资料更新
    u2, created = auth.login_with_identity("google", "g-alice", prof("alice@new.com", "A2"))
    assert not created and u2["id"] == u["id"]
    assert u2["identities"] == [{"provider": "google", "email": "alice@new.com"}]
    rec = json.loads((Path(_TMP.name) / "identities.json").read_text(encoding="utf-8"))
    assert rec[0]["name"] == "A2" and rec[0]["last_login_at"]
    print("2. 老用户再登录 / 资料更新 ✓")

    # 3. 用户名生成：重名加后缀、过短补 user_、非法字符去掉
    bob = auth.register("bob", "secret1")
    assert bob["has_password"] is True and bob["identities"] == []
    b2, _ = auth.login_with_identity("google", "g-b2", prof("Bob@x.com"))
    assert b2["username"] == "Bob_2", b2["username"]
    short, _ = auth.login_with_identity("google", "g-s", prof("a@x.com"))
    assert short["username"].startswith("user_") and len(short["username"]) == 9
    odd, _ = auth.login_with_identity("google", "g-o", prof("张三.li+tag@x.com"))
    assert odd["username"] == "张三.litag", odd["username"]
    noemail, _ = auth.login_with_identity("google", "g-n", prof("", "Mary Ann"))
    assert noemail["username"] == "MaryAnn", noemail["username"]
    print("3. 用户名：重名后缀 / 过短补 user_ / 去非法字符 / 无邮箱用名字 ✓")

    # 4. 无密码账号走密码登录 → 统一报「用户名或密码不正确」
    e = must_raise(auth.AuthError, auth.authenticate, "alice", "anything")
    assert str(e) == "用户名或密码不正确"
    assert auth.authenticate("bob", "secret1")["username"] == "bob"
    print("4. 无密码账号不能走密码登录 ✓")

    # 5. 绑定：bob 绑 g-bob；重复绑同一个幂等；绑别人的 → 冲突；再绑第二个 Google → 冲突
    lb = auth.link_identity(bob["id"], "google", "g-bob", prof("bob@gmail.com"))
    assert lb["identities"] == [{"provider": "google", "email": "bob@gmail.com"}]
    assert auth.link_identity(bob["id"], "google", "g-bob", prof("bob@gmail.com"))["id"] == bob["id"]
    e = must_raise(auth.IdentityConflict, auth.link_identity, bob["id"], "google", "g-alice", prof("x"))
    assert "已绑定另一个用户" in str(e)
    e = must_raise(auth.IdentityConflict, auth.link_identity, bob["id"], "google", "g-zzz", prof("z"))
    assert "已绑定 Google" in str(e)
    again, created = auth.login_with_identity("google", "g-bob", prof("bob@gmail.com"))
    assert not created and again["id"] == bob["id"], "绑定后用 Google 登录进的是原账号"
    print("5. 绑定 / 幂等 / 被他人占用 / 已绑另一个 ✓")

    # 6. 解绑：无密码拒绝；有密码可解；再解 → 未绑定
    e = must_raise(auth.AuthError, auth.unlink_identity, u["id"], "google")
    assert "没有设置密码" in str(e)
    ub = auth.unlink_identity(bob["id"], "google")
    assert ub["identities"] == []
    must_raise(auth.IdentityMissing, auth.unlink_identity, bob["id"], "google")
    print("6. 解绑：无密码拒绝 / 有密码可解 / 未绑定 ✓")

    # 7. token 照常：Google 用户签发的 token 能通过校验，get_user 带上 identities
    who = auth.verify_token(auth.issue_token(u["id"]))
    assert who["id"] == u["id"] and who["has_password"] is False and who["identities"]
    print("7. token 签发与校验不变 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python tests/server/test_identities.py`
Expected: FAIL，`AttributeError: module 'server.auth' has no attribute 'login_with_identity'`

- [ ] **Step 3: 实现**

在 `backend/server/auth.py` 中：

(a) 在 `SECRET_FILE = DATA_DIR / "secret.key"` 下一行加：

```python
IDENTITIES_FILE = DATA_DIR / "identities.json"
```

(b) 在 `class AuthError` 之后加：

```python
class IdentityConflict(AuthError):
    """第三方身份已被别的用户占用，或当前用户已绑了同一提供方的另一个账号。"""


class IdentityMissing(AuthError):
    """要解绑的身份不存在。"""


_PROVIDER_LABEL = {"google": "Google"}
```

(c) 把 `_load_users` / `_save_users` 改成共用的 JSON 读写，并加身份文件的读写（替换原有两个函数）：

```python
def _load_json(path: Path) -> list:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_json(path: Path, rows: list) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _load_users() -> list:
    return _load_json(USERS_FILE)


def _save_users(users: list) -> None:
    _save_json(USERS_FILE, users)


def _load_identities() -> list:
    return _load_json(IDENTITIES_FILE)


def _save_identities(rows: list) -> None:
    _save_json(IDENTITIES_FILE, rows)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
```

(d) 替换 `_public`：

```python
def _public(u: dict, identities: Optional[list] = None) -> dict:
    rows = _load_identities() if identities is None else identities
    return {
        "id": u["id"], "username": u["username"], "created_at": u["created_at"],
        # 第三方新建的用户没有密码：前端据此决定能不能解绑
        "has_password": bool(u.get("password_hash")),
        "identities": [{"provider": r["provider"], "email": r.get("email", "")}
                       for r in rows if r["user_id"] == u["id"]],
    }
```

(e) `register` 里把 `"created_at": time.strftime(...)` 改成 `"created_at": _now(),`；`return _public(user)` 改成 `return _public(user, [])`。

(f) 替换 `authenticate`：

```python
def authenticate(username: str, password: str) -> dict:
    users = _load_users()
    for u in users:
        if u["username"].lower() == (username or "").strip().lower():
            # 第三方注册的账号没有密码：同样回「不正确」，不透露它是怎么注册的
            if u.get("password_hash") and hmac.compare_digest(
                    _hash(password or "", u["salt"]), u["password_hash"]):
                return _public(u)
            break
    raise AuthError("用户名或密码不正确")
```

(g) 在 `get_user` 之前加身份相关函数：

```python
def _unique_username(hint: str, users: list) -> str:
    """第三方新建用户的用户名：取邮箱 @ 前（没有邮箱就用名字），去掉不合法字符，重名加后缀。"""
    base = re.sub(r"[^\w一-龥.-]", "", (hint or "").split("@")[0])[:28]
    if len(base) < 2:
        base = f"user_{secrets.token_hex(2)}"
    taken = {u["username"].lower() for u in users}
    name, n = base, 2
    while name.lower() in taken:
        name = f"{base}_{n}"
        n += 1
    return name


def _profile(p: dict) -> dict:
    return {k: (p.get(k) or "") for k in ("email", "name", "picture")}


def _find_identity(rows: list, provider: str, subject: str) -> Optional[dict]:
    return next((r for r in rows if r["provider"] == provider and r["subject"] == subject), None)


def login_with_identity(provider: str, subject: str, profile: dict) -> tuple:
    """第三方登录：按 (provider, subject) 找用户，找不到就新建。返回 (用户, 是否新建)。"""
    now = _now()
    with _lock:
        rows = _load_identities()
        users = _load_users()
        hit = _find_identity(rows, provider, subject)
        if hit:
            hit.update(_profile(profile), last_login_at=now)
            _save_identities(rows)
            u = next((x for x in users if x["id"] == hit["user_id"]), None)
            if u is None:
                raise AuthError("绑定的用户已不存在")
            return _public(u, rows), False

        user = {"id": secrets.token_hex(6),
                "username": _unique_username(profile.get("email") or profile.get("name") or "",
                                             users),
                "created_at": now}
        first = not users
        users.append(user)
        _save_users(users)
        rows.append({"provider": provider, "subject": subject, "user_id": user["id"],
                     **_profile(profile), "created_at": now, "last_login_at": now})
        _save_identities(rows)
        user_dir(user["id"]).mkdir(parents=True, exist_ok=True)
        if first:
            _adopt_legacy_runs(user["id"])
        return _public(user, rows), True


def link_identity(user_id: str, provider: str, subject: str, profile: dict) -> dict:
    """已登录用户绑定第三方身份。不自动合并：被别人占用或自己已绑另一个都报冲突。"""
    label = _PROVIDER_LABEL.get(provider, provider)
    with _lock:
        rows = _load_identities()
        u = next((x for x in _load_users() if x["id"] == user_id), None)
        if u is None:
            raise AuthError("用户不存在")
        hit = _find_identity(rows, provider, subject)
        if hit and hit["user_id"] != user_id:
            raise IdentityConflict(f"这个 {label} 账号已绑定另一个用户，请先用它登录并解除绑定")
        if hit:
            hit.update(_profile(profile))
        elif any(r["provider"] == provider and r["user_id"] == user_id for r in rows):
            raise IdentityConflict(f"当前账号已绑定 {label}，请先解除绑定")
        else:
            now = _now()
            rows.append({"provider": provider, "subject": subject, "user_id": user_id,
                         **_profile(profile), "created_at": now, "last_login_at": now})
        _save_identities(rows)
        return _public(u, rows)


def unlink_identity(user_id: str, provider: str) -> dict:
    """解绑。账号没有密码时拒绝——解了就再也登不进来。"""
    label = _PROVIDER_LABEL.get(provider, provider)
    with _lock:
        rows = _load_identities()
        u = next((x for x in _load_users() if x["id"] == user_id), None)
        if u is None:
            raise AuthError("用户不存在")
        mine = [r for r in rows if r["provider"] == provider and r["user_id"] == user_id]
        if not mine:
            raise IdentityMissing(f"未绑定 {label}")
        if not u.get("password_hash"):
            raise AuthError("账号没有设置密码，解除绑定后将无法登录")
        rest = [r for r in rows if r not in mine]
        _save_identities(rest)
        return _public(u, rest)
```

- [ ] **Step 4: 跑测试确认通过，并跑既有后端测试防回归**

Run:
```bash
cd backend && .venv/bin/python tests/server/test_identities.py \
  && .venv/bin/python tests/server/test_novels.py \
  && .venv/bin/python tests/server/test_keyframes.py
```
Expected: 三个都以 `ALL PASS` 结束

- [ ] **Step 5: 提交**

```bash
git add backend/server/auth.py backend/tests/server/test_identities.py
git commit -m "第三方身份绑定：identities.json 按 (provider, sub) 找或建用户，密码变可选，用户名按邮箱生成防重名；绑定不自动合并，无密码账号禁止解绑"
```

---

### Task 3: 登录接口

**Files:**
- Modify: `backend/server/app.py`（`from server import ...` 那行；`# ---------- 认证 ----------` 一节）
- Modify: `docs/specs/2026-10-28-google-login-design.md`（401 → 400）
- Test: `backend/tests/server/test_google_login.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/server/test_google_login.py`:

```python
#!/usr/bin/env python3
"""Google 登录接口：/auth/config、/auth/google、绑定、解绑、/auth/me。

校验函数换成假的（credential 形如 ok:<sub>:<email>），不连网。
用法: python3 tests/server/test_google_login.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name          # 必须在导入 server.* 之前
os.environ["STORYBOARD_GOOGLE_CLIENT_ID"] = "cid-test"

from fastapi.testclient import TestClient  # noqa: E402

from server import app as app_mod, google_id  # noqa: E402

seen = []


def fake_verify(credential: str, audience: str) -> dict:
    seen.append(audience)
    if credential == "down":
        raise google_id.Unavailable("boom")
    if not credential.startswith("ok:"):
        raise google_id.InvalidToken("bad")
    _, sub, email = credential.split(":", 2)
    return {"sub": sub, "email": email, "email_verified": True, "name": "", "picture": ""}


google_id.verify = fake_verify
c = TestClient(app_mod.app)


def bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


def main() -> int:
    # 1. 配置
    assert c.get("/auth/config").json() == {"google_client_id": "cid-test", "password_login": True}
    print("1. /auth/config ✓")

    # 2. Google 登录：新建 → 再登录
    r = c.post("/auth/google", json={"credential": "ok:g1:alice@gmail.com"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True and body["user"]["username"] == "alice"
    assert seen[-1] == "cid-test", "必须按配置的 client ID 校验 aud"
    me = c.get("/auth/me", headers=bearer(body["token"])).json()
    assert me["has_password"] is False
    assert me["identities"] == [{"provider": "google", "email": "alice@gmail.com"}]
    again = c.post("/auth/google", json={"credential": "ok:g1:alice@gmail.com"}).json()
    assert again["created"] is False and again["user"]["id"] == body["user"]["id"]
    alice_tok = body["token"]
    print("2. 新建 / 再登录 / me 带 has_password 与 identities ✓")

    # 3. 错误：凭证无效 400（不是 401，免得前端把已登录用户踢出）、公钥不可用 503、空凭证 422
    r = c.post("/auth/google", json={"credential": "bad"})
    assert r.status_code == 400 and r.json()["detail"] == "Google 登录失败，请重试"
    r = c.post("/auth/google", json={"credential": "down"})
    assert r.status_code == 503 and "暂时无法验证" in r.json()["detail"]
    assert c.post("/auth/google", json={"credential": ""}).status_code == 422
    print("3. 无效 400 / 不可用 503 / 空 422 ✓")

    # 4. 无密码账号走密码登录 → 401
    assert c.post("/auth/login", json={"username": "alice", "password": "x"}).status_code == 401
    print("4. Google 账号不能用密码登录 ✓")

    # 5. 绑定与解绑
    bob = c.post("/auth/register", json={"username": "bob", "password": "secret1"}).json()
    hb = bearer(bob["token"])
    r = c.post("/auth/google/link", json={"credential": "ok:g2:bob@gmail.com"}, headers=hb)
    assert r.status_code == 200 and r.json()["user"]["identities"][0]["email"] == "bob@gmail.com"
    r = c.post("/auth/google/link", json={"credential": "ok:g1:x@x"}, headers=hb)
    assert r.status_code == 409 and "已绑定另一个用户" in r.json()["detail"]
    r = c.post("/auth/google/link", json={"credential": "ok:g3:y@y"}, headers=hb)
    assert r.status_code == 409 and "已绑定 Google" in r.json()["detail"]
    r = c.post("/auth/google/link", json={"credential": "bad"}, headers=hb)
    assert r.status_code == 400, "绑定时凭证无效也是 400，不能踢掉登录态"
    assert c.post("/auth/google/link", json={"credential": "ok:g9:z@z"}).status_code == 401
    login_as_bob = c.post("/auth/google", json={"credential": "ok:g2:bob@gmail.com"}).json()
    assert login_as_bob["user"]["id"] == bob["user"]["id"]
    r = c.delete("/auth/identities/google", headers=bearer(alice_tok))
    assert r.status_code == 400 and "没有设置密码" in r.json()["detail"]
    r = c.delete("/auth/identities/google", headers=hb)
    assert r.status_code == 200 and r.json()["user"]["identities"] == []
    assert c.delete("/auth/identities/google", headers=hb).status_code == 404
    print("5. 绑定 / 冲突 409 / 无效 400 / 未登录 401 / 解绑 / 无密码 400 / 未绑定 404 ✓")

    # 6. 未配置 client ID → 配置为空、Google 接口 404
    del os.environ["STORYBOARD_GOOGLE_CLIENT_ID"]
    assert c.get("/auth/config").json()["google_client_id"] is None
    r = c.post("/auth/google", json={"credential": "ok:g1:alice@gmail.com"})
    assert r.status_code == 404 and r.json()["detail"] == "未启用 Google 登录"
    print("6. 未配置 → 404 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python tests/server/test_google_login.py`
Expected: FAIL，`/auth/config` 返回 404（`AssertionError` 在第 1 段）

- [ ] **Step 3: 实现**

(a) `backend/server/app.py` 把 `from server import auth, library, novels, store` 改成：

```python
from server import auth, google_id, library, novels, store
```

(b) 把 `register` 里资产库回填那段抽成函数，放在 `class Credentials` 之后：

```python
def _backfill_library(user_id: str) -> None:
    # 首个用户会接管单用户时代的历史记录，这些旧产物的资产卡也要一并进库，
    # 否则新账号打开资产库页会是空的（迁移只搬了历史文件）
    try:
        filled = library.backfill_from_runs(user_id)
        if filled:
            print(f"[library] 已从接管的历史记录补齐资产库：{filled}", flush=True)
    except (OSError, ValueError) as e:
        print(f"[library] 资产库回填失败（可在资产库页手动补齐）：{e!r}", flush=True)
```

`register` 改为：

```python
@app.post("/auth/register")
def register(body: Credentials):
    try:
        user = auth.register(body.username, body.password)
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    _backfill_library(user["id"])
    return {"token": auth.issue_token(user["id"]), "user": user}
```

(c) 在 `@app.get("/auth/me")` 那个函数之后加：

```python
class GoogleCredential(BaseModel):
    credential: str = Field(..., min_length=1)


@app.get("/auth/config")
def auth_config():
    """登录页据此决定显示哪些登录方式。client ID 本来就是公开的。"""
    return {"google_client_id": google_id.client_id(), "password_login": True}


def _google_claims(credential: str) -> dict:
    cid = google_id.client_id()
    if not cid:
        raise HTTPException(404, "未启用 Google 登录")
    try:
        return google_id.verify(credential, cid)
    except google_id.InvalidToken:
        # 400 而不是 401：前端把 401 当作登录过期，已登录用户绑定失败不该被踢出
        raise HTTPException(400, "Google 登录失败，请重试")
    except google_id.Unavailable:
        raise HTTPException(503, "暂时无法验证 Google 身份，请稍后再试")


@app.post("/auth/google")
def google_login(body: GoogleCredential):
    claims = _google_claims(body.credential)
    try:
        user, created = auth.login_with_identity("google", claims["sub"], claims)
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    if created:
        _backfill_library(user["id"])
    return {"token": auth.issue_token(user["id"]), "user": user, "created": created}


@app.post("/auth/google/link")
def google_link(body: GoogleCredential, user: dict = Depends(current_user)):
    claims = _google_claims(body.credential)
    try:
        return {"user": auth.link_identity(user["id"], "google", claims["sub"], claims)}
    except auth.IdentityConflict as e:
        raise HTTPException(409, str(e))
    except auth.AuthError as e:
        raise HTTPException(400, str(e))


@app.delete("/auth/identities/google")
def google_unlink(user: dict = Depends(current_user)):
    try:
        return {"user": auth.unlink_identity(user["id"], "google")}
    except auth.IdentityMissing as e:
        raise HTTPException(404, str(e))
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
```

(d) 同步 spec：在 `docs/specs/2026-10-28-google-login-design.md` 第 3 节接口表把 `/auth/google` 一行的「凭证无效 401」改成「凭证无效 400」，错误文案表里「凭证无效、过期、`aud` 不符」那一行状态码 `401` 改成 `400`，并在该表下加一句：「用 400 不用 401：前端把 401 当作登录过期并清空会话，已登录用户绑定时传了坏凭证不该被踢出。」

- [ ] **Step 4: 跑测试确认通过，并防回归**

Run:
```bash
cd backend && .venv/bin/python tests/server/test_google_login.py \
  && .venv/bin/python tests/server/test_identities.py \
  && .venv/bin/python tests/server/test_novels.py
```
Expected: 都以 `ALL PASS` 结束

- [ ] **Step 5: 提交**

```bash
git add backend/server/app.py backend/tests/server/test_google_login.py docs/specs/2026-10-28-google-login-design.md
git commit -m "Google 登录接口：/auth/config、/auth/google、绑定与解绑；凭证无效回 400 免得已登录用户被踢出，未配置 client ID 时 404"
```

---

### Task 4: 前端 API、类型与 GIS 加载

**Files:**
- Modify: `frontend/src/auth.ts`
- Modify: `frontend/src/api.ts`（`/* ---------- 认证 ---------- */` 一节）
- Create: `frontend/src/google.ts`

这一步只加类型与函数，没有界面；由 Task 5、6 的测试覆盖，本步以类型检查为准。

- [ ] **Step 1: `auth.ts`**

把 `export interface User {...}` 替换为：

```ts
export interface Identity {
  provider: string
  email: string
}

export interface User {
  id: string
  username: string
  created_at: string
  /** 第三方新建的账号没有密码：此时不能解绑（解了就登不进来） */
  has_password?: boolean
  identities?: Identity[]
}
```

在 `setSession` 之后加：

```ts
/** 绑定/解绑后用户信息变了，token 不变：只刷新缓存的用户 */
export function updateCachedUser(user: User): void {
  write(USER_KEY, JSON.stringify(user))
}
```

- [ ] **Step 2: `api.ts`**

在 `export function me()` 之后加：

```ts
export interface AuthConfig {
  google_client_id: string | null
  password_login: boolean
}

export function authConfig() {
  return req<AuthConfig>('/auth/config')
}

export function googleLogin(credential: string) {
  return req<{ token: string; user: User; created: boolean }>('/auth/google',
    jsonPost({ credential }))
}

export function googleLink(credential: string) {
  return req<{ user: User }>('/auth/google/link', jsonPost({ credential }))
}

export function googleUnlink() {
  return req<{ user: User }>('/auth/identities/google', { method: 'DELETE' })
}
```

- [ ] **Step 3: 新建 `frontend/src/google.ts`**

```ts
/** Google Identity Services（GIS）：官方登录按钮的脚本加载与最小类型。
 *
 *  脚本整页只加载一次；加载失败（网络打不开 Google）时下次再试。
 *  只声明用到的那几个方法，不引额外的类型包。
 */
export interface GsiCredentialResponse {
  credential: string
}

export interface Gsi {
  accounts: {
    id: {
      initialize(o: { client_id: string; callback: (r: GsiCredentialResponse) => void }): void
      renderButton(el: HTMLElement, o: Record<string, unknown>): void
    }
  }
}

declare global {
  interface Window {
    google?: Gsi
  }
}

const SRC = 'https://accounts.google.com/gsi/client'
let loading: Promise<Gsi> | null = null

export function loadGsi(): Promise<Gsi> {
  if (window.google?.accounts?.id) return Promise.resolve(window.google)
  if (loading) return loading
  loading = new Promise<Gsi>((resolve, reject) => {
    const s = document.createElement('script')
    s.src = SRC
    s.async = true
    s.onload = () => (window.google?.accounts?.id
      ? resolve(window.google)
      : reject(new Error('Google 登录脚本加载异常')))
    s.onerror = () => reject(new Error('Google 登录脚本加载失败'))
    document.head.appendChild(s)
  }).catch((e: unknown) => {
    loading = null
    throw e
  })
  return loading
}
```

- [ ] **Step 4: 类型检查**

Run: `cd frontend && npx tsc -b --force`
Expected: 无输出、退出码 0

- [ ] **Step 5: 提交**

```bash
git add frontend/src/auth.ts frontend/src/api.ts frontend/src/google.ts
git commit -m "前端 Google 登录基础：登录配置与 Google 登录/绑定/解绑接口、用户带 has_password 与 identities、GIS 脚本只加载一次"
```

---

### Task 5: 登录页的 Google 按钮

**Files:**
- Create: `frontend/src/components/GoogleButton.tsx`
- Modify: `frontend/src/components/LoginView.tsx`
- Modify: `frontend/src/index.css`（`.login__field` 那组规则之后）
- Modify: `frontend/tests/flow.test.tsx`（桩后端 `/healthz` 一行之后）
- Create: `frontend/tests/login.test.tsx`
- Modify: `frontend/package.json`（`test` 脚本）

- [ ] **Step 1: 写失败测试**

Create `frontend/tests/login.test.tsx`:

```tsx
/** 登录页与账号面板的界面回归：Google 按钮按配置出现、回调换 token、加载失败的提示，
 *  以及账号面板的绑定与解绑。GIS 用假对象代替，不连网。
 *
 *  跑法：npm test
 */
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement',
                 'Element', 'Node', 'Event', 'CustomEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k],
    writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true
win.localStorage.clear()

/* 假 GIS：记下最近一次 initialize 的回调，按钮渲染成一个可识别的占位 */
// 用对象装回调：在闭包里赋值的 let，TS 在顶层会把它收窄成 null
const gsi: { cb: (r: { credential: string }) => void; clientId: string } = {
  cb: () => { throw new Error('✗ GIS 尚未 initialize') }, clientId: '',
}
;(win as unknown as Record<string, unknown>).google = {
  accounts: { id: {
    initialize(o: { client_id: string; callback: (r: { credential: string }) => void }) {
      gsi.clientId = o.client_id
      gsi.cb = o.callback
    },
    renderButton(el: HTMLElement) { el.innerHTML = '<span class="fake-gsi">G</span>' },
  } },
}

/* 桩后端 */
let googleId: string | null = 'cid-test'
const calls: string[] = []
type U = { id: string; username: string; created_at: string; has_password: boolean;
           identities: { provider: string; email: string }[] }
let server: U = { id: 'u1', username: 'bob', created_at: '', has_password: true, identities: [] }
g.fetch = async (url: string, init?: { method?: string; body?: string }) => {
  const path = String(url).replace(/^\/api/, '')
  const method = init?.method ?? 'GET'
  calls.push(`${method} ${path}${init?.body ? ' ' + init.body : ''}`)
  const json = (data: unknown) => ({ ok: true, status: 200, json: async () => data })
  const err = (status: number, detail: string) => ({
    ok: false, status, text: async () => JSON.stringify({ detail }), json: async () => ({ detail }) })
  if (path === '/auth/config') return json({ google_client_id: googleId, password_login: true })
  if (path === '/auth/google' && method === 'POST') {
    const { credential } = JSON.parse(init!.body!)
    if (credential === 'bad') return err(400, 'Google 登录失败，请重试')
    return json({ token: 'tok-g', created: true,
                  user: { id: 'g1', username: 'alice', created_at: '', has_password: false,
                          identities: [{ provider: 'google', email: 'alice@gmail.com' }] } })
  }
  if (path === '/auth/google/link' && method === 'POST') {
    server = { ...server, identities: [{ provider: 'google', email: 'bob@gmail.com' }] }
    return json({ user: server })
  }
  if (path === '/auth/identities/google' && method === 'DELETE') {
    server = { ...server, identities: [] }
    return json({ user: server })
  }
  throw new Error(`桩后端未实现的路径: ${method} ${path}`)
}

const { act, useState } = await import('react')
const { createRoot } = await import('react-dom/client')
const { LoginView } = await import('../src/components/LoginView')
const { GoogleButton } = await import('../src/components/GoogleButton')
const { AccountPanel } = await import('../src/components/AccountPanel')
import type { ReactNode } from 'react'
import type { User } from '../src/auth'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const container = win.document.createElement('div')
win.document.body.appendChild(container)
let root = createRoot(container as unknown as HTMLElement)
const settle = async (ms = 30) => {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)) })
}
const has = (s: string) => container.innerHTML.includes(s)
const button = (text: string) => {
  const b = [...container.querySelectorAll('button')].find((x) => (x.textContent ?? '').includes(text))
  if (!b) throw new Error(`✗ 找不到按钮「${text}」`)
  return b as unknown as HTMLButtonElement
}
const remount = async (node: ReactNode) => {
  await act(async () => { root.unmount() })
  root = createRoot(container as unknown as HTMLElement)
  await act(async () => { root.render(node) })
  await settle()
}

// 1. 有 client ID：登录页顶部出 Google 按钮与分隔线，密码表单仍在
const got: { user: User | null } = { user: null }
await remount(<LoginView firstRun={false} onDone={(u) => { got.user = u }} />)
must(!!container.querySelector('.fake-gsi'), '应渲染 Google 按钮')
must(gsi.clientId === 'cid-test', '按配置的 client ID 初始化')
must(has('或使用用户名密码'), '应有分隔线')
must(!!container.querySelector('input[type=password]'), '密码表单应保留')
console.log('1. 有配置：Google 按钮 + 分隔线 + 密码表单 ✓')

// 2. Google 回调：换 token、存会话、进入
await act(async () => { gsi.cb({ credential: 'cred-1' }) })
await settle()
must(calls.includes('POST /auth/google {"credential":"cred-1"}'), `应把凭证发给后端：${calls.join(' | ')}`)
must(got.user?.username === 'alice', '应以 Google 用户进入')
must(win.localStorage.getItem('storyboard.token') === 'tok-g', '应保存 token')
console.log('2. 回调 → /auth/google → 保存会话并进入 ✓')

// 3. 后端拒绝：显示错误，不进入
got.user = null
await act(async () => { gsi.cb({ credential: 'bad' }) })
await settle()
must(has('Google 登录失败，请重试') && got.user === null, '应显示后端错误')
console.log('3. 凭证被拒显示错误 ✓')

// 4. 没配置：不出 Google 按钮与分隔线
googleId = null
await remount(<LoginView firstRun={false} onDone={() => {}} />)
must(!container.querySelector('.fake-gsi') && !has('或使用用户名密码'), '未配置不应出现 Google 登录')
console.log('4. 未配置不显示 ✓')

// 5. 脚本加载失败：提示不可用
await remount(<GoogleButton clientId="cid-test" onCredential={() => {}}
                            load={() => Promise.reject(new Error('net'))} />)
must(has('Google 登录暂不可用'), '加载失败应提示')
console.log('5. 加载失败提示 ✓')

console.log('\nALL PASS')
await act(async () => { root.unmount() })
```

> 第 6、7 段（账号面板）在 Task 6 追加到 `console.log('\nALL PASS')` 之前。本任务里先把 `AccountPanel` 的导入行也写上——它在 Task 6 才存在，所以 Step 2 的失败原因是缺 `GoogleButton` / `AccountPanel` 两个模块；Step 4 之前先建一个最小的 `AccountPanel` 占位（见 Step 3(d)），Task 6 再替换成完整实现。

- [ ] **Step 2: 加进测试脚本并确认失败**

`frontend/package.json` 的 `test` 脚本末尾（`node .ssrout/canvas.test.js` 之后）追加：

```
 && vite build --ssr tests/login.test.tsx --outDir .ssrout --logLevel error && node .ssrout/login.test.js
```

Run: `cd frontend && npm test`
Expected: FAIL，类型检查或构建报找不到 `../src/components/GoogleButton`

- [ ] **Step 3: 实现**

(a) Create `frontend/src/components/GoogleButton.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react'
import { loadGsi } from '../google'

interface Props {
  clientId: string
  onCredential: (credential: string) => void
  /** 按钮文案：登录页「使用 Google 登录」，绑定时「使用 Google 继续」 */
  text?: 'signin_with' | 'continue_with'
  /** 测试注入；默认加载官方脚本 */
  load?: typeof loadGsi
}

/** Google 官方登录按钮。GIS 的 initialize 是全局的，同一时刻只渲染一个按钮。 */
export function GoogleButton({ clientId, onCredential, text = 'signin_with', load = loadGsi }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const cb = useRef(onCredential)
  const [failed, setFailed] = useState(false)

  useEffect(() => { cb.current = onCredential })

  useEffect(() => {
    let alive = true
    load().then((gsi) => {
      if (!alive || !box.current) return
      gsi.accounts.id.initialize({ client_id: clientId, callback: (r) => cb.current(r.credential) })
      gsi.accounts.id.renderButton(box.current,
        { theme: 'outline', size: 'large', text, width: 280 })
    }).catch(() => { if (alive) setFailed(true) })
    return () => { alive = false }
  }, [clientId, text, load])

  if (failed) return <p className="gbtn gbtn--down">Google 登录暂不可用</p>
  return <div className="gbtn" ref={box} />
}
```

(b) `frontend/src/components/LoginView.tsx`：

- 第一行改为 `import { useEffect, useState } from 'react'`
- `import { login, register } from '../api'` 改为 `import { authConfig, googleLogin, login, register } from '../api'`
- 加一行 `import { GoogleButton } from './GoogleButton'`
- 在 `const [error, setError] = useState<string | null>(null)` 之后加：

```tsx
  /** 后端配了 client ID 才显示 Google 登录；取配置失败按未配置处理 */
  const [googleId, setGoogleId] = useState<string | null>(null)
  useEffect(() => {
    authConfig().then((c) => setGoogleId(c.google_client_id)).catch(() => setGoogleId(null))
  }, [])

  const google = async (credential: string) => {
    setBusy(true)
    setError(null)
    try {
      const { token, user } = await googleLogin(credential)
      setSession(token, user)
      onDone(user)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }
```

- 在 `<p className="login__sub">…</p>` 之后、`<div className="login__tabs">` 之前插入：

```tsx
        {googleId && (
          <>
            <GoogleButton clientId={googleId} onCredential={(c) => void google(c)} />
            <div className="login__or"><span>或使用用户名密码</span></div>
          </>
        )}
```

(c) `frontend/src/index.css` 在 `.login__field input` 那条规则之后加：

```css
.login__or {
  display: flex; align-items: center; gap: 10px;
  font-size: 12px; color: var(--faint);
}
.login__or::before, .login__or::after {
  content: ''; flex: 1; border-top: 1px solid var(--line-2);
}
.gbtn { display: flex; justify-content: center; min-height: 40px; }
.gbtn--down { font-size: 12px; color: var(--faint); align-items: center; margin: 0; }
```

(d) 占位 `frontend/src/components/AccountPanel.tsx`（Task 6 替换）：

```tsx
import type { User } from '../auth'

export function AccountPanel(_: { user: User; onUser: (u: User) => void; onClose: () => void }) {
  return null
}
```

(e) `frontend/tests/flow.test.tsx`：在 `if (path === '/healthz') return json({...})` 那条语句之后加一行（登录页现在会请求配置，桩后端没有这条会走到 401 分支）：

```ts
  if (path === '/auth/config') return json({ google_client_id: null, password_login: true })
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npm test`
Expected: 六个套件都以 `ALL PASS` 结束（`login.test` 打印 1–5 段 ✓）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/GoogleButton.tsx frontend/src/components/LoginView.tsx \
  frontend/src/components/AccountPanel.tsx frontend/src/index.css \
  frontend/tests/login.test.tsx frontend/tests/flow.test.tsx frontend/package.json
git commit -m "登录页加 Google 按钮：按后端配置出现、回调换 token 进入、脚本加载失败提示不可用，密码登录保留在分隔线下"
```

---

### Task 6: 账号面板（绑定与解绑）

**Files:**
- Modify: `frontend/src/components/AccountPanel.tsx`（替换占位）
- Modify: `frontend/src/App.tsx`（`.who` 那段与 imports）
- Modify: `frontend/src/index.css`（`.who__out:hover` 之后）
- Modify: `frontend/tests/login.test.tsx`

- [ ] **Step 1: 写失败测试**

在 `frontend/tests/login.test.tsx` 的 `console.log('\nALL PASS')` 之前插入：

```tsx
// 6. 账号面板：有密码、未绑定 → 显示 Google 按钮；回调 → 绑定；解除绑定 → 清空
googleId = 'cid-test'
function Host({ initial }: { initial: User }) {
  const [u, setU] = useState<User>(initial)
  return <AccountPanel user={u} onUser={setU} onClose={() => {}} />
}
await remount(<Host initial={server} />)
must(!!container.querySelector('.fake-gsi'), '未绑定时应显示 Google 按钮')
await act(async () => { gsi.cb({ credential: 'cred-link' }) })
await settle()
must(calls.includes('POST /auth/google/link {"credential":"cred-link"}'), '应请求绑定')
must(has('bob@gmail.com'), '绑定后显示 Google 邮箱')
const unlink = button('解除绑定')
must(!unlink.disabled, '有密码时可解绑')
await act(async () => { unlink.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event) })
await settle()
must(calls.includes('DELETE /auth/identities/google'), '应请求解绑')
must(!has('bob@gmail.com') && !!container.querySelector('.fake-gsi'), '解绑后回到可绑定状态')
console.log('6. 账号面板：绑定 / 解绑 ✓')

// 7. 无密码的 Google 账号：解绑禁用并说明原因
await remount(<Host initial={{ id: 'g1', username: 'alice', created_at: '', has_password: false,
                               identities: [{ provider: 'google', email: 'alice@gmail.com' }] }} />)
must(button('解除绑定').disabled, '无密码时解绑应禁用')
must(has('账号没有设置密码，解除绑定后将无法登录'), '应说明原因')
console.log('7. 无密码账号禁止解绑 ✓')
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm test`
Expected: `login.test` 在第 6 段失败：`✗ 未绑定时应显示 Google 按钮`

- [ ] **Step 3: 实现**

(a) 替换 `frontend/src/components/AccountPanel.tsx`：

```tsx
import { useEffect, useState } from 'react'
import { authConfig, googleLink, googleUnlink } from '../api'
import type { User } from '../auth'
import { GoogleButton } from './GoogleButton'

interface Props {
  user: User
  onUser: (u: User) => void
  onClose: () => void
}

/** 账号面板：看已绑定的登录方式，绑定或解绑 Google。 */
export function AccountPanel({ user, onUser, onClose }: Props) {
  const [googleId, setGoogleId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    authConfig().then((c) => setGoogleId(c.google_client_id)).catch(() => setGoogleId(null))
  }, [])

  const google = user.identities?.find((i) => i.provider === 'google')

  const run = async (fn: () => Promise<{ user: User }>) => {
    setBusy(true)
    setError(null)
    try {
      onUser((await fn()).user)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="acct" role="dialog" aria-label="账号">
      <div className="acct__head">
        <b>{user.username}</b>
        <button className="acct__close" aria-label="关闭" onClick={onClose}>×</button>
      </div>
      <div className="acct__row">
        <span className="acct__k">Google</span>
        {google ? (
          <>
            <span className="acct__v">{google.email}</span>
            <button className="btn btn--sm btn--ghost" disabled={busy || !user.has_password}
                    onClick={() => void run(googleUnlink)}>
              解除绑定
            </button>
          </>
        ) : googleId ? (
          <GoogleButton clientId={googleId} text="continue_with"
                        onCredential={(c) => void run(() => googleLink(c))} />
        ) : (
          <span className="acct__v acct__v--muted">未启用</span>
        )}
      </div>
      {google && !user.has_password && (
        <p className="acct__note">账号没有设置密码，解除绑定后将无法登录。</p>
      )}
      {error && <p className="acct__err">{error}</p>}
    </div>
  )
}
```

(b) `frontend/src/App.tsx`：

- 加 `import { AccountPanel } from './components/AccountPanel'`
- 在从 `'./auth'` 导入的那一行里加上 `updateCachedUser`
- 在 `const [user, setUser] = useState<User | null>(...)` 之后加 `const [acct, setAcct] = useState(false)`
- `logout` 里加一行 `setAcct(false)`
- 把 `.who` 那段替换为：

```tsx
          <span className="who" title={`已登录：${user.username}`}>
            {user.username}
            <button className="who__out who__acct" onClick={() => setAcct((v) => !v)}>账号</button>
            <button className="who__out" onClick={logout}>退出</button>
            {acct && (
              <AccountPanel
                user={user}
                onUser={(u) => { updateCachedUser(u); setUser(u) }}
                onClose={() => setAcct(false)}
              />
            )}
          </span>
```

(c) `frontend/src/index.css` 在 `.who__out:hover {...}` 之后加：

```css
.who { position: relative; }
.who__acct:hover { color: var(--accent); border-color: var(--accent); }
.acct {
  position: absolute; top: calc(100% + 8px); right: 0; z-index: 40;
  width: 320px; padding: 14px; display: flex; flex-direction: column; gap: 10px;
  background: var(--bg, #fff); border: 1px solid var(--line); border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, .12);
}
.acct__head { display: flex; justify-content: space-between; align-items: center; }
.acct__close { border: none; background: none; cursor: pointer; font-size: 16px; color: var(--faint); }
.acct__row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.acct__k { width: 56px; font-size: 12px; color: var(--muted); }
.acct__v { flex: 1; font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; }
.acct__v--muted { color: var(--faint); }
.acct__note { margin: 0; font-size: 12px; color: var(--muted); }
.acct__err { margin: 0; font-size: 12px; color: var(--danger); }
```

> 如果 `index.css` 里没有 `--bg` 变量，保留 `#fff` 兜底即可；不要新增全局变量。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npm test`
Expected: 六个套件都以 `ALL PASS` 结束（`login.test` 打印 1–7 段 ✓）

- [ ] **Step 5: 构建检查**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/AccountPanel.tsx frontend/src/App.tsx frontend/src/index.css frontend/tests/login.test.tsx
git commit -m "账号面板：用户名旁「账号」查看绑定的 Google 邮箱，未绑定可绑定，有密码时可解绑，无密码账号禁止解绑并说明原因"
```

---

### Task 7: 文档与配置说明

**Files:**
- Modify: `backend/.env.example`
- Modify: `README.md`
- Modify: `frontend/README.md`

- [ ] **Step 1: `backend/.env.example`**

在 `# STORYBOARD_SERVER_WORKERS=1 ...` 那行之后加：

```
# STORYBOARD_GOOGLE_CLIENT_ID=        # 启用 Google 登录：Google Cloud「OAuth 客户端 ID（Web 应用）」；
#                                     #   不填则登录页不显示 Google 按钮。client ID 是公开值，不需要 secret
# HTTPS_PROXY=                        # 后端访问 Google 校验登录（取公钥）走的代理；部署在海外不需要
```

- [ ] **Step 2: 根 `README.md`**

在「方式一」HTTP 服务那段 curl 示例之后（`docker run ...` 之前）加一段：

```markdown
**登录方式**：用户名 + 密码，或 Google 账号（配置 `STORYBOARD_GOOGLE_CLIENT_ID` 后出现）。
已有账号可在右上角「账号」里绑定 Google，之后两种方式进的是同一个账号。
Google Cloud 配置：OAuth 同意屏幕选外部、范围 `openid email profile`；凭证选「OAuth 客户端 ID → Web 应用」，
「已获授权的 JavaScript 来源」填 `http://localhost:5173`、`http://localhost` 和正式域名，不需要回调地址。
国内开发时浏览器要能访问 Google，后端配 `HTTPS_PROXY`。
```

- [ ] **Step 3: `frontend/README.md`**

在讲登录或会话的段落附近（找不到就加在文件末尾）加：

```markdown
### 登录

登录页先请求 `/auth/config`：后端配了 Google client ID 就在顶部显示官方「使用 Google 登录」按钮
（Google Identity Services，脚本整页只加载一次，加载失败显示「Google 登录暂不可用」），下面保留用户名密码表单。
Google 回调拿到的 ID token 交给 `/auth/google`，换回与密码登录同一种 token。
右上角「账号」面板可绑定、解绑 Google；没有密码的账号不能解绑。界面回归见 `tests/login.test.tsx`。
```

- [ ] **Step 4: 全量回归**

Run:
```bash
cd backend && for t in tests/server/test_*.py; do .venv/bin/python $t || break; done
cd ../frontend && npm test && npm run build
```
Expected: 后端每个文件 `ALL PASS`；前端六个套件 `ALL PASS`；构建成功

- [ ] **Step 5: 提交**

```bash
git add backend/.env.example README.md frontend/README.md
git commit -m "文档：Google 登录的配置项、Google Cloud 设置步骤与国内开发的代理说明"
```

---

### Task 8: 手动验证（需要用户配合）

自动测试不连 Google，真实登录必须手动走一遍。这一步不改代码。

- [ ] **Step 1: 用户在 Google Cloud 建好 client ID**（spec 第 5 节），写入 `backend/.env` 的 `STORYBOARD_GOOGLE_CLIENT_ID`；国内网络下同时配置 `HTTPS_PROXY`。
- [ ] **Step 2: 启动服务**：`cd backend && .venv/bin/uvicorn server.app:app --port 8000`，`cd frontend && npm run dev`。
- [ ] **Step 3: 新用户登录**：退出后在登录页点 Google 按钮登录一个从未用过的 Google 账号 → 进入后右上角用户名为邮箱前缀；「账号」面板显示该邮箱且「解除绑定」禁用。
- [ ] **Step 4: 绑定已有账号**：退出，用原有用户名密码登录 → 「账号」→ 用另一个 Google 账号绑定 → 显示邮箱；退出后用这个 Google 账号登录，进入的是原账号（小说列表不变）。
- [ ] **Step 5: 解绑**：在原账号「账号」面板解除绑定 → 邮箱消失；再用该 Google 账号登录会新建一个账号（预期行为）。
- [ ] **Step 6: 把结果记在本计划末尾**（成功或遇到的错误原文），不提交 `.env`。
