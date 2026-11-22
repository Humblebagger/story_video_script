"""内容检查的判定入口（spec §2.5）。统一顺序：结论缓存（含放行）→ 词表 → 模型分类。

check_sync：转换任务、合成任务用（已在后台线程，允许等几秒）。
lookup + classify_async：出片线程用——tick 里只查缓存与词表，要调模型的交给本模块自己的线程池。
环境变量 STORYBOARD_SAFETY=0 整体关闭（缺省开启）。
"""
import logging
import os
import threading
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from pipeline.config import load_settings
from safety import blocklist, classifier, store
from safety.categories import UNSPECIFIED
from safety.text import normalize, text_hash
from server import usage
from server.messages import UserError, msg, ref, with_ref

log = logging.getLogger("safety.gate")

BLOCKLIST_REASON = "safety.reason.blocklist"


class SafetyBlocked(UserError, Exception):
    """内容被拦下：消息 safety.blocked，带类别引用与拦截编号。"""


class SafetyUnavailable(UserError, Exception):
    """暂时无法完成检查（不放行）。"""


def enabled() -> bool:
    return os.environ.get("STORYBOARD_SAFETY", "1").strip() != "0"


def blocked_error(category: str, block_id: str) -> SafetyBlocked:
    m = with_ref(msg("safety.blocked", category=ref(f"safety.category.{category}")), block_id)
    return SafetyBlocked.from_msg(m)


def unavailable_error() -> SafetyUnavailable:
    return SafetyUnavailable.of("safety.unavailable")


@contextmanager
def _guard():
    """存储层写盘失败（磁盘满、无权限等）一律按「暂时无法检查」处理，不放行。"""
    try:
        yield
    except OSError as e:
        log.warning("内容检查存储失败：%s", type(e).__name__)  # i18n: internal
        raise unavailable_error() from e


def _make_chat():
    """分类用的模型调用（测试替换这个名字）。"""
    return classifier.make_chat()


def _local(text: str, ctx: dict):
    """缓存与词表能定的结论：("pass",) / ("block", 编号, 类别)；定不了返回 None。"""
    with _guard():
        v = store.get_verdict(text_hash(text))
        if v is not None and v["verdict"] == "pass":
            return ("pass",)
        if v is not None and v["verdict"] == "block":
            store.touch_block(v["block_id"])
            return ("block", v["block_id"], v["category"])
        category = blocklist.match(text)
        if category:
            bid = store.record_block(text, category=category, reason_code=BLOCKLIST_REASON, ctx=ctx)
            return ("pass",) if bid is None else ("block", bid, category)    # None：同时被管理员放行了
        return None


def _record_usage(chat, ctx: dict, ok: bool) -> None:
    try:
        totals = chat.usage_totals()
        if totals.get("calls"):
            usage.record(user_id=ctx.get("user_id") or "", purpose="safety", model=load_settings().model,
                         usage=totals, ok=ok, novel_id=ctx.get("novel_id"),
                         chapter_id=ctx.get("chapter_id"), version_id=ctx.get("version_id"))
    except Exception as e:  # noqa: BLE001  落账失败不能影响判定
        log.warning("内容检查落账失败：%r", e)  # i18n: internal


def _classify(text: str, ctx: dict):
    """调模型并把结论落盘：("pass",) / ("block", 编号, 类别)。分不出结论抛 SafetyUnavailable。"""
    chat, ok = None, False
    try:
        chat = _make_chat()
        verdict = classifier.classify(text, chat)
        ok = True
    except classifier.Unavailable as e:
        log.warning("内容检查不可用 stage=%s 原因=%s", ctx.get("stage"), e)  # i18n: internal
        raise unavailable_error() from e
    except Exception as e:  # noqa: BLE001  建不起模型（没配置等）同样不放行
        log.warning("内容检查不可用 stage=%s %s", ctx.get("stage"), type(e).__name__)  # i18n: internal
        raise unavailable_error() from e
    finally:
        if chat is not None:
            _record_usage(chat, ctx, ok)
    with _guard():
        if not verdict.blocked:
            store.set_pass(text_hash(text))
            return ("pass",)
        if verdict.refused:
            bid = store.record_block(text, category=UNSPECIFIED, reason_code=store.REFUSED, ctx=ctx, cache=False)
            return ("pass",) if bid is None else ("block", bid, UNSPECIFIED)
        bid = store.record_block(text, category=verdict.category, reason=verdict.reason, ctx=ctx)
        return ("pass",) if bid is None else ("block", bid, verdict.category)


def check_sync(text, ctx: dict) -> None:
    """同步检查。拦截抛 SafetyBlocked，分不出结论抛 SafetyUnavailable，通过返回 None。"""
    body = normalize(text)
    if not enabled() or not body:
        return
    result = _local(body, ctx) or _classify(body, ctx)
    if result[0] == "block":
        raise blocked_error(result[2], result[1])


def check_items_sync(items, ctx: dict) -> None:
    """分条检查（转换前的注入文本用）：每条各自查缓存与词表；只有没缓存的拼成一次分类（空行分隔）。
    通过则每条都记通过；拦截按拼接文本记录。拦截抛 SafetyBlocked，分不出结论抛 SafetyUnavailable。"""
    if not enabled():
        return
    todo, seen = [], set()
    for item in items:
        body = normalize(item)
        h = text_hash(body) if body else None
        if not body or h in seen:
            continue
        seen.add(h)
        result = _local(body, ctx)
        if result is None:
            todo.append(body)
        elif result[0] == "block":
            raise blocked_error(result[2], result[1])
    if not todo:
        return
    result = _classify("\n\n".join(todo), ctx)
    if result[0] == "block":
        raise blocked_error(result[2], result[1])
    with _guard():
        for body in todo:
            store.set_pass(text_hash(body))


# ---------- 出片线程用：不在 tick 里调模型 ----------

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="safety")
_plock = threading.Lock()
_pending: set = set()      # 正在排队或分类中的文本 hash
_waiters: dict = {}        # hash → 正在等这次分类结果的调用方个数
_temp: dict = {}           # hash → [结论, 还剩几个等待者要读]：只在进程内、不进结论缓存的终态
                           # 结论是 ("unavailable",)，或模型拒答的 ("block", 编号, 类别)；读完即清


def pending() -> int:
    with _plock:
        return len(_pending)


def _take_temp(h: str):
    with _plock:
        entry = _temp.get(h)
        if entry is None:
            return None
        entry[1] -= 1
        if entry[1] <= 0:
            del _temp[h]
        return entry[0]


def lookup(text, ctx: dict):
    """只查缓存与词表（毫秒级）：("pass",) / ("block", 编号, 类别) / ("unavailable",)；还不知道返回 None。
    异步分类的临时终态（不可用、模型拒答）每个等待者读到一次，读完清掉，再来就是 None（重新分类）。"""
    body = normalize(text)
    if not enabled() or not body:
        return ("pass",)
    try:
        result = _local(body, ctx)
    except SafetyUnavailable:
        return ("unavailable",)
    if result is not None:
        return result
    return _take_temp(text_hash(body))


def classify_async(text, ctx: dict) -> bool:
    """把分类交给专用线程池。同一文本已在排队返回 False（调用方也算一个等待者，各读一次结果）。"""
    body = normalize(text)
    h = text_hash(body)
    with _plock:
        _waiters[h] = _waiters.get(h, 0) + 1
        if h in _pending:
            return False
        _pending.add(h)
        _temp.pop(h, None)

    def job():
        final = None
        try:
            r = _classify(body, dict(ctx))
            if r[0] == "block" and store.get_verdict(h) is None:
                final = r            # 没写进结论缓存的拦截（模型拒答）：只交给等待者
        except Exception:  # noqa: BLE001  含 SafetyUnavailable：等待者读到 unavailable
            final = ("unavailable",)
        finally:
            with _plock:
                n = _waiters.pop(h, 1)
                if final is not None:
                    _temp[h] = [final, max(1, n)]
                _pending.discard(h)

    _pool.submit(job)
    return True
