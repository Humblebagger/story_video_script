"""内容检查的判定入口（spec §2.5）。统一顺序：结论缓存（含放行）→ 词表 → 模型分类。

check_sync：转换任务、合成任务用（已在后台线程，允许等几秒）。
lookup + classify_async：出片线程用——tick 里只查缓存与词表，要调模型的交给本模块自己的线程池。
环境变量 STORYBOARD_SAFETY=0 整体关闭（缺省开启）。
"""
import itertools
import logging
import os
import threading
import time
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


def _cached(text: str):
    """只查结论缓存（含放行）：("pass",) / ("block", 编号, 类别)；没有返回 None。"""
    v = store.get_verdict(text_hash(text))
    if v is not None and v["verdict"] == "pass":
        return ("pass",)
    if v is not None and v["verdict"] == "block":
        store.touch_block(v["block_id"])
        return ("block", v["block_id"], v["category"])
    return None


def _local(text: str, ctx: dict):
    """缓存与词表能定的结论：("pass",) / ("block", 编号, 类别)；定不了返回 None。"""
    with _guard():
        hit = _cached(text)
        if hit is not None:
            return hit
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
    joined = "\n\n".join(todo)
    with _guard():
        result = _cached(joined)          # 合并文本也先看缓存：重复拦截不重新分类，放行后分类器不可用也能过
    if result is None:
        result = _classify(joined, ctx)
    if result[0] == "block":
        raise blocked_error(result[2], result[1])
    with _guard():
        for body in todo:
            store.set_pass(text_hash(body))


# ---------- 出片线程用：不在 tick 里调模型 ----------

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="safety")
_plock = threading.Lock()
# 票据模型：每个等待者有代次 gen（forget 加一）；登记以 (等待者, 代次) 为单位，叫一张票据。
# 每个分类任务记下绑定给它的票据集合；临时终态只交给这些票据里代次仍有效的。
_jobs: dict = {}           # 任务号 → {"h": 文本 hash, "tickets": {等待者键: 代次}}（只含正在排队或分类中的任务）
_by_hash: dict = {}        # 文本 hash → [任务号, ...]（启动先后顺序；同一 hash 允许新旧任务并存）
_gen: dict = {}            # 等待者键 → 当前代次（第一次登记即为 0）
_temp: dict = {}           # (hash, 等待者键) → (结论, 时刻)：只在进程内、不进结论缓存的临时终态
                           # 结论是 ("unavailable",)，或模型拒答的 ("block", 编号, 类别)；该等待者读一次即清
TEMP_TTL_SEC = 600.0       # 没人来读的临时结论超时即视为不存在
_now = time.monotonic
_job_ids = itertools.count(1)


def pending() -> int:
    """正在排队或分类中的任务数。"""
    with _plock:
        return len(_jobs)


def forget(waiter, prefix: bool = False) -> None:
    """这个等待者不等了（片段取消、重新排队、会话移除）：代次加一、清掉它的未读结论。
    它在正在跑的任务里的旧票据留着但已失效：旧任务的临时终态不再交给它，它再登记也不会并入旧任务。
    prefix=True 时 waiter 是元组前缀，批量处理（登记过的等待者都有代次，都能被前缀命中）。"""
    def hit(w):
        return (isinstance(w, tuple) and w[:len(waiter)] == waiter) if prefix else w == waiter
    with _plock:
        for k in [k for k in _temp if hit(k[1])]:
            del _temp[k]
        for w in {w for w in _gen if hit(w)} | ({waiter} if not prefix else set()):
            _gen[w] = _gen.get(w, 0) + 1


def lookup(text, ctx: dict, waiter=None):
    """先查这个等待者的临时结论（读一次即清，超过有效期当作没有），再查缓存与词表（毫秒级）：
    ("pass",) / ("block", 编号, 类别) / ("unavailable",)；还不知道返回 None。
    waiter：稳定的等待者键（出片线程用 (用户, 小说, 章节, 版本, 片段)）；不传则所有匿名调用方共用一个键。"""
    body = normalize(text)
    if not enabled() or not body:
        return ("pass",)
    with _plock:
        entry = _temp.pop((text_hash(body), waiter), None)
    if entry is not None and _now() - entry[1] <= TEMP_TTL_SEC:
        return entry[0]
    try:
        return _local(body, ctx)
    except SafetyUnavailable:
        return ("unavailable",)


def classify_async(text, ctx: dict, waiter=None) -> bool:
    """以 (等待者, 当前代次) 登记，并按需把分类交给专用线程池。起了新任务返回 True，否则 False：
    - 该 (文本, 等待者) 已有没读走的结论：不删它、不登记（下一次 lookup 交付）；
    - 这张票据已登记在某个正在跑的任务里：不重复登记；
    - 最新的那个同文本任务里没有这个等待者：并入它（同代次加入正在运行的任务）；
    - 否则（没有任务，或最新任务里只有它 forget 之前的旧票据）：另起一个任务。"""
    body = normalize(text)
    h = text_hash(body)
    with _plock:
        if (h, waiter) in _temp:
            return False
        g = _gen.setdefault(waiter, 0)
        ids = _by_hash.get(h, [])
        if any(_jobs[j]["tickets"].get(waiter, -1) == g for j in ids):
            return False
        if ids and waiter not in _jobs[ids[-1]]["tickets"]:
            _jobs[ids[-1]]["tickets"][waiter] = g
            return False
        jid = next(_job_ids)
        _jobs[jid] = {"h": h, "tickets": {waiter: g}}
        _by_hash.setdefault(h, []).append(jid)

    def job():
        final = None
        try:
            r = _classify(body, dict(ctx))
            if r[0] == "block" and store.get_verdict(h) is None:
                final = r            # 没写进结论缓存的拦截（模型拒答）：只交给票据
        except Exception:  # noqa: BLE001  含 SafetyUnavailable：票据读到 unavailable
            final = ("unavailable",)
        finally:
            with _plock:
                tickets = _jobs.pop(jid)["tickets"]
                rest = [j for j in _by_hash.get(h, []) if j != jid]
                if rest:
                    _by_hash[h] = rest
                else:
                    _by_hash.pop(h, None)
                if final is not None:
                    now = _now()
                    for w, tg in tickets.items():
                        if _gen.get(w, 0) == tg:
                            _temp[(h, w)] = (final, now)

    _pool.submit(job)
    return True
