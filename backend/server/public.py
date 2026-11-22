"""给普通用户的出口：厂商词表、旧代码归一、消息对象与出片会话视图的净化（spec 2026-11-21-vendor-name-cleanup §4、§7）。
管理接口（/admin/*）不经过这里。打码只用于错误文字，不用于分镜、提示词、小说、对话等用户内容。"""
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional

from server import messages

WORDS_FILE = Path(__file__).with_name("vendor_words.json")
_W = json.loads(WORDS_FILE.read_text(encoding="utf-8"))
_ALTS = sorted([re.escape(w) for w in _W["substr"] + _W["cjk"]]
               + [rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])" for w in _W["word"]], key=len, reverse=True)
VENDOR_RE = re.compile("|".join(_ALTS), re.I)
MASK = "***"
GENERIC = "common.failed_generic"
_REF_RE = re.compile(r"[0-9A-Z]{1,16}")
# 尝试里可以给普通用户的字段（白名单：新增字段默认不下发）
ATTEMPT_KEYS = ("state", "cost_cny", "file", "last_frame", "at", "fingerprint", "first_frame_used",
                "style_ref", "free_id", "late", "cancelled_at", "settled_at", "images")


def redact(text) -> str:
    """错误文字里的厂商词换成 ***。"""
    return VENDOR_RE.sub(MASK, str(text))


def find_vendor_words(v) -> list:
    """任意 JSON 值里出现的厂商词（守卫测试用；只能用在不含用户内容的值上）。"""
    return sorted({m.group(0).lower() for m in VENDOR_RE.finditer(json.dumps(v, ensure_ascii=False))})


def task_key(task_id) -> Optional[str]:
    """厂商任务号 → 不可逆的短键。同一个任务号在会话视图与任务列表里得到同一个键。"""
    return "t" + hashlib.sha256(str(task_id).encode("utf-8")).hexdigest()[:16] if task_id else None


def _value(v: Any) -> Any:
    if isinstance(v, str):
        return redact(v)
    if isinstance(v, list):
        return [_value(x) for x in v]
    if isinstance(v, dict):
        t = v.get("t")
        if t == "money":
            return v
        if t == "ref":
            code = messages.canonical(str(v.get("code")))
            return {"t": "ref", "code": code} if messages.registered(code) else ""
        if t == "vendor":
            return {"t": "vendor", "text": redact(v.get("text", ""))}
        if t == "lines":
            return {"t": "lines", "items": [_value(x) for x in v.get("items") or []]}
        if isinstance(v.get("code"), str):
            m = public_msg(v)
            return {"code": m["code"], "params": m["params"]}
        return ""
    return v


def public_msg(m) -> dict:
    """消息对象 → 可以给普通用户的消息对象：旧代码归一、只留登记过的参数、文字里的厂商词打码、中文兜底重写。
    认不出的代码、缺参数的，一律换成通用失败文案（保留参考编号）。"""
    out = None
    if isinstance(m, dict) and isinstance(m.get("code"), str):
        code = messages.canonical(m["code"])
        src = m.get("params") if isinstance(m.get("params"), dict) else {}
        if messages.registered(code) and all(k in src for k in messages.params_of(code)):
            params = {k: _value(src[k]) for k in messages.params_of(code)}
            out = {"code": code, "params": params, "message": messages.render_zh(code, params)}
    if out is None:
        out = messages.msg(GENERIC)
    ref = m.get("ref") if isinstance(m, dict) else None
    if isinstance(ref, str) and _REF_RE.fullmatch(ref):
        out = messages.with_ref(out, ref)
    return out


def error_pair(obj: dict, text_key: str = "error", msg_key: str = "error_msg") -> tuple:
    """(中文兜底, {code, params[, ref]})；两样都没有时 (None, None)。只有文字、没有代码的不外放，换通用文案。"""
    m, text = obj.get(msg_key), obj.get(text_key)
    if not m and not text:
        return None, None
    pm = public_msg(m)
    return pm["message"], {k: pm[k] for k in ("code", "params", "ref") if k in pm}


def scrub_errors(v: Any) -> Any:
    """递归：带 error / error_msg 的字典把这一对换成净化后的；step / step_msg 同理（步骤没有代码时置空）；
    字符串型的 detail 打码。其它键原样。"""
    if isinstance(v, list):
        return [scrub_errors(x) for x in v]
    if not isinstance(v, dict):
        return v
    out = {k: scrub_errors(x) for k, x in v.items()}
    if "error" in v or "error_msg" in v:
        out["error"], out["error_msg"] = error_pair(v)
    if "step" in v or "step_msg" in v:
        out["step"], out["step_msg"] = error_pair(v, "step", "step_msg") if v.get("step_msg") else (None, None)
    if isinstance(v.get("detail"), str):
        out["detail"] = redact(v["detail"])
    return out


def _attempt(a: dict) -> dict:
    out = {k: a[k] for k in ATTEMPT_KEYS if k in a}
    out["task_id"] = task_key(a.get("task_id"))
    out["error"], out["error_msg"] = error_pair(a)
    return out


def _holder(c: dict) -> dict:
    out = scrub_errors({k: x for k, x in c.items() if k != "attempts"})
    out["attempts"] = [_attempt(a) for a in c.get("attempts") or []]
    return out


def film_view(view: dict, *, tier: Optional[str], tiers: list, rate_note: dict) -> dict:
    """出片会话视图（render.session.view 的结果）→ 给普通用户的：去掉厂商与模型，尝试按白名单留字段，
    任务号换短键，错误净化；档位用中性 id。不改入参，存储不动。"""
    out = {k: x for k, x in view.items() if k not in ("provider", "model")}
    out["tier"] = tier
    for key in ("clips", "free", "orphaned"):
        if key in view:
            out[key] = [_holder(c) for c in view.get(key) or []]
    if view.get("final"):
        out["final"] = scrub_errors(view["final"])
    opts = {k: x for k, x in (view.get("options") or {}).items()
            if k not in ("providers", "models", "default_note")}
    opts["rate_note"] = rate_note
    opts["tiers"] = tiers
    out["options"] = opts
    return out
