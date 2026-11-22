"""出片会话：一个版本的出片状态（chapters/<cid>/render/<vid>/session.json）与全部状态迁移。

接口线程与出片线程都只通过这里改状态：同一会话的读改写用进程内锁串行，写入先写临时文件再改名。
段状态（设计文档 1.5）：planned → queued → running → downloading → done；failed；stale（指纹与
当前分镜不符，旧视频仍可播）。每段保留全部尝试，chosen 指向采用的那次。
"""
import json
import logging
import os
import re
import shutil
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from render import compose
from render.providers import base, default_fell_back, default_video_name, get_video, names
from server.messages import UserError, compact, money, msg, render_zh, vendor

log = logging.getLogger("render.session")


SESSION_FILE = "session.json"
IN_FLIGHT = ("queued", "running", "downloading")
ABANDONED = "abandoned"     # 尝试的状态：用户不等了，厂商那边可能还在跑；出片线程在后台盯到它有结果
REMAINING = ("planned", "failed")
DEFAULT_BUDGET_CNY = 200.0
DEFAULT_CONFIRM_OVER_CNY = 20.0
SETTING_KEYS = ("provider", "model", "resolution", "audio_mode", "budget_cny", "confirm_over_cny")
COMPOSE_BUSY = ("queued", "running")
FREE_PREFIX = "F"          # 自由节点 id 前缀（F01、F02…）；段 id 是 E01-C01，不会冲突


class SessionError(UserError, ValueError):
    """请求本身不成立（422）。"""


class NotFound(SessionError):
    """会话或段不存在（404）。"""


class Conflict(SessionError):
    """与当前状态冲突（409），可附带服务端重算的金额。"""

    def __init__(self, message: str, expected_cny: Optional[float] = None):
        super().__init__(message)
        self.expected_cny = expected_cny


class Corrupt(SessionError):
    """会话文件损坏（原文件保留，另存备份）。"""


class BudgetExceeded(SessionError):
    """超出单章上限（422）。"""


def set_error(obj: dict, err) -> None:
    """写给用户看的失败原因：error 为中文兜底，error_msg 为 {code, params}（前端按语言渲染）。
    err：None（清空）/ 消息对象（dict 带 code）/ 带代码的异常 / 字符串（未改造的模块、旧写法）。"""
    if err is None:
        obj["error"], obj["error_msg"] = None, None
        return
    m = err.as_msg() if isinstance(err, UserError) else err if isinstance(err, dict) and err.get("code") else None
    if m:
        params = m.get("params") or {}
        obj["error"] = m.get("message") or render_zh(m["code"], params)
        obj["error_msg"] = {"code": m["code"], "params": params, **({"ref": m["ref"]} if m.get("ref") else {})}
    else:
        obj["error"], obj["error_msg"] = str(err), None


def copy_error(dst: dict, src: dict) -> None:
    dst["error"], dst["error_msg"] = src.get("error"), src.get("error_msg")


_locks: dict = {}
_locks_guard = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _lock(root) -> threading.RLock:
    key = str(Path(root).resolve())
    with _locks_guard:
        return _locks.setdefault(key, threading.RLock())


def load(root) -> Optional[dict]:
    try:
        return json.loads((Path(root) / SESSION_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_existing(root) -> Optional[dict]:
    """文件不存在返回 None；存在但读不出来则备份后抛 Corrupt，绝不当作没有会话。"""
    path = Path(root) / SESSION_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        try:
            shutil.copy2(path, path.with_name(f"{SESSION_FILE}.corrupt-{stamp}"))
        except OSError:
            pass
        raise Corrupt.of("film.session.corrupt", path=str(path))


def _save(root, s: dict) -> None:
    """只写进已有的会话目录（由 build 建）：目录没了说明版本已删，不能把它重新建出来。"""
    root = Path(root)
    if not root.is_dir():
        raise NotFound.of("film.session.dir_gone")
    s["updated_at"] = _now()
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=root, delete=False,
                                     suffix=".tmp") as f:
        f.write(json.dumps(s, ensure_ascii=False, indent=2) + "\n")
    os.replace(f.name, root / SESSION_FILE)


@contextmanager
def mutate(root):
    """读改写一个已有会话；块内抛异常则不写回。"""
    with _lock(root):
        s = _read_existing(root)
        if s is None:
            raise NotFound.of("film.session.none")
        yield s
        _save(root, s)


def _clip(s: dict, clip_id: str) -> dict:
    for c in s["clips"]:
        if c["id"] == clip_id:
            return c
    raise NotFound.of("film.clip.not_found", id=clip_id)


def is_free(item_id: str) -> bool:
    return str(item_id).startswith(FREE_PREFIX)


def items(s: dict) -> list:
    """出片线程要推进的全部条目：剧本段在前，自由节点在后。凡是「有没有在跑」「在跑预留多少」都按它算。"""
    return list(s["clips"]) + list(s.get("free") or [])


def any_in_flight(s: dict) -> bool:
    return any(c["state"] in IN_FLIGHT for c in items(s))


def _item(s: dict, item_id: str) -> dict:
    """按 id 在剧本段与自由节点里找（出片线程的迁移函数用）。"""
    for c in items(s):
        if c["id"] == item_id:
            return c
    raise NotFound.of("film.clip.not_found", id=item_id)


def _ended(c: dict, how: str) -> None:
    """记下这一条刚结束（done / failed / cancelled）：任务列表的「最近结束」按它显示。"""
    c["ended_at"], c["ended_as"] = _now(), how


def _rest_state(c: dict) -> str:
    """不在跑时该回到的状态：有采用的按指纹判 done / stale（自由节点没有过期），没有采用就是未出片。"""
    if c.get("chosen") is None:
        return "planned"
    if is_free(c["id"]):
        return "done"
    return "done" if c["attempts"][c["chosen"]].get("fingerprint") == c.get("fingerprint") else "stale"


def abandoned(s: dict) -> list:
    """[(所在的段 / 自由节点 / orphaned 记录, 尝试)]：用户不等了、还没有结果的尝试。"""
    holders = items(s) + list(s.get("orphaned") or [])
    return [(h, a) for h in holders for a in h.get("attempts") or []
            if a.get("state") == ABANDONED and a.get("task_id")]


def abandoned_cny(s: dict) -> float:
    """这些尝试厂商可能照常完成并计费：按提交时的预估预留，算进上限。"""
    return round(sum(float((a.get("billing") or {}).get("estimate_cny") or 0.0) for _, a in abandoned(s)), 2)


def needs_runner(s: dict) -> bool:
    """出片线程还要不要盯这个会话：有在跑的，或有不等了但还没结果的。"""
    return any_in_flight(s) or bool(abandoned(s))


def _provider(name: str):
    try:
        return get_video(name)
    except KeyError as e:
        raise (SessionError.of(e.code, **e.params) if getattr(e, "code", None) else SessionError(e.args[0]))
    except base.ProviderError as e:
        raise (SessionError.of(e.code, **e.params) if e.code else SessionError(str(e)))


# ---------- 设置与建立 ----------

def resolve_settings(old: Optional[dict], patch: dict) -> tuple:
    """合并旧设置与本次修改，校验后返回 (settings, provider, caps)。"""
    patch = {k: v for k, v in (patch or {}).items() if v is not None}
    unknown = set(patch) - set(SETTING_KEYS)
    if unknown:
        raise SessionError.of("film.settings.unknown", keys=sorted(unknown))
    cur = {k: (old or {}).get(k) for k in SETTING_KEYS}
    cur.update(patch)
    provider = _provider(cur["provider"] or default_video_name())
    cur["provider"] = provider.name
    if cur["model"] not in provider.models:
        if "model" in patch:
            log.warning("%s", base.scrub_secrets(f'厂商 {provider.name} 没有档位 {cur["model"]}'))  # i18n: internal
            raise SessionError.of("film.settings.no_model")
        cur["model"] = provider.default_model
    caps = provider.caps(cur["model"])
    if cur["resolution"] not in caps.resolutions:
        if "resolution" in patch:
            raise SessionError.of("film.settings.bad_resolution", resolution=str(cur["resolution"]),
                                  options=list(caps.resolutions))
        cur["resolution"] = "720p" if "720p" in caps.resolutions else caps.resolutions[0]
    cur["audio_mode"] = cur["audio_mode"] or "tts_all"
    if cur["audio_mode"] not in compose.AUDIO_MODES:
        raise SessionError.of("film.settings.bad_audio", mode=str(cur["audio_mode"]))
    if cur["audio_mode"] not in compose.audio_modes(caps):
        old_ = old or {}
        switched = (("provider" in patch and patch["provider"] != old_.get("provider"))
                    or ("model" in patch and patch["model"] != old_.get("model")))
        if "audio_mode" in patch:
            raise SessionError.of("film.settings.no_native_audio")
        if switched or old is None:
            cur["audio_mode"] = "tts_all"
        # 其它情况（只读刷新、patch 为空）不改写：避免把会话改得与已出片段不一致、触发过期；
        # compose 侧 caps.native_audio 为 False 时本就不请求原声
    cur["budget_cny"] = float(cur["budget_cny"] or DEFAULT_BUDGET_CNY)
    cur["confirm_over_cny"] = float(DEFAULT_CONFIRM_OVER_CNY if cur["confirm_over_cny"] is None
                                    else cur["confirm_over_cny"])
    return cur, provider, caps


def _carry(row: dict, old: Optional[dict], back: Optional[dict] = None) -> dict:
    """沿用同一段（同 id、同镜头）的尝试记录，并按采用那次的指纹判定 done / stale。

    back 是这个段 id 之前被移进 orphaned 的记录：段 id 重新出现时把那些尝试接回来（排在前面，
    chosen 随之后移），和沿用的尝试一样按指纹判定，已付费的视频不丢。
    """
    same = old is not None
    prior = list((back or {}).get("attempts") or [])
    row["attempts"] = prior + (old["attempts"] if same else [])
    chosen = old.get("chosen") if same else None
    if chosen is not None:
        chosen += len(prior)
    elif back and back.get("chosen") is not None:
        chosen = back["chosen"]
    row["chosen"] = chosen
    row["mute_native"] = bool(old.get("mute_native")) if same else False
    row["uncertain"] = bool(old.get("uncertain")) if same else False
    if same and old.get("ended_at"):                  # 结束标记跨重建保留（任务列表「最近结束」按它显示）
        row["ended_at"], row["ended_as"] = old["ended_at"], old.get("ended_as")
    set_error(row, None)
    if row["chosen"] is not None:
        chosen = row["attempts"][row["chosen"]]
        row["state"] = "done" if chosen.get("fingerprint") == row["fingerprint"] else "stale"
    elif same and old["state"] == "failed" and old["fingerprint"] == row["fingerprint"]:
        row["state"] = "failed"
        copy_error(row, old)
    else:
        row["state"] = "planned"
    return row


def _merge_orphan(orph: dict, o: dict) -> None:
    """把一条 orphaned 记录并进 {段 id: 记录}：同 id 已有记录则把尝试接在后面（chosen 随之后移），
    不覆盖也不跳过，保证已付费的尝试一次都不丢。"""
    prev = orph.get(o["id"])
    if prev is None:
        orph[o["id"]] = {"id": o["id"], "shots": o.get("shots"),
                         "attempts": list(o.get("attempts") or []), "chosen": o.get("chosen")}
        return
    n = len(prev["attempts"])
    prev["attempts"] = prev["attempts"] + list(o.get("attempts") or [])
    prev["shots"] = o.get("shots") or prev["shots"]
    if o.get("chosen") is not None:
        prev["chosen"] = o["chosen"] + n


def _sync_free(nodes: list, clips: list, caps, resolution: str) -> list:
    """重建会话时带上自由节点：在跑的原样不动（落地之后的下一次重建再同步）；挂靠的段不在了或同 id
    换了镜头就转为独立素材（target_lost）；挂靠的时长跟随目标段；预估按当前设置重算。"""
    by_id = {c["id"]: c for c in clips}
    for n in nodes:
        if n["state"] in IN_FLIGHT:
            continue
        if n.get("target"):
            t = by_id.get(n["target"])
            if t is None or t["shots"] != n.get("target_shots"):
                n.update(target=None, target_shots=None, target_lost=True)
            else:
                n["duration"] = t["duration"]
        n["estimate_cny"] = base.estimate_cny(n["duration"], caps, resolution, compose.image_count(n))
    return nodes


def build(root, doc: dict, *, owner: dict, patch: dict, keyframes: dict,
          allow_in_flight: bool = False, style: Optional[dict] = None) -> dict:
    """按已保存的分镜切段、组装提示词，生成或重建会话。不花钱。

    改设置时（allow_in_flight=False）有段在排队或生成中就拒绝；读取时的刷新传 True，
    在跑的段原样保留（切段变了也保留到跑完）。已花金额与尝试记录跨重建保留。
    """
    root = Path(root)
    with _lock(root):
        old = _read_existing(root)
        if not any((ep or {}).get("shots") for ep in (doc or {}).get("episodes") or []):
            # 分镜被清空（或还没产物）：不能据此重建，否则全部段连同已付费的尝试都会被挤进 orphaned
            if old is not None and not any(v is not None for v in (patch or {}).values()):
                return old
            raise SessionError.of("film.build.no_shots")
        settings, provider, caps = resolve_settings(old, patch)
        olds = {c["id"]: c for c in (old or {}).get("clips", [])}
        flying = {cid: c for cid, c in olds.items() if c["state"] in IN_FLIGHT}
        old_free = list((old or {}).get("free") or [])
        free_flying = any(n["state"] in IN_FLIGHT for n in old_free)
        if (flying or free_flying) and (not allow_in_flight or any(v is not None for v in (patch or {}).values())):
            raise Conflict.of("film.build.in_flight")
        try:
            built = compose.build_clips(doc, caps, provider=settings["provider"],
                                        model=settings["model"], resolution=settings["resolution"],
                                        audio_mode=settings["audio_mode"], keyframes=keyframes,
                                        rewrite=provider.rewrite_prompt, style=style)
        except (KeyError, TypeError, ValueError) as e:
            raise SessionError.of("film.build.incomplete", detail=vendor(e))
        orph = {}
        for o in (old or {}).get("orphaned", []):
            _merge_orphan(orph, o)
        clips = []
        for b in built:
            if b["id"] in flying:
                clips.append(flying.pop(b["id"]))
                continue
            row = {k: v for k, v in b.items() if not k.startswith("_")}
            row["estimate_cny"] = base.estimate_cny(row["duration"], caps, settings["resolution"], compose.image_count(row))
            clips.append(_carry(row, olds.get(b["id"]), orph.pop(b["id"], None)))
        clips.extend(flying.values())
        kept = {c["id"] for c in clips}
        for cid, oc in olds.items():
            if cid not in kept and oc.get("attempts"):
                _merge_orphan(orph, {"id": cid, "shots": oc["shots"], "attempts": oc["attempts"],
                                     "chosen": oc.get("chosen")})
        s = {"version": 1, "owner": owner, **settings,
             "spent_cny": (old or {}).get("spent_cny", 0.0), "clips": clips,
             "orphaned": list(orph.values()),
             "free": _sync_free(old_free, clips, caps, settings["resolution"]),
             "free_seq": int((old or {}).get("free_seq") or 0),
             "voices": (old or {}).get("voices", {}), "final": (old or {}).get("final"),
             "created_at": (old or {}).get("created_at") or _now()}
        root.mkdir(parents=True, exist_ok=True)
        _save(root, s)
        return s


def _style_outdated(c: dict) -> bool:
    """已出完、本段带风格图，但采用的那次尝试用的不是当前风格图（旧会话没记录按 None 算）。
    采用的是自由节点复制来的那次：带不带风格图由用户在节点上定，不算过期。"""
    if c["state"] != "done" or c.get("style") != "used" or c.get("chosen") is None:
        return False
    a = c["attempts"][c["chosen"]]
    if a.get("free_id"):
        return False
    return a.get("style_ref") != c.get("style_hash")


def _default_note(s: dict):
    """缺省厂商回落到 Seedance（没配 MiniMax 而配了方舟）且这个会话用的是 seedance 时给原因代码，文案由前端按语言给。"""
    if s.get("provider") == "seedance" and default_fell_back():
        return "minimax_key_missing"
    return None


def view(s: dict, lenient: bool = False) -> dict:
    """给界面的会话：去掉归属，附状态计数、剩余与在跑预估、可选项。
    lenient：厂商建不起来（密钥被撤、配置变了）时不抛，选项里只留厂商名单、参考位不标超限；
    用在「操作已落账、只差序列化响应」的场合（取消），界面随后的刷新会照常报出厂商问题。"""
    try:
        provider = _provider(s["provider"])
        caps = provider.caps(s["model"])
    except (SessionError, base.ProviderError):
        if not lenient:
            raise
        provider = caps = None
    counts = {}
    for c in s["clips"]:
        counts[c["state"]] = counts.get(c["state"], 0) + 1
    out = {k: v for k, v in s.items() if k != "owner"}
    out["server_now"] = _now()          # 浏览器据此校准自己的时钟（等待时长不能拿两台机器的时钟直接相减）
    # uncertain：厂商那边可能还有这一段的任务（提交中断、查询放弃），界面提示「请到控制台核对」
    out["clips"] = [dict(c, uncertain=bool(c.get("uncertain")), style_outdated=_style_outdated(c))
                    for c in s["clips"]]
    out["style_outdated_count"] = sum(1 for c in out["clips"] if c["style_outdated"])
    out["counts"] = counts
    out["remaining_cny"] = round(sum(c["estimate_cny"] for c in _remaining(s)), 2)
    out["uncertain_count"] = sum(1 for c in s["clips"] if c.get("uncertain"))
    out["reserved_cny"] = round(sum(c["estimate_cny"] for c in items(s)
                                    if c["state"] in IN_FLIGHT) + abandoned_cny(s), 2)
    # 自由节点：参考位超出当前厂商上限（改了设置）时标出来，删减之前生成会被拒
    out["free"] = [dict(n, uncertain=bool(n.get("uncertain")),
                        over_refs=caps is not None and compose.free_slots_needed(n["refs"], n.get("first_frame"), caps) > caps.max_refs)
                   for n in s.get("free") or []]
    out["free_seq"] = int(s.get("free_seq") or 0)
    if provider is None:
        # 厂商不可用：结构仍完整（空值），界面读 models[...] / resolutions.map 不会崩；不为填充去初始化厂商
        out["options"] = {"providers": names(), "models": {}, "resolutions": [], "cny_per_sec": {},
                          "max_clip_sec": 0, "max_refs": 0, "first_frame": False, "frame_with_refs": False,
                          "audio_modes": [], "rate_note": "", "typical_sec": list(base.DEFAULT_TYPICAL_SEC),
                          "default_note": _default_note(s)}
        return out
    out["options"] = {"providers": names(), "models": provider.models,
                      "resolutions": caps.resolutions, "cny_per_sec": caps.cny_per_sec,
                      "max_clip_sec": caps.max_clip_sec, "max_refs": caps.max_refs,
                      "first_frame": caps.first_frame, "frame_with_refs": caps.frame_with_refs,
                      "audio_modes": compose.audio_modes(caps),
                      "rate_note": provider.rate_note,
                      "typical_sec": base.typical_sec(provider),
                      "default_note": _default_note(s)}
    return out


# ---------- 接口侧操作 ----------

def _remaining(s: dict) -> list:
    """批量「出剩余各段」的范围：planned / failed，跳过待核对（uncertain）的段，免得重复付费。"""
    return [c for c in s["clips"] if c["state"] in REMAINING and not c.get("uncertain")]


def run_quote(s: dict, clip_ids: Optional[list] = None) -> tuple:
    """要出的段与合计预估（元），不改会话。queue_run 与助手的确认卡共用这一套挑选、计价与前提检查。"""
    if (s.get("final") or {}).get("state") in COMPOSE_BUSY:
        raise Conflict.of("film.run.composing")
    if clip_ids is None:
        targets = _remaining(s)
    else:
        targets = [_clip(s, cid) for cid in dict.fromkeys(clip_ids)]
        for c in targets:
            if c["state"] in IN_FLIGHT:
                raise Conflict.of("film.run.busy", id=c["id"])
    if not targets:
        raise SessionError.of("film.run.nothing")
    return targets, round(sum(c["estimate_cny"] for c in targets), 2)


def queue_run(root, clip_ids: Optional[list] = None, expected_cny: Optional[float] = None) -> dict:
    """排队出片。clip_ids=None 为批量出剩余各段（planned / failed，不含待核对的段），必须带
    确认金额；单段超过确认线也要带。金额与服务端重算不一致 → Conflict（附重算金额）。
    单段点名重做视为用户已看过「请到控制台核对」，清掉待核对标记。"""
    with mutate(root) as s:
        targets, total = run_quote(s, clip_ids)
        if (clip_ids is None or total > s["confirm_over_cny"]) and expected_cny is None:
            raise Conflict.of("film.run.confirm", total, amount=money(total))
        if expected_cny is not None and abs(expected_cny - total) > 0.005:
            raise Conflict.of("film.run.changed", total, amount=money(total))
        reserved = sum(c["estimate_cny"] for c in items(s) if c["state"] in IN_FLIGHT) + abandoned_cny(s)
        if s["spent_cny"] + reserved + total > s["budget_cny"] + 1e-9:
            raise BudgetExceeded.of("film.budget.exceeded", budget=f"{s['budget_cny']:g}",
                                    spent=money(s["spent_cny"]), reserved=money(reserved), total=money(total))
        for c in targets:
            c["state"], c["queued_at"] = "queued", _now()
            c.pop("ended_at", None)                   # 重新排队：上一次的结束标记作废
            c.pop("ended_as", None)
            set_error(c, None)
            c["uncertain"] = False
        return s


def set_chosen(root, clip_id: str, index: int) -> dict:
    with mutate(root) as s:
        c = _clip(s, clip_id)
        if c["state"] in IN_FLIGHT:
            raise Conflict.of("film.choose.busy")
        if not (0 <= index < len(c["attempts"])) or c["attempts"][index].get("state") != "succeeded":
            raise SessionError.of("film.choose.not_success")
        c["chosen"] = index
        c["state"] = "done" if c["attempts"][index].get("fingerprint") == c["fingerprint"] else "stale"
        set_error(c, None)      # 采用成功的那次：段上遗留的失败原因不再成立（失败尝试自己的记录保留）
        return s


def set_mute(root, clip_id: str, mute: bool) -> dict:
    with mutate(root) as s:
        _clip(s, clip_id)["mute_native"] = bool(mute)
        return s


def _cancel_check(c: dict) -> Optional[str]:
    """能不能取消：还没提交返回 None（纯本地取消，不花钱）；已提交返回任务 id；其余抛 Conflict。"""
    last = c["attempts"][-1] if c["attempts"] else None
    if c["state"] == "queued":
        if last and last["state"] == "submitting":
            raise Conflict.of("film.cancel.submitting")     # 请求正在路上，拿不到任务 id：几秒后再试
        return None
    if c["state"] == "running" and last and last.get("task_id"):
        return last["task_id"]
    if c["state"] == "downloading":
        raise Conflict.of("film.cancel.finished")
    raise Conflict.of("film.cancel.not_running")


def _check_kind(task_id: Optional[str], expect: Optional[str]) -> None:
    """用户确认的取消种类（free 不花钱 / paid 不等了）与锁内实际种类不一致 → 409，什么都不动。"""
    if expect is not None and expect != ("free" if task_id is None else "paid"):
        raise Conflict.of("film.cancel.kind_changed")


def cancel_target(root, item_id: str, expect: Optional[str] = None) -> tuple:
    """取消前看一眼（不改会话）：(任务 id 或 None, 厂商名)。调用方拿任务 id 在锁外请厂商取消，再调 cancel。
    expect 为用户确认时的取消种类，与实际不符就抛 Conflict（还没请厂商，不会误发取消）。"""
    with _lock(root):
        s = _read_existing(root)
        if s is None:
            raise NotFound.of("film.session.none")
        task_id = _cancel_check(_item(s, item_id))
        _check_kind(task_id, expect)
        return task_id, s["provider"]


def cancel(root, item_id: str, task_id: Optional[str] = None, confirmed: bool = False,
           expect: Optional[str] = None) -> dict:
    """取消一段或一个自由节点，立即放开它（回到未出片 / 原来采用的那次）。
    task_id 是 cancel_target 看到的那个：对不上说明两步之间状态变了，抛 Conflict 让用户再试。
    - 还没提交（task_id=None）：什么都没发出去，不留尝试。
    - 已提交、厂商确认取消（confirmed=True）：那次尝试记 cancelled，不计费。
    - 已提交、没取消成：那次尝试记 abandoned，连同提交时的厂商、档位、分辨率、时长与预估（之后改设置也按它记费）；
      出片线程接着盯，结果回来由 settle_abandoned 落账。"""
    with mutate(root) as s:
        c = _item(s, item_id)
        if _cancel_check(c) != task_id:
            raise Conflict.of("film.cancel.changed")
        _check_kind(task_id, expect)
        if task_id is not None:
            a = c["attempts"][-1]
            a["cancelled_at"] = _now()
            if confirmed:
                a["state"] = "cancelled"
                set_error(a, msg("film.provider.task_cancelled"))
            else:
                a["state"] = ABANDONED
                a["billing"] = {"provider": s["provider"], "model": s["model"], "resolution": s["resolution"],
                                "duration": c["duration"], "estimate_cny": c["estimate_cny"]}
        c["state"] = _rest_state(c)
        set_error(c, None)
        _ended(c, "cancelled")
        return s


# ---------- 出片线程侧迁移 ----------

def begin_submit(root, clip_id: str) -> Optional[dict]:
    """提交前：再查一次上限（实际花费可能超过预估），追加一次「提交中」的尝试，返回段的快照。
    不该提交（不在排队、超上限）返回 None；超上限的段转 failed。"""
    with mutate(root) as s:
        c = _item(s, clip_id)
        if c["state"] != "queued":
            return None
        last = c["attempts"][-1] if c["attempts"] else None
        if last and last["state"] == "submitting" and not last.get("task_id"):
            # 上一次提交了却没写回任务 id（如写盘失败）：厂商可能已受理，不能再提交一次
            set_error(last, msg("film.submit.interrupted"))
            last["state"] = "failed"
            c["state"], c["uncertain"] = "failed", True
            copy_error(c, last)
            _ended(c, "failed")
            return None
        running = sum(x["estimate_cny"] for x in items(s) if x["state"] in ("running", "downloading"))
        if s["spent_cny"] + running + abandoned_cny(s) + c["estimate_cny"] > s["budget_cny"] + 1e-9:
            c["state"] = "failed"
            set_error(c, msg("film.submit.over_budget"))
            _ended(c, "failed")
            return None
        c["attempts"].append({"task_id": None, "state": "submitting", "cost_cny": 0.0,
                              "file": None, "last_frame": None, "error": None, "error_msg": None, "at": _now(),
                              "fingerprint": c.get("fingerprint"), "first_frame_used": None})
        return json.loads(json.dumps(c))


def submitted(root, clip_id: str, task_id: str, first_frame_used: Optional[str],
              style_ref: Optional[str] = None, images: Optional[int] = None) -> None:
    with mutate(root) as s:
        c = _item(s, clip_id)
        c["attempts"][-1].update(task_id=task_id, state="running", first_frame_used=first_frame_used,
                                 style_ref=style_ref)
        if images is not None:
            c["attempts"][-1]["images"] = int(images)
        c["state"] = "running"


def submit_failed(root, clip_id: str, error, *, stale: bool = False,
                  uncertain: bool = False) -> None:
    """提交没成：stale=True（分镜已改）撤回这次尝试、退回待确认；否则记失败。
    uncertain=True：厂商可能已受理（提交结果不明），标待核对，批量出片跳过它。"""
    with mutate(root) as s:
        c = _item(s, clip_id)
        pending = c["attempts"] and c["attempts"][-1]["state"] == "submitting"
        if stale:
            if pending:
                c["attempts"].pop()
            c["state"] = "stale" if c.get("chosen") is not None else "planned"
        else:
            if pending:
                c["attempts"][-1]["state"] = "failed"
                set_error(c["attempts"][-1], error)
            c["state"] = "failed"
            if uncertain:
                c["uncertain"] = True
        set_error(c, error)
        _ended(c, "failed")


def poll_update(root, clip_id: str, st: base.TaskState, cost: float = 0.0, *,
                uncertain: bool = False) -> None:
    """uncertain=True：不是厂商报的终态（如多次查询失败后放弃），任务可能还在跑、在计费。"""
    with mutate(root) as s:
        c = _item(s, clip_id)
        a = c["attempts"][-1] if c["attempts"] else {}
        if c["state"] != "running" or a.get("task_id") != st.task_id:
            return
        if st.status == "succeeded":
            a.update(video_url=st.video_url, last_frame_url=st.last_frame_url, usage=st.usage)
            c["state"] = "downloading"
        elif st.status == "failed":
            err = ({"code": st.error_msg["code"], "params": st.error_msg.get("params") or {}, "message": st.error,
                    **({"ref": st.error_msg["ref"]} if st.error_msg.get("ref") else {})}
                   if st.error_msg else (st.error or msg("film.provider.failed")))
            a.update(state="failed", cost_cny=cost)
            set_error(a, err)
            s["spent_cny"] = round(s["spent_cny"] + cost, 2)
            c["state"] = "failed"
            copy_error(c, a)
            _ended(c, "failed")
            if uncertain:
                c["uncertain"] = True


def note_error(root, clip_id: str, err, task_id: Optional[str] = None) -> None:
    """只记一条给用户看的提示，不改状态（如厂商暂时不可达、正在重试）。
    task_id：发出这条提示的那次任务；会话里这一条已不是同一次在跑（取消、重排队、换了新任务）就丢弃。"""
    with mutate(root) as s:
        c = _item(s, clip_id)
        if task_id is not None:
            a = c["attempts"][-1] if c["attempts"] else {}
            if c["state"] not in ("running", "downloading") or a.get("task_id") != task_id:
                return
        set_error(c, err)


def clip_dest(root, clip_id: str, task_id: str) -> Path:
    """一次尝试的视频文件路径：按任务 id 命名，同一段 id 再出现时也不会覆盖已付费的旧文件
    （尾帧按 base.last_frame_path 随之命名）。只在会话目录还在时建 clips/，版本删了不重建。"""
    root = Path(root)
    if not root.is_dir():
        raise NotFound.of("film.session.dir_gone")
    (root / "clips").mkdir(exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", str(task_id))
    return root / "clips" / f"{clip_id}.{safe}.mp4"


def _rel(root, p) -> Optional[str]:
    return Path(p).resolve().relative_to(Path(root).resolve()).as_posix() if p else None


def _deliver(s: dict, node: dict, a: dict) -> None:
    """挂靠的自由节点成功一次：把这次尝试复制进目标段（free_id 标来源，花费记在节点上这里为 0，
    指纹记目标段此刻的指纹），不自动采用。目标段不在了或镜头变了：不复制，节点转为独立素材。

    目标段最后一次尝试正在提交或生成（runner 认 attempts[-1] 为在跑的那次）：插到它前面。
    chosen 只可能指向更早的尝试，下标不受影响。
    """
    t = next((c for c in s["clips"] if c["id"] == node.get("target")), None)
    if t is None or t["shots"] != node.get("target_shots"):
        node.update(target=None, target_shots=None, target_lost=True)
        return
    cp = dict(a, free_id=node["id"], cost_cny=0.0, fingerprint=t["fingerprint"])
    last = t["attempts"][-1] if t["attempts"] else None
    if last and last.get("state") in ("submitting", "running"):
        t["attempts"].insert(len(t["attempts"]) - 1, cp)
    else:
        t["attempts"].append(cp)


def downloaded(root, clip_id: str, files: dict, cost: float) -> None:
    with mutate(root) as s:
        c = _item(s, clip_id)
        if c["state"] != "downloading":
            return
        a = c["attempts"][-1]
        a.update(state="succeeded", file=_rel(root, files["video"]),
                 last_frame=_rel(root, files.get("last_frame")), cost_cny=cost)
        s["spent_cny"] = round(s["spent_cny"] + cost, 2)
        c["chosen"] = len(c["attempts"]) - 1
        if is_free(c["id"]):
            c["state"] = "done"         # 自由节点不依赖分镜，没有过期
            if c.get("target"):
                _deliver(s, c, a)
        else:
            c["state"] = "done" if a["fingerprint"] == c["fingerprint"] else "stale"
        set_error(c, None)
        _ended(c, "done")


def download_failed(root, clip_id: str, error, cost: float) -> None:
    """已经生成、但下载或校验失败：生成费用照记。"""
    with mutate(root) as s:
        c = _item(s, clip_id)
        c["attempts"][-1].update(state="failed", cost_cny=cost)
        set_error(c["attempts"][-1], error)
        s["spent_cny"] = round(s["spent_cny"] + cost, 2)
        c["state"] = "failed"
        set_error(c, error)
        _ended(c, "failed")


def record_abandoned_result(root, task_id: str, st: base.TaskState, cost: float) -> None:
    """用户不等了的那次已查到成功：把结果地址与已确认的费用记在那次尝试上（仍是待结算），
    之后下载再失败也不会退回「是否生成未知」。"""
    with mutate(root) as s:
        for _, a in abandoned(s):
            if a["task_id"] == task_id:
                a.update(video_url=st.video_url, last_frame_url=st.last_frame_url, usage=st.usage,
                         known_cost_cny=cost)
                return


def settle_abandoned(root, task_id: str, state: str, *, cost: float = 0.0, files: Optional[dict] = None,
                     error=None) -> None:
    """用户不等了的那次有了结果。state：succeeded（文件已下好）/ failed / cancelled。费用照记进 spent_cny。
    成功的标 late、留作可采用的一次，不自动采用，也不动所在段的状态；挂靠的自由节点照常复制进目标段。"""
    with mutate(root) as s:
        for h, a in abandoned(s):
            if a["task_id"] != task_id:
                continue
            a.update(state=state, cost_cny=cost, settled_at=_now())
            if state == "succeeded":
                a.update(file=_rel(root, files["video"]), last_frame=_rel(root, files.get("last_frame")), late=True)
                set_error(a, None)
                if is_free(h["id"]) and h.get("target"):
                    _deliver(s, h, a)
            else:
                set_error(a, error)
            s["spent_cny"] = round(s["spent_cny"] + cost, 2)
            return


def _prev(s: dict, clip: dict) -> Optional[dict]:
    ff = clip.get("first_frame") or ""
    if not ff.startswith("relay:"):
        return None
    return next((c for c in s["clips"] if c["id"] == ff[len("relay:"):]), None)


def waiting_on_relay(s: dict, clip: dict) -> bool:
    """接力的段要等上一段跑完（成功就带尾帧，失败就不带）。"""
    prev = _prev(s, clip)
    return clip.get("frame_mode") == "frame" and prev is not None and prev["state"] in IN_FLIGHT


def relay_frame(root, s: dict, clip: dict) -> Optional[Path]:
    """上一段采用那次的尾帧文件；没有返回 None。"""
    prev = _prev(s, clip)
    if prev is None or prev.get("chosen") is None:
        return None
    rel = prev["attempts"][prev["chosen"]].get("last_frame")
    return Path(root) / rel if rel else None


def recover(root) -> bool:
    """进程重启后：提交中断（没拿到任务 id）的尝试标失败，不重复提交。返回是否还有在跑的段。"""
    with _lock(root):
        s = load(root)
        if s is None:
            return False
        changed = False
        for c in items(s):
            a = c["attempts"][-1] if c["attempts"] else None
            if a and a["state"] == "submitting":
                a["state"] = "failed"
                set_error(a, msg("film.submit.interrupted"))
                c["state"], c["uncertain"] = "failed", True
                copy_error(c, a)
                _ended(c, "failed")
                changed = True
        changed = _fail_interrupted_compose(s) or changed
        if changed:
            _save(root, s)
        return needs_runner(s)


def _fail_interrupted_compose(s: dict) -> bool:
    f = s.get("final") or {}
    if f.get("state") not in COMPOSE_BUSY:
        return False
    f.update(state="failed", finished_at=_now())
    set_error(f, msg("compose.interrupted"))
    s["final"] = f
    return True


def recover_compose(root) -> None:
    """只收尾合成：重启前没合成完的标失败（关掉后台出片时启动也要做，段的提交中断留给 recover）。"""
    with _lock(root):
        s = load(root)
        if s is not None and _fail_interrupted_compose(s):
            _save(root, s)


# ---------- 配音与合成（设计文档第 3 节） ----------

def set_voices(root, voices: dict) -> dict:
    """说话人 → 厂商音色 id；空值为清除（回到按提示的默认）。音色是否存在由调用方按厂商校验。"""
    with mutate(root) as s:
        cur = dict(s.get("voices") or {})
        for k, v in voices.items():
            if v:
                cur[k] = v
            else:
                cur.pop(k, None)
        s["voices"] = cur
        return s


def begin_compose(root, *, fingerprint: str, tts_cny: float, draft: bool, voices: dict = None) -> dict:
    """开始合成：不能正在合成、不能有段在跑；配音费用过同一上限。旧成片的文件留着直到新的合成完成，
    连同它出自哪次合成（files_fingerprint、files_draft）。voices 为预览时的音色选择，与现在的不同就要重新确认。"""
    with mutate(root) as s:
        f = s.get("final") or {}
        if f.get("state") in COMPOSE_BUSY:
            raise Conflict.of("compose.busy")
        if voices is not None and (s.get("voices") or {}) != voices:
            raise Conflict.of("compose.voices_changed")
        if any_in_flight(s):
            raise Conflict.of("compose.clips_busy")
        if s["spent_cny"] + tts_cny > s["budget_cny"] + 1e-9:
            raise BudgetExceeded.of("compose.over_budget", budget=money(s["budget_cny"]), spent=money(s["spent_cny"]),
                                    cost=money(tts_cny))
        s["final"] = {"state": "running", "fingerprint": fingerprint, "draft": draft,
                      "step": render_zh("compose.step.start", {}),
                      "step_msg": compact(msg("compose.step.start")),
                      "started_at": _now(), "files": f.get("files") or [], "report": f.get("report"),
                      "files_fingerprint": f.get("files_fingerprint", f.get("fingerprint")),
                      "files_draft": f.get("files_draft", f.get("draft")),
                      "error": None, "error_msg": None, "detail": None}
        return s


def compose_progress(root, step) -> None:
    """step：消息对象（写 step 中文兜底与 step_msg）或字符串（只写 step）。"""
    with mutate(root) as s:
        f = s.get("final") or {}
        if isinstance(step, dict) and step.get("code"):
            f["step"] = step.get("message") or render_zh(step["code"], step.get("params") or {})
            f["step_msg"] = compact(step)
        else:
            f["step"], f["step_msg"] = step, None


def add_spent(root, cny: float) -> None:
    """配音的真实花费（每合成一条记一次）计入同一 spent_cny。"""
    with mutate(root) as s:
        s["spent_cny"] = round(s["spent_cny"] + cny, 4)


def compose_done(root, files: list, report: str) -> None:
    with mutate(root) as s:
        f = s["final"]
        f.update(state="done", files=files, report=report, detail=None,
                 step=render_zh("compose.step.done", {}), step_msg=compact(msg("compose.step.done")),
                 files_fingerprint=f.get("fingerprint"), files_draft=f.get("draft"), finished_at=_now())
        set_error(f, None)


def compose_failed(root, error, detail: str = "") -> None:
    with mutate(root) as s:
        f = s.get("final") or {}
        f.update(state="failed", detail=detail or None, finished_at=_now())
        set_error(f, error)
        s["final"] = f
