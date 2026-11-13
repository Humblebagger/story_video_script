"""后端对用户文字的消息对象（设计 docs/specs/2026-11-13-backend-i18n-design.md §3–§5）。

每个代码登记一条中文兜底模板，参数名取自模板里的 {name}。后端返回、持久化的都是
{code, params, message}：前端按代码与当前语言渲染（文案在 frontend/src/i18n 的 srv 节点），
message 是中文兜底，给旧前端、日志与测试阅读。登记表导出到 messages_codes.json，前端测试核对。

参数值允许：字符串、数字、列表、嵌套消息 {code, params}（内层原因）、
金额 {"t":"money","cny":…}、代码引用 {"t":"ref","code":…}、厂商原文 {"t":"vendor","text":…}。
"""
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

CODES_FILE = Path(__file__).with_name("messages_codes.json")
VENDOR_MAX = 300
_PH = re.compile(r"\{(\w+)\}")
_REG: dict = {}          # code → (参数名元组, 中文模板)


def register(code: str, zh: str) -> None:
    if code in _REG:
        raise ValueError(f"重复登记：{code}")  # i18n: internal
    for other in _REG:
        if other.startswith(code + ".") or code.startswith(other + "."):
            raise ValueError(f"{code} 与 {other} 一个是另一个的前缀")  # i18n: internal
    _REG[code] = (tuple(dict.fromkeys(_PH.findall(zh))), zh)


def money(cny: float) -> dict:
    return {"t": "money", "cny": round(float(cny), 2)}


def ref(code: str) -> dict:
    if code not in _REG:
        raise KeyError(code)
    return {"t": "ref", "code": code}


def vendor(text: Any) -> dict:
    """厂商或系统原文：原样显示、不翻译。调用方先脱敏（如 minimax.scrub），这里只截断。"""
    return {"t": "vendor", "text": str(text)[:VENDOR_MAX]}


def compact(m: dict) -> dict:
    """消息对象 → 只留 code、params（嵌进别的消息当原因时用）。"""
    return {"code": m["code"], "params": m.get("params") or {}}


def _zh_value(v: Any) -> str:
    if isinstance(v, list):
        return "、".join(_zh_value(x) for x in v)
    if isinstance(v, dict):
        t = v.get("t")
        if t == "money":
            return f"¥{float(v['cny']):.2f}"
        if t == "ref":
            return _REG[v["code"]][1]
        if t == "vendor":
            return str(v.get("text", ""))
        if "code" in v:
            return v.get("message") or render_zh(v["code"], v.get("params") or {})
        return ""
    return "" if v is None else str(v)


def render_zh(code: str, params: dict) -> str:
    tpl = _REG[code][1]
    return _PH.sub(lambda m: _zh_value(params[m.group(1)]) if m.group(1) in params else m.group(0), tpl)


def msg(code: str, **params) -> dict:
    if code not in _REG:
        raise KeyError(code)
    want = set(_REG[code][0])
    if set(params) != want:
        raise ValueError(f"{code} 的参数应为 {sorted(want)}，实际 {sorted(params)}")  # i18n: internal
    return {"code": code, "params": params, "message": render_zh(code, params)}


class UserError:
    """混入现有异常类：带代码与参数，str() 仍是中文兜底（原有 except 链、日志、测试不受影响）。"""
    code: Optional[str] = None
    params: dict = {}

    @classmethod
    def of(cls, code: str, *args, **params):
        m = msg(code, **params)
        e = cls(m["message"], *args)
        e.code, e.params = code, m["params"]
        return e

    def as_msg(self) -> Optional[dict]:
        if not self.code:
            return None
        text = self.args[0] if self.args else str(self)
        return {"code": self.code, "params": self.params, "message": text}


def cause_of(e: BaseException) -> dict:
    """异常 → 可嵌进外层消息的原因：带代码的给紧凑消息，其它给原文（截断）。"""
    m = e.as_msg() if isinstance(e, UserError) else None
    return compact(m) if m else vendor(e.args[0] if isinstance(e, KeyError) and e.args else e)


def to_detail(e: BaseException, **extra) -> Any:
    """HTTPException 的 detail：带代码 → 消息对象（附加字段同层）；不带代码 → 与现在一致。"""
    m = e.as_msg() if isinstance(e, UserError) else None
    if m:
        return {**m, **extra}
    text = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
    return {"message": text, **extra} if extra else text


def dump_codes() -> dict:
    return {c: {"params": list(p), "zh": z} for c, (p, z) in sorted(_REG.items())}


# ---------- 登记表（按域分组；改动后运行 python -m server.messages --write） ----------

register("common.unknown", "{message}")


if __name__ == "__main__":
    if "--write" in sys.argv:
        CODES_FILE.write_text(json.dumps(dump_codes(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {CODES_FILE}")
