"""错误参考编号（设计 docs/specs/2026-11-13-backend-i18n-design.md「子计划 3 范围补充」B）。

意外失败时给用户一个 8 位编号；同一编号的完整记录（脱敏后的堆栈、位置、用户）写进
DATA_DIR/error_refs.jsonl（保留最近 MAX_ROWS 条）与日志，管理后台按编号查。
只记堆栈或原文，不记请求体、请求头、查询串、局部变量。
"""
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import traceback
from pathlib import Path
from typing import Optional

from render.providers.base import scrub_secrets
from server import auth, usage
from server.messages import msg, with_ref
from server.store import now_iso

log = logging.getLogger("server.errors")

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"      # 32 个：去掉易混的 I L O U
REF_LEN = 8
MAX_ROWS = 1000                                    # 保留最近这么多条；超过两倍时整体裁剪
DETAIL_MAX = 8000

_lock = threading.Lock()
_rows: dict = {}                                   # 文件路径 → 当前行数（首次写时数一遍）


def _file() -> Path:
    return auth.DATA_DIR / "error_refs.jsonl"


def new_ref() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(REF_LEN))


_CROCKFORD = str.maketrans({"O": "0", "I": "1", "L": "1"})


def normalize(ref) -> str:
    """用户转述的编号：忽略大小写、空格与连字符；按 Crockford 把 O 当 0、I/L 当 1；只留 0-9A-Z。"""
    return re.sub(r"[^0-9A-Z]", "", str(ref or "").upper().translate(_CROCKFORD))


def user_of_root(root) -> Optional[str]:
    """DATA_DIR/users/<uid>/… → uid（后台线程只有会话目录时用）；不在 DATA_DIR/users 下时 None。"""
    try:
        uid = Path(str(root)).resolve().relative_to((auth.DATA_DIR / "users").resolve()).parts[0]
    except (ValueError, IndexError, OSError):
        return None
    return uid if re.fullmatch(r"[0-9a-f]{12}", uid) else None


def _rel(text: str) -> str:
    """服务器上的数据目录换成 <data>：位置与堆栈里不留主机的绝对路径。"""
    for d in {str(auth.DATA_DIR.resolve()), str(auth.DATA_DIR)}:
        text = text.replace(d, "<data>")
    return text


def scrub_text(text: str, secrets_extra=()) -> str:
    """日志文字统一脱敏：密钥抹掉、数据目录换成 <data>（record 与调用方的二次失败日志共用）。"""
    return _rel(scrub_secrets(str(text), secrets_extra))


def _clip(text: str) -> str:
    """截断到 DETAIL_MAX：保留头尾。链式异常先打印原因，最后一行才是最终异常，不能被截掉。"""
    if len(text) <= DETAIL_MAX:
        return text
    head = 2000
    return text[:head] + "\n…\n" + text[-(DETAIL_MAX - head - 3):]


def _trim_locked(path: Path) -> None:
    keep = path.read_text(encoding="utf-8").splitlines()[-MAX_ROWS:]
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".error_refs.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(keep) + "\n")
        os.replace(tmp, path)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        raise


def record(code: str, detail, *, params: Optional[dict] = None, user_id: Optional[str] = None,
           where: str = "", secrets_extra=(), logger: Optional[logging.Logger] = None) -> str:
    """记一条，返回编号。detail 先脱敏再截断；同一内容写一条 ERROR 日志（logger 缺省为 server.errors）。
    写盘失败只记日志，编号照常返回：记账不能拖垮报错本身。"""
    ref = new_ref()
    clean = _clip(_rel(scrub_secrets(str(detail), secrets_extra)))
    where = _rel(scrub_secrets(str(where or ""), secrets_extra))
    (logger or log).error("ref=%s code=%s user=%s where=%s\n%s", ref, code, user_id or "-", where, clean)
    row = {"ref": ref, "at": now_iso(), "user_id": user_id, "code": code,
           "params": params or {}, "where": where, "detail": clean}
    try:
        with _lock:
            path = _file()
            path.parent.mkdir(parents=True, exist_ok=True)
            key = str(path)
            if key not in _rows:
                if path.exists():
                    with open(path, encoding="utf-8") as f:
                        _rows[key] = sum(1 for _ in f)
                else:
                    _rows[key] = 0
            with open(path, "a", encoding="utf-8") as f:
                usage.ensure_line_start(path, f)
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            _rows[key] += 1
            if _rows[key] > 2 * MAX_ROWS:
                _trim_locked(path)
                _rows[key] = MAX_ROWS
    except OSError as werr:
        # 不用 log.exception：exc_info 的 __context__ 链会带出正在处理的业务异常（可能含密钥），绕过脱敏
        log.error("错误记录写盘失败 ref=%s %s", ref, _rel(scrub_secrets(f"{type(werr).__name__}: {werr}", secrets_extra)))  # i18n: internal
    return ref


def record_exc(e: BaseException, code: str, *, context: str = "", **kw) -> str:
    """异常 → 一条记录（完整堆栈，含 __cause__/__context__ 链）。context 是放在堆栈前的定位文字。"""
    tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
    return record(code, f"{context}\n{tb}" if context else tb, **kw)


def unexpected(e: BaseException, code: str = "common.internal", **kw) -> dict:
    """意外异常 → 带编号的消息对象。code 的模板不得有参数（这类文案只说「出了问题、联系管理员」）。"""
    return with_ref(msg(code), record_exc(e, code, **kw))


def _read() -> list:
    path = _file()
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def recent(limit: int = 200) -> list:
    return list(reversed(_read()))[:limit]


def find(ref) -> Optional[dict]:
    want = normalize(ref)
    return next((r for r in reversed(_read()) if r.get("ref") == want), None) if want else None
