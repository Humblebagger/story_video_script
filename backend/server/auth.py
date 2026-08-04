"""用户与会话。

多用户下每个人的历史记录与资产库互相隔离，隔离靠 user_id 分目录实现
（见 store.py / library.py 的 user_dir）。

口令用 PBKDF2-HMAC-SHA256 存哈希，会话用 HMAC 签名的自包含 token——
都走标准库，不引第三方依赖；token 自包含意味着服务重启不会把所有人踢下线。
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from pathlib import Path
from typing import Optional

from pipeline.config import ROOT

_DATA_DIR_OVERRIDDEN = "STORYBOARD_DATA_DIR" in os.environ
DATA_DIR = Path(os.environ.get("STORYBOARD_DATA_DIR", ROOT / "data"))
USERS_FILE = DATA_DIR / "users.json"
SECRET_FILE = DATA_DIR / "secret.key"

# 单用户时代的历史记录，归给首个注册用户。
# 只在「原地升级」时才接管：一旦显式指定了 STORYBOARD_DATA_DIR（测试、多实例、
# 另起一套数据），就不该去动别处的真实数据——搬错一次就是用户产物凭空消失。
# 需要在自定义数据目录下迁移时，显式给出 STORYBOARD_LEGACY_RUNS。
_LEGACY_ENV = os.environ.get("STORYBOARD_LEGACY_RUNS")
LEGACY_RUNS = (Path(_LEGACY_ENV) if _LEGACY_ENV
               else (None if _DATA_DIR_OVERRIDDEN else ROOT / "runs"))

TOKEN_TTL = int(os.environ.get("STORYBOARD_TOKEN_TTL", 30 * 24 * 3600))
PBKDF2_ROUNDS = 200_000

USERNAME_RE = re.compile(r"^[\w一-龥.-]{2,32}$")
MIN_PASSWORD = 6

_lock = threading.RLock()


class AuthError(Exception):
    """凭据/注册相关的可预期错误，由 app.py 翻成 4xx。"""


def _secret() -> bytes:
    """签名密钥：优先取环境变量，否则在数据目录里生成一份并复用。"""
    env = os.environ.get("STORYBOARD_SECRET")
    if env:
        return env.encode()
    with _lock:
        if SECRET_FILE.exists():
            return SECRET_FILE.read_bytes()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(32)
        SECRET_FILE.write_bytes(key)
        SECRET_FILE.chmod(0o600)
        return key


def _load_users() -> list:
    if not USERS_FILE.exists():
        return []
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_users(users: list) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = USERS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(users, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(USERS_FILE)


def user_dir(user_id: str) -> Path:
    """每个用户一个数据目录——隔离的落点。"""
    if not re.fullmatch(r"[0-9a-f]{12}", user_id):
        raise AuthError(f"非法的用户 ID：{user_id!r}")
    return DATA_DIR / "users" / user_id


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()


def _public(u: dict) -> dict:
    return {"id": u["id"], "username": u["username"], "created_at": u["created_at"]}


def user_count() -> int:
    return len(_load_users())


def register(username: str, password: str) -> dict:
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        raise AuthError("用户名需为 2–32 位的中英文、数字、下划线、点或连字符")
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"密码至少 {MIN_PASSWORD} 位")

    with _lock:
        users = _load_users()
        if any(u["username"].lower() == username.lower() for u in users):
            raise AuthError("用户名已被占用")
        salt = secrets.token_hex(16)
        user = {
            "id": secrets.token_hex(6),
            "username": username,
            "salt": salt,
            "password_hash": _hash(password, salt),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        }
        first = not users
        users.append(user)
        _save_users(users)
        user_dir(user["id"]).mkdir(parents=True, exist_ok=True)
        if first:
            _adopt_legacy_runs(user["id"])
    return _public(user)


def _adopt_legacy_runs(user_id: str) -> int:
    """把单用户时代 runs/ 里的记录移交给首个注册用户，避免旧产物凭空消失。"""
    if LEGACY_RUNS is None or not LEGACY_RUNS.is_dir():
        return 0
    files = sorted(LEGACY_RUNS.glob("*.json"))
    if not files:
        return 0
    dest = user_dir(user_id) / "runs"
    dest.mkdir(parents=True, exist_ok=True)
    moved = 0
    for src in files:
        target = dest / src.name
        if target.exists():
            continue
        try:
            src.replace(target)
            moved += 1
        except OSError:
            continue
    print(f"[auth] 已把 {moved} 条历史记录移交给首个注册用户 {user_id}", flush=True)
    return moved


def authenticate(username: str, password: str) -> dict:
    users = _load_users()
    for u in users:
        if u["username"].lower() == (username or "").strip().lower():
            # compare_digest 防时序侧信道
            if hmac.compare_digest(_hash(password or "", u["salt"]), u["password_hash"]):
                return _public(u)
            break
    raise AuthError("用户名或密码不正确")


def get_user(user_id: str) -> Optional[dict]:
    for u in _load_users():
        if u["id"] == user_id:
            return _public(u)
    return None


def issue_token(user_id: str) -> str:
    """自包含 token：base64(user_id:过期时间).hmac —— 无需服务端会话表。"""
    payload = f"{user_id}:{int(time.time()) + TOKEN_TTL}".encode()
    body = urlsafe_b64encode(payload).decode().rstrip("=")
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(token: str) -> Optional[dict]:
    try:
        body, sig = (token or "").split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        pad = "=" * (-len(body) % 4)
        user_id, exp = urlsafe_b64decode(body + pad).decode().split(":")
    except (ValueError, UnicodeDecodeError):
        return None
    if int(exp) < time.time():
        return None
    return get_user(user_id)
